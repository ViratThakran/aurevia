# Conversation Memory

## Two layers

```text
IN-CALL MEMORY
current transcript/context
current intent
current objections
current sales state
        |
        v
DURABLE MEMORY
useful lead facts
business information
preferences
objections
promises
follow-up context
```

Only information useful for future interactions should become durable memory.

## Requirements
- Store provenance/confidence where practical.
- Retrieve only information relevant to the current lead.
- Enforce tenant isolation.
- Support correction and applicable deletion/retention policies.
- Do not store unnecessary sensitive information.

## Phase 1
Keep active context in the voice session. Cross-call durable memory is a later phase.
