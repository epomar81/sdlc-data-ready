.PHONY: build lint test run quality

FILE ?= $(STORY_SLICER_INPUT_PATH)
SOURCE ?= $(STORY_SLICER_INPUT_SOURCE)
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
	input_source="$(SOURCE)"; \
	if [ -z "$$input_source" ]; then input_source="$${STORY_SLICER_INPUT_SOURCE:-yaml}"; fi; \
	if [ -z "$(FILE)" ]; then \
		if [ -z "$$STORY_SLICER_INPUT_PATH" ]; then \
			echo "Set STORY_SLICER_INPUT_PATH or use make run FILE=my_feature.yaml" >&2; exit 1; \
		fi; \
		uv run --locked python cli.py "$$STORY_SLICER_INPUT_PATH" --source "$$input_source" --output "$(OUTPUT)"; \
	else \
		uv run --locked python cli.py "$(FILE)" --source "$$input_source" --output "$(OUTPUT)"; \
	fi
