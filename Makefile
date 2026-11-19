PY ?= .venv/bin/python

.PHONY: setup seed reset run test lint

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	@test -f .env || cp .env.example .env

seed:
	$(PY) -m services.seed

reset:
	$(PY) -m services.seed --reset-scenarios

run:
	.venv/bin/streamlit run app.py

test:
	$(PY) -m pytest -q

lint:
	.venv/bin/ruff check .
