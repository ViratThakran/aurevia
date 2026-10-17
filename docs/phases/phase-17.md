# Phase 17: Pilots and launch

State: **not started.** Content is from the plan only. Starts when each track has reached its
last gate. Most of this phase is Virat's work.

## Goal

Prove the agent with two or three real companies, with numbers a buyer believes, then start
selling.

## Gate 17 and how to measure it

| Check | Target | How it is measured |
|---|---|---|
| Pilots | two or three finish four weeks | Pilot records |
| Cost per booked meeting | measured per pilot, next to the company's own team baseline | Weekly pilot report (WP-17.5) and the usage engine |
| Commitment | at least one company agrees to pay or to be a named case study | Signed agreement |
| Legal pack | in place | WP-17.3 |

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 17.1 | Pick the niche and ideal customer: insurance brokers or the recordings' industry. Criteria: many outbound calls today, a meeting worth real money, an existing human team to compare, India-based, willing to share results. | **To confirm** | Not started (Virat) | none |
| 17.2 | Design the pilot: four weeks; success numbers agreed in writing first (connect rate, qualified leads and meetings per 100 dials, meetings attended, cost per booked meeting, vs the company's callers on similar leads); start with warm leads; no live outbound before Gate 14. | **To confirm** | Not started (Virat) | none |
| 17.3 | Legal pack (counsel): pilot agreement, terms, privacy policy, DPA (customer as data fiduciary, Aurevia as processor), acceptable-use rules; legal entity for contracts and GST invoices. | **To confirm** | Not started (counsel) | none |
| 17.4 | Sales material: ROI calculator (WP-13.7), landing page, two-minute demo video, "request a demo call" form recording express consent and calling only that person through the compliance gate, compliance one-pager, case-study template. | **To confirm** | Not started | none |
| 17.5 | Run the pilot: daily call review in week one, a fix list, an automatic weekly report per pilot company, the Phase 14 incident process. | **To confirm** | Not started | none |
| 17.6 | Decide: if cost per booked meeting beats the human baseline and quality holds, finalise pricing and sell; if not, return to Phase 13 or 11 first. | Decision recorded: **to confirm** where | Not started (Virat) | none |

What Claude Code builds here (per the plan): the weekly report generator, the demo-call form
with consent capture, pilot tenants with caps, and a pilot results page. Everything else is
business work for Virat and counsel.

## Decisions and open questions

- Virat: first niche, find two or three pilot companies and sign pilot agreements, legal
  entity, GST, payment gateway, final pricing.
- Counsel: the legal pack.
- Exact pilot success thresholds: agreed in writing with each company, **to confirm**.

## Parts of the system it touches

- Backend: weekly report generator, demo-call form with consent capture through the
  compliance gate, pilot tenants with caps (plans and limits).
- Dashboard: pilot results page.
- Outside the code: landing page, demo video, legal documents.

## Risks and dependencies

- Depends on Gate 14 (no live outbound before it) and on each track's last gate.
- Risk: a pilot shows no gain over human callers. Fallback: return to Phases 11 and 13, or
  switch the first product to inbound answering and follow-ups.
- Risk: one person carries the whole build. Fallback: keep phase order and gates, one PR per
  WP, use counsel and a sales partner for non-code work.
- Cross-cutting before the first pilot: rotate all provider keys; penetration test before the
  first paying customer.

## Measured results

None yet.

## Done checklist

- [ ] WP-17.1 to 17.6 done (done-when to confirm)
- [ ] Gate 17 met
- [ ] Launch checklist in the plan (pages 21 to 22) reported against
- [ ] `CLAUDE.md` status and this file updated
