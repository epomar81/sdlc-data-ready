# Story Slicer

Story Slicer will turn product requirements into atomic, independent, valuable
user stories guided by INVEST, with Gherkin acceptance criteria and strict
Pydantic schemas. Domain models, ports, environment configuration, bounded file
reads, Gemini/NVIDIA, OpenTelemetry, and the self-healing core engine are
implemented. Invoke slicing with `await SliceRequirement(dependencies).execute(path)`.

## Development

Requires Python 3.14 and `uv`. Dependencies are pinned in `uv.lock`.
Run the following commands from the project root. Testing and running use the
source checkout; no `make build`, binary, or package from `dist/` is required.

Install the runtime and development dependencies into `.venv`:

```sh
uv sync --locked
```

Run the tests, or run linting and tests together:

```sh
make test
make quality
```

To run the application, copy `.envrc.example` to `.envrc` if you do not already
have one, then edit the exported `STORY_SLICER_GEMINI_API_KEY` and
`STORY_SLICER_LLM_MODEL` with your credentials and model ID. `.envrc` is ignored
by Git; `.envrc.example` contains placeholders.

With direnv installed and its shell hook enabled, run from the project root:

```sh
cp -n .envrc.example .envrc
direnv allow
```

Direnv loads the exported settings when you enter the project directory. Run
`direnv allow` again after editing `.envrc`. If you do not use direnv, load the
file manually in your current shell with `source .envrc`.

Create `my_feature.yaml` using the product input contract below, then run:

```sh
make run
```

The `.envrc` sets `STORY_SLICER_INPUT_PATH=my_feature.yaml` as the default input
for `make run`. Edit this value to point to your YAML file. Relative paths resolve
from your terminal's current directory; absolute paths are also supported.
After editing `.envrc`, reload it with direnv or `source .envrc`.

For example, if your YAML file is `requirements/checkout.yaml`, run it from the
project root with the Makefile:

```sh
make run FILE=requirements/checkout.yaml
```

The `run` target executes `uv run --locked python cli.py` with the configured
path. An explicit `FILE=...` overrides `STORY_SLICER_INPUT_PATH` for that run.
The run target reloads the project-root `.envrc` before starting the CLI, so edits
to provider settings override stale terminal values. It uses the source checkout, so
you do not need to build the package or activate `.venv` first.

Paths containing spaces can be passed as `make run FILE="my feature.yaml"`.
The CLI automatically saves the resulting story batch to `stories.json` and
prints the saved path. Choose a different destination with `OUTPUT` or the
CLI's `--output` (`-o`) option:

```sh
make run OUTPUT=results/stories.json
uv run --locked python cli.py my_feature.yaml --output results/stories.json
```

You can also test and run without Make or activating the virtual environment:

```sh
uv run --locked pytest
uv run --locked python cli.py my_feature.yaml
```

If you prefer invoking Python directly, activate the virtual environment first:

```sh
source .venv/bin/activate
python cli.py my_feature.yaml
```

`make build` is optional and produces a wheel and source distribution in `dist/`
for packaging.

`make lint` runs Ruff lint, a formatting check, and strict mypy checks without
rewriting files. `make test` runs the offline pytest suite; tests require no
provider credentials, network, or telemetry backend. To format intentionally,
run `uv run --locked ruff format .`.

The suite covers domain models, ports, architecture, adapters, orchestration,
the CLI, and Makefile targets. HTTP calls use mocked transports; telemetry uses
in-memory SDK collectors. Live provider and collector connectivity are not
tested by this suite.

Use TDD: write a failing unit test before behavior, implement minimally, then
refactor. Every handwritten function or method accepts at most two parameters
excluding `self`/`cls`; use typed request objects for compound data. Run both
Makefile targets after changes. Architecture tests check domain imports and
function signatures.

## Architecture

| Hexagonal role | Implemented package | Responsibility |
| --- | --- | --- |
| Domain | `story_slicer.domain.models` | Requirement, story, scenario, metadata, and final-batch validation. |
| Ports and contracts | `story_slicer.ports` | Provider-neutral protocols, requests/results, runtime settings, telemetry events, and shared errors. |
| Adapters | `story_slicer.adapters` | Environment configuration, bounded local file reads, safe YAML parsing, Gemini/NVIDIA HTTP APIs, and OpenTelemetry. |
| Application | `story_slicer.application` | Prompts, ID assignment, bounded self-healing, deadlines, and session lifecycle. |

