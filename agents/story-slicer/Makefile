.PHONY: build lint test run quality

FILE ?= $(STORY_SLICER_INPUT_PATH)
OUTPUT ?= stories.json

build:
	uv build

lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked mypy

test:
	uv run --locked pytest

quality: lint test

run:
	@set -e; \
	if [ -f .envrc ]; then . ./.envrc; fi; \
	if [ -z "$(FILE)" ]; then \
		if [ -z "$$STORY_SLICER_INPUT_PATH" ]; then \
			echo "Set STORY_SLICER_INPUT_PATH or use make run FILE=my_feature.yaml" >&2; exit 1; \
		fi; \
		uv run --locked python cli.py "$$STORY_SLICER_INPUT_PATH" --output "$(OUTPUT)"; \
	else \
		uv run --locked python cli.py "$(FILE)" --output "$(OUTPUT)"; \
	fi
