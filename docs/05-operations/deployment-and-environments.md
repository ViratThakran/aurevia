# Deployment and Environments

```text
Local -> Development -> Staging -> Production
```

Components: Next.js, FastAPI, workers, PostgreSQL, Redis, object storage, voice runtime and monitoring.

Rules:
- Separate credentials by environment.
- Never use production secrets locally.
- Version migrations.
- Test backups.
- Make deployments reproducible.
- Document rollback.
- Run CI tests before deployment.
- Keep secrets out of source control.
