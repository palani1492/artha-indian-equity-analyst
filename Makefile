SHELL := /bin/sh

.PHONY: help install lint test build compose-up compose-down compose-logs tf-fmt tf-validate infra-plan deploy migrate

help:
	@echo "install       Install frontend and backend dependencies"
	@echo "lint          Run frontend and backend linters"
	@echo "test          Run frontend and backend tests"
	@echo "build         Build both container images"
	@echo "compose-up    Start the local stack"
	@echo "compose-down  Stop the local stack"
	@echo "tf-validate   Validate Terraform configuration"
	@echo "infra-plan    Plan the production infrastructure"
	@echo "deploy        Push images and roll out ECS (requires env vars)"
	@echo "migrate       Run Alembic in a one-off ECS task"

install:
	npm ci
	python3 -m pip install -r backend/requirements-dev.txt

lint:
	npm run lint
	cd backend && ruff check . && mypy app

test:
	npm test
	cd backend && pytest --cov=app --cov-report=term-missing --cov-fail-under=80

build:
	docker build -f Dockerfile.frontend -t sentellent-frontend:local .
	docker build -f backend/Dockerfile -t sentellent-backend:local backend

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f

tf-fmt:
	terraform -chdir=infra fmt -recursive

tf-validate:
	terraform -chdir=infra init -backend=false
	terraform -chdir=infra validate

infra-plan:
	terraform -chdir=infra plan -out=tfplan

deploy:
	./scripts/deploy.sh

migrate:
	./scripts/run-migrations.sh
