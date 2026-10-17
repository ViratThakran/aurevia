# Human-feel scorecard (WP-11.7)

**Status: template; nothing scored yet.**
- **Needs Virat:** the listening test needs Virat and ten listeners.
- **Waits on providers:** recording the test calls needs Cartesia and Deepgram (waiting on
  credits).
- **Waits on Phase 12:** expert numbers come from the timing profile.

**Gate 11 (proposed pass marks; Virat confirms):** at least 70% of ten listeners would happily
stay on the call, and average scores are at least 4 of 5 for naturalness, warmth, listening
and timing.

## 1. Blind A/B listening test

For each feature, record the same simulated scenario twice: once with the feature off (A),
once on (B). Shuffle the order so listeners do not know which is which. Every feature is off
by default and turned on only for the B recording:

| Feature | Switch for the B recording |
|---|---|
| Agent reactions (WP-11.3) | `AUREVIA_AGENT_REACTIONS=true` |
| Mood and voice style (WP-11.4) | `AUREVIA_PROSPECT_MOOD=true` and `AUREVIA_MOOD_VOICE=true` |
| Natural speech (WP-11.5) | `AUREVIA_NATURAL_SPEECH=true` |
| Turn-taking polish (WP-11.6) | `AUREVIA_TURN_TAKING=true` |
| Backchannels (WP-11.2) | Not built; waits on the design approval |

Each listener scores each recording from 1 to 5 on four questions, and answers a fifth yes or
no:

| Question | Score |
|---|---|
| Naturalness: does it sound like a person talking, not reading? | 1 to 5 |
| Warmth: is it friendly without being fake? | 1 to 5 |
| Listening: does it respond to what was said? | 1 to 5 |
| Timing: are the pauses and turn-taking right? | 1 to 5 |
| Would you happily stay on this call? | yes / no |

Results (fill in after the test; averages over ten listeners):

| Feature | A: naturalness / warmth / listening / timing | B: same | "Stay on the call", A / B |
|---|---|---|---|
| | | | |

## 2. Numbers from calls

Run `python -m aurevia.evaluation.human_feel --tenant-id <tenant> --days 7 --out report.json`
against the test calls. It is read-only and uses the tenant's own row-level security scope.

| Measure | How it is computed | Our calls | Expert callers (Phase 12) |
|---|---|---|---|
| Pause before replying, p10 / p50 / p90 | End of the prospect's speech to the agent's first audio (turn metrics) | | |
| Talk ratio | Agent's share of all words spoken (no audio durations are stored) | | |
| Words per agent turn | Agent words / agent turns | | |
| Questions per agent turn | "?" count / agent turns | | |
| Reactions per minute | Replies opening with a short reaction (WP-11.3) | | |
| Backchannels per minute | Not measurable until WP-11.2 is built | n/a | |

## 3. Decision

Gate 11 met: yes / no. Date. Recorded by.
