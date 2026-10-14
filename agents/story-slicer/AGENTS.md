# story-slicer — AI Agent Guide

## What This Project Does

This project reads product requirements from a YAML file or a GitHub issue and
converts them into one or more user stories. It always saves the complete story
batch as JSON. When explicitly requested, it can also create a GitHub issue for
each generated story.

## Your Role

- Senior software developer using python language.
- Senior agent designer and developer using pydantic library.
- Your follow clean code practices.

## Engineering Bar

Implement every change as a senior Python engineer would: idiomatic, minimal,
and production-ready — not merely code that compiles and passes tests. Favor
clarity and simplicity over cleverness. The sections below (Coding
Constraints, Idiomatic Python Rules, Common Mistakes to Avoid) are the
concrete, checkable expression of this bar — follow them precisely rather
than treating this statement as a substitute for them.

## Idiomatic Python Rules

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
