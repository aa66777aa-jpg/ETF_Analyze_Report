.PHONY: lint run all help

help:
	@echo "Available targets:"
	@echo "  all   - Run lint then run"
	@echo "  lint  - Check and format code with ruff"
	@echo "  run   - Execute ETF.py"

all: lint run

lint:
	uvx ruff check --fix .
	uvx ruff format .
	uvx ruff clean

run:
	uv run python ETF.py
