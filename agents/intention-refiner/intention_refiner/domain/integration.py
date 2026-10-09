import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Provider = Literal["github", "jira"]
FailureReason = Literal[
    "rate_limit",
    "timeout",
    "auth",
    "circuit_open",
    "validation",
    "network",
    "remote_error",
    "unsupported",
]


@dataclass(frozen=True)
class SourceReference:
    provider: Literal["file", "github", "jira"]
    reference: str


class SourceProvenance(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    provider: Provider
    identifier: str = Field(min_length=1)
    url: str = Field(min_length=1)


@dataclass(frozen=True)
class RequirementInput:
    text: str
    provenance: SourceProvenance | None = None


class PublicationResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    provider: Provider
    identifier: str = Field(min_length=1)
    result_comment_id: int | str
    clarification_comment_id: int | str | None = None
    completed_operations: tuple[
        Literal["result", "clarification", "tag_comments", "labels"], ...
    ]

    @model_validator(mode="after")
    def validate_identifiers(self):
        pattern = r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*" if self.provider == "github" else r"[A-Z][A-Z0-9_]*-[1-9][0-9]*"
        if not re.fullmatch(pattern, self.identifier):
            raise ValueError("Invalid publication issue identity")
        if len(set(self.completed_operations)) != len(self.completed_operations):
            raise ValueError("Duplicate completed operations")
        if (self.clarification_comment_id is not None) != ("clarification" in self.completed_operations):
            raise ValueError("Clarification identifier must match completed operations")
        for identifier in (self.result_comment_id, self.clarification_comment_id):
            if identifier is None:
                continue
            if self.provider == "github" and (
                type(identifier) is not int or identifier <= 0
            ):
                raise ValueError("GitHub comment identifiers must be positive integers")
            if self.provider == "jira" and (
                not isinstance(identifier, str)
                or not identifier.isascii()
                or not identifier.isdigit()
            ):
                raise ValueError("Jira comment identifiers must be numeric strings")
        if "result" not in self.completed_operations:
            raise ValueError("Publication requires a result comment")
        return self


class IntegrationError(ValueError):
    def __init__(self, reason: FailureReason, operation: str = "request"):
        self.reason = reason
        self.completed_operations: tuple[str, ...] = ()
        self.uncertain_operation: str | None = None
        super().__init__(f"Integration {operation} failed: {reason}")
