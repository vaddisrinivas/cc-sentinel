.PHONY: test lint format smoke install dev clean help

test:
	pytest tests/ -v --tb=short

lint:
	ruff check cc_retrospect/ scripts/ tests/
	pyright cc_retrospect/ scripts/

format:
	ruff format cc_retrospect/ scripts/ tests/

smoke:
	python3 scripts/dispatch.py status
	python3 scripts/dispatch.py config

install:
	uv pip install -e . || pip install -e .

dev:
	uv pip install -e ".[test]" || pip install -e ".[test]"
	pre-commit install

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache/ .ruff_cache/ build/ dist/ *.egg-info/

help:
	@echo "cc-retrospect development targets:"
	@echo "  make test       - run pytest"
	@echo "  make lint       - run ruff + pyright"
	@echo "  make format     - format code with ruff"
	@echo "  make smoke      - quick sanity check"
	@echo "  make install    - install package"
	@echo "  make dev        - install dev deps + pre-commit hook"
	@echo "  make clean      - remove cache/build artifacts"
	@echo "  make help       - show this message"
