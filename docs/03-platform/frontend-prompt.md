# Frontend Implementation Prompt

Act as a senior frontend engineer implementing Aurevia.

## Stack
Next.js, TypeScript, Tailwind CSS.

## Rules
- Read documentation first.
- Use typed API contracts.
- Never invent backend endpoints.
- Never put secrets in browser code.
- UI authorization is not a security boundary.
- Keep components modular and responsive.

## Implemented (Phase 8b)
See `web/dashboard/README.md`: typed client from OpenAPI, cookie-held refresh token behind
`/session` routes, permission-aware navigation, onboarding wizard and all dashboard areas.

## Initial UI
App shell, authentication, dashboard skeleton, agent configuration, lead list and voice test page.
