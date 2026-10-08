import json
import re
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from intention_refiner.adapters.requirements.integration_http import (
    CircuitBreaker,
    HttpRequest,
    IntegrationHttp,
)
from intention_refiner.adapters.requirements.rich_text import (
    adf_to_text,
    render_questions,
    render_result,
    text_to_adf,
)
from intention_refiner.application.integrations import PublicationRequest
from intention_refiner.config import IntegrationConfig
from intention_refiner.domain.integration import (
    IntegrationError,
    PublicationResult,
    RequirementInput,
    SourceProvenance,
    SourceReference,
)

PositiveId = Annotated[int, Field(strict=True, gt=0)]
NumericId = Annotated[str, Field(strict=True, pattern=r"^[0-9]+$")]
Nonempty = Annotated[str, Field(strict=True, min_length=1)]


class RemoteModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class RemoteLabel(RemoteModel):
    name: Nonempty


class JiraIdentity(RemoteModel):
    accountId: Nonempty


class JiraFields(RemoteModel):
    summary: str
    description: dict | None
    labels: list[str] = Field(default_factory=list)


class JiraIssue(RemoteModel):
    id: NumericId
    key: Nonempty
    fields: JiraFields


class JiraComment(RemoteModel):
    id: NumericId
    body: dict
    author: JiraIdentity


class JiraCommentPage(RemoteModel):
    comments: list[JiraComment]
    total: Annotated[int, Field(ge=0)]
    startAt: Annotated[int, Field(ge=0)]
    maxResults: Annotated[int, Field(gt=0)]


@dataclass
class AdapterDependencies:
    config: IntegrationConfig
    client: httpx.Client
    breaker: CircuitBreaker
    telemetry: Any = None


@dataclass(frozen=True)
class CommentUpdate:
    kind: str
    text: str
    existing: Any = None


def validate_response(response: httpx.Response, model):
    try:
        return TypeAdapter(model).validate_python(response.json(), strict=True)
    except (ValidationError, ValueError, TypeError):
        raise IntegrationError("validation", "response contract") from None


def normalize_reference(
    source: SourceReference, config: IntegrationConfig
) -> SourceReference:
    raw = source.reference
    if raw.startswith("https://"):
        parsed = urlsplit(raw)
        if (
            parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or parsed.port
        ):
            raise IntegrationError("validation", "source reference")
        if source.provider == "github" and parsed.netloc == "github.com":
            match = re.fullmatch(
                r"/([^/]+)/([^/]+)/issues/([1-9][0-9]*)/?", parsed.path
            )
            raw = f"{match[1]}/{match[2]}#{match[3]}" if match else ""
        elif (
            source.provider == "jira"
            and parsed.netloc == urlsplit(config.jira_base_url).netloc
        ):
            match = re.fullmatch(
                r"/browse/([A-Z][A-Z0-9_]*-[1-9][0-9]*)/?", parsed.path
            )
            raw = match[1] if match else ""
        else:
            raw = ""
    pattern = (
        r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*"
        if source.provider == "github"
        else r"[A-Z][A-Z0-9_]*-[1-9][0-9]*"
    )
    if source.provider != config.provider or not re.fullmatch(pattern, raw):
        raise IntegrationError("validation", "source reference")
    return SourceReference(source.provider, raw)


