"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from orchestrator.application.router import IssueEventDispatcher
from orchestrator.infrastructure.agents.refiner import IntentionRefinerAdapter
from orchestrator.infrastructure.agents.slicer import (
    GitHubStoryPublisherAdapter,
    StorySlicerAdapter,
)
from orchestrator.infrastructure.inbound.webhooks import create_webhook_router
from orchestrator.infrastructure.observability import OpenTelemetryBatchObservability


def create_app(
    dispatcher: IssueEventDispatcher | None = None,
    webhook_secret: str | None = None,
) -> FastAPI:
    telemetry = OpenTelemetryBatchObservability()
    workflow = dispatcher or IssueEventDispatcher(
        refiner=IntentionRefinerAdapter(),
        slicer=StorySlicerAdapter(),
        publisher=GitHubStoryPublisherAdapter(),
        observability=telemetry,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        telemetry.close()

    application = FastAPI(
        title="SDLC Data Ready Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(create_webhook_router(workflow, webhook_secret))

    @application.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
