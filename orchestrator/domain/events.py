"""Validated, framework-independent representations of GitHub issue events.

The models in this module contain only the webhook data used by the
application. Pydantic validates their fields and rejects unknown fields.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model that requires strict field types and forbids extra fields.

    Subclasses inherit these validation rules so malformed or unexpected
    webhook data is rejected at the domain boundary.
    """

    model_config = ConfigDict(extra="forbid", strict=True)


class IssueLabel(StrictModel):
    """A label currently attached to a GitHub issue.

    Attributes:
        name: Non-empty label name.

    Raises:
        pydantic.ValidationError: If ``name`` is empty, has the wrong type, or
            additional fields are supplied.

    Example:
        ``IssueLabel(name="ready-for-slicing")``
    """

    name: str = Field(min_length=1)


class Repository(StrictModel):
    """GitHub repository identity represented as ``owner/name``.

    Attributes:
        full_name: Repository name with one non-empty owner and repository
            component, separated by a slash.

    Raises:
        pydantic.ValidationError: If ``full_name`` does not match the required
            format or additional fields are supplied.

    Example:
        ``Repository(full_name="octo-org/example")``
    """

    full_name: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")


class Issue(StrictModel):
    """The issue fields consumed by the orchestrator.

    Attributes:
        number: Positive GitHub issue number.
        title: Non-empty issue title.
        body: Optional issue description.
        html_url: HTTPS URL for the GitHub issue.
        labels: Labels attached to the issue; defaults to an empty list.

    Raises:
        pydantic.ValidationError: If a required field is missing, a value
            violates its constraints, or additional fields are supplied.

    Example:
        ``Issue(number=42, title="Add export", body=None,
        html_url="https://github.com/octo-org/example/issues/42")``
    """

    number: int = Field(gt=0)
    title: str = Field(min_length=1)
    body: str | None = None
    html_url: str = Field(pattern=r"^https://github\.com/.+/issues/[1-9][0-9]*$")
    labels: list[IssueLabel] = Field(default_factory=list)


class AddedLabel(StrictModel):
    """The label included in a GitHub ``issues.labeled`` event.

    Attributes:
        name: Non-empty name of the label that was added.

    Raises:
        pydantic.ValidationError: If ``name`` is empty, has the wrong type, or
            additional fields are supplied.

    Example:
        ``AddedLabel(name="ready-for-slicing")``
    """

    name: str = Field(min_length=1)


class IssueWebhook(StrictModel):
    """Validated subset of a GitHub issue webhook used by the application.

    Attributes:
        action: Supported issue action, either ``"opened"`` or ``"labeled"``.
        issue: Validated issue details, including labels already on the issue.
        repository: Owner and repository name for the issue.
        label: Label added by a ``labeled`` action, or ``None`` otherwise.

    Raises:
        pydantic.ValidationError: If the action is unsupported, nested data is
            invalid, required fields are missing, or additional fields are
            supplied.

    Example:
        ``IssueWebhook(action="opened", issue=issue,
        repository=Repository(full_name="octo-org/example"))``
    """

    action: Literal["opened", "labeled"]
    issue: Issue
    repository: Repository
    label: AddedLabel | None = None

    def requirement_text(self) -> str:
        """Combine the issue title and non-blank body into requirement text.

        Leading and trailing whitespace is removed from each included part;
        the title and body are separated by a blank line. A missing or
        whitespace-only body is omitted.

        Returns:
            The trimmed title, optionally followed by the trimmed body.

        Example:
            For title ``" Export "`` and body ``" CSV files "``, returns
            ``"Export\n\nCSV files"``.
        """
        parts = [self.issue.title.strip()]
        if self.issue.body and self.issue.body.strip():
            parts.append(self.issue.body.strip())
        return "\n\n".join(parts)

    @property
    def issue_reference(self) -> str:
        """Return the repository-qualified issue number.

        Returns:
            A string in ``owner/repository#number`` form.

        Example:
            ``"octo-org/example#42"``
        """
        return f"{self.repository.full_name}#{self.issue.number}"

    @property
    def issue_url(self) -> str:
        """Return the validated GitHub URL for this issue.

        Returns:
            The issue URL as a plain string.

        Example:
            ``"https://github.com/octo-org/example/issues/42"``
        """
        return str(self.issue.html_url)
