"""Validated, framework-independent webhook events."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class IssueLabel(StrictModel):
    name: str = Field(min_length=1)


class Repository(StrictModel):
    full_name: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")


class Issue(StrictModel):
    number: int = Field(gt=0)
    title: str = Field(min_length=1)
    body: str | None = None
    html_url: str = Field(pattern=r"^https://github\.com/.+/issues/[1-9][0-9]*$")
    labels: list[IssueLabel] = Field(default_factory=list)


class AddedLabel(StrictModel):
    name: str = Field(min_length=1)


class IssueWebhook(StrictModel):
    """The subset of a GitHub issue webhook used by the application."""

    action: Literal["opened", "labeled"]
    issue: Issue
    repository: Repository
    label: AddedLabel | None = None

    def requirement_text(self) -> str:
        parts = [self.issue.title.strip()]
        if self.issue.body and self.issue.body.strip():
            parts.append(self.issue.body.strip())
        return "\n\n".join(parts)

    @property
    def issue_reference(self) -> str:
        return f"{self.repository.full_name}#{self.issue.number}"

    @property
    def issue_url(self) -> str:
        return str(self.issue.html_url)
