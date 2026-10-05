# Observability and Operations

## Call trace
Call ID -> Session ID -> Tenant -> Lead -> Provider -> STT latency -> LLM latency -> TTS latency -> Tools -> Errors -> Outcome.

## Metrics
Call attempts, connections, duration, first response latency, end-to-end latency, provider failures, tool failures, handoffs, meetings, qualification and estimated cost.

Use structured correlated logs. Avoid unnecessary sensitive transcript content.

## Incident loop
Detect -> Correlate -> Classify -> Mitigate -> Recover -> Review -> Add regression test.
