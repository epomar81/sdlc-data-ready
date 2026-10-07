from intention_refiner.adapters.integrations import PositiveId, RemoteModel


class GitHubIdentity(RemoteModel):
    id: PositiveId


class GitHubIssue(GitHubIdentity):
    number: PositiveId
    title: str
    body: str | None
    pull_request: dict | None = None


class GitHubComment(GitHubIdentity):
    body: str
    user: GitHubIdentity
