.PHONY: build test lint quality run

build:
	uv build

test:
	uv run --extra test pytest

lint:
	uv run --group dev ruff check .

quality: lint test

run:
	uv run intention-refiner $(ARGS)