Domain dependencies are limited to Pydantic and Python's standard library.
Domain code does not import SDKs, YAML, OpenTelemetry, environment access, or
filesystem APIs. Ports depend on domain models, never concrete adapters.

`create_llm(settings)` selects the model adapter from environment settings.
Provider selection must not change domain or application code. YAML carries
product data only; all runtime configuration comes from environment variables
through the central configuration adapter. For local development, direnv exports
settings from the project-root `.envrc`. The adapter reads the process environment
and does not execute configuration files. YAML settings are not supported.

The Gemini base URL must point to the REST API:
`STORY_SLICER_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta`.
An AI Studio API-key page URL is not an API endpoint and may return HTTP 302.
After changing `.envrc`, reload it with `source .envrc` or `direnv allow`.

## Product input contract

`RequirementDocument` describes YAML product input. The engine reads the requested
file through `FileSystemPort`, then decodes/parses its bytes through
`RequirementParserPort`. `YamlRequirementParser` uses a safe UTF-8 YAML loader and
rejects duplicate keys, multiple documents, unsupported tags, and invalid input
schemas. Parsing errors become `InputError` with YAML line/column locations or
schema field paths and validation messages, without displaying input values or
source excerpts. List indices in field paths are zero-based (for example,
`requirements.0.description`). The CLI prints these details to stderr.

Input requires an explicit file path: `RequirementSource(path="requirements.yaml")`.
Absolute paths are used directly, and relative paths resolve against the process
working directory. The Makefile passes `STORY_SLICER_INPUT_PATH` from `.envrc`
as this explicit path unless `FILE=...` overrides it. Direct CLI calls still
require a path argument. There is no directory scanning.

```yaml
project: SHOP
requirements:
  - description: Customers need to track delivery of their orders.
    context: Customers already have an account and order history.
    constraints:
      - Show only the customer's own orders.
```

`project` starts with a letter and contains only letters, digits, underscores,
or hyphens. `requirements` is nonempty; each item requires a nonblank
`description`. Optional `context` defaults to `null` and must be nonblank when
provided. Optional `constraints` defaults to an empty list; each entry must be
nonblank. Unknown fields, including runtime settings, are rejected.

### Initiative-refiner input

The parser also accepts the initiative-refiner output directly: `initiative`,
`suggestions`, `audit`, `refinement_proposals`, and `metadata`. The initiative
requires a nonblank `title` and at least one of `problem_statement`,
`business_scope`, or `desired_outcomes`. Other initiative fields may be null.

The parser normalizes it into one source requirement for the agent to split.
The complete document is retained as context, including exclusions, metrics,
clarification questions, audit findings, and proposed refinements. Proposals are
not treated as approved facts. A project prefix is derived from the initiative
ID, or its title when the ID is absent, by replacing unsupported characters with
hyphens and adding `INIT-` when needed to start with a letter.

## Story output contract

`StoryBatch` is the final JSON envelope. Each story has exactly the fields shown
below, and each acceptance scenario has exactly `Scenario`, `Given`, `When`,
and `Then`.

```json
{
  "stories": [
    {
      "ID": "SHOP-1",
      "title": "Track an order",
      "Who": "Customer",
      "Action_What": "View the shipping status of my order",
      "Benefit_Why": "Know when to expect delivery",
      "Priority": "HIGH",
      "acceptance_criteria": [
        {
          "Scenario": "View a shipped order",
          "Given": "The customer's order has shipped",
          "When": "The customer opens that order",
          "Then": "The current shipping status is displayed"
        }
      ],
      "tags": [],
      "clarification": "",
      "suggestions": []
    }
  ]
}
```

All story fields are required. Validation is strict, forbids extra fields, and
rejects blank story/scenario text. `Priority` is `HIGH`, `MEDIUM`, or `LOW`.
Each story has at least one acceptance scenario; each batch has at least one
story with unique IDs.

