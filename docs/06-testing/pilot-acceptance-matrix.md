# Pilot acceptance matrix (Phase 9)

Every item of [pilot-acceptance-tests.md](pilot-acceptance-tests.md), mapped to the test that proves it. Test names are `file::test_` (backend tests under `backend/tests`, worker tests under `voice-worker/tests`). **Sales scenarios** are the model-in-the-loop evaluation, `python -m aurevia.evaluation.run` (see [voice-evaluation.md](voice-evaluation.md)).

Status:
- ✅ proven by an automated test or evaluation
- 🟡 proven in the dev stack, but needs the pilot environment or a person to confirm
- ⛔ not met yet

Last full run: 2026-10-10. Backend and worker suites pass; sales scenarios 8/8.

## Voice

| Item | Evidence | Status |
|---|---|---|
| Speech reaches STT | Live browser calls since Phase 2 (26-turn call, 2026-10-08); `test_speech_providers::builds_deepgram_and_cartesia_behind_livekit_interfaces` | 🟡 a person confirms on the pilot setup |
| AI responds | `integration/test_voice::full_browser_call`; sales scenarios (real model) | ✅ |
| TTS streams | `test_backend_bridge::backend_llm_streams_through_livekit`; live calls | 🟡 a person confirms |
| Latency meets defined target (median < 1.0 s, p95 < 1.8 s) | Measured: median ~2–4 s on the Gemini dev key (`turn_metrics`, simulator) | ⛔ needs a faster model or key (decision 2026-10-09) |
| Interruption stops speech | Barge-in measured in the Phase 3 simulator (`--barge-in`); `test_gateway::consumer_stopping_early_closes_the_provider_stream` | 🟡 |
| New turn is understood | `test_conversation::turn_must_end_with_the_prospect`; the simulator | ✅ |
| Connection failure is handled | `integration/test_voice::worker_failure_marks_the_call_failed`; `integration/test_telephony::a_room_that_ends_closes_its_open_call`, `::an_unanswered_call_fails_and_frees_the_agent`; `test_gateway::falls_back_before_the_first_word` | ✅ |

## Sales

| Item | Evidence | Status |
|---|---|---|
| Identify intent | Scenarios `interested_books_meeting`, `not_interested` | ✅ |
| Qualify | Scenario `interested_books_meeting` (`qualify_lead`); `integration/test_sales_tools::recording_tools_and_validation` | ✅ |
| Explain approved information | Scenario `price_objection_no_invented_numbers`; `test_conversation::prompt_carries_honesty_rules_company_facts_and_state_goal` | ✅ |
| Handle objection | Scenario `price_objection_no_invented_numbers` (`log_objection`) | ✅ |
| Never invent product information | Scenario `price_objection_no_invented_numbers` (forbids any amount) | ✅ |
| Schedule follow-up | `integration/test_sales_tools::recording_tools_and_validation` (incl. rejecting past dates) | ✅ |
| Book meeting | Scenario `interested_books_meeting`; `integration/test_sales_tools::slots_then_booking_then_no_double_booking` | ✅ |
| Escalate to human | Scenarios `wants_a_human`, `send_me_an_email`; `integration/test_sales_tools::call_without_lead_and_handoff` | ✅ |
| Record outcome | Tool audit (`tool_executions`), `integration/test_platform::analytics_summary` | ✅ |
| Never claim a failed action succeeded | `integration/test_sales_tools::rejected_booking_reaches_the_model_as_not_ok`; judge `claims_need_their_tool`; scenario `do_not_call_request` | ✅ |

## Memory

| Item | Evidence | Status |
|---|---|---|
| Store useful fact | `integration/test_memory::second_call_recalls_the_first` | ✅ |
| Retrieve later | same | ✅ |
| Use naturally | `test_memory_extraction::notes_are_data_and_cannot_open_new_prompt_sections`; live call 2026-10-09 | 🟡 human-judged quality |
| Correct stale fact | Memory deletion API (`integration/test_memory`), the prompt prefers what the prospect says now | 🟡 |
| Prevent cross-tenant access | `integration/test_memory::memory_is_tenant_isolated`; `integration/test_rls::*` | ✅ |

## Security

| Item | Evidence | Status |
|---|---|---|
| Tenant A cannot access Tenant B | `integration/test_rls::*`, `integration/test_tenant_isolation::*`, the per-phase RLS tests | ✅ |
| Unauthorized tool call rejected | `integration/test_sales_tools::recording_tools_and_validation` (unknown tool, invalid arguments, no lead) | ✅ |
| Provider secrets inaccessible to clients | `integration/test_secrets::no_secret_appears_in_any_response`; `test_provider_selection::logs_redact_secrets_in_messages_fields_and_tracebacks`; the dashboard keeps the refresh token out of JS | ✅ |
| Webhook authentication works | `integration/test_telephony::webhooks_must_be_signed`; verified against the real LiveKit server (forged → 401) | ✅ |
| Authentication / authorization / object-level | `integration/test_auth::*`, `integration/test_platform::custom_roles_and_no_privilege_escalation`, `::permission_changes_apply_immediately` | ✅ |
| Prompt injection resistance | Scenario `prompt_injection`; memory notes framed as data | ✅ |
| CSV ingestion safety | `integration/test_platform::csv_import_into_a_campaign` (validation, limits, unknown columns) | ✅ |
| Rate limiting | `test_ratelimit::*` (API per IP, sign-in per IP and per email) | ✅ |

## Compliance

| Item | Evidence | Status |
|---|---|---|
| Disallowed call blocked | `integration/test_telephony::a_number_that_is_not_a_test_number_is_never_dialed`; `test_compliance_checks::*` (70 rules) | ✅ |
| Outside-window call blocked | `test_compliance_checks::calling_window_boundaries`; `integration/test_telephony::outside_the_calling_window_nothing_is_dialed` | ✅ |
| Required consent / policy state verified | `test_compliance_checks::missing_consent_is_blocked`; `integration/test_compliance_hardening::live_calls_open_only_under_a_reviewed_version` | ✅ |
| Decision audited | `integration/test_telephony::*` (decision records); `integration/test_compliance_hardening::the_audit_log_is_chained_and_tampering_shows` | ✅ |
| Gate cannot be bypassed | `test_architecture::only_the_gated_dialer_places_calls`, `::only_the_gate_issues_approvals`, `::an_approval_cannot_be_forged` | ✅ |
| Counsel review of the policy | [counsel-review-pack.md](../04-compliance-security/counsel-review-pack.md) | ⛔ needs a lawyer |

## Operations

| Item | Evidence | Status |
|---|---|---|
| Backups restore | `backend/scripts/backup.sh` + `restore_check.sh`: restored 34 tables with identical row counts (2026-10-10) | ✅ on dev; repeat on the pilot host |
| Real phone call to an own number | [telephony.md](../02-voice/telephony.md) | ⛔ needs hosting and Exotel |

**Verdict:** the software is ready for a pilot on browser calls and test phones. Calls to real prospects stay blocked by design until three things are done: counsel review, hosting with Exotel, and a faster model.
