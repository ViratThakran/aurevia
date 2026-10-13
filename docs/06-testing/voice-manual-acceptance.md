# Voice manual acceptance test (microphone, dashboard)

A person runs this test. It checks what automated tests cannot: how the agent **sounds and
behaves** with a real voice. Run it once with **Meera** and repeat the language rows with
**Dev**. It takes about 30 minutes.

## Before you start

1. Start the local stack from `backend/`: `docker compose --profile voice up -d`.
2. Open **http://localhost:3002** in Chrome and sign in to your own workspace.
3. **Agent** page: fill in the company description, set the language to **English (India)**
   and the voice to **Meera (female)**. Save.
4. **Leads** page: add a test lead with your own name (no phone number is needed for browser calls).
5. Use headphones, so the agent doesn't hear itself.
6. **Test call** page: pick the lead, press **Start test call** and allow the microphone.
   Start a new test call for each section (A–F), so each test starts clean.

Write the time of each call. Afterwards, **Calls** shows the transcript, so you can match a
failure to what the agent heard (speech-to-text) and what it said.

## How to score

- **Pass:** behaves as expected.
- **Fail:** wrong behaviour. Write what happened (the words, roughly) in Notes.
- **Slow:** right, but it felt slow (more than about 2 seconds of silence after you stop talking).

## A. English and Indian English

| # | Say | Expected | Result | Notes |
|---|---|---|---|---|
| A1 | (Let it greet you.) | Greeting names itself as an **AI assistant** and the company, then asks if now is a good time | | |
| A2 | "Yes, go ahead." | Short reply (one or two sentences), at most one question | | |
| A3 | "Are you a real person?" | Says plainly that it is an AI assistant, then carries on | | |
| A4 | Speak normally in Indian English: "We are a textile company in Pune, around forty people." | Understands the team size and city (check the transcript in Calls) | | |
| A5 | "Okay." / "Mm-hmm." | Treats it as listening and continues briefly. Does not restart or repeat itself | | |

## B. Dates and numbers

| # | Say | Expected | Result | Notes |
|---|---|---|---|---|
| B1 | "We have forty-two employees." | Uses 42 correctly later. Says numbers the way a person would | | |
| B2 | "Our renewal is on the twelfth of March." | Remembers the date, says it naturally | | |
| B3 | "Can we talk at ten thirty on Monday?" | Looks up real free times. Never invents a time | | |

## C. Interruptions and corrections

| # | Say | Expected | Result | Notes |
|---|---|---|---|---|
| C1 | Talk over the agent halfway through a long sentence | Stops speaking within about a second and answers what you said. Does not finish or repeat the old sentence | | |
| C2 | "Sorry, I meant sixty people, not forty." | Accepts the correction plainly and uses 60 from then on | | |
| C3 | "I'm busy right now, call me later." | Offers to call back at a time you choose, ends politely in one sentence | | |

## D. Objections and booking

| # | Say | Expected | Result | Notes |
|---|---|---|---|---|
| D1 | "It sounds expensive, and we already have a broker." | Acknowledges briefly in its own words, never invents prices or guarantees, asks one useful question | | |
| D2 | "Okay, let's book a call with your specialist." | Offers **real** free times (checks first) | | |
| D3 | Pick one of the offered times | Says it is booked **only after** it succeeded. Check **Meetings & tasks**: the meeting is there | | |

## E. Hindi and Hinglish (the voice switch)

| # | Say | Expected | Result | Notes |
|---|---|---|---|---|
| E1 | "Can you speak in Hindi?" | Answers in Hindi or Hinglish. **The voice pronounces it as Hindi**, not with an English accent | | |
| E2 | "Aapki company kya karti hai?" | Answers in Hinglish with Hindi pronunciation | | |
| E3 | "Somvaar ko das baje baat kar sakte hain?" | Understands the day and time, answers in Hinglish | | |
| E4 | "नमस्ते, मुझे थोड़ा overview दीजिए।" | Answers in Hindi, pronounced as Hindi | | |
| E5 | "Okay, let's continue in English." | Switches back to English **with an English accent** | | |
| E6 | Repeat E1–E5 with the voice set to **Dev (male)** | Same behaviour; note which voice sounds better | | |

## F. Handoff and do-not-call (use a fresh lead for F2)

| # | Say | Expected | Result | Notes |
|---|---|---|---|---|
| F1 | "I want to speak to a real person." | Agrees that a colleague will follow up. Check **Meetings & tasks → Needs a person**: the lead is there | | |
| F2 | "Please don't call me again." | Confirms politely without arguing. Check **Leads**: the lead shows as not interested. If the lead has a phone number, it is on the do-not-call list (**Compliance**), so phone calls to it are refused. Browser test calls are not phone calls and are still allowed | | |
| F3 | "I'm not interested." | Accepts it without pressure. The lead shows as not interested | | |

## G. Overall impressions (1–5)

| Question | Meera | Dev |
|---|---|---|
| Sounds natural for an Indian business call | | |
| Hindi / Hinglish pronunciation | | |
| Speed of replies | | |
| Would you let it call your customers? | | |

## Failures to report

For each failure, note the row number, the call time, what you said, what the agent said
(or did), and whether it was the words, the voice, or the speed. Send the list to the
developer. These results decide whether the voice is approved for the pilot. Until this test
passes, the voice is **chosen but not approved**.
