# story-slicer — AI Agent Guide

## What This Project Does

This project reads product requirements from a YAML file or a GitHub issue and
converts them into one or more user stories. It always saves the complete story
batch as JSON. When explicitly requested, it can also create a GitHub issue for
each generated story.

## Your Role

- Act as a senior Python developer and Pydantic-based agent designer.
- Follow clean-code practices and the engineering constraints below.

## Engineering Bar

Implement every change as a senior Python engineer would: idiomatic, minimal,
and production-ready — not merely code that compiles and passes tests. Favor
clarity and simplicity over cleverness. The sections below (Coding
Constraints, Idiomatic Python Rules, Common Mistakes to Avoid) are the
concrete, checkable expression of this bar — follow them precisely rather
than treating this statement as a substitute for them.

## Coding Constraints

- **Function arguments** — functions and methods must have at most 2 parameters (excluding python required conventions). If more data is needed, define a dedicated struct to carry the parameters; do not add a third bare argument under any circumstance.
- **TDD** — always write unit tests before implementing the code logic. Define the test cases first, confirm they fail, then write the minimum code to make them pass.

## Verification

- After applying any project change, you MUST run both `make lint` and `make test`
  before considering the work complete. This includes code, tests, dependencies,
  configuration, Makefile, documentation, and this `AGENTS.md` file.
- Run both targets against the final changed state. If you make further changes
  after verification, rerun both targets.
- Fix any reported issues and rerun both targets until both pass. Do not skip
  either target because the change appears small or unrelated to Python code.
- If a target cannot run, report the command and reason; do not claim verification
  passed or the work is fully verified.
- In the final response, report the result of both `make lint` and `make test`.

## Product Workflow

- The workflow loads YAML or GitHub input through `RequirementInputPort` and
  normalizes it to `RequirementDocument`. The application sends that document
  to the selected `LLMPort` with the slicing instructions and the JSON schema
  generated from `StoryBatch`.
- The model returns a story batch as JSON. `application.validation` parses it
  and validates each story with the Pydantic `Story` model, assigns the final
  project-prefixed IDs, then validates the complete `StoryBatch`. The domain
  structure is defined by `Story`, `Scenario`, and `StoryBatch` in
  `story_slicer.domain.models`; the generation guidance is in
  `story_slicer.application.prompts`. Invalid output follows the application's
  bounded repair flow and is validated again.
- A successful run saves the complete validated `StoryBatch` as JSON. Optional
  GitHub ticket publishing happens afterward.
- Keep YAML as the default input source and preserve the existing positional
  file-path invocation. GitHub issues are selected explicitly with
  `--source github` and may be referenced as `owner/repo#number` or an issue URL.
  The Makefile `run` target must expose the source selector as `SOURCE` and
  accept the input through `FILE`.
- Load all requirement sources through `RequirementInputPort` and normalize
  them to `RequirementDocument`. Keep source-specific HTTP and filesystem work
  in adapters; keep story slicing independent of GitHub and YAML details.
- Read the GitHub token from `STORY_SLICER_GITHUB_TOKEN`. Use the injected
  `httpx` client and configured request timeout. Convert GitHub failures to
  concise errors without including raw response bodies or credentials.
- Story ticket creation is opt-in through `--create-tickets`. GitHub input uses
  its source repository by default. YAML input uses
  `STORY_SLICER_GITHUB_REPOSITORY` by default, with `--target-repo` as a
  per-run override. Save the full `StoryBatch` JSON before publishing, and
  report partial ticket failures without deleting or replacing that JSON.
- Do not add duplicate detection for story tickets unless the user requests it;
  each explicit publishing run creates new issues.

## Architecture

- Keep domain models independent of YAML, GitHub, HTTP clients, environment
  access, filesystem APIs, provider SDKs, and telemetry exporters.
- Put source-specific loading in adapters behind `RequirementInputPort`.
  YAML files may use either the product input schema or the initiative-refiner
  schema; normalize both to `RequirementDocument` before slicing.
- Keep LLM providers behind `LLMPort`. Select Gemini, NVIDIA, or OpenAI through
  `create_llm(settings)`; provider details must not enter the application flow.
- Keep runtime configuration in `RuntimeSettings`, loaded once through
  `ConfigurationPort`. `.envrc` is a local direnv convenience; the application
  reads exported environment variables and does not parse that file itself.
- Keep telemetry behind `ObservabilityPort`. Do not send requirement content,
  prompts, model responses, credentials, or validation diagnostics to telemetry.

## CLI and output

- YAML is the default input and the positional argument remains a file path.
  GitHub issue input requires `--source github` and accepts
  `owner/repo#number` or an issue URL.
- Every successful run writes the complete validated `StoryBatch` as JSON.
  The default output is `stories.json`; `--output` or `OUTPUT` selects another
  path. Save that JSON before starting optional ticket publishing.
- Ticket publishing is opt-in. Report per-story failures and preserve the
  generated JSON when some or all GitHub issue creations fail.
