"""Adapter for the existing intention-refiner application service."""

import httpx

from orchestrator.domain.events import IssueWebhook


class IntentionRefinerAdapter:
    def refine(self, event: IssueWebhook) -> object:
        from intention_refiner.adapters.llm.models import build_model
        from intention_refiner.adapters.requirements.github import GitHubAdapter
        from intention_refiner.adapters.requirements.integration_http import (
            CircuitBreaker,
        )
        from intention_refiner.adapters.requirements.integrations import (
            AdapterDependencies,
        )
        from intention_refiner.application.integrations import (
            PublicationRequest,
            PublishRequirement,
        )
        from intention_refiner.application.refine import RefineInitiative
        from intention_refiner.config import LabelPolicy, Settings
        from intention_refiner.domain.integration import (
            SourceProvenance,
            SourceReference,
        )
        from intention_refiner.domain.models import RefinementReport
        from intention_refiner.telemetry import Telemetry

        settings = Settings()
        telemetry = Telemetry(settings.telemetry_enabled, settings.metrics_exporter)
        source = SourceReference("github", event.issue_reference)
        try:
            result = RefineInitiative(build_model(settings), telemetry).execute(
                event.requirement_text()
            )
            report = RefinementReport(
                **result.model_dump(),
                provider=settings.provider,
                model=settings.model,
                source=SourceProvenance(
                    provider="github",
                    identifier=event.issue_reference,
                    url=event.issue_url,
                ),
            )
            with httpx.Client(trust_env=False) as client:
                publisher = GitHubAdapter(
                    AdapterDependencies(
                        settings.integration_config("github"),
                        client,
                        CircuitBreaker(),
                        telemetry,
                    )
                )
                return PublishRequirement(publisher, telemetry).execute(
                    PublicationRequest(
                        source=source,
                        report=report,
                        labels=LabelPolicy().for_source(source),
                    )
                )
        finally:
            telemetry.shutdown()
