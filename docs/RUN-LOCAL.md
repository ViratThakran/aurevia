# Run Aurevia on your own computer (Windows 10 or 11)

This guide gets the whole app running on your PC: the database, the API, the voice server,
the voice worker and the dashboard. Then you can talk to the agent with your microphone. It
takes about 30 minutes the first time, mostly downloads.

You type commands into **PowerShell** (Start menu → type "PowerShell" → open it). Copy each
grey block as it is, paste it into PowerShell and press Enter.

> **Your keys stay on your computer.** You put them in one file, `backend\.env`, which git
> ignores, so it can never be committed. Never paste a key into chat, a document, a screenshot
> or a GitHub comment. If one ends up somewhere it shouldn't, rotate it at the provider.

## What a voice test costs

Talking to the agent uses three paid services, billed to your own accounts:

| What | Service | Key in `.env` |
|---|---|---|
| Understanding your speech | Deepgram | `DEEPGRAM_API_KEY` |
| The agent's voice | Cartesia | `CARTESIA_API_KEY` |
| The agent's thinking | Google Gemini | `AUREVIA_GEMINI_API_KEY` |

On 17 Oct the Cartesia account ran **out of credits**. Top it up before a voice test, or the
agent stays silent and the dashboard shows a voice-failure notice. Everything else (dashboard,
leads, campaigns, Learning) works without these keys.

## 1. Install the tools (once)

1. **WSL 2** (Docker needs it). In PowerShell **run as administrator** (right-click →
   "Run as administrator"):

   ```powershell
   wsl --install
   ```

   Restart the PC when it asks. If it says WSL is already installed, carry on.

2. **Docker Desktop and Git.** In a normal PowerShell window:

   ```powershell
   winget install -e --id Docker.DockerDesktop
   winget install -e --id Git.Git
   ```

   If `winget` is not found, download them instead: Docker Desktop from
   https://www.docker.com/products/docker-desktop/ and Git from https://git-scm.com/download/win.

3. Start **Docker Desktop** from the Start menu and accept the terms. Wait until the bottom
   left says **Engine running**. Settings → General: tick **Use the WSL 2 based engine** (it
   usually is already).

4. Install **Google Chrome** if you don't have it. The microphone test is written for Chrome.

5. Close PowerShell and open a new window, so it finds the new tools. Check:

   ```powershell
   docker --version
   git --version
   ```

   Both should print a version number.

## 2. Get the code (once)

```powershell
cd $HOME
git clone https://github.com/ViratThakran/aurevia.git
cd aurevia
```

A GitHub sign-in window may open, because the repository is private. Sign in with the account
that owns it.

To get the latest code later, run this in the `aurevia` folder:

```powershell
git pull
```

## 3. Your local settings file, `backend\.env` (once)

1. Make your copy of the example file and open it in Notepad:

   ```powershell
   cd $HOME\aurevia\backend
   Copy-Item .env.example .env
   notepad .env
   ```

2. You need four random passwords, which only your computer uses. Make each one with this
   command (run it four times and copy each result):

   ```powershell
   $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString("x2") }) -join ""
   ```

3. In Notepad, fill in these lines. The right-hand sides below are descriptions; put your own
   values there, with no quotes and no spaces around `=`:

   ```text
   AUREVIA_JWT_SECRET=<random password 1>
   POSTGRES_USER=aurevia
   POSTGRES_PASSWORD=<random password 2>
   POSTGRES_DB=aurevia
   AUREVIA_APP_DB_PASSWORD=<random password 3>
   AUREVIA_GEMINI_API_KEY=<your Gemini key>
   DEEPGRAM_API_KEY=<your Deepgram key>
   CARTESIA_API_KEY=<your Cartesia key>
   ```

   (Random password 4 is spare. Use it if you ever reset the database and want new passwords.)

4. Find the line `AUREVIA_CORS_ORIGINS=` and change it so the dashboard may call the API:

   ```text
   AUREVIA_CORS_ORIGINS=["http://localhost:3002","http://localhost:3000"]
   ```

5. Leave `AUREVIA_DATABASE_URL` and `AUREVIA_MIGRATION_DATABASE_URL` **empty**: Docker fills
   them in. Leave the LiveKit lines as they are: they are local development values, not
   secrets.

6. Optional: to see the Phase 12 screens (Learning, review queue, playbooks), add these two
   lines. They are off by default:

   ```text
   AUREVIA_LEARNING_ENABLED=true
   AUREVIA_PLAYBOOKS_ENABLED=true
   ```

7. Save (Ctrl+S) and close Notepad.

Check that git ignores the file. This should print `.env` back to you:

```powershell
git check-ignore .env
```

If it prints nothing, stop and ask before going further.

## 4. Start everything

Make sure Docker Desktop says **Engine running**, then:

```powershell
cd $HOME\aurevia\backend
docker compose --profile voice up -d --build
```

The first time this downloads and builds for 5 to 15 minutes. Later starts take seconds. When
it finishes, check that everything is up:

```powershell
docker compose --profile voice ps
```

You should see `api`, `postgres`, `livekit`, `redis`, `voice-worker`, `dashboard` and
`voice-test` with status **running** (postgres also says **healthy**).

| Open in Chrome | What it is |
|---|---|
| http://localhost:3002 | The dashboard (use this) |
| http://localhost:8000/docs | The API reference |
| http://localhost:3000 | The old bare test page (not needed) |

