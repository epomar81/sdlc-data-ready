# GitHub Webhook Orchestrator

FastAPI service that routes GitHub issue events to the intention refiner and
story slicer agents. Matching deliveries are acknowledged with HTTP 200 and
processed with FastAPI `BackgroundTasks` in the service process.

## Local setup

Use Python 3.12 for the orchestrator. The agent packages are imported from the
workspace without installing them as local distributions. From the repository
root, expose their package roots on `PYTHONPATH`:

```sh
cd /path/to/sdlc-data-ready
export PYTHONPATH="$PWD/agents/intention-refiner:$PWD/agents/story-slicer/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
```

Install the orchestrator and both agents' external dependencies into the active
environment. The project manifest does not install either agent as a local
distribution:

```sh
uv sync --project orchestrator --python 3.12 --group dev
uv run --project orchestrator --python 3.12 uvicorn orchestrator.infrastructure.inbound.app:app --reload
```

The service listens on `http://127.0.0.1:8000`; the webhook endpoint is
`POST /webhooks/github`.

## Environment

Set `GITHUB_WEBHOOK_SECRET` to the webhook secret configured in GitHub.

Agent 01 requires `INTENTION_REFINER_PROVIDER` (`gemini` or `nvidia`),
`INTENTION_REFINER_MODEL`, and the selected provider's
`INTENTION_REFINER_GEMINI_API_KEY` or `INTENTION_REFINER_NVIDIA_API_KEY`.
Set `INTENTION_REFINER_GITHUB_TOKEN` with permission to read and comment on the
source issue and apply its configured labels.

Agent 02 requires `STORY_SLICER_LLM_PROVIDER`, `STORY_SLICER_LLM_MODEL`, and
the selected provider's API key and base URL:
`STORY_SLICER_GEMINI_API_KEY` / `STORY_SLICER_GEMINI_BASE_URL`,
`STORY_SLICER_NVIDIA_API_KEY` / `STORY_SLICER_NVIDIA_BASE_URL`, or
`STORY_SLICER_OPENAI_API_KEY` / `STORY_SLICER_OPENAI_BASE_URL`. Set
`STORY_SLICER_GITHUB_TOKEN` with permission to read the source issue and create
issues, labels, and comments in the target repository.

Set `OTEL_EXPORT_MODE=otlp` to enable Agent 02 OTLP export. Configure
`OTEL_EXPORTER_OTLP_ENDPOINT` (for example, `http://localhost:4318`),
`OTEL_SERVICE_NAME`, `OTEL_EXPORT_INTERVAL_SECONDS`, and
`OTEL_EXPORT_TIMEOUT_SECONDS`. The orchestrator's batch metrics use the same
endpoint. With export disabled, telemetry instruments are still recorded
in-process but are not exported.

Agent 02 also requires `STORY_SLICER_MAX_RETRIES`,
`STORY_SLICER_REQUEST_TIMEOUT_SECONDS`, `STORY_SLICER_SESSION_TIMEOUT_SECONDS`,
`STORY_SLICER_MAX_INPUT_BYTES`, `STORY_SLICER_SCHEMA_ERROR_RATE_THRESHOLD`,
and `STORY_SLICER_SCHEMA_ERROR_MIN_ATTEMPTS`. The OTel variables above are
required by its settings loader even when export is disabled. See
`agents/intention-refiner/intention_refiner/config.py` and
`agents/story-slicer/src/story_slicer/adapters/configuration/environment.py`
for defaults and optional settings.

## Tests

From the repository root, with the `PYTHONPATH` above and development
dependencies installed, run:

```sh
uv run --project orchestrator --python 3.12 pytest orchestrator/tests
```
