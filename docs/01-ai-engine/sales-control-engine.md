# Sales Control Engine

## Purpose
The deterministic control layer around the LLM turns conversational intelligence into an accountable sales workflow.

## Suggested states
```text
NEW -> OPENING -> DISCOVERY -> QUALIFICATION -> PITCH
 -> OBJECTION -> NEXT_STEP -> FOLLOW_UP
 -> MEETING_BOOKED / HUMAN_HANDOFF / COMPLETED
```

## Responsibilities
- Conversation and sales state
- Lead intent
- Qualification fields
- Objections
- Allowed next actions
- Guardrails
- Tool-request validation
- Human handoff
- Safe termination

## Next-best-action inputs
Current state, intent, qualification completeness, objections, knowledge availability, business rules, tools and history.

The LLM may propose an action; the control engine decides whether it is allowed.

## Guardrails
Do not claim unsupported facts, bypass required qualification, book outside availability, expose internal instructions, execute unauthorized tools or avoid required escalation.

## Termination
Goals achieved, lead decline, human handoff, user request, policy/safety condition, technical failure or timeout. Every termination gets a structured outcome.