`ID` is `<project>-<positive integer>` with no leading zeros in the number.
The engine validates individual LLM stories, replaces their IDs with sequential
project-prefixed IDs in output order, then validates the final batch. Duplicate
provisional LLM IDs alone do not trigger repair. Numbering restarts per invocation;
persistent numbering is outside the first release.

`tags` is a list of nonblank strings. `clarification` and `suggestions` each
accept a string or a list of nonblank strings. Empty strings/lists are allowed
only without the exact reserved tag `MISSING_INFO`; whitespace-only values are
always invalid. With that tag, both fields must contain meaningful text.
Clarifications ask about unresolved critical information; suggestions describe
assumptions or why no safe assumption can be made. Such stories are valid drafts
requiring Product Owner review, not implementation-ready stories.

Pydantic validates structure and metadata consistency. INVEST, independence,
atomicity, and recognition of missing business information are semantic goals
for prompts and review; schemas cannot prove them.

```python
from story_slicer.domain.models import StoryBatch

# Validate a final batch decoded by the caller:
# batch = StoryBatch.model_validate(data)
schema = StoryBatch.model_json_schema()
```

## Port contracts

| Protocol | Methods | Contract |
| --- | --- | --- |
| `LLMPort` | Async `generate(request)` | Takes `GenerationRequest`, returns raw `GenerationResult` text and `TokenUsage`. |
| `ConfigurationPort` | Sync `load()` | Returns validated, immutable `RuntimeSettings`. |
| `FileSystemPort` | Async `read(request)` | Takes `FileReadRequest(path, max_bytes)`, returns raw bytes or raises `InputError`. |
| `RequirementParserPort` | Sync `parse(content)` | Converts raw bytes to `RequirementDocument` or raises `InputError`. |
| `RequirementInputPort` | Async `load(source)` | Combined input contract; the engine uses separate filesystem and parser ports. |
| `ObservabilityPort` | Sync `start_session(context)` and `record(event)` | Starts timing, records a start event, returns a `SessionHandle`, then accepts typed lifecycle events. |

`GenerationRequest` carries instructions, requirement data, a JSON schema, and
optional `RepairFeedback` with the previous raw response and exact diagnostic.
Its Python schema attribute is `json_schema`; the serialized field is `schema`.
Adapters return raw output, including malformed output, for application
validation. Missing input/output token counts are `None`, never fabricated zeroes.
Counts must be nonnegative integers.

Telemetry has a discriminated `kind` union: `session_started`,
`attempt_completed`, `schema_failure`, `repair_scheduled`, `operational_alert`,
`critical_alert`, and `session_completed`. Events carry a session handle;
attempt numbers start at one. Completion includes finite nonnegative elapsed
seconds, outcome, known token counts, and `usage_complete`. Complete usage
requires both counts; partial aggregates may carry known counts with
`usage_complete=false`. Outcomes are `success`, `invalid_input`,
`provider_failure`, `timeout`, `aborted`, and `cancelled`.

Operational alerts have warning severity and a schema error rate in [0, 1].
Critical alerts have critical severity and reason `unstable_llm`. Events contain
no raw requirements, prompts, responses, credentials, or validation diagnostics.
Adapters must keep session IDs out of metric labels and isolate export failures.
Port objects are frozen; nested lists/dictionaries must be treated as read-only.

Shared failures derive from `StorySlicerError`: `ConfigurationError`, `InputError`,
`ProviderError`, `SessionTimeoutError`, and `ValidationExhaustedError`. Boundary
implementations must use sanitized messages without provider-specific payloads.

## Runtime settings contract

`EnvironmentConfiguration().load()` reads the following environment variables.
Call it once at startup and inject the resulting settings. The adapter reads
exported environment variables (or an explicitly injected environment mapping).
It does not load files; direnv loads `.envrc` before the application starts.
Network telemetry export defaults to disabled for local development; all other
operational settings remain explicit.

For local CLI use, copy `.envrc.example` to `.envrc`, replace the provider model and API
key, and enable direnv with its shell hook. The `.envrc` file is ignored by Git.
Install dependencies and run from the project root:

```sh
uv sync --locked
direnv allow
uv run --locked python cli.py my_feature.yaml
```

