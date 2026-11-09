# PaintMixer developer commands. Run `make help` for a list.
SHELL := /bin/bash
UV ?= uv
BACKEND := backend
FRONTEND := frontend
export UV_NO_PROGRESS := 1

.PHONY: help install dev dev-backend dev-frontend test test-backend test-frontend test-slow \
        lint lint-backend lint-frontend fmt openapi gen-api e2e sample-data migrate build seed-demo

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install backend (uv) and frontend (npm) dependencies
	cd $(BACKEND) && $(UV) sync
	cd $(FRONTEND) && npm install

dev: ## Run FastAPI (8000) and Vite (5173, proxies /api) together
	@trap 'kill 0' EXIT; \
	$(MAKE) dev-backend & \
	$(MAKE) dev-frontend & \
	wait

dev-backend: ## Run the FastAPI dev server
	cd $(BACKEND) && $(UV) run alembic upgrade head && $(UV) run uvicorn paintmixer.api.app:app --reload --port 8000

dev-frontend: ## Run the Vite dev server
	cd $(FRONTEND) && npm run dev

seed-demo: ## Seed the CMYKW demo (5 paints, colour library, calibrated + swatch models)
	cd $(BACKEND) && $(UV) run paintmixer seed-demo

migrate: ## Apply database migrations
	cd $(BACKEND) && $(UV) run alembic upgrade head

test: test-backend test-frontend ## Run all fast tests

test-backend: ## Backend unit + API tests (excludes slow)
	cd $(BACKEND) && $(UV) run pytest -m "not slow"

test-slow: ## Slow solver accuracy/performance tests
	cd $(BACKEND) && $(UV) run pytest -m slow

test-frontend: ## Vitest
	cd $(FRONTEND) && npm test

e2e: ## Playwright smoke test (added with the M6 UI)
	cd $(FRONTEND) && npm run e2e

lint: lint-backend lint-frontend ## ruff + mypy + vue-tsc

lint-backend:
	cd $(BACKEND) && $(UV) run ruff check . && $(UV) run ruff format --check . && $(UV) run mypy

lint-frontend:
	cd $(FRONTEND) && npm run typecheck

fmt: ## Auto-format backend
	cd $(BACKEND) && $(UV) run ruff format . && $(UV) run ruff check --fix .

openapi: ## Export the OpenAPI schema to backend/openapi.json
	cd $(BACKEND) && $(UV) run paintmixer openapi --out openapi.json

gen-api: openapi ## Regenerate the frontend API client types and forward-model parity fixture
	cd $(FRONTEND) && npm run gen:api
	cd $(BACKEND) && $(UV) run paintmixer parity-fixture

sample-data: ## Regenerate synthetic calibration data in sample_data/
	cd $(BACKEND) && $(UV) run paintmixer synthetic --out ../sample_data

build: ## Production build of the frontend
	cd $(FRONTEND) && npm run build
