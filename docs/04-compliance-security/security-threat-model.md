# Security Threat Model

## Prompt injection
Treat caller and lead text as untrusted. Keep policy separate and authorize tools outside the LLM.

## Malicious lead data
Validate imported text and never treat it as system instructions.

## Unauthorized tools
Use server-side authorization, schemas, business validation and audit trails.

## Tenant breakout
Use server-derived tenant context and tenant-scoped queries.

## Webhook spoofing
Validate provider signatures, use replay protection where applicable, and make handlers idempotent.

## Credential theft
Use secret management, least privilege and rotation.

## Transcript/recording leakage
Use access controls, tenant-scoped storage, retention and audit access.
