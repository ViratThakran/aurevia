# Counsel review pack: India policy `india-2026-10-draft-1`

**Purpose.** Aurevia places AI voice sales calls for its customers (initially insurance
brokers in India). Before any call reaches a real prospect, a server-side compliance gate must
allow it. This pack lists every rule the gate applies, the values we assumed, and the questions
we need counsel to answer. **Nothing here is legal advice. These are the engineering team's
assumptions, written down so they can be checked.**

**What review means in the product.** Rules live in an immutable, versioned policy file
(`backend/src/aurevia/compliance/packs/india-2026-10-draft-1.json`, SHA-256
`c10ff64e9d19357c5d9276ac750de78bcbb83d1ad3e57b75fa642946c86a45fd`). Live calling is impossible
until the platform operator records that counsel reviewed **this exact version**: who reviewed
it, when, and a reference to the written opinion. Any change counsel asks for becomes a new
version, which needs its own review. Customers can make the rules stricter, never looser.

**Who is responsible for what (please confirm).** We assume the customer (e.g. the broker) is
the principal entity / telemarketer of record under TRAI's rules and the data fiduciary under
the DPDP Act, and that Aurevia is a technology provider and data processor. Questions 1.1–1.2
ask whether that is right.

---

## 1. Roles and registrations

| # | Assumption | Question for counsel |
| --- | --- | --- |
| 1.1 | The customer registers on DLT as the principal entity; Aurevia does not. | Who must register on DLT (principal entity, telemarketer, both)? Does Aurevia need its own registration as the platform that places the calls? |
| 1.2 | Customer = data fiduciary; Aurevia = data processor. | Is this allocation correct for an AI agent that decides what to say, records facts and books meetings? What must our customer contract say? |
| 1.3 | Promotional sales calls use a 140-series caller ID; service calls use a 160-series one. Both must be registered (`dlt_registered`). | Is the 140 / 160 split right for AI-placed insurance sales and service calls? Are other headers or registrations needed for voice? |
| 1.4 | IRDAI rules apply because our first customers are insurance intermediaries. | Which IRDAI rules (telemarketing, distance marketing, outsourcing, call recording) apply to AI calls placed for a broker, and what do they require of us versus the broker? |

## 2. The gate's rules (every call, in this order; all must pass)

| Rule | Draft value | Question for counsel |
| --- | --- | --- |
| Destination | Only +91 numbers | Fine as a first market limit? |
| Calling window | Calls may **start** 09:00–21:00 India time (21:00 itself is outside), every day | Is 09:00–21:00 correct for promotional and for service calls? Are Sundays or public holidays restricted? Does the window apply to when a call starts, or must it also end by 21:00? |
| Consent: express | Valid until revoked or its expiry date | What must express consent contain (form, wording, evidence) to be valid for AI-placed promotional calls? Must it name AI calling specifically? |
| Consent: enquiry | A prospect's own enquiry counts as consent for **30 days** | Is implied consent from an enquiry valid at all for promotional calls, and for how long? |
| Consent purpose | Consent is per purpose (promotional / service) | Correct? |
| National DND | Every number is checked against the DND registry before each dial; **unknown status blocks** | Which source must we scrub against (DLT platform, operator API), and how fresh must the result be (we assume real time per call)? |
| DND override | **Express** consent allows calling a DND-registered number; enquiry consent does not | Can express consent override a full or partial DND preference under current TRAI rules? Under what conditions? |
| Do-not-call (customer list) | Always blocks, overriding any consent | Fine. |
| Attempts | At most **2 calls per day and 6 per week** to one number | Is there a legal cap? Is ours reasonable? |
| Lead status | Archived leads and leads who said "not interested" are never called | Should "not interested" become a do-not-call request automatically, or expire? |
| Caller ID | An active, DLT-registered number of the right series | See 1.3. |
| Disclosure | The opening line must contain: that it is an **AI**, the **agent's name**, the **company's name** | What must be disclosed at the start of an AI sales call (AI identity, principal entity, purpose, recording notice)? Is our check sufficient? |
| Campaign | Live calls must belong to an active campaign (dates, hours, attempts per lead, daily cap) | Are there rules for campaign records we should keep? |

Mid-call, the agent must stop and add the number to the do-not-call list as soon as the person
asks not to be called again. It must also say that it is an AI whenever asked, and it may not
claim an action succeeded unless the system confirms it.

## 3. Personal data (DPDP Act)

| # | What we do | Question for counsel |
| --- | --- | --- |
| 3.1 | Transcripts are kept **90 days**, then deleted automatically. No audio is recorded. | Is 90 days appropriate? Do IRDAI rules *require* keeping call recordings or transcripts for longer? |
| 3.2 | The agent remembers facts about a prospect across calls (needs, preferences), with confidence scores; these can be deleted. | What notice must the prospect receive about this processing, and when (at the start of the call)? Is consent needed for it? |
| 3.3 | **Access request:** an admin can export everything held about a person. | Format and time limits for answering? Must the person be able to self-serve? |
| 3.4 | **Erasure request:** transcripts, remembered facts, notes, objections, follow-ups, handoff reasons and tool records are deleted or redacted. Future appointments are cancelled. The lead becomes an anonymous stub. **Kept:** the number on the do-not-call list (so they are never called again), compliance decisions, consent records and call metadata (numbers, times, outcomes), as proof of lawful calling. | Is keeping these records lawful under the DPDP Act (legal obligation / legitimate use)? For how long may they be kept? Must the do-not-call entry store the number itself, or would a one-way hash suffice? |
| 3.5 | Data is hosted wherever the customer deployment runs; India hosting is planned. | Are there data-localisation requirements for this data (DPDP, IRDAI, sector rules)? |
| 3.6 | Speech-to-text, text-to-speech and the language model are third-party processors (Deepgram, Cartesia, Google Gemini; Anthropic planned). Audio and text pass through them. | What contractual terms and cross-border transfer conditions are needed? |

## 4. Audit and evidence

- Every gate decision records the checks, the facts seen (consents, DND result, attempt
  counts, campaign state), the policy version, and the effective rules after the customer's
  tightening. Decisions cannot be edited or deleted by the application.
- The customer's audit log is hash-chained: any edited or removed event is detectable, and the
  current head hash can be exported for safekeeping.

**Question 4.1:** what records must we be able to produce, for how long, and to whom (TRAI /
operators, IRDAI, the Data Protection Board, the customer)?

## 5. Not built yet (known gaps)

- No live DND registry integration: every number that is not the customer's own test phone is
  blocked until one exists.
- No audio recording, and so no recording notice or retention for recordings.
- No complaint-handling workflow beyond adding a number to the do-not-call list.
- Consent capture is recorded by the customer. Aurevia does not yet collect consent itself
  (e.g. web forms).

## Sign-off

Counsel's written opinion should reference the version above (`india-2026-10-draft-1`) and its
SHA-256. Changes are made as a new version (`india-…-2`), and that version is reviewed again.
The platform operator then records the review:

```bash
python -m aurevia.compliance.operator review <version> --by "<name, firm>" --reference "<opinion ref, date>"
```
