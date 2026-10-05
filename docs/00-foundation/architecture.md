# System Architecture

```text
                    AUREVIA AI SALES PLATFORM
                              |
             +----------------+----------------+
             |                                 |
      SALES CONTROL ENGINE              AI MODEL GATEWAY
             |                                 |
      +------+------+------+             +------+------+
      |      |      |      |             |             |
    State  Intent  Qual. Objections    Claude         GPT
      |      |      |      |             |             |
      +------+------+------+             +------+------+
                     |                          |
             TOOL & ACTION FRAMEWORK             |
                     |                          |
          +----------+-----------+              |
          |          |           |              |
         CRM      Calendar     Human            |
                     |                          |
                     +------------+-------------+
                                  |
                           VOICE RUNTIME
                                  |
                    +-------------+-------------+
                    |             |             |
                   STT            LLM           TTS
                    |             |             |
                    +-------------+-------------+
                                  |
                             Telephony
                                  |
                                Lead
```

## Boundaries
- AI Model Gateway: model/provider abstraction.
- Sales Control Engine: sales state and decisions.
- Tool & Action Framework: validated side effects.
- Voice Runtime: real-time audio lifecycle.
- Memory: active and durable context.
- Platform API: tenancy, leads, calls, analytics.
- Compliance: server-side policy gates.
- Observability: traces, metrics, errors and costs.

## Rule
The LLM is an intelligence component, not the application controller.
