Act as an Expert Software Architect in Python (target: version 3.11/3.12), Domain-Driven Design, and Monorepos.
Please inspect the existing agents located under the `@agents` folder.

Context & Goal:
- This repository is a flat Monorepo. We are creating a new service in a sibling folder called `orchestrator/` to coordinate the existing agents based on GitHub Webhook events.
- Both existing agents are built with Hexagonal Architecture and strict Pydantic schemas.

STRICT BOUNDARIES & SCOPE:
1. DO NOT modify, refactor, or update any code inside the `agents/` directory. Treat them as read-only black boxes.
2. Flat Structure: Do NOT create redundant nested folders (e.g., no `orchestrator/orchestrator/`). Create `domain/`, `application/`, and `infrastructure/` directly inside the root `orchestrator/` folder.
3. Simple Imports: Import agents using standard Python relative/absolute imports. Do not add complex local package installations to `pyproject.toml` or mutate `sys.path`.

TECHNICAL CONSTRAINTS (Anti-Over-engineering):
- Framework: Use FastAPI. Place the FastAPI app and webhooks inside `infrastructure/inbound/` (it is an inbound adapter, not a root `api/` folder).
- Async Execution: Use FastAPI `BackgroundTasks`. The endpoint must return HTTP 200 immediately and process the agent logic in the background.
- State Management: KEEP IT SIMPLE. Do NOT introduce any external database, message broker (Redis/Celery), or complex in-memory state tracking/deduplication. Fire and forget.

BUSINESS RULES & ROUTING (Application Layer):
1. `issues.opened` (without exact "ready-for-slicing" label) -> Route to Agent 01 (Refiner).
2. `issues.labeled` (with exact "ready-for-slicing" label) -> Route to Agent 02 (Slicer).
3. Ignore other events immediately.

OBSERVABILITY & OUTPUTS (Infrastructure Layer):
- When Agent 02 finishes, extract its generated Pydantic metrics (e.g., `ambiguity_score`, `story_count`) and `alerts` (INFO, WARNING, CRITICAL with rationale).
- Emit these metrics and alerts to OpenTelemetry (keep rationale out of metric labels to avoid high cardinality).
- Publish stories to the source GitHub repository using the existing agent publishers. Separate the story body from clarification comments.

DELIVERABLES:
1. Provide the complete implementation following the flat Hexagonal structure.
2. Include a `README.md` at the root of `orchestrator/` with setup, environment variables (GitHub/OTel), and local run commands.
3. Include tests (`tests/`) mocking the agent ports and verifying the webhook routing, background dispatch, metric extraction, and alert generation.