Results are saved as UTF-8 JSON to `stories.json` by default. Missing output
directories are created. A successful run replaces an existing output file;
generation failures leave it unchanged. Output write failures print an error and
exit with status 1. The output path must differ from the input path. The example
telemetry endpoint is used only with `OTEL_EXPORT_MODE=otlp`. Local runs need no
collector: `OTEL_EXPORT_MODE=disabled` prevents network export while keeping local
instrumentation. To export telemetry, set `OTEL_EXPORT_MODE=otlp` and point
`OTEL_EXPORTER_OTLP_ENDPOINT` to a running OTLP/HTTP collector.

| Environment variable | `RuntimeSettings` field |
| --- | --- |
| `STORY_SLICER_LLM_PROVIDER` | `provider` (`gemini`, `nvidia`, or `openai`) |
| `STORY_SLICER_LLM_MODEL` | `model` |
| `STORY_SLICER_GEMINI_API_KEY` | `gemini_api_key` |
| `STORY_SLICER_GEMINI_BASE_URL` | `gemini_base_url` (e.g. `https://generativelanguage.googleapis.com/v1beta`) |
| `STORY_SLICER_OPENAI_API_KEY` | `openai_api_key` |
| `STORY_SLICER_OPENAI_BASE_URL` | `openai_base_url` (e.g. `https://api.openai.com/v1`) |
| `STORY_SLICER_NVIDIA_API_KEY` | `nvidia_api_key` |
| `STORY_SLICER_NVIDIA_BASE_URL` | `nvidia_base_url` |
| `STORY_SLICER_MAX_RETRIES` | `max_retries` (nonnegative additional repairs) |
| `STORY_SLICER_REQUEST_TIMEOUT_SECONDS` | `request_timeout_seconds` (finite and positive) |
| `STORY_SLICER_SESSION_TIMEOUT_SECONDS` | `session_timeout_seconds` (finite and positive) |
| `STORY_SLICER_MAX_INPUT_BYTES` | `max_input_bytes` (positive integer) |
| `STORY_SLICER_SCHEMA_ERROR_RATE_THRESHOLD` | `schema_error_rate_threshold` ([0, 1]) |
| `STORY_SLICER_SCHEMA_ERROR_MIN_ATTEMPTS` | `schema_error_min_attempts` (positive integer) |
| `OTEL_EXPORT_MODE` | `otel_export_mode` (`disabled` by default, or `otlp`) |
| `OTEL_SERVICE_NAME` | `otel_service_name` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `otel_exporter_otlp_endpoint` (HTTP/HTTPS URL) |
| `OTEL_EXPORT_INTERVAL_SECONDS` | `otel_export_interval_seconds` (finite and positive) |
| `OTEL_EXPORT_TIMEOUT_SECONDS` | `otel_export_timeout_seconds` (finite and positive) |

OpenAI credentials/endpoints default to `None` when constructing `RuntimeSettings`;
the selected provider must have its key and endpoint. Inactive-provider
credentials/endpoints may be `None`; the adapter supplies these null values when
their variables are absent. Each provider requires its respective key and base
URL. For NVIDIA, the base URL includes `/v1`, for example
`https://integrate.api.nvidia.com/v1`. Model/service names and credentials cannot
be blank. Credentials use `SecretStr` to mask representations and JSON output.
The adapter converts numeric environment strings before strict validation and
reports field/variable names without exposing rejected values.

Example configuration (replace the model and key):

```sh
export STORY_SLICER_LLM_PROVIDER=gemini
export STORY_SLICER_LLM_MODEL=your-gemini-model
export STORY_SLICER_GEMINI_API_KEY=your-api-key
export STORY_SLICER_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
export STORY_SLICER_MAX_RETRIES=2
export STORY_SLICER_REQUEST_TIMEOUT_SECONDS=900
export STORY_SLICER_SESSION_TIMEOUT_SECONDS=2700
export STORY_SLICER_MAX_INPUT_BYTES=65536
export STORY_SLICER_SCHEMA_ERROR_RATE_THRESHOLD=0.5
export STORY_SLICER_SCHEMA_ERROR_MIN_ATTEMPTS=2
export OTEL_SERVICE_NAME=story-slicer
export OTEL_EXPORT_MODE=disabled
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORT_INTERVAL_SECONDS=30
export OTEL_EXPORT_TIMEOUT_SECONDS=5
```