## 5. First sign-in and a browser test call

1. Open **http://localhost:3002** in Chrome and choose **Create an account**. This creates a
   workspace on your own computer only. Use any email; nothing is sent.
2. **Agent** page: fill in your company description (the agent only says what is written
   there), the goal of the call and the opening line. Set the language to `en-IN` and the
   voice to **Meera** (female) or **Dev** (male). Press **Save**.
3. **Leads** page: add a test lead with your own name. Browser calls need no phone number.
4. Put on **headphones**, so the agent doesn't hear itself.
5. **Test call** page: pick the lead and press **Start test call**. When Chrome asks to use
   the microphone, choose **Allow**.
6. Wait for the greeting, then talk normally. Press **End call** when you're done.
7. **Calls** page: open the call to see the transcript, the reply times and the usage.

Browser calls never dial a phone. Phone calls stay off unless they are set up separately
(they are not, today).

## 6. The microphone test (WP-10.5)

The full test, with scoring, is in
[`docs/06-testing/voice-manual-acceptance.md`](06-testing/voice-manual-acceptance.md). In
short:

1. Allow about 30 minutes. Use headphones and a quiet room.
2. Run sections A to F of that document, with a **new test call for each section**, first with
   Meera, then the language rows again with Dev.
3. Write the time of each call and mark each row **Pass**, **Fail** or **Slow** (about 2
   seconds or more of silence after you stop talking). For a fail, note roughly what was said.
4. Afterwards the **Calls** page has every transcript, so you can match a fail to what the
   agent heard and said.
5. Record your decision in that document (or tell me the results and I'll write them in).
   Gate 10's proposed pass mark is an average of 4 out of 5 on naturalness and timing, with
   no call that breaks a safety rule.

Watch especially for these. Each one is a fail:
- the agent says or implies it is human;
- it claims something is booked or sent when it isn't;
- it invents a price or fact that isn't in your company description;
- it keeps talking over you.

## 7. Stop

```powershell
cd $HOME\aurevia\backend
docker compose --profile voice down
```

This stops everything and **keeps** your workspace, leads and calls for next time. To start
again, repeat step 4 (without `--build`, unless you ran `git pull`).

To wipe the local database completely and start fresh:

```powershell
docker compose --profile voice down -v
```

**This deletes all local data**: workspace, leads, calls and transcripts.

## 8. Common problems

| You see | What to do |
|---|---|
| `error during connect` or `The system cannot find the file specified` (mentions `dockerDesktopLinuxEngine`) | Docker Desktop is not running, or it stopped by itself (it does that). Start it, wait for **Engine running**, and run the command again. |
| `set POSTGRES_USER in .env` (or another `set ... in .env`) | A line in `backend\.env` is empty, or you're not in the `backend` folder. Run `cd $HOME\aurevia\backend` and check the file. |
| `WSL 2 installation is incomplete` or `Virtualization is not enabled` | Run `wsl --install` as administrator and restart. If it still fails, turn on virtualization ("Intel VT-x" or "AMD-V/SVM") in the PC's BIOS settings. |
| `port is already allocated` / `address already in use` | Another program uses that port. For 5432 (another Postgres), add `POSTGRES_HOST_PORT=5433` to `.env`. For other ports, see which program it is: `netstat -ano \| findstr :8000` (use the port from the message). Close that program and start again. |
| Sign-in or sign-up does nothing, or the browser console says **CORS** | `AUREVIA_CORS_ORIGINS` in `.env` must include `http://localhost:3002` (step 3.4). Then run `docker compose --profile voice up -d` again. |
| Sign-in fails after a restart | Your `AUREVIA_JWT_SECRET` changed or is empty. Set it once and keep it. |
| `The AI model is not configured` | `AUREVIA_GEMINI_API_KEY` is empty or wrong in `.env`. Fix it, then run `docker compose --profile voice up -d`. |
| The agent answers slowly or stops mid-call; logs say `rate_limited` | The free Gemini key hit its per-minute limit. Wait a minute, or use the paid key. |
| The call connects but the agent is silent; the dashboard shows a voice-failure notice | Check the worker's log: `docker compose logs --tail 50 voice-worker`. `402` from Cartesia means **out of credits**; `401` means a wrong key (`CARTESIA_API_KEY` or `DEEPGRAM_API_KEY`). Never paste the log into chat without checking it holds no keys. |
| Chrome never asks for the microphone, or says it is blocked | Click the icon left of the address bar → Site settings → Microphone → Allow. Also Windows Settings → Privacy & security → Microphone → let desktop apps (Chrome) use it. |
| The agent interrupts itself or hears its own voice | Use headphones. |
| You changed `.env` but nothing changed | Run `docker compose --profile voice up -d`. It restarts the containers whose settings changed. If in doubt, add `--force-recreate`. |
| After `git pull` something is broken | Rebuild: `docker compose --profile voice up -d --build`. |
| The page at http://localhost:3002 doesn't load | Check `docker compose --profile voice ps` and the dashboard's log: `docker compose logs --tail 50 dashboard`. |

To see what a part of the app is doing, use `docker compose logs -f api` (or `voice-worker`,
`dashboard`). Press Ctrl+C to stop following the log; the app keeps running.

If you're stuck, send me the exact error line and which step you were on. **Check that it
holds no key first.**
