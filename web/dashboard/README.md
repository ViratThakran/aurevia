# Aurevia dashboard

Next.js (App Router) + TypeScript + Tailwind. It is the customer-facing app: onboarding, agent setup, browser test calls, leads, campaigns, calls, meetings and tasks, usage, compliance, team, audit log, and, for Aurevia staff, platform admin.

## Run it

With the Docker stack: `docker compose --profile voice up` from `backend/` serves it at http://localhost:3002.

For development with hot reload:

```bash
cd web/dashboard
npm install
npm run dev    # http://localhost:3002, talks to the API at http://localhost:8000
```

The API must allow the dashboard's origin: add `http://localhost:3002` to `AUREVIA_CORS_ORIGINS` in `backend/.env`.

## How it is built

- **Typed API contract.** `src/lib/api-schema.d.ts` is generated from the API's OpenAPI schema. Never hand-write endpoint types. After changing the API, regenerate:
  - from `backend/`: `uv run python scripts/export_openapi.py ../web/dashboard/openapi.json`
  - from here: `npm run gen:api`

  CI fails if either file is out of date. Responses the API returns as free-form JSON (analytics, usage, platform admin) are typed in `src/lib/types.ts`.
- **Sessions.**
  - The refresh token never reaches browser JavaScript. The `/session/*` route handlers sign in through the API and keep the refresh token in an httpOnly, SameSite=Strict cookie scoped to `/session`; they also refuse cross-origin requests.
  - The browser holds only the short-lived access token, in memory. It renews it through `/session/refresh` once and then retries the request.
- **Authorization.** Menus and buttons follow the permissions in `/auth/me`, but that is only tidiness: the API checks every request.
- **Test calls** use `livekit-client`. The API creates the room and sends the agent; the browser gets a participant token for that one room.

## Checks

```bash
npm run typecheck && npm run lint && npm run build
```
