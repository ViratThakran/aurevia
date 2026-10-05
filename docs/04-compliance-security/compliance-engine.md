# Compliance Engine

## Pre-call gate
```text
CALL REQUEST
 -> Consent check
 -> DND/policy check
 -> Calling-window check
 -> Tenant policy
 -> Campaign restrictions
 -> Provider/registration prerequisites
 -> ALLOW / BLOCK
```

Every decision should record tenant, lead, campaign, requested action, policy version, checks, decision, reason code and timestamp.

Compliance is a server-side gate. The LLM cannot override it.

Exact regulatory rules must be verified against current authoritative requirements before production.