These are example values, not application defaults. To select OpenAI or NVIDIA, set `STORY_SLICER_LLM_PROVIDER` to the provider name
and configure its corresponding API key and base URL. You can keep credentials
for multiple providers in `.envrc`; only the selected provider needs a nonblank
key and endpoint. Empty settings for inactive providers are treated as unset.
To select NVIDIA, set
`STORY_SLICER_LLM_PROVIDER=nvidia`, its model, `STORY_SLICER_NVIDIA_API_KEY`, and
`STORY_SLICER_NVIDIA_BASE_URL`; Gemini variables may be absent.

To select OpenAI, set these values in `.envrc` (retain your existing input path):

```sh
export STORY_SLICER_LLM_PROVIDER=openai
export STORY_SLICER_LLM_MODEL=your-openai-model-id
export STORY_SLICER_OPENAI_API_KEY=your-openai-api-key
export STORY_SLICER_OPENAI_BASE_URL=https://api.openai.com/v1
```

Choose a Responses API model that supports JSON mode and is available to your
API project. Run `make run`; it reloads `.envrc` and saves `stories.json`.
The CLI reads `STORY_SLICER_OPENAI_API_KEY`; the local `.envrc` can also populate
it from an exported `OPENAI_API_KEY`. Keep actual keys in the ignored `.envrc`.

