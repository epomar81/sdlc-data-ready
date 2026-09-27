# Intention refiner

Intention refiner reads one software initiative from a UTF-8 text file and saves a structured YAML report. It extracts facts, identifies gaps and ambiguous language, and proposes improvements for review. Missing facts remain `null` in the extracted initiative; proposed values appear separately as suggestions.

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

For example:

```sh
export INTENTION_REFINER_PROVIDER=gemini
export INTENTION_REFINER_MODEL=your-gemini-model
export INTENTION_REFINER_GEMINI_API_KEY=your-api-key
intention-refiner path/to/initiative.txt
```

The tool reads the process environment; it does not load `.env` files itself. To load settings automatically when entering the project directory, install [direnv](https://direnv.net/), copy `.envrc.example` to `.envrc`, replace the placeholder model and API key, then run `direnv allow` in the project directory. `.envrc` is ignored by Git so your local API key is not committed. The example uses Gemini; for NVIDIA, set `INTENTION_REFINER_PROVIDER="nvidia"` and `INTENTION_REFINER_NVIDIA_API_KEY` instead.

## Console logging

The command prints one JSON object per log line, with `level` and `message` fields. Each completed model request reports the exact prompt, completion, and total token counts returned by the provider. Each entry in `refinement_proposals` reports its field, proposed content, and rationale. Suggestion tags are not logged. The CLI logs each failure once at the command boundary and exits with status 1.

The model port returns both the generated text and provider usage metadata. Gemini usage comes from `usage_metadata`; NVIDIA usage comes from the chat completion's `usage` object. Token counts are kept in the model response and logged after the request succeeds. If a model request or response validation fails, the error propagates to the CLI and is logged once there.

Run the self-contained demonstration from the repository root. It uses a local fake model, needs no API key, and prints representative token and refinement proposal logs:

```sh
uv run python examples/logging_demo.py
```

Example output:

```text
{"level": "info", "message": "Token usage: Prompt tokens: 120, Completion tokens: 45, Total tokens: 165"}
{"level": "info", "message": "Refinement proposal: Field: target | Content: Customers booking online. | Reason: The intended users were not specified."}
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

The YAML report has five sections:

- `initiative`: one requirement with `id`, `title`, `problem_statement`, `target`, `business_value`, `business_scope`, `ex_scope`, `kpi`, `desired_outcomes`, and `kpis_and_outcomes`.
- `suggestions`: field-linked recommendations tagged `MISSING_INFO`, `AI_ENHANCED`, `FEATURE_IDEA`, or `CLARIFICATION`.
- `audit`: lists of ambiguities, missing information, metric gaps, and other risks.
- `refinement_proposals`: proposed replacement text, its field, and a rationale.
- `metadata`: provider, model, and model response time in milliseconds.

The model generates the content, so a person should review its suggestions before treating them as requirements. DORA metrics are suggested only when the initiative concerns software delivery performance.

## Architecture

The package uses ports and adapters to keep the refinement workflow separate from model SDKs and file handling:

| Hexagonal role | Current module | Responsibility |
| --- | --- | --- |
| Domain | `intention_refiner/domain/models.py` | Validated initiative, suggestions, audit, proposals, and report types. |
| Application port | `intention_refiner/application/ports.py` | `ModelPort` defines the model operation needed by the workflow. |
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
