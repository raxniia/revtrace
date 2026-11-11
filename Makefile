.PHONY: install build serve test lint eval

install:
	pip install -e ".[dev]"
	cd frontend && npm install

build:
	cd frontend && npm run build

serve: build
	revtrace serve

test:
	pytest -q

lint:
	ruff check . && ruff format --check .

eval:
	revtrace eval --scenarios 16