The OpenAI adapter sends one request to `/v1/responses`, uses JSON mode with
`store=false`, and carries the schema in instructions. Pydantic validates the
result and the existing application repair flow handles invalid story output.
JSON mode does not itself guarantee schema compliance. Refused, incomplete, or
malformed response envelopes produce `ProviderError`. Input/output token usage is
normalized, with absent usage left unknown. Transport failures are not retried.
See the [official OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

## Phase 2 adapters

**File access:** `LocalFileSystem.read()` runs a bounded binary read in a worker
thread. It reads at most `max_bytes + 1` to detect oversized files and maps
unreadable paths and size-limit failures to `InputError`. YAML parsing is a
separate concern.

```python
from story_slicer.adapters.configuration.environment import EnvironmentConfiguration
from story_slicer.adapters.filesystem.local import LocalFileSystem
from story_slicer.ports.filesystem import FileReadRequest


async def read_requirements(path: str) -> bytes:
    settings = EnvironmentConfiguration().load()
    return await LocalFileSystem().read(
        FileReadRequest(path=path, max_bytes=settings.max_input_bytes)
    )
```

**Models:** the abstract `LLMPort` is implemented by `GeminiAdapter` and
`NvidiaAdapter`. `create_llm(settings)` chooses the configured implementation.
Both use async HTTP, a per-request timeout, sanitized shared errors, and exactly
one HTTP call per generation. Raw model text remains available for application
validation and repair, even when it is not valid JSON.

Gemini requests JSON output using `generationConfig.responseJsonSchema` with
the supplied schema. NVIDIA receives the schema in its system instructions,
avoiding assumptions about constrained-output support across its models. Local
Pydantic validation is performed by the core engine. Gemini output usage includes
reported thinking tokens; unavailable token counts remain `None`.

```python
from story_slicer.adapters.llm.selection import create_llm
from story_slicer.domain.models import RequirementDocument, StoryBatch
from story_slicer.ports.llm import GenerationRequest, GenerationResult


async def generate_stories(requirement: RequirementDocument) -> GenerationResult:
    adapter = create_llm(EnvironmentConfiguration().load())
    try:
        return await adapter.generate(
            GenerationRequest(
                instructions="Slice into independent, valuable stories.",
                requirement=requirement,
                json_schema=StoryBatch.model_json_schema(),
            )
        )
    finally:
        await adapter.aclose()
```

This example makes a single model call. Adapters close
their own HTTP clients through `aclose()`; injected clients remain caller-owned.
Provider/API references: [Gemini generateContent](https://ai.google.dev/api/generate-content)
and [NVIDIA LLM APIs](https://docs.api.nvidia.com/nim/reference/llm-apis).

**Telemetry:** `OpenTelemetryObservability.from_settings(settings)` creates
local tracer/meter providers with OTLP/HTTP exporters. The collector base URL
is extended with `/v1/traces` and `/v1/metrics`; export interval and timeout are
explicit settings. No global providers are replaced. Call `close()` on shutdown
to finish active spans, flush, and stop its providers.

The adapter records session spans, child attempt spans, duration histograms,
session outcome/schema failure/repair/alert counters, and known aggregate tokens
once per completed session. Token totals are supplied by the application,
including failed attempts; the adapter does not sum them again. Metric labels
use provider, finite classifications/outcomes, severity, and token direction,
never session IDs or raw product data.

Operational and critical alerts are structured span events carrying severity
and trace correlation. The application decides when to emit them; backend
paging is external. Export/recording failures do not escape to the caller.
Constructor injection supports in-memory collectors for offline tests. See
[OpenTelemetry Python exporters](https://opentelemetry.io/docs/languages/python/exporters/).

## Core engine

`SliceRequirement` takes a `SlicingDependencies` struct containing configuration,
filesystem, parser, LLM, and observability ports. It loads immutable runtime
settings once at construction. Session state is local to each execution, so one
use case instance can serve concurrent invocations.

```python
from story_slicer.application.slice_requirement import (
    SliceRequirement,
    SlicingDependencies,
)
from story_slicer.domain.models import StoryBatch


async def slice_yaml(path: str, dependencies: SlicingDependencies) -> StoryBatch:
    return await SliceRequirement(dependencies).execute(path)
```

For production, supply `EnvironmentConfiguration`, `LocalFileSystem`,
`YamlRequirementParser`, the adapter selected by `create_llm(settings)`, and
`OpenTelemetryObservability`. Provider/client and telemetry shutdown belong to
the caller; the engine finishes each session but keeps shared adapters available.

Execution follows this sequence:

1. Read the explicit path with the configured byte limit. File access failures
   raise `InputError` before opening a session. File reading is bounded by the
   session timeout setting.
2. Start the observability session and monotonic elapsed-time measurement, then
   parse and validate the YAML. Session latency measures parsing and all model
   attempts after file reading.
3. Request independent, valuable INVEST stories with Gherkin scenarios and the
   metadata rules. Treat product requirements as data, not overriding instructions.
4. Parse strict JSON, rejecting duplicate keys, nonstandard numeric constants,
   fenced output, and surrounding prose. Validate each story, assign authoritative
   project-prefixed IDs, and validate the final `StoryBatch`.
5. On parsing/Pydantic failure, record `SchemaFailure`. When a repair remains,
   record `RepairScheduled` and send the original requirements, previous response,
   and exact error message through `RepairFeedback` with correction instructions.
   Validation messages are not exported to telemetry; Pydantic hides input values
   in displayed diagnostics.
6. Allow at most `1 + max_retries` model calls. Emit one operational alert per
   session when the schema-error rate reaches its configured threshold after the
   minimum completed responses. Exhaustion emits `CriticalAlert` and raises
   `ValidationExhaustedError`, without returning partial results.
7. On success, return validated `StoryBatch` objects and record completion with
   total monotonic latency and known input/output tokens across all attempts.
   Missing usage stays unknown; partial known totals have `usage_complete=false`.

Per-request and whole-session deadlines apply to model calls. Provider failures
terminate immediately; only parsing/schema errors trigger repair. Completion is
recorded for success, exhaustion, invalid YAML, provider failure, timeout, and
cancellation. Fleet-wide alerting and paging remain telemetry backend concerns.

The three mock-port tests cover first-attempt success, successful self-healing
after a `MISSING_INFO` validation failure, and persistent parsing failure through
retry exhaustion. They verify exact repair feedback, call limits, authoritative
IDs, aggregate/unknown usage, repair metrics, and operational/critical alerts.

Local example settings allow 900 seconds (15 minutes) per LLM request and
2700 seconds (45 minutes) for the slicing session, including schema repair
attempts. These are upper limits; successful requests return immediately. Tune
`STORY_SLICER_REQUEST_TIMEOUT_SECONDS` and
`STORY_SLICER_SESSION_TIMEOUT_SECONDS` in `.envrc` for your provider latency.
Timeout errors identify the request or session limit; timed-out calls are not
automatically retried.
