"""Adapter for story slicing and GitHub story publication."""

import logging
from contextlib import AsyncExitStack

import httpx

from orchestrator.domain.events import IssueWebhook

logger = logging.getLogger(__name__)


class StorySlicerAdapter:
    async def slice(self, event: IssueWebhook) -> object:
        from story_slicer.adapters.configuration.environment import (
            EnvironmentConfiguration,
        )
        from story_slicer.adapters.llm.selection import create_llm
        from story_slicer.adapters.observability.opentelemetry import (
            OpenTelemetryObservability,
        )
        from story_slicer.adapters.requirements.github import GitHubRequirementLoader
        from story_slicer.application.slice_requirement import (
            SliceRequirement,
            SlicingDependencies,
        )
        from story_slicer.domain.models import StoryBatch
        from story_slicer.ports.requirements import RequirementSource

        settings = EnvironmentConfiguration().load()
        async with AsyncExitStack() as resources:
            client = httpx.AsyncClient(trust_env=False)
            resources.push_async_callback(client.aclose)
            llm = create_llm(settings, client)
            resources.push_async_callback(llm.aclose)
            telemetry = OpenTelemetryObservability.from_settings(settings)
            resources.callback(telemetry.close)

            loader = GitHubRequirementLoader(settings, client)
            dependencies = SlicingDependencies(
                configuration=_LoadedConfiguration(settings),
                requirement_loader=loader,
                llm=llm,
                observability=telemetry,
            )
            batch = await SliceRequirement(dependencies).execute(
                RequirementSource(kind="github", reference=event.issue_reference)
            )
            if not isinstance(batch, StoryBatch):
                raise TypeError("Story Slicer returned an invalid batch")
            return batch


class _LoadedConfiguration:
    def __init__(self, settings: object) -> None:
        self._settings = settings

    def load(self) -> object:
        return self._settings


class GitHubStoryPublisherAdapter:
    async def publish(self, event: IssueWebhook, batch: object) -> object:
        from story_slicer.adapters.configuration.environment import (
            EnvironmentConfiguration,
        )
        from story_slicer.adapters.requirements.github import GitHubStoryPublisher
        from story_slicer.domain.models import StoryBatch
        from story_slicer.ports.requirements import StoryPublishRequest

        if not isinstance(batch, StoryBatch):
            raise TypeError("Story Slicer returned an invalid batch")
        settings = EnvironmentConfiguration().load()
        async with httpx.AsyncClient(trust_env=False) as client:
            result = await GitHubStoryPublisher(settings, client).publish(
                StoryPublishRequest(
                    batch=batch,
                    repository=event.repository.full_name,
                    source_url=event.issue_url,
                )
            )
        return result


