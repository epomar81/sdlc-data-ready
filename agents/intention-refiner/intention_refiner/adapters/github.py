from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

import httpx
from githubkit import GitHub
from githubkit.exception import RequestError, RequestFailed

from intention_refiner.adapters.github_models import (
    GitHubComment,
    GitHubIdentity,
    GitHubIssue,
)
from intention_refiner.adapters.integration_http import failure_reason
from intention_refiner.adapters.integrations import (
    AdapterDependencies,
    CommentUpdate,
    RemoteAdapter,
    RemoteLabel,
    validate_response,
)
from intention_refiner.domain.integration import (
    IntegrationError,
    RequirementInput,
    SourceProvenance,
    SourceReference,
)
from intention_refiner.telemetry import PublicationPayloadMetrics


class GitHubAuthenticationError(IntegrationError):
    """Provide authentication guidance without exposing GitHub response data."""

    def __init__(self, status_code: int, operation: str):
        super().__init__("auth", operation)
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code == 401:
            guidance = (
                "INTENTION_REFINER_GITHUB_TOKEN was rejected; it may be invalid, "
                "expired, or revoked. Replace it in .envrc and run source .envrc."
            )
        else:
            guidance = (
                "GitHub denied access. Check INTENTION_REFINER_GITHUB_TOKEN: "
                "allow the target repository and Issues: Read permission "
                "(Issues: Write for --publish). Check organization approval and "
                "SSO authorization if required."
            )
        return f"{super().__str__()} (HTTP {self.status_code}). {guidance}"


def github_failure(response: httpx.Response, operation: str) -> IntegrationError:
    reason = failure_reason(response)
    if reason == "auth":
        return GitHubAuthenticationError(response.status_code, operation)
    return IntegrationError(reason, operation)


class GitHubTransport(httpx.BaseTransport):
    """Instrument SDK requests using the injected client; the SDK owns API plumbing."""

    def __init__(self, dependencies: AdapterDependencies):
        self.dependencies = dependencies
        self.operation: ContextVar[str] = ContextVar("github_operation", default="read")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != "https"
            or request.url.host != "api.github.com"
            or request.url.port not in (None, 443)
        ):
            raise IntegrationError("validation", "GitHub request origin")
        deps = self.dependencies
        probe = deps.breaker.before_request()
        if request.method in {"POST", "PATCH", "PUT"} and deps.telemetry:
            deps.telemetry.record_publication_payload(
                PublicationPayloadMetrics(
                    "github", self.operation.get(), len(request.content)
                )
            )
        try:
            response = deps.client.send(request, follow_redirects=False)
        except httpx.TimeoutException:
            deps.breaker.transport_failure(probe)
            raise IntegrationError("timeout", self.operation.get()) from None
        except httpx.HTTPError:
            deps.breaker.transport_failure(probe)
            raise IntegrationError("network", self.operation.get()) from None
        deps.breaker.after_response(response, probe)
        # Interpret rate limits before SDK retry parsing; Retry-After may be an HTTP date.
        # A 404 remains available to SDK label lookup for create-if-missing behavior.
        if not response.is_success and response.status_code != 404:
            raise github_failure(response, self.operation.get())
        return response


