.PHONY: lint run all update sync help

help:
	@echo "Available targets:"
	@echo "  all    - Update uv, sync dependencies, lint, and run"
	@echo "  sync   - Sync project dependencies with uv sync"
	@echo "  lint   - Check and format code with ruff, then clean cache"
	@echo "  run    - Execute main.py"
	@echo "  update - Update uv itself"

all: update sync lint run

sync:
	uv sync

lint:
	uvx ruff check --fix .
	uvx ruff format .
	uvx ruff clean

update:
	uv self update

run:
	uv run python main.py
