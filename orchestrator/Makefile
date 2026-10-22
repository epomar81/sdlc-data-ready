.PHONY: help install run test lint format-check

REPO_ROOT := $(abspath ..)
PYTHON := uv run --project orchestrator --python 3.12
AGENT_PYTHONPATH := $(REPO_ROOT)/agents/intention-refiner:$(REPO_ROOT)/agents/story-slicer/src:$(REPO_ROOT)

help: ## Show available project commands
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  make -C orchestrator %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install orchestrator and development dependencies
	cd $(REPO_ROOT) && uv sync --project orchestrator --python 3.12 --group dev

run: ## Run the FastAPI server with auto-reload on port 8000
	cd $(REPO_ROOT) && PYTHONPATH="$(AGENT_PYTHONPATH):$${PYTHONPATH}" $(PYTHON) uvicorn orchestrator.infrastructure.inbound.app:app --reload --host 127.0.0.1 --port 8000

test: ## Run the orchestrator test suite
	cd $(REPO_ROOT) && PYTHONPATH="$(AGENT_PYTHONPATH):$${PYTHONPATH}" $(PYTHON) pytest orchestrator/tests

lint: ## Run Ruff lint checks
	cd $(REPO_ROOT) && $(PYTHON) ruff check --config orchestrator/pyproject.toml orchestrator

format-check: ## Check formatting with Ruff
	cd $(REPO_ROOT) && $(PYTHON) ruff format --check --config orchestrator/pyproject.toml orchestrator
