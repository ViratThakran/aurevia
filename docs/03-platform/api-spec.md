# API Specification

The API is the controlled boundary between clients, services and data.

## Rules
- Version public APIs.
- Validate inputs.
- Authenticate protected requests.
- Authorize by tenant/resource.
- Return structured errors.
- Never expose provider secrets.
- Keep side effects in service/action layers.

## Domains
Authentication, tenants, users, agents, leads, campaigns, calls, conversations, memory, knowledge, appointments, tools/actions, analytics and usage.
