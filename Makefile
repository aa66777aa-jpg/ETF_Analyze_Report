.PHONY: lint run all update help

help:
	@echo "Available targets:"
	@echo "  all    - Run lint then run"
	@echo "  lint   - Check and format code with ruff, then clean cache"
	@echo "  run    - Execute main.py"
	@echo "  update - Update uv itself"

all: update lint run

lint:
	uvx ruff check --fix .
	uvx ruff format .
	uvx ruff clean

update:
	uv self update

run:
	uv run python main.py
