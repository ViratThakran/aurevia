# Phase 14: Phone go-live

State: **not started.** Content is from the plan only. PR #17 (hosting stage 1 packaging,
relates to WP-14.1) is merged; nothing is deployed and no server exists.

## Goal

Real calls to real phones, hosted in India, inside the law, with the safety rails already in the
code left intact.

## Gate 14 and how to measure it

| Check | Target | How it is measured |
|---|---|---|
| Staging | India-region server with HTTPS | Health endpoint ready on the public address (WP-14.1) |
| Real phone call | to Virat's own registered number, end to end, phone-audio quality measured | WP-14.3 and 14.4 |
| Do-not-disturb registry | a real registry integrated | WP-14.5 tests |
| Counsel review | recorded against the exact policy version | `python -m aurevia.compliance.operator review VERSION --by ... --reference ...` (WP-14.7) |
| Backups | restored successfully at least once | `restore_check.sh` or drill (WP-14.9) |
| Pilot acceptance matrix | passes | `docs/06-testing/pilot-acceptance-matrix.md` |

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 14.1 | Choose and build staging per the hosting plan: Caddy HTTPS, private Postgres and Redis, real LiveKit keys, firewall rules, root-only secrets file, dashboard built with the public API address. | Health endpoint ready on the public address; a browser Test Call works from outside the home network. | Not started (Virat picks provider, domain, budget). Packaging merged 17 Oct; nothing deployed. | [#17](https://github.com/ViratThakran/aurevia/pull/17) (packaging only) |
| 14.2 | Measure region and media options from the India server and one region nearer the AI providers; price LiveKit Cloud (Option C) if delay or UDP/NAT work is painful. | Decision and numbers in the hosting plan. | Not started | none |
| 14.3 | Phone trunk: LiveKit SIP to the carrier from WP-13.6, SIP ports open to the carrier only, caller ID numbers registered. | In test mode the system calls Virat's own phone and an inbound call reaches the right tenant. | Not started | none |
| 14.4 | Phone-audio quality: best speech-model setting for narrow-band audio; word error rate on real phone calls (English, Hinglish); barge-in and echo on a real network. Synthetic audio does not count. | Numbers in the voice audit doc. | Not started | none |
| 14.5 | Real do-not-disturb registry behind the existing `DndRegistry` interface (carrier or approved scrubbing service), caching rules from counsel. Unknown still means blocked. | Tests cover registered, not registered, unknown and a failing lookup. | Not started | none |
| 14.6 | Registrations (Virat and counsel): DLT, caller ID series for sales and service, carrier KYC, sender and number approvals. Answers recorded in the policy pack questions. | **To confirm** | Not started (Virat, counsel) | none |
| 14.7 | Counsel review: every requested change becomes a new immutable policy version; record the review. Ask about: AI disclosure at the start of every call, recording and transcript notice, calling hours and holidays, consent wording, insurance rules. | Review recorded against the exact version used. | Not started (counsel) | none |
| 14.8 | Call safety: voicemail handling, pacing and per-tenant concurrency limits, abandoned-call limit, daily caps, instant campaign kill switch, retry rules, in-call opt-out. | Tests prove each limit and the kill switch. | Not started | none |
| 14.9 | Operations: alerts for failed calls, provider outages, cost spikes; scheduled backups with a restore check; incident runbook; Virat as named responder; run `docs/06-testing/pilot-acceptance-tests.md` and fill the acceptance matrix. | **To confirm** | Not started | none |

**Live mode stays off until WP-14.5 and WP-14.7 are done.**

## Decisions and open questions

- Decided: hosting Option A (one server, Docker Compose and Caddy, India region).
- Virat: hosting provider, domain and budget; phone carrier (after WP-13.6 quotes) and business
  documents for carrier verification; telecom registrations; hire Indian counsel and get the
  written opinion.
- Counsel's answers to the WP-14.7 questions.
- The counsel pack says the first customers are insurance brokers.

## Parts of the system it touches

- `deploy/` (from PR #17), Caddy, LiveKit and LiveKit SIP, backups.
- Backend: telephony adapter, `providers/dnd.py` and `DndRegistry`, compliance policy versions
  and operator CLI, campaign limits, kill switch, alerts.
- Voice worker: phone-audio speech settings, voicemail handling.
- Docs to read first: `docs/02-voice/telephony.md`, `docs/05-operations/hosting-plan.md`,
  `cloud-setup.md`, `deployment-and-environments.md`, `disaster-recovery.md`,
  `pilot-runbook.md`, `docs/04-compliance-security/counsel-review-pack.md`.

## Risks and dependencies

- Known state: Exotel trunk untested; `providers/dnd.py` returns "unknown" for every number
  and the policy blocks unknown, so live calling is impossible until a real registry is
  connected.
- Depends on WP-13.6 (carrier), counsel, Virat's registrations and hosting choices.
- Risks: counsel requires stricter consent or an AI notice at the start of every call (fallback:
  notice in the opening line, new policy version, warm leads first); rules restrict promotional
  AI calling (fallback: service calls, inbound and follow-ups; stay in test mode); caller ID
  labelled as spam (fallback: registered numbers, low abandoned-call rate, honest scripts,
  reputation monitoring).

## Measured results

None yet. (PR #17's local production-style run is not a Gate 14 measurement.)

## Done checklist

- [ ] WP-14.1 to 14.9 done (done-when to confirm for 14.6 and 14.9)
- [ ] Live mode enabled only after WP-14.5 and WP-14.7, and only on Virat's instruction
- [ ] Gate 14 met
- [ ] Definition of done for each WP; `CLAUDE.md` status and this file updated
