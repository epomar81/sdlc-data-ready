# Intention refiner

Intention refiner reads one software initiative from a UTF-8 file, GitHub issue, or Jira Cloud issue and saves a structured YAML report. Remote runs can optionally publish results, clarification questions, and review labels back to the originating issue. It extracts facts, identifies gaps and ambiguous language, and proposes improvements for review. Missing facts remain `null` in the extracted initiative; proposed values appear separately as suggestions.

## Run from source

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). You can run the package directly from the source tree; you do not need to build a binary or install the `intention-refiner` executable. Configure the environment variables below, then run:

```sh
uv run python -m intention_refiner path/to/initiative.txt
```

`uv` resolves the project dependencies and runs the module from the checkout. The default output is `output_requirements.yaml` in the current directory. The command exits with status 1 and prints an error if configuration, input, model response, or output fails. It does not replace an existing report on failure.

Set `INTENTION_REFINER_OUTPUT_PATH` to save the report to a different location. The path may be relative to the current directory or absolute, and its parent directory must already exist:

```sh
INTENTION_REFINER_OUTPUT_PATH=reports/initiative.yaml uv run python -m intention_refiner path/to/initiative.txt
```

The Makefile provides the same source-based run command:

```sh
make run ARGS="path/to/initiative.txt"
```

Set `INTENTION_REFINER_OUTPUT_PATH` before `make` to choose a different report location:

```sh
INTENTION_REFINER_OUTPUT_PATH=reports/initiative.yaml make run ARGS="/tmp/example/initiative.txt"
```

If you prefer pip, install the project in editable mode with `python -m pip install -e .`, then run `python -m intention_refiner path/to/initiative.txt`.

## Test and lint

Run the unit tests without building a binary or installing the command-line executable:

```sh
uv run --extra test pytest
```

Or use the Makefile targets. `make quality` runs both the linter and the tests:

```sh
make test
make lint
make quality
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `INTENTION_REFINER_PROVIDER` | Required: `gemini` or `nvidia`. |
| `INTENTION_REFINER_MODEL` | Required: model identifier accepted by the selected provider. |
| `INTENTION_REFINER_GEMINI_API_KEY` | Required when using Gemini. |
| `INTENTION_REFINER_NVIDIA_API_KEY` | Required when using NVIDIA. |
| `INTENTION_REFINER_TIMEOUT_SECONDS` | Optional request timeout; defaults to `120`. |
| `INTENTION_REFINER_OUTPUT_PATH` | Optional YAML output path; defaults to `output_requirements.yaml`. Its parent directory must exist. |
| `INTENTION_REFINER_TELEMETRY_ENABLED` | Optional: enable OTLP/HTTP traces; defaults to `false`. Metrics remain active independently. |
| `INTENTION_REFINER_METRICS_EXPORTER` | `console` (default) or `otlp`; controls model and integration metric export. |
| `INTENTION_REFINER_GITHUB_TOKEN` | Required for GitHub input; token with Issues read access. Publishing also needs Issues write access. |
| `INTENTION_REFINER_JIRA_BASE_URL` | Required for Jira: HTTPS site origin, e.g. `https://team.atlassian.net`. |
| `INTENTION_REFINER_JIRA_EMAIL` | Required for Jira: account email. |
| `INTENTION_REFINER_JIRA_API_TOKEN` | Required for Jira: site-compatible API token used with Basic authentication. |
| `INTENTION_REFINER_INTEGRATION_TIMEOUT_SECONDS` | Positive per-request timeout for source and publication HTTP calls; defaults to `30`. |

For OTLP export, configure the destination using the standard OpenTelemetry OTLP environment variables, such as `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`. The service name is `intention-refiner`. Each CLI invocation receives a correlation ID that appears in its JSON logs and root trace. The YAML report does not contain the correlation ID. Telemetry records operation status, provider/model, request duration, token counts, publication outcomes, and publication payload sizes; initiative text, prompts, generated responses, and exception messages are never recorded. Existing console logs are not exported as an OpenTelemetry log signal.

