.DEFAULT_GOAL := help
PY := python
COMPOSE := docker compose

.PHONY: help install install-ai lint format typecheck test cov migrate migrate-down run worker admin check

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies
	$(PY) -m pip install -r requirements-dev.txt

install-ai: ## Install optional AI/browser extras
	$(PY) -m pip install -r requirements-ai.txt
	playwright install --with-deps chromium

lint: ## Ruff lint
	ruff check src/app tests

format: ## Ruff auto-format
	ruff check --fix src/app tests
	ruff format src/app tests

typecheck: ## Mypy (core + modules)
	mypy

test: ## Run tests
	pytest

cov: ## Tests with coverage report
	pytest --cov --cov-report=term-missing

migrate: ## Apply database migrations (single instance!)
	alembic upgrade head

migrate-down: ## Roll back one migration
	alembic downgrade -1

run: ## Start the API (dev, auto-reload)
	uvicorn src.main:app --reload --host 127.0.0.1 --port 8000

worker: ## Start the async task worker
	$(PY) -m src.worker

admin: ## Promote a user: make admin EMAIL=you@example.com
	$(PY) -m src.make_admin --email $(EMAIL)

check: lint test ## Full local gate (lint + tests)

up: ## Start the whole stack (db, redis, migrate, api, worker)
	$(COMPOSE) up -d --build
	$(COMPOSE) ps

down: ## Stop the stack
	$(COMPOSE) down
