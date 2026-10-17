# Phase 13: Make it cheap

State: **not started.** Content is from the plan only.

## Goal

Variable cost under 2 rupees per talk minute, and cost per booked meeting visible for every
customer, so the pitch "cheaper than your 10 or 20 person team" holds.

## Gate 13 and how to measure it

| Check | Target | How it is measured |
|---|---|---|
| Cost per talk minute | 2 rupees or less, **measured** not estimated | At least 20 real test calls through the usage engine (WP-13.1) |
| Cost per booked meeting | report per tenant | Usage engine report |
| ROI calculator | exists and states its assumptions | WP-13.7 |

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 13.1 | True cost metering: check `usage/costs.py`, `usage/recorder.py`, `docs/03-platform/cost-and-usage-engine.md` record STT seconds, TTS characters, model tokens (cached and uncached), phone minutes and pulses; prices in a versioned config, never in code; cost per call, minute, booked meeting, tenant; budget alert and per-tenant kill switch. | 20 test calls give a real cost per minute, saved in the docs. | Not started | none |
| 13.2 | Voice bake-off: blind listening plus cost for the current voice, a volume plan, other providers including Indian-language specialists, a self-hosted open model at break-even. Choose by quality per rupee; the adapter layer stays. | **To confirm** | Not started | none |
| 13.3 | Audio cache: pre-render greeting, backchannels, closing lines and common phrases per voice, language and emotion; track hit rate. | **To confirm** | Not started | none |
| 13.4 | Model routing: small fast model for routine turns, stronger one for objections, pricing and booking; prompt caching, stage-aware trimming, summaries for long calls. | 8 scenarios still pass and cost per scenario drops. | Not started | none |
| 13.5 | Do not pay for silence: start speech services after answer, voicemail and answering-machine detection, per-campaign call-length cap, skip the model for very short non-answers, keep the silence cut-off. | **To confirm** | Not started | none |
| 13.6 | Phone rates: written quotes from Plivo, Exotel and at least one more India carrier; per-second vs per-minute billing; choose behind the telephony adapter. | **To confirm** (a carrier chosen; feeds WP-14.3) | Not started (Virat gets quotes) | none |
| 13.7 | Pricing and ROI: plans with a price per booked meeting plus a per-minute floor, gross margin per tenant shown to Virat; ROI calculator from team size, salaries and talk time. | **To confirm** | Not started | none |

## Decisions and open questions

- Virat: phone carrier after written quotes; final pricing (also Phase 17).
- Exchange rate: the plan assumes about 90 rupees to the dollar; **confirm the current rate**.
- The plan's estimate (not measured): STT about 0.7, TTS 1.2 to 2.1, model 0.45 to 1.35, phone
  0.4 to 0.6 rupees per minute; total about 2.7 to 4.7, hosting not included.
- Exotel publishes no per-minute rate and bills in 60-second pulses.
- ROI calculator honesty: pay data is thin (telesales about 2 lakh a year, SDRs about 9.8 lakh,
  small and old samples). Against entry-level telecallers the margin is thin.
- Related, from Phase 10: pricing follow-ups (price seed, spend limit with unpriced usage,
  cache-write pricing) proposed 17 Oct, awaiting Virat. Overlaps WP-13.1: **to confirm** where
  they land.

## Parts of the system it touches

- Backend: usage engine (`usage/costs.py`, `usage/recorder.py`), prices, plans and platform
  admin, budget alert and kill switch, model routing in the Model Gateway, telephony adapter.
- Voice worker: audio cache, voicemail detection, starting speech services after answer, TTS
  provider adapters.
- Dashboard: cost reports, plans, ROI calculator.

## Risks and dependencies

- Needs real test calls (Phase 14 phone path, or browser calls: **to confirm** which count).
- Feeds Phase 14 (carrier choice) and Phase 17 (ROI, pricing).
- Risk: cost stays above 2 rupees a minute. Fallback: price per booked meeting, target teams
  with costly SDRs, cheaper voice, self-hosted speech at volume.
- Risk: a provider raises prices. Fallback: adapters plus a second provider, spend alerts.

## Measured results

None yet. (The table above is the plan's estimate, not a measurement.)

## Done checklist

- [ ] WP-13.1 real cost per minute from 20 test calls saved in docs
- [ ] WP-13.2 to 13.7 done (done-when to confirm for 13.2, 13.3, 13.5, 13.6, 13.7)
- [ ] Gate 13 met
- [ ] Definition of done for each WP; `CLAUDE.md` status and this file updated