def sdk_operation(method):
    """Keep SDK exceptions and their private payloads outside application contracts."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except RequestFailed as exc:
            raise github_failure(
                exc.response.raw_response, method.__name__
            ) from None
        except RequestError as exc:
            if isinstance(exc.exc, IntegrationError):
                raise exc.exc from None
            raise IntegrationError("network", method.__name__) from None

    return wrapped


class GitHubAdapter(RemoteAdapter):
    def __init__(self, dependencies: AdapterDependencies):
        self.dependencies = dependencies
        self.transport = GitHubTransport(dependencies)
        self.sdk = GitHub(
            dependencies.config.github_token.get_secret_value(),
            transport=self.transport,
            timeout=dependencies.config.timeout_seconds,
            auto_retry=False,
            follow_redirects=False,
            http_cache=False,
        )

    def repository_arguments(self, source: SourceReference) -> dict:
        owner, repository = source.reference.split("#")[0].split("/")
        return {"owner": owner, "repo": repository}

    def issue_arguments(self, source: SourceReference) -> dict:
        return {
            **self.repository_arguments(source),
            "issue_number": int(source.reference.split("#")[1]),
        }

    @sdk_operation
    def read(self, reference: SourceReference) -> RequirementInput:
        source = self.normalize(reference)
        issue = validate_response(
            self.sdk.rest.issues.get(**self.issue_arguments(source)).raw_response,
            GitHubIssue,
        )
        if (
            issue.pull_request is not None
            or str(issue.number) != source.reference.split("#")[1]
        ):
            raise IntegrationError("validation", "issue identity or pull request")
        if not issue.title.strip() and not (issue.body or "").strip():
            raise IntegrationError("validation", "empty requirement")
        repository, number = source.reference.split("#")
        return RequirementInput(
            f"{source.reference}\nTitle: {issue.title}\n\nDescription:\n{issue.body or ''}",
            SourceProvenance(
                provider="github",
                identifier=source.reference,
                url=f"https://github.com/{repository}/issues/{number}",
            ),
        )

    @sdk_operation
    def current_author(self) -> int:
        return validate_response(
            self.sdk.rest.users.get_authenticated().raw_response, GitHubIdentity
        ).id

    @sdk_operation
    def comments(self, source: SourceReference) -> list[GitHubComment]:
        return list(
            self.sdk.rest.paginate(
                self.sdk.rest.issues.list_comments,
                map_func=lambda response: validate_response(
                    response.raw_response, list[GitHubComment]
                ),
                **self.issue_arguments(source),
                per_page=100,
            )
        )

    def comment_author(self, comment: GitHubComment) -> int:
        return comment.user.id

    def comment_text(self, comment: GitHubComment) -> str:
        return comment.body

    @contextmanager
    def operation(self, name: str):
        token = self.transport.operation.set(name)
        try:
            yield
        finally:
            self.transport.operation.reset(token)

    @sdk_operation
    def upsert(self, source: SourceReference, update: CommentUpdate) -> int:
        with self.operation(update.kind):
            if update.existing:
                response = self.sdk.rest.issues.update_comment(
                    **self.repository_arguments(source),
                    comment_id=update.existing.id,
                    body=update.text,
                )
            else:
                response = self.sdk.rest.issues.create_comment(
                    **self.issue_arguments(source), body=update.text
                )
        comment = validate_response(response.raw_response, GitHubComment)
        if comment.body != update.text or (
            update.existing and comment.id != update.existing.id
        ):
            raise IntegrationError("validation", "comment write verification")
        return comment.id

    @sdk_operation
    def ensure_labels(self, source: SourceReference, labels: tuple[str, ...]) -> None:
        with self.operation("labels"):
            for name in labels:
                try:
                    response = self.sdk.rest.issues.get_label(
                        **self.repository_arguments(source), name=name
                    )
                except RequestFailed as exc:
                    if exc.response.status_code != 404:
                        raise
                    response = self.sdk.rest.issues.create_label(
                        **self.repository_arguments(source),
                        name=name,
                        color="7057ff",
                        description="Requirement refinement review",
                    )
                if validate_response(response.raw_response, RemoteLabel).name != name:
                    raise IntegrationError("validation", "label identity")
            response = self.sdk.rest.issues.add_labels(
                **self.issue_arguments(source), labels=list(labels)
            )
            if response.status_code != 204:
                validate_response(response.raw_response, list[RemoteLabel])
            verified = list(
                self.sdk.rest.paginate(
                    self.sdk.rest.issues.list_labels_on_issue,
                    map_func=lambda response: validate_response(
                        response.raw_response, list[RemoteLabel]
                    ),
                    **self.issue_arguments(source),
                    per_page=100,
                )
            )
            if not set(labels) <= {item.name for item in verified}:
                raise IntegrationError("remote_error", "label verification")
