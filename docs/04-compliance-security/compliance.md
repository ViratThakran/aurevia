# Compliance

This is a product-level compliance boundary, not legal advice.

Principles:
- Obtain and respect required consent.
- Respect applicable DND and calling restrictions.
- Apply calling-window rules.
- Maintain required registration/configuration.
- Maintain auditable decisions.
- Be transparent about AI identity when directly asked.
- Never fabricate compliance status.

Telecom requirements can change; production implementation must verify current requirements with authoritative sources and qualified counsel.

## Timing
The pre-call gate ships with telephony in Phase 6: no call is placed to a real number until the
gate passes its test suite. Phase 7 hardens it (versioned policies, campaign rules, audit).

## Policy packs
The engine is generic; market rules are configuration, selected per tenant.

**India pack (first customers)** — to be confirmed with counsel before production:
- DLT registration of the principal entity, telemarketer and call headers.
- 140-series numbers for promotional calls, 160-series for service/transactional calls.
- Calls only between 9 AM and 9 PM.
- Real-time DND scrubbing before every dial, not a one-time list check.
- Consent records, including implied consent from recent enquiries where applicable.
- DPDP Act: data minimisation, retention limits, data held in an Indian region.
- IRDAI rules for insurance telemarketing and distance selling (including any call-recording
  retention requirements).
