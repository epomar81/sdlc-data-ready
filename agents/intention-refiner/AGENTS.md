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

## Standards Maintenance

- When a user requests a best practice that this guide does not already require, add the agreed practice to this file as a concise, enforceable rule. Keep this guide aligned with the standards established during the work.

## Project Structure

- `intention_refiner/adapters/` groups concrete adapters by responsibility:
  - `filesystem/` — text input and YAML report file access.
  - `llm/` — Gemini and NVIDIA model providers.
  - `requirements/` — GitHub and Jira integrations, API models, HTTP behavior, and rich-text conversion.
- Keep Python modules inside a responsibility subpackage under `intention_refiner/adapters/`; do not add implementation modules directly in the adapters root.
- Keep application-wide configuration in `intention_refiner/config.py` and observability in `intention_refiner/telemetry.py`; these are shared across layers rather than adapter implementations.

## Coding Constraints

- **Function arguments** — functions and methods must have at most 2 parameters (excluding python required conventions). If more data is needed, define a dedicated struct to carry the parameters; do not add a third bare argument under any circumstance.
- **TDD** — always write unit tests before implementing the code logic. Define the test cases first, confirm they fail, then write the minimum code to make them pass.

## Verification

- After applying any project change, run `make lint` and `make test` before considering the work complete.
- Fix any reported issues and rerun both targets. If a target cannot run, report the reason and do not claim verification passed.