Example:

```sh
export INTENTION_REFINER_TELEMETRY_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
intention-refiner path/to/initiative.txt
```

For example:

```sh
export INTENTION_REFINER_PROVIDER=gemini
export INTENTION_REFINER_MODEL=your-gemini-model
export INTENTION_REFINER_GEMINI_API_KEY=your-api-key
intention-refiner path/to/initiative.txt
```

The tool reads the process environment; it does not load `.env` files itself. To load settings automatically when entering the project directory, install [direnv](https://direnv.net/), copy `.envrc.example` to `.envrc`, replace the placeholder model and API key, then run `direnv allow` in the project directory. `.envrc` is ignored by Git so your local API key is not committed. The example uses Gemini; for NVIDIA, set `INTENTION_REFINER_PROVIDER="nvidia"` and `INTENTION_REFINER_NVIDIA_API_KEY` instead.

## Console logging

The command prints one JSON object per log line, with `level` and `message` fields. Each completed model request reports the exact prompt, completion, and total token counts returned by the provider. Each suggestion logs its field and tag without logging its content. The CLI logs each failure once at the command boundary and exits with status 1.

The model port returns both the generated text and provider usage metadata. Gemini usage comes from `usage_metadata`; NVIDIA usage comes from the chat completion's `usage` object. Token counts are kept in the model response and logged after the request succeeds. If a model request or response validation fails, the error propagates to the CLI and is logged once there.

Run the self-contained demonstration from the repository root. It uses a local fake model, needs no API key, and prints representative token and suggestion logs:

```sh
uv run python examples/logging_demo.py
```

Example output:

```text
{"level": "info", "message": "Token usage: Prompt tokens: 120, Completion tokens: 45, Total tokens: 165"}
{"level": "info", "message": "Suggestion created", "event": "suggestion_created", "field_name": "target", "tag": "AI_ENHANCED"}
```

The demo's model adapter shows the response contract used by real adapters:

```python
ModelResponse(
    text='{"initiative": {}, "suggestions": [...], ...}',
    prompt_tokens=120,
    completion_tokens=45,
    total_tokens=165,
)
```

## Report

The YAML report has four sections:

- `initiative`: one requirement with `id`, `title`, `problem_statement`, `target`, `business_value`, `business_scope`, `ex_scope`, `kpi`, and `desired_outcomes`.
- `suggestions`: field-linked recommendations tagged `AI_ENHANCED`, `FEATURE_IDEA`, or `CLARIFICATION`.
- `audit`: lists of ambiguities, missing information, and other risks.
- `metadata`: provider, model, model response time in milliseconds, and optional remote `source` provenance (`provider`, `identifier`, `url`). Local reports omit source provenance.

The model generates the content, so a person should review its suggestions before treating them as requirements. DORA metrics are suggested only when the initiative concerns software delivery performance.

## Architecture

The package uses ports and adapters to keep the refinement workflow separate from model SDKs and file handling:

| Hexagonal role | Current module | Responsibility |
| --- | --- | --- |
| Domain | `intention_refiner/domain/models.py` | Validated initiative, suggestions, audit, and report types. |
| Application ports | `intention_refiner/application/ports.py` | Model generation, requirement loading, and issue publication contracts. |
| Application use case | `intention_refiner/application/refine.py` | Builds the prompt, calls the model port, parses its JSON, and validates the result. |
| Model adapters | `intention_refiner/adapters/models.py` | Gemini and NVIDIA implementations of the model port. |
| File adapters | `intention_refiner/adapters/files.py` | Reads the input text and writes the YAML report atomically. |
| Entry point and composition | `intention_refiner/cli.py`, `intention_refiner/__main__.py` | Parses the input path, creates the selected adapter, runs the use case, and writes the report. |
| Configuration | `intention_refiner/config.py` | Validates environment variables and supplies the selected model's settings. |
| Prompt resource | `intention_refiner/requirements_prompt.md` | Defines the extraction and refinement instructions used by the application use case. |

```text
CLI → text file adapter → refinement use case → ModelPort → Gemini or NVIDIA adapter
                              ↓
                        domain models
                              ↓
                      YAML file adapter
```

The application depends on the `ModelPort` interface and domain models. The CLI chooses the concrete model adapter at startup; the domain and application do not import provider SDKs.


## Remote input and publication

```sh
uv run python -m intention_refiner --source github 'owner/repository#123'
uv run python -m intention_refiner --source github https://github.com/owner/repository/issues/123 --publish
uv run python -m intention_refiner --source jira TEAM-123 --publish
uv run python -m intention_refiner --source jira https://team.atlassian.net/browse/TEAM-123
```

`--source` defaults to `file`. Each run reads one issue's title and description; comments,
attachments, GitHub project draft cards, board discovery, batch commands, pull requests,
and workflow transitions are outside this release. Jira rich text is converted to readable
text, including paragraphs, lists, tables, code, mentions, and links. A title-only issue is
valid; an empty title and description are rejected. Jira URLs must match the configured site.
No temporary input file is required.

Without `--publish`, remote runs are read-only. With it, the agent first saves YAML, then
publishes a result comment, a clarification comment when applicable, and review labels.
The original description remains unchanged. `CLARIFICATION` suggestions must be answerable
questions and are grouped by field in the question comment. When strategic context is
missing, the model drafts reviewable completions prefixed with `[IA ENHANCED]`; reports
keep `audit.missing_information` empty.

Agent comments have stable versioned markers and are updated only when their author matches
the authenticated account. Reruns update existing agent comments; when questions disappear,
the existing clarification comment is marked resolved. Duplicate owned markers fail
explicitly rather than selecting an arbitrary comment. Concurrent publishers for the same
issue are unsupported; serialize these jobs to avoid duplicate creation races.

GitHub credentials need Issues read access to fetch requirements and Issues write access to
create/update comments, create repository labels, and apply labels. Jira accounts need Browse
Projects, Add Comments, Edit Own Comments, and Edit Issues permissions (including access under
issue security). This CLI uses email/API-token Basic authentication for Jira Cloud; OAuth,
scoped-token gateway routing, GitHub Enterprise, and Jira Data Center are outside this release.

Use `--integration-config path/to/integrations.yaml` to customize label mappings:

```yaml
github:
  defaults:
    clarification: question
    ai_review: help wanted
  projects:
    owner/repository:
      ai_review: needs-review
jira:
  defaults:
    clarification: question
    ai_review: ai-review
  projects:
    TEAM:
      clarification: needs-answer
```

Project mappings override provider defaults. A clarification label is applied for any
`CLARIFICATION` suggestion. An AI-review label is applied for any `AI_ENHANCED` or `FEATURE_IDEA`
suggestion. Existing matching labels are reused; missing GitHub
labels are created with color `7057ff`, while Jira labels are introduced through issue updates.
Other labels are preserved, and labels are never automatically removed. Jira label names
cannot contain whitespace. Names are validated before writes, and additions are verified.

GitHub uses the `githubkit` API library for token authentication, endpoint calls, request body
validation, and Link-header pagination. A small injected transport wrapper retains the circuit
breaker, sanitized errors, and exact outgoing payload metrics. SDK caching, automatic retries,
and redirects are disabled. Strict response validation checks the fields consumed by the agent;
provider schema expansion does not require duplicating the complete SDK models.

The source and publisher ports keep the application independent of HTTP clients and provider
schemas. New providers implement both contracts and declare `comments` and `labels`
capabilities; unsupported publication capabilities fail explicitly. Remote identifiers are
strictly validated with Pydantic before they are recorded. Unknown additional response fields
are allowed, but missing fields and changed identifier types are rejected.

## HTTP resilience and publication failures

HTTP clients have configurable 30-second timeouts, disabled redirects, and no automatic
retries. Each provider account/site has one circuit breaker shared by its source and publisher
adapters for the invocation. Five consecutive HTTP 429 responses open the circuit. A non-429
response resets the closed-state streak; transport failures do not increment it.

Open circuits reject requests immediately. The cooldown is 60 seconds, extended by a valid
longer `Retry-After` value (seconds or HTTP date). After cooldown, only one half-open probe is
allowed: success closes the circuit; failure reopens it. State is in memory, with a monotonic
clock and guarded probes. Future batch runners must reuse the same adapter dependencies for
a provider account/site; separate CLI processes do not share breaker state.

Publishing stops at the first failure and exits with status 1. Diagnostics identify completed
operations and the operation whose remote outcome may be uncertain. The YAML report remains
available. Before rerunning an uncertain write, inspect the issue and allow any in-flight
request to settle; comment discovery reconciles completed writes. Publication is not a remote
transaction. Oversized comment payloads are rejected before writes instead of truncated;
conservative UTF-8 JSON body limits are 65,536 bytes for GitHub and 32,767 bytes for Jira.

## Integration metrics and operational runbook

The OpenTelemetry meter `agent.integration.metrics` registers:

| Instrument | Semantics | Attributes |
| --- | --- | --- |
| `publications_success_total` | One increment per fully completed publication | `provider=github\|jira` |
| `publications_failed_total` | One increment per failed or partially completed publication | `provider`, `reason` |
| `publication_payload_bytes` | Serialized UTF-8 JSON body bytes before each remote write; histogram unit `By` | `provider`, `operation=result\|clarification\|labels` |

Failure reasons are bounded to `rate_limit`, `timeout`, `auth`, `circuit_open`, `validation`,
`network`, `remote_error`, and `unsupported`. Read-only runs do not increment publication
counters. One publication can contain several HTTP writes, but its outcome is counted once.
Payload metrics describe attempted HTTP bodies, not report file sizes. Metrics exclude issue
identifiers, URLs, credentials, and content. Trace failures record exception types only.

Metrics are always instrumented, independently of OTLP tracing. The default
`ConsoleMetricExporter` exports to stdout every 10 seconds, with a forced flush and SDK shutdown
on all CLI exits. Console metrics appear alongside normal command output; this is an interim
diagnostic format, not a stable archival format or active alerting backend. Telemetry export
failures do not undo publication. Set `INTENTION_REFINER_METRICS_EXPORTER=otlp` and the standard
OTLP variables when a collector becomes available; application instrumentation stays unchanged.

Configure these alerts in the future centralized backend:

| SLI / condition (per provider) | Threshold |
| --- | --- |
| Five-minute failure ratio: `increase(failed) / (increase(success) + increase(failed))` | Greater than 10%, at least 10 attempts in the window, sustained for five minutes |
| Five-minute authentication failures (`reason=auth`) | At least one |
| Five-minute circuit rejections (`reason=circuit_open`) | At least one |

No attempts means no failure-ratio evaluation. Partial publications count as failures.
Calculate increases separately for each process/resource series, account for counter resets,
then sum across instances and failure reasons by provider. Do not sum raw cumulative snapshots
or omit failure reasons from the ratio. Console output alone does not provide centralized
five-minute windows. Dashboard provisioning and alert delivery are infrastructure follow-up.

When an alert fires:

1. Inspect sanitized provider, operation, failure reason, and completed/uncertain operations.
2. For authentication failures, verify token validity, provider permissions, and issue access.
3. For rate limits or circuit rejection, inspect provider limits and `Retry-After`; wait for
   cooldown instead of immediately repeating writes.
4. For validation failures, compare the response contract against provider API documentation
   and update adapter validators before retrying.
5. Inspect partial comments and labels on the issue, then rerun with the same account once
   uncertain requests settle. Preserve the local YAML as the generated result.
