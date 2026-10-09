# intention-refiner — AI Agent Guide

## What This Project Does

It is a refiner of initiatives that will become as requirements of the aplications.

## Engineering Bar

Implement every change as a senior Python engineer would: idiomatic, minimal,
and production-ready — not merely code that compiles and passes tests. Favor
clarity and simplicity over cleverness. The sections below (Coding
Constraints, Idiomatic Python Rules, Common Mistakes to Avoid) are the
concrete, checkable expression of this bar — follow them precisely rather
than treating this statement as a substitute for them.

## Idiomatic Python Rules

- **Logging** — use `DEBUG` only for deep troubleshooting, `INFO` for lifecycle events and important transactions, `WARNING` for anomalous conditions that do not stop the main flow, and `ERROR` for failed operations requiring attention. Emit JSON logs with `timestamp`, `level`, `event`, and `duration_ms`; keep event names concise and put searchable context in structured fields instead of long message strings. Suppress debug output, traces, verbose intermediate state, and all third-party log records; expose only concise structured application events. Redirect console telemetry output so it cannot bypass the JSON log stream.

## Standards Maintenance

- When a user requests a best practice that this guide does not already require, add the agreed practice to this file as a concise, enforceable rule. Keep this guide aligned with the standards established during the work.

## Project Structure

- `intention_refiner/adapters/` groups concrete adapters by responsibility:
  - `filesystem/` — text input and YAML report file access.
  - `llm/` — Gemini and NVIDIA model providers.
  - `requirements/` — GitHub and Jira integrations, API models, HTTP behavior, and rich-text conversion.
- Keep Python modules inside a responsibility subpackage under `intention_refiner/adapters/`; do not add implementation modules directly in the adapters root.
- Keep application-wide configuration in `intention_refiner/config.py` and observability in `intention_refiner/telemetry.py`; these are shared across layers rather than adapter implementations.

## Refinement and Publication Rules

- Validate and normalize the complete local YAML report before any remote publication. Never publish a report that has not passed local structure and content validation.
- Keep initiative fields distinct: remove repeated sentences and paragraphs across fields and suggestions. State each KPI target in one place only.
- Convert every ambiguity into a direct, actionable question tagged `CLARIFICATION`; serialized reports must not retain those items in `audit.ambiguities`.
- Keep `schemas/initiative-report.schema.yaml`, the refinement prompt, local report normalization, and published report behavior aligned when changing the report contract.
- The initiative report has no `kpis_and_outcomes` field; keep KPI definitions and targets in `kpi`, and intended results in `desired_outcomes`.
- When business value, expected impact, metrics, or alerts are absent, proactively draft a reasonable completion, prefix generated content with `[IA ENHANCED]`, and leave `audit.missing_information` empty.
- Preserve source ticket wording verbatim; distinguish any generated paragraph, metric, or alert with the `[IA ENHANCED]` prefix.
- Put every proposed improvement in `suggestions` with an appropriate tag; the report has no separate refinement proposal section.
- In each suggestion, put the classification only in the `tag` field; do not repeat tag labels or prefixes such as `[IA ENHANCED]` in `text`.
- Publish refinement feedback as one additional structured comment with `Suggested requirement` and `Clarifications` sections. Build suggested requirement paragraphs from AI-enhanced and feature-idea suggestions, and list clarification-tagged questions separately. Omit unchanged, correct input points and empty sections; never overwrite or modify the source issue title or main requirement description.

## Coding Constraints

- **Function arguments** — functions and methods must have at most 2 parameters (excluding python required conventions). If more data is needed, define a dedicated struct to carry the parameters; do not add a third bare argument under any circumstance.
- **TDD** — always write unit tests before implementing the code logic. Define the test cases first, confirm they fail, then write the minimum code to make them pass.

## Verification

- After applying any project change, run `make lint` and `make test` before considering the work complete.
- Fix any reported issues and rerun both targets. If a target cannot run, report the reason and do not claim verification passed.
