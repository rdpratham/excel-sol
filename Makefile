.PHONY: dev dev-backend dev-frontend install migrate seed test test-backend test-frontend lint clean

# ── Local development ─────────────────────────────────────────────────────────

dev: ## Start all services (db + redis + backend + frontend)
	docker-compose up -d db redis
	@echo "Waiting for Postgres..."
	@sleep 3
	$(MAKE) migrate
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# ── Installation ──────────────────────────────────────────────────────────────

install: install-backend install-frontend

install-backend:
	cd backend && pip install -r requirements.txt

install-frontend:
	cd frontend && npm ci

# ── Database ──────────────────────────────────────────────────────────────────

migrate: ## Apply all pending Alembic migrations
	cd backend && alembic upgrade head

migrate-down: ## Rollback one migration
	cd backend && alembic downgrade -1

migrate-history:
	cd backend && alembic history --verbose

seed: ## Create the initial admin user
	cd backend && python scripts/create_admin.py

# ── Testing ───────────────────────────────────────────────────────────────────

test: test-backend test-frontend

test-backend:
	cd backend && pytest -v

test-frontend:
	cd frontend && npm test

# ── Utilities ─────────────────────────────────────────────────────────────────

infra-up:
	docker-compose up -d

infra-down:
	docker-compose down

clean:
	docker-compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	cd frontend && rm -rf node_modules dist 2>/dev/null || true

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
