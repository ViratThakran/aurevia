# Phase 15: Integrations that replace the sales workflow

State: **not started.** Content is from the plan only.

## Goal

The agent finishes the job without a person: the meeting lands on a real calendar, the call
result lands in the customer's CRM, and the follow-up goes out on the right channel.

## Gate 15 and how to measure it

| Check | Target | How it is measured |
|---|---|---|
| Calendar | a meeting booked on a call appears on the customer's real calendar with an invite | **To confirm** (sandbox vs real customer calendar) |
| CRM | outcome, notes and summary appear in their CRM | **To confirm** |
| Follow-up | sent only after a consent check | Compliance gate decision plus delivery status |
| No-show | recovered in a test run | WP-15.4 test run |

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 15.1 | Calendar: Google first, Outlook second; per-tenant sign-in, tokens encrypted at rest, free/busy to slots, events created and cancelled with invite and meeting link, time zones; keep the unique index that blocks double booking. | Tests against a sandbox calendar cover races, a revoked sign-in and an outage; each failure returns a not-ok tool result. | Not started | none |
| 15.2 | CRM: HubSpot and Zoho first, Salesforce later; import leads; push outcome, stage, qualification facts, notes, summary, meeting; per-tenant field mapping, duplicate matching, idempotent retries, visible sync status; signed webhook and CSV export for the rest. | **To confirm** | Not started | none |
| 15.3 | Messaging follow-ups: WhatsApp Business (approved templates, opt-in recorded), SMS (DLT templates), email (SPF, DKIM, DMARC, unsubscribe). A validated, audited tool sends only after the compliance gate checks consent for that channel and purpose, inside allowed hours; delivery tracked; opt-outs honoured at once; the model picks a template and fills fields, no free-form messages. | **To confirm** | Not started | none |
| 15.4 | After the call: summary, next steps and lead score within seconds; follow-up sequences by outcome; no-show recovery with reminder and reschedule. | **To confirm** (Gate 15 needs a no-show recovered in a test run) | Not started | none |
| 15.5 | Handoff and callbacks: warm handoff alert (email, WhatsApp or Slack) with summary, building on the handoff tool; "call me at 5" queued as a scheduled callback. | **To confirm** | Not started | none |
| 15.6 | Public API and webhooks: per-tenant API keys with scopes and rate limits; signed `call.completed`, `meeting.booked`, `lead.updated`; API docs from the OpenAPI file. | **To confirm** | Not started | none |

## Decisions and open questions

- Calendar order: Google, then Outlook. CRM order: HubSpot and Zoho, then Salesforce.
- Calling windows and retries from the Phase 12 addition land here: prospect's local window,
  3 to 5 pm as the first window to test, compliance gate's legal hours win; retry no-answers
  on another day and time; honour "call me in a week"; stop after a set number of attempts
  (number **to confirm**); wrong numbers leave the sequence.
- Which WhatsApp, SMS and email providers: **to confirm**.

## Parts of the system it touches

- Backend: `sales/scheduling.py` and the booking tools (Google and Outlook behind the same tool
  interface), new provider adapters (calendar, CRM, messaging), token encryption, compliance
  gate for channel consent, follow-up sequences, callbacks queue, API keys and webhooks.
- Dashboard: sign-in to calendar and CRM, field mapping, sync status.

## Risks and dependencies

- Rule: every tool result must still say ok truthfully; the agent never claims a booking or
  message that failed.
- SMS depends on DLT template registration (Phase 14, WP-14.6).
- Live follow-ups depend on Gate 14 compliance work.

## Measured results

None yet.

## Done checklist

- [ ] WP-15.1 to 15.6 done (done-when to confirm for 15.2 to 15.6)
- [ ] Gate 15 met
- [ ] Definition of done for each WP; `CLAUDE.md` status and this file updated
