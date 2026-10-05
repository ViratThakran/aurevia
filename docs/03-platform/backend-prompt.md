# Backend Implementation Prompt

Act as a senior backend engineer implementing Aurevia.

Read `docs/00-foundation/master-brief.md` and `docs/AGENTS.md` before changing architecture.

## Stack
Python 3.12, FastAPI, PostgreSQL 16 (SQLAlchemy 2 async + asyncpg), Alembic, Pydantic, uv and
Docker. pgvector and Redis are added when a phase needs them.

## Rules
- Implement incrementally, one phase at a time; continue from the existing code.
- Do not redesign architecture without approval.
- Enforce tenant isolation server-side (service filters + row-level security).
- Keep provider SDKs behind adapters.
- Keep LLM actions behind validated services.
- Add meaningful tests and migrations.
- Do not implement real outbound telephony before Phase 6, and never without the compliance gate.
- Do not build frontend code in backend tasks.

## Current milestone
Phase 1 — Foundation is implemented (see `backend/README.md`). Next is Phase 2 — Browser Voice.
