# Pilot runbook (Phase 9)

How to run the pilot with 2–3 friendly customers, what to watch, what to do when something goes wrong, and how to decide go / no-go.

## 0. Prerequisites (blocking)

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Host with a public IP (Indian region), the stack deployed, HTTPS in front of the API and the dashboard | Aurevia | open |
| 2 | Exotel trunk and numbers; outbound trunk configured in LiveKit ([telephony.md](../02-voice/telephony.md)) | Aurevia | open |
| 3 | Faster model or key (latency target: median < 1.0 s) | Aurevia | open |
| 4 | Counsel review recorded for the policy version (`operator review`) | Counsel + Aurevia | open |
| 5 | Provider keys rotated (the dev keys were shared in chat) and kept only in the host's `.env` | Aurevia | open |
| 6 | Daily backups scheduled and one restore checked on the host | Aurevia | open |

Until items 1–4 are done, a pilot runs on **browser calls and the customers' own test phones only**. The gate enforces this; nothing needs to be switched off.

## 1. Onboarding a pilot customer

1. They sign up at the dashboard. Onboarding covers the agent setup and a browser test call.
2. A platform admin sets their plan: **Platform admin → Plan**, for example 300 calls and 600 minutes a month, 2 at once.
3. Together with them:
   - Fill in the agent: company facts with no prices unless approved, qualification questions, objection and escalation guidance.
   - Run 3 test calls each, playing a skeptical, an interested and a busy prospect.
4. Phone tests: they register their own phones under **Compliance → Numbers**.
5. Agree on the review rhythm (section 3).

## 2. Daily checks (5 minutes)

- **Overview:** calls, meetings, typical reply time; **Meetings & tasks:** open handoffs (someone must call those people back the same day).
- **Platform admin:** each tenant's calls this month, against their plan.
- **API logs:**
  - `Model request failed` (model outages; the fallback serves)
  - `Dialing failed`
  - `Auto-dialer tick failed`
- **Health check:** `curl https://<api>/api/v1/health/ready` should report the database as ok.

## 3. Weekly review with each customer

- **Listen and score:** 5 call transcripts per customer (**Calls**). Score each 1–5 for: natural, helpful, honest, on goal.
- **Sales outcomes:** meetings booked per connected call, handoffs, do-not-call requests.
- **Cost:** **Usage**, against the price list in **Platform admin → Prices**, giving cost per call and cost per meeting.
- **Write it down:** every bad moment becomes a new scenario in `evaluation/scenarios.py`.

## 4. Incident process

Detect → correlate → classify → mitigate → recover → review → add a regression test.

| Severity | Examples | Respond |
|---|---|---|
| S1 | A call reached someone it should not have (gate failure); data visible across tenants; the agent claimed to be human or made a false promise | Same hour: suspend the tenant or stop the dialer (`AUREVIA_CAMPAIGN_SCHEDULER_ENABLED=false`, restart the API); keep the evidence (decision record, transcript, audit log); tell the customer |
| S2 | Calls fail or the agent is silent; model outage beyond the fallback; latency doubled | Same day: check provider status and the model fallback; pause campaigns |
| S3 | Poor answer, wrong tone, a small UI bug | Next weekly review |

For every incident:
- Write the incident note (what happened, timeline, impact, cause, fix).
- Add a regression test or scenario.
- For S1, verify the audit log (**Audit log → Verify**) and export the decision records involved.

Correlate with these IDs:
- the request id (the `X-Request-ID` header, and in every log line)
- the call id (dashboard **Calls**)
- the compliance decision id (dashboard **Compliance → Decisions**)

## 5. Backups and restore

```bash
backend/scripts/backup.sh          # daily (cron); keep 30 days, off-host copy weekly
backend/scripts/restore_check.sh   # weekly: restores into a scratch DB, compares every table
```

- Targets for the pilot: recovery point ≤ 24 h, recovery time ≤ 2 h.
- Backups contain personal data: encrypted storage only, never in git.

## 6. Go / no-go after the pilot (4–6 weeks)

**Go** requires all of:
- [ ] Zero S1 incidents (or every one fully explained, fixed and covered by a test)
- [ ] Gate: zero calls placed without an allow decision (check: every phone call has a decision)
- [ ] Median reply time < 1.0 s, p95 < 1.8 s on pilot calls
- [ ] Average call-review score ≥ 4/5 for honesty and helpfulness
- [ ] Sales scenarios 8/8 (plus every scenario added during the pilot)
- [ ] Each customer says they would keep using it; at least one meeting booked per customer
- [ ] Cost per call known (all usage priced), and inside the plan's margin
- [ ] Counsel review done; a backup restore checked on the production host

**No-go** if any of these fail. Fix, then pilot again for 2 weeks.
