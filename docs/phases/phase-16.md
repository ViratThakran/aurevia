# Phase 16: A product companies can buy

State: **not started.** Content is from the plan only.

## Goal

A company signs up, teaches the agent its business, tests it, launches a campaign and sees
results and cost, without Virat in the room.

## Gate 16 and how to measure it

| Check | Target | How it is measured |
|---|---|---|
| Unaided onboarding | a new test company finishes in under an hour (proposed target) | Timed run by a test company. Who plays the company: **to confirm** |
| Test-mode campaign | launched | Campaign in test mode |
| Cost and results | visible to the company | Dashboard |
| Invoice | correct for its test usage | WP-16.7 billing |

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 16.1 | Onboarding wizard: company details, knowledge base, personality and voice, qualification and objections, test call, connect calendar and CRM, import leads, launch in test mode; progress saved, each step says what is missing. | **To confirm** | Not started | none |
| 16.2 | Knowledge base: documents, web pages, FAQs and prices; per-tenant chunking and retrieval; facts only from what the company supplied, otherwise offer a colleague follow-up; answer source visible in call review. | Retrieval with playbook retrieval under 100 ms (plan's budget); done-when otherwise **to confirm** | Not started | none |
| 16.3 | Vertical templates: a ready agent per industry, insurance first; companies edit them. | **To confirm** | Not started | none |
| 16.4 | Try it before launch: practice against simulated prospects (friendly, busy, skeptical, price-sensitive, confused, strong-objection) with transcript, stage path and problems found. | **To confirm** | Not started | none |
| 16.5 | Call review: transcript with tool actions, stage changes, mood, techniques, knowledge sources; tags, quality score, thumbs up/down feeding the review queue; audio only if a later consented recording feature exists. | **To confirm** | Not started | none |
| 16.6 | Analytics: funnel (dialed, answered, talked, qualified, booked, attended), cost per booked meeting, best times, objection counts, playbook A/B results. | **To confirm** | Not started | none |
| 16.7 | Billing: Razorpay first (Stripe if abroad), GST invoices, usage-based charges, trial credits, plan limits, failed-payment handling, suspend and resume through platform admin. | **To confirm** | Not started | none |
| 16.8 | Account safety: two-factor sign-in for owners and admins if not present, session controls, invitation flow check. SSO later. | **To confirm** | Not started | none |
| 16.9 | Owner view for Virat: per-customer cost, revenue and margin, call health, provider status, Phase 14 kill switches. | **To confirm** | Not started | none |
| 16.10 | Customer help: in-app help per step, status page, support email, counsel-approved terms, privacy policy and data processing agreement. | **To confirm** | Not started | none |

## Decisions and open questions

- Virat: legal entity for contracts and GST invoices, bank account, payment gateway account
  (also Phase 17).
- Confirm the "under an hour" onboarding target.
- Whether two-factor sign-in already exists: **to confirm** in the code before WP-16.8.

## Parts of the system it touches

- Dashboard: onboarding wizard, knowledge base, templates, practice runs, call review,
  analytics, billing, owner view, help pages.
- Backend: knowledge base storage and retrieval (tenant-scoped), simulator personas, usage
  engine for billing, payment gateway adapter, platform admin, auth.
- Today the dashboard already has agent setup, test call, leads, campaigns, calls with
  transcripts, compliance, audit, usage, team, platform admin and an onboarding page.

## Risks and dependencies

- Depends on Phase 15 (calendar and CRM connections in onboarding), Phase 12 (techniques in
  call review, playbook A/B), Phase 14 (kill switches), Phase 17 legal pack (terms, privacy,
  DPA).
- Knowledge base documents are untrusted input: prompt-injection and tool-abuse tests needed
  (cross-cutting security).

## Measured results

None yet.

## Done checklist

- [ ] WP-16.1 to 16.10 done (done-when to confirm for most)
- [ ] Gate 16 met
- [ ] Definition of done for each WP; `CLAUDE.md` status and this file updated
