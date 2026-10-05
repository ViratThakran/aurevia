# Aurevia backend

Phase 1 — foundation. Architecture and rules live in `../docs/` (start with `INDEX.md` and
`AGENTS.md`).

## Local development (Docker)

```bash
cp .env.example .env     # fill in POSTGRES_*, AUREVIA_APP_DB_PASSWORD, AUREVIA_JWT_SECRET
docker compose up --build
curl localhost:8000/api/v1/health/ready
```

On start the API container runs `alembic upgrade head` as the schema owner, then serves as the
`aurevia_app` role. If port 5432 is taken on your machine, set `POSTGRES_HOST_PORT` in `.env`.

## Local development (no Docker)

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/), plus a reachable Postgres 16.

```bash
uv sync
uv run alembic upgrade head      # needs AUREVIA_MIGRATION_DATABASE_URL (schema owner)
uv run uvicorn aurevia.main:create_app --factory --reload   # needs AUREVIA_DATABASE_URL (app role)
```

Create the application role once, as a superuser, before the first migration:

```sql
CREATE ROLE aurevia_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '...';
```

## Checks (run before every commit)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

Database tests need a Postgres server whose user may create databases and roles; each run
creates and drops its own throwaway database and role:

```bash
AUREVIA_TEST_DATABASE_URL=postgresql://admin:pw@localhost:5432/postgres uv run pytest
```

Without that variable the database tests are skipped (CI sets `AUREVIA_REQUIRE_DB_TESTS=1`, so
there they fail instead).

## Tenant isolation

Tenant-owned tables (`tenants`, `memberships`, `audit_events`, and every future one) are
isolated twice:

1. Services filter on the principal's `tenant_id`, which comes only from a verified membership,
   never from the request.
2. Postgres row-level security, forced on the table owner too, compares each row's `tenant_id`
   with the transaction-local `app.tenant_id` setting (`aurevia.db.session.set_tenant_context`).
   A transaction without tenant context sees no tenant-owned rows.

The API must connect as a role that is not a superuser and lacks `BYPASSRLS`; staging and
production refuse to start otherwise. Rows of another tenant are reported as `404`, never `403`.

## API (v1)

| Method | Path | Who |
| --- | --- | --- |
| POST | `/api/v1/auth/signup` | anyone: creates a tenant and its owner |
| POST | `/api/v1/auth/login` | anyone: `tenant_id` needed only for multi-tenant accounts |
| POST | `/api/v1/auth/refresh` | refresh token: rotates; reuse revokes the whole session |
| POST | `/api/v1/auth/logout` | refresh token |
| GET | `/api/v1/auth/me` | signed in |
| GET | `/api/v1/tenant`, `/api/v1/tenant/members` | signed in |
| PATCH, DELETE | `/api/v1/tenant/members/{membership_id}` | owner or admin; only owners touch owners; the last owner stays |

## Conventions

- Configuration: environment variables prefixed `AUREVIA_`; see `.env.example`. Nothing
  sensitive is hard-coded or has a default.
- Errors: one envelope, `{"error": {"code", "message", "request_id", "details"}}`.
- Every response carries `X-Request-ID`; the same ID appears in the JSON logs, together with
  `tenant_id` and `user_id` once a request is authenticated.
- Probes: `GET /health` (liveness), `GET /api/v1/health/ready` (readiness, includes the database).
- Database changes: a new Alembic migration in `alembic/versions/`, never edits to an applied
  one. `tests/integration/test_migrations.py` fails if models and migrations drift apart.
- Vendor SDKs (LLM, STT, TTS, telephony) are imported only under `src/aurevia/providers/`;
  `tests/test_architecture.py` enforces it.
