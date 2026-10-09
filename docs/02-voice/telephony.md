# Telephony (Phase 6)

Phone calls run through **LiveKit SIP**: a phone line joins the call's LiveKit room as one more
participant, so the voice worker, the conversation engine, tools, memory and transcripts work
exactly as for browser calls. The carrier (**Exotel** first) is only a SIP trunk configured in
LiveKit. Switching carriers is configuration, not code.

```text
POST /api/v1/calls/outbound {lead_id}
  -> compliance gate (decision recorded, allowed or blocked)
  -> call row (carries the decision id) + room + agent dispatch (channel=phone)
  -> background dial: LiveKit SIP -> Exotel -> the phone
       answered    -> agent hears sip.callStatus=active, starts the call, greets
       busy / no answer / failed -> call failed (end_reason dial_*), room closed

Inbound: phone -> Exotel -> LiveKit SIP -> room "aurevia-in-..."
  -> webhook participant_joined -> backend finds the tenant by the dialed number
  -> call row (inbound, lead matched by caller number) -> agent dispatched
```

## Safety rails

- **The gate cannot be bypassed.** `place_call` is called only from `telephony/service.py`
  `dial()`, which needs an `Approval`; only `ComplianceGate.check_outbound` can create one.
  Architecture tests enforce both. A database check also requires every outbound call row to
  reference the decision that allowed it, and one decision allows exactly one call.
- **Test mode (default)** dials only the tenant's registered test numbers (its own phones, at
  most 5). Every other number is blocked and the block is recorded.
- **Live mode** is blocked by the gate (`policy_not_reviewed`) until the India policy pack is
  reviewed by counsel (Phase 7). Setting `AUREVIA_TELEPHONY_MODE=live` alone cannot place a
  live call.
- **No DND registry is integrated yet.** Lookups answer "unknown", which the India pack treats
  as blocked. Own test numbers are not scrubbed.
- No audio is recorded (decision 2026-10-09). Transcripts follow the 90-day retention.

## The gate (India draft pack `india-2026-10-draft-1`)

| Check | Blocks when |
| --- | --- |
| mode | test mode and not a registered test number; live mode with an unreviewed pack |
| number | the lead's phone is missing/invalid, or not a +91 number |
| lead | lead archived, or marked not interested |
| do_not_call | number on the tenant's do-not-call list (incl. prospect requests during calls) |
| consent | no valid consent for this purpose (express; or an inquiry within 30 days) |
| dnd | registered on DND (express consent may override), or status unknown |
| calling_window | outside 09:00-21:00 India time (21:00 itself is outside) |
| attempts | 2 calls/day or 6/week per number (test mode: 20/day) |
| caller_id | no active, DLT-registered 140-series (promotional) / 160-series (service) number |

Every check runs every time. The decision record lists each result, the facts it saw, and the
policy version. **The values are a draft from the product brief and must be confirmed by
counsel before any live calling.**

## Hosting requirement

A carrier must reach the SIP service (UDP/TCP 5060 and the RTP range) over the internet. On a
laptop behind NAT, `docker compose --profile voice --profile telephony up` starts LiveKit SIP,
but no carrier can reach it. Real calls need a host with a public IP (a cloud VM in an Indian
region is the planned production shape), or LiveKit Cloud's managed SIP.

## First real test call (once hosted)

1. **Exotel:** get a SIP trunk (vSIP) and a number. From Exotel you need the SIP host/domain,
   digest username/password, and which numbers belong to the trunk. Ask Exotel to allow the SIP
   server's public IP. Confirm these details with Exotel's onboarding; this doc does not
   assume them.
2. **LiveKit:** create an outbound trunk (address = Exotel SIP host, auth = the digest
   credentials, numbers = the Exotel number). Put its id in
   `AUREVIA_LIVEKIT_SIP_OUTBOUND_TRUNK_ID`, and set `AUREVIA_TELEPHONY_PROVIDER=livekit_sip`.
3. **Inbound (optional):** create an inbound trunk for the Exotel number and a dispatch rule
   of type *individual* with room prefix `aurevia-in-` and **no agent dispatch**. The backend
   dispatches the agent after registering the call.
4. **LiveKit webhooks** must point at `https://<api>/webhooks/livekit` (signed with the API
   key), as in `docker-compose.yml`.
5. **Aurevia (owner/admin):** register the Exotel number (`POST /api/v1/telephony/numbers`,
   with `inbound_enabled` for inbound) and your own phone (`POST /api/v1/telephony/test-numbers`).
   Create a lead with your own phone number and call it: `POST /api/v1/calls/outbound`.
6. **Verify on that first call:** that the caller number arrives as the `sip.phoneNumber`
   attribute and the dialed number as `sip.trunkPhoneNumber` (used for inbound routing), and
   that busy / unanswered calls map to `busy` / `no_answer`.

Checked locally (2026-10-09): the real adapter against local LiveKit SIP with an unroutable
trunk (`sip.invalid`). LiveKit accepted the request and the SIP service attempted the dial;
the failure came back as `DialError(failed)` in 0.3 s. Real LiveKit webhooks reached the API
and passed signature verification. Forged or unsigned webhooks get 401.
