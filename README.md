# MindSpread

Production-grade Excel-as-a-SaaS. Upload `.xlsx`, `.xlsm`, or `.csv` files, edit them in a live spreadsheet grid, and query them in plain English via an AI assistant.

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic |
| Database | PostgreSQL 16 (citext · pgcrypto) |
| Cache / Queue | Redis 7 · arq |
| AI | Anthropic `claude-sonnet-4-6` · DuckDB text-to-SQL |
| Frontend | React 18 · TypeScript · Vite · TanStack Query · Zustand |
| Grid | Glide Data Grid (Phase 3) |
| Auth | JWT access token (15 min) + httpOnly refresh cookie |

---

## Prerequisites

- Python 3.12+
- Node 20+
- Docker + Docker Compose (for local Postgres & Redis)

---

## Local setup

```bash
# 1. Clone
git clone <repo> && cd excel-sol

# 2. Backend dependencies
cd backend
pip install -r requirements.txt

# 3. Frontend dependencies
cd ../frontend
npm ci

# 4. Environment
cp .env.example .env
# Edit .env — at minimum set JWT_SECRET to a random hex string

# 5. Start infrastructure
docker-compose up -d

# 6. Run migrations
make migrate

# 7. Create admin user
make seed

# 8. Start dev servers (two terminals, or use make dev)
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) and sign in with the admin credentials you created.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | asyncpg URL: `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | Yes | `redis://host:6379` |
| `JWT_SECRET` | Yes | Random hex string ≥ 32 chars |
| `FRONTEND_ORIGIN` | Yes | Exact origin of the frontend (no trailing slash) |
| `ANTHROPIC_API_KEY` | Phase 5 | Anthropic API key |
| `ENVIRONMENT` | No | `development` (default) or `production` |
| `MAX_UPLOAD_MB` | No | Default `50` |
| `SENTRY_DSN` | No | Enables Sentry error tracking |

Frontend (Vite):

| Variable | Description |
|---|---|
| `VITE_API_URL` | Backend URL in production (empty = use Vite proxy in dev) |

---

## Makefile targets

```
make dev              Start everything (infra + backend + frontend)
make migrate          Apply Alembic migrations
make seed             Create initial admin user
make test             Run all tests
make test-backend     pytest
make test-frontend    vitest
make infra-up         docker-compose up -d
make infra-down       docker-compose down
```

---

## Phases

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ Done | Scaffold, DB models, auth API, login page, protected shell |
| 2 | Planned | Upload pipeline, file tree, dashboard stats |
| 3 | Planned | Spreadsheet grid (read + edit + undo + export) |
| 4 | Planned | WebSocket real-time sync + presence |
| 5 | Planned | AI chat with DuckDB text-to-SQL |
| 6 | Planned | RBAC, rate limiting, tests, Render deploy |

---

## Deploy (Render)

See `render.yaml` (Phase 6). Short summary:
1. Create Render Postgres + Key Value (Redis) instances.
2. Set all env vars in Render dashboard.
3. Push to the connected repo — Render auto-deploys.
4. Run `alembic upgrade head` (the build command does this automatically).
5. SSH into the web service and run `python scripts/create_admin.py` once.