class RemoteAdapter:
    capabilities = frozenset({"comments", "labels"})

    def __init__(self, dependencies: AdapterDependencies):
        self.dependencies = dependencies
        self.http = IntegrationHttp(dependencies)

    def normalize(self, source: SourceReference) -> SourceReference:
        return normalize_reference(source, self.dependencies.config)

    def publish(self, request: PublicationRequest) -> PublicationResult:
        source = self.normalize(request.source)
        completed = []
        uncertain = None
        try:
            # Preflight every rendered body before creating any remote state.
            result_text = self.marked_text("result", render_result(request.report))
            question_content = render_questions(request.report)
            question_text = self.marked_text(
                "clarification",
                question_content
                or "Clarifications resolved: no outstanding questions in the latest refinement.",
            )
            self.validate_size(result_text)
            self.validate_size(question_text)
            labels = request.required_labels()
            self.validate_labels(labels)
            author = self.current_author()
            comments = self.comments(source)
            existing = {}
            for comment in comments:
                if self.comment_author(comment) != author:
                    continue
                text = self.comment_text(comment)
                for kind in ("result", "clarification"):
                    if text.startswith(self.marker(kind)):
                        if kind in existing:
                            raise IntegrationError(
                                "validation", "duplicate agent comments"
                            )
                        existing[kind] = comment
            uncertain = "result"
            result_id = self.upsert(
                source, CommentUpdate("result", result_text, existing.get("result"))
            )
            completed.append("result")
            uncertain = None
            question_id = None
            if question_content or "clarification" in existing:
                uncertain = "clarification"
                question_id = self.upsert(
                    source,
                    CommentUpdate(
                        "clarification", question_text, existing.get("clarification")
                    ),
                )
                completed.append("clarification")
                uncertain = None
            if labels:
                uncertain = "labels"
                self.ensure_labels(source, labels)
                completed.append("labels")
                uncertain = None
            return PublicationResult(
                provider=source.provider,
                identifier=source.reference,
                result_comment_id=result_id,
                clarification_comment_id=question_id,
                completed_operations=tuple(completed),
            )
        except (ValidationError, ValueError, TypeError, RecursionError) as exc:
            error = (
                exc
                if isinstance(exc, IntegrationError)
                else IntegrationError("validation", "publication")
            )
            error.completed_operations = tuple(completed)
            error.uncertain_operation = uncertain
            raise error from None

    def marker(self, kind: str) -> str:
        return f"[intention-refiner:{kind}:v1]"

    def marked_text(self, kind: str, text: str) -> str:
        return f"{self.marker(kind)}\n{text}"

    def validate_size(self, text: str) -> None:
        limit = 65536 if self.dependencies.config.provider == "github" else 32767
        body = {
            "body": text
            if self.dependencies.config.provider == "github"
            else text_to_adf(text)
        }
        # Conservative byte bound prevents platform-limit truncation.
        if (
            len(
                json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            > limit
        ):
            raise IntegrationError("validation", "publication payload size")

    def validate_labels(self, labels: tuple[str, ...]) -> None:
        jira = self.dependencies.config.provider == "jira"
        for label in labels:
            if (
                not label.strip()
                or len(label) > (255 if jira else 50)
                or any(ord(char) < 32 for char in label)
                or (jira and any(char.isspace() for char in label))
            ):
                raise IntegrationError("validation", "label name")


class JiraAdapter(RemoteAdapter):
    def issue_path(self, source: SourceReference) -> str:
        return f"/rest/api/3/issue/{source.reference}"

    def read(self, reference: SourceReference) -> RequirementInput:
        source = self.normalize(reference)
        issue = validate_response(
            self.http.send(
                HttpRequest(
                    "GET",
                    self.issue_path(source),
                    params={"fields": "summary,description"},
                )
            ),
            JiraIssue,
        )
        if issue.key != source.reference:
            raise IntegrationError("validation", "issue identity")
        try:
            description = adf_to_text(issue.fields.description)
        except (ValueError, TypeError, RecursionError):
            raise IntegrationError("validation", "description") from None
        if not issue.fields.summary.strip() and not description.strip():
            raise IntegrationError("validation", "empty requirement")
        return RequirementInput(
            f"{source.reference}\nTitle: {issue.fields.summary}\n\nDescription:\n{description}",
            SourceProvenance(
                provider="jira",
                identifier=source.reference,
                url=f"{self.dependencies.config.jira_base_url}/browse/{source.reference}",
            ),
        )

    def current_author(self) -> str:
        return validate_response(
            self.http.send(HttpRequest("GET", "/rest/api/3/myself")), JiraIdentity
        ).accountId

    def comments(self, source: SourceReference) -> list[JiraComment]:
        result = []
        start = 0
        while True:
            page = validate_response(
                self.http.send(
                    HttpRequest(
                        "GET",
                        self.issue_path(source) + "/comment",
                        params={"startAt": start, "maxResults": 100},
                    )
                ),
                JiraCommentPage,
            )
            if page.startAt != start or (not page.comments and start < page.total):
                raise IntegrationError("validation", "comment pagination")
            result.extend(page.comments)
            start += len(page.comments)
            if start >= page.total:
                return result

    def comment_author(self, comment: JiraComment) -> str:
        return comment.author.accountId

    def comment_text(self, comment: JiraComment) -> str:
        return adf_to_text(comment.body)

    def upsert(self, source: SourceReference, update: CommentUpdate) -> str:
        path = self.issue_path(source) + "/comment"
        method = "POST"
        if update.existing:
            path += "/" + update.existing.id
            method = "PUT"
        comment = validate_response(
            self.http.send(
                HttpRequest(
                    method, path, update.kind, {"body": text_to_adf(update.text)}
                )
            ),
            JiraComment,
        )
        if adf_to_text(comment.body).rstrip() != update.text.rstrip() or (
            update.existing and comment.id != update.existing.id
        ):
            raise IntegrationError("validation", "comment write verification")
        return comment.id

    def ensure_labels(self, source: SourceReference, labels: tuple[str, ...]) -> None:
        self.http.send(
            HttpRequest(
                "PUT",
                self.issue_path(source),
                "labels",
                {"update": {"labels": [{"add": name} for name in labels]}},
            )
        )
        issue = validate_response(
            self.http.send(
                HttpRequest(
                    "GET",
                    self.issue_path(source),
                    params={"fields": "summary,description,labels"},
                )
            ),
            JiraIssue,
        )
        if issue.key != source.reference or not set(labels) <= set(issue.fields.labels):
            raise IntegrationError("remote_error", "label verification")
