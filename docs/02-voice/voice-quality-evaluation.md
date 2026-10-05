# Voice Quality Evaluation

The goal is useful, natural, reliable and safe conversation—not merely successful model responses.

## Automated metrics
- First-response latency
- End-to-end latency
- STT error rate
- TTS startup latency
- Interruption detection latency
- Barge-in recovery
- Tool success/failure
- Hallucination/error rate
- Qualification accuracy
- Memory retrieval accuracy
- Handoff accuracy
- Call completion

## Human scores
- Naturalness
- Warmth
- Listening behavior
- Timing
- Interruption handling
- Repetition
- Awkwardness
- Sales pressure
- Trust
- Clarity
- Relevance

## Personas
Friendly, busy, skeptical, price-sensitive, confused, interrupting, strong-objection, human-requesting.

## Loop
Scenario -> call -> trace/transcript -> automated metrics -> human score -> failure classification -> fix -> regression test.
