# Tool and Action Framework

## Principle
The LLM never writes directly to PostgreSQL or external systems.

```text
LLM -> Tool Request -> Schema Validation -> Authorization
   -> Business Validation -> Action Service
   -> Database/Calendar/CRM -> Tool Result -> Conversation
```

## Lead tools
- get_lead
- update_lead
- add_note
- change_status

## Sales tools
- mark_interested
- mark_not_interested
- log_objection
- qualify_lead

## Follow-up tools
- schedule_followup
- cancel_followup

## Calendar
- get_available_slots
- book_meeting
- cancel_meeting

## Human escalation
- flag_for_handoff
- transfer_to_human

Every tool defines input/output schemas, authorization, tenant scope, idempotency, validation, audit requirements and failure behavior.

Critical actions require server-side validation. A tool failure must never be represented to the caller as success.
