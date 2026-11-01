# Chronos demo script (S16d)

For showing Chronos to our project guide and examiners, and for recording the demo video.
2026-11-02 · Rohan (with Claude Code) · branch `docs/demo-script`.

- **Length:** 8–10 minutes (planned 8 min 55 s, section 2).
- **Where it runs:** on a laptop. The deployed site is about 9 times slower, so it is shown, not
  driven (D64). Address: <https://chronos-l6x6.onrender.com/>
- **Who does what:** Rohan drives the mouse throughout, so Nidhi and Dhruv only talk in their steps.
- **Period names:** this script uses T0–T9 as the screen does. The code and other docs say P0–P9
  for the same periods (D60).
- **Not yet rehearsed in a browser.** The Claude in Chrome extension was not connected, so the
  clicks and wording come from the code and the backend calls were run for real (section 5). The
  planned times are estimates until the rehearsal by hand.

**Numbers on screen.** Every place, score and count in steps 2–13 assumes the demo began with
`--reset`, which restores the committed timetable. Generate changes them, so Generate comes last,
and the next demo starts with a reset. Say no score aloud except 26.5 and the printed 21.5; for the
rest, point at the line named in the table. Section 2.1 lists the values to check against.

## 1. Before the demo

Start 15 minutes early. Never type a password into this file or a chat.

### Laptop

Terminal 1, from the repo root:

```powershell
# Docker Desktop. Repeat docker info until it answers without an error.
Start-Process "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
docker info

.\.venv\Scripts\Activate.ps1

# Database. 55432 is this laptop's port; use "5432" if no native PostgreSQL owns that port.
$env:CHRONOS_DB_PORT = "55432"
docker compose up db -d
docker compose ps        # db must say healthy

$env:DATABASE_URL = "postgresql+psycopg2://chronos:chronos@localhost:$env:CHRONOS_DB_PORT/chronos"
alembic upgrade head

# Skip this line if backend\.env already has SECRET_KEY.
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"

# Typed, not echoed. --reset creates missing demo accounts, sets the demo passwords again, clears
# the accepted changes and restores the committed 26.5 timetable without solving (D63).
$env:CHRONOS_DEMO_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Demo password')).Password
python -m backend.app.demo_seed --reset

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

`demo_seed` must end with `job …: solved, official`.

Terminal 2, from the repo root:

```powershell
cd frontend; npm run dev
```

It must print `Local: http://localhost:5173/`. If it prints another port, an old dev server is still
running: stop that one in its own terminal with Ctrl+C. (Run `npm ci` once beforehand if
`frontend\node_modules` is missing.)

### Checklist

- [ ] `Invoke-RestMethod http://127.0.0.1:8000/health` answers `ok`.
- [ ] Laptop on mains power, notifications off, other windows closed.
- [ ] Chrome window maximised, browser zoom 100% (Ctrl+0), page in light mode.
- [ ] http://localhost:5173 open at the login page.
- [ ] Logins ready: `demo-admin`, `demo-faculty`, `demo-student`, with `demo-coordinator` as the
      spare. Five wrong passwords lock a username for five minutes.
- [ ] Deployed site opened and logged in **2 minutes early**, in its own tab. It sleeps when idle:
      waking takes up to about a minute, then about 6 s to show the timetable. Touch nothing there.
- [ ] Demo video ready to play from the laptop, as the last fallback.

### Recording the video

Run the checklist, then record steps 1–16 in one take, in the same order. Keep the file outside the
repository. Run `--reset` again before any second take, because the take ends after Generate.

## 2. The arc

Where the page is long: click an empty part of the page, then **Home** or **End** jumps to the top
or bottom. The order down the page is Generate, Repair, Accepted changes, Quality, Comparison,
Weekly timetable, Room timetable and Free rooms, Free and engaged teachers, Problems found in the
source files, Audit log.

| # | Time | Who | Click | The audience should see | Say | If it fails |
|---|---|---|---|---|---|---|
| 1 | 0:20 | Nidhi | At http://localhost:5173: Username `demo-admin`, type the password, **Log in**. | "Signed in as demo-admin (Administrator)" at the top right; green badge "Solved, no clashes". | "Chronos builds a department's weekly timetable from its real data, using graph colouring and no machine learning." | Wrong password: retype once. Locked: use `demo-coordinator` and skip the audit log and Clear (steps 11, 12). Page stuck: look at terminal 1; if it has stopped, play the video. |
| 2 | 0:50 | Nidhi | **Timetable:** pick "Even semester 2025–26, as printed by SPIT". **Division:** pick "SE-Comp A". Click the first row of "Printed timetable: 36 violations". Scroll to the grid. | Badge "Printed timetable (SPIT)". Heading "Printed timetable: 36 violations". First row: "A teacher would be in two places at once", Tuesday T0, Kailas Devadkar with SE-Comp A and SE-Comp B. Its session outlined in red. | "Checked against our rules, SPIT's printed timetable has 36 hard-rule conflicts: 26 are lectures taught to two divisions together, which we schedule one per division, and 10 are TE practicals in slots held by fixed items." | Say the sentence and show `docs/real-baseline-even-2025-26.md` afterwards. Go on. |
| 3 | 0:50 | Rohan | **Timetable:** pick "Even semester 2025–26, SE and TE". **Division:** pick "SE-Comp A" (it went back to all). Scroll to "Weekly timetable". Point at the items in the next column. Then **Division:** "TE-Comp A", point at T4, and back to "SE-Comp A". | Period column T0–T9 with times such as "9:00 AM – 10:00 AM"; the T2 break row. "SE lunch" at T5, then "TE lunch" at T4 for TE. Tuesday T0–T1: "Lab block, 2 periods (T0–T1), 3 batches at the same time", with "SE-Comp A batch A", "batch C" and "batch D", each with its own room. | "This is the generated timetable for one division: each year has its own lunch, and a lab block runs its batches side by side, each in its own room." | Grid empty: check the Timetable picker says "SE and TE". Reload (F5) and log in again if needed. |
| 4 | 0:30 | Dhruv | **Home**, then scroll to "Timetable quality". | Score **26.5**. Under "Where points were lost": "Students' free periods", "Teachers without a break", "Teachers over the weekly limit", "Uneven teaching days". | "A timetable starts at 100 points and scores 26.5 here, losing points for free periods between students' classes, teachers with no break, teachers over the weekly limit, and uneven teaching days." | Card missing: click "Show quality score" in the header. Score not 26.5: you did not reset, so see the note under this table. |
| 5 | 0:30 | Dhruv | Scroll to "Generated and printed timetables compared". Point at the top row. | Row "Hard-rule violations (rules that must hold)": Generated **0**, Printed **36**. Sentence above: "The printed timetable scores lower on the soft rules and breaks 36 hard rules; the generated one breaks none." | "The generated timetable breaks no hard rule against the printed one's 36, and it also scores 26.5 against 21.5 on the soft rules." | Say it from `docs/evaluation-even-2025-26.md` § 3. Go on. |
| 6 | 0:40 | Rohan | Scroll below the grid. **Room timetable:** pick "701 (classroom, 80)". **Free rooms:** Thursday, T1. **Free and engaged teachers:** Thursday, T1. | Room 701, Thursday T1: "CE207 · SE-Comp A · Anant Nimkar (AVN)". Free rooms lists the rooms free then, with labs' free batch places. Engaged list: "Anant Nimkar (AVN): CE207 · SE-Comp A · 701". | "At any period, the coordinator can see what is in a room, which rooms are free, and which teachers are free or engaged." | Skip to step 7. |
| 7 | 0:30 | Dhruv | Scroll to the grid (Division still SE-Comp A). Drag the **CE207** lecture at Thursday **T1** (Room 701, not the one at T3) onto Wednesday **T0**, "Free: drop a session here". The page jumps up to the Repair panel. Point, then click **Discard**. | "Proposed: the grid shows the repaired timetable…". "Change: CE207 · SE-Comp A · Anant Nimkar (AVN) moved to Wednesday T0, Room 701". The "Score:" line and the "… session changed" line. | "A clean move is proposed, not applied: it shows exactly what would change, and nothing is official until someone accepts it." | Drag does nothing: try once more, or Tab to the card, Space, Tab to the cell, Enter. "This move is not allowed": you did not reset, so click Dismiss and skip to step 8. |
| 8 | 0:50 | Dhruv | Scroll to the grid. Drag the same lecture onto Monday **T1**, onto "MDM - I LABs" (T1, not T0). In the red box click **Repair around this**. Point down the panel, then click **Discard** below it. | Red box "This move is not allowed": "Clashes for CE207 (SE-Comp A) at Monday T1:", "MDM - I LABs holds SE-Comp A then." After about 1 s: "This change is not possible". "These 2 rules cannot all hold." "A fixed item already holds this time" and "The change you asked for". Green box "What would make it possible": "Free SE-Comp A from the fixed item at Monday T1."; "checked: with this change a timetable exists". "Official timetable: Unchanged." | "Instead of just failing, Chronos proves the move impossible, names the two rules in the way, and tells us what would make it possible, having checked that it would work." | Still running after 10 s: wait, it has a limit. If you dropped on T0 it takes about 5 s and also names room 701 as taken; the point still holds. Show `docs/repair-even-2025-26.md` § S17c only if it errors. |
| 9 | 0:35 | Dhruv | In "Mark unavailable": first list "Teacher", second list "Swapnali Kurhade (SK)". Tick **Tuesday T1** and **Thursday T1** (both show ●). **Mark unavailable and repair**. Point, then **Accept**. | After about 2 s: "Proposed: …", "Change: Swapnali Kurhade (SK) unavailable: Tuesday T1, Thursday T1", the "Score:" line, and the list of changed sessions marked "(moved)". After Accept: "Accepted: the repaired timetable is now the official one." | "When a teacher is absent, Chronos repairs only the sessions around the absence and leaves the rest of the week where it was." | "Not possible" or a refusal about a change already in force: you did not reset. Click Discard, say the sentence and skip to step 11. |
| 10 | 0:45 | Nidhi | **Division:** pick "SE-Comp C". In the grid, click (do not drag) the **CE206** lecture at Friday **T0**, Room 601. In the window: **Find substitute**. In "Find a substitute" click **Aishwarya Nalawade (AN)**. Point, then **Accept**. | Window "Operating Systems for SE-Comp C, Swapnali Kurhade (SK)". Two candidates with "quality score … if picked"; "Not suggested": Kailas Devadkar. Proposal: "1 session: teacher changed", "Swapnali Kurhade (SK) → Aishwarya Nalawade (AN)", "Weekly load, before → after", and the warning "16 h → 17 h, over the 16 h limit". | "Only teachers SPIT's faculty–subject sheets list for the subject and who are free are suggested, both workloads are recalculated with a warning over the limit, and a person decides." | The card moved a little and nothing opened: click it again. No candidates: click Close (X) on the panel, say the sentence and go on. |
| 11 | 0:30 | Nidhi | **Home**, scroll to "Accepted changes". Point. **End**, scroll up to "Audit log". Point at the top rows. | Two accepted changes: the absence and "CE206 · SE-Comp C: taught by Aishwarya Nalawade (AN)". Audit log, newest first: "demo-admin (administrator) accepted the repair for Aishwarya Nalawade (AN) teaching CE206 · SE-Comp C instead." | "Every later timetable keeps these accepted changes, and the audit log records who asked for what and who accepted it." | Not logged in as administrator: no audit log; skip it. |
| 12 | 0:15 | Nidhi | **Home**, scroll to "Accepted changes". **Clear accepted changes…**, then **Clear all**. | "No accepted changes." In "Timetable quality" the Score is back to 26.5. | "Clearing the changes makes the last timetable made without them official again, so the official timetable is always valid." | Clear not offered: you are a coordinator; skip it and reset afterwards. |
| 13 | 0:45 | Dhruv | **Home**. In "Generate a timetable" leave the limit at 300. **Generate**. Read the question aloud. Red **Generate**. Wait about 15 s. Scroll to "Timetable quality", then the comparison card. | "Generate makes a new timetable and replaces the official one for everyone. Continue?" Then "Running: … s of at most 300 s", then "Done: the grid and quality score show the new timetable." A **lower** Score than 26.5. Hard-rule row: Generated 0, Printed 36. The sentence now reads "…scores higher on the soft rules but breaks 36 hard rules; the generated one breaks none." | "This quick run uses fewer improvement steps than the committed timetable, so its score is lower, though it still breaks no hard rule, and the next demo starts with a reset." | Not finished after 60 s: keep talking, it has 300 s. "No timetable found within 300 s" means no answer, not impossible (D33). Stuck: move on; nothing was replaced. |
| 14 | 0:30 | Rohan | Top right **Log out**. Log in as `demo-faculty`. | "Signed in as demo-faculty (Faculty Member)". "Weekly teaching load: Anant Nimkar (AVN)" with the hours split into lectures and practicals. Only that teacher's sessions. No Generate, Repair or Quality card. Read only. | "A teacher sees only their own timetable and their own workload, read only." | Skip to step 16. |
| 15 | 0:20 | Rohan | **Log out**. Log in as `demo-student`. | "Signed in as demo-student (Student)". "Class: SE-Comp A", locked. The class's timetable with its lab blocks. | "A student sees their own class's timetable, and nothing else." | Skip to step 16. |
| 16 | 0:15 | Nidhi | Open a **new tab** and go to `https://chronos-l6x6.onrender.com/`. Show the address bar and the login page. Do not log in. | The Chronos login page at the deployed address. A new tab has no session, so it asks for a login. | "The same system is deployed at this address on a free server about nine times slower than this laptop, so we show it here rather than drive it." | Slow to appear: switch to the tab logged in earlier. No answer: say the address and stop. Do not wait on stage. |

**Last fallback, any step:** play the demo video from that step, and say what it shows.

**Wrong score at step 4.** The demo did not start from a reset. Before the audience is in the room:
stop uvicorn with Ctrl+C in terminal 1, run `python -m backend.app.demo_seed --reset`, start uvicorn
again, press F5 and log in. If the audience is already watching, say the timetable on screen is from
an earlier run, then play the video.

### 2.1 Values to check against

Do not read these aloud. **A fresh Generate changes all of them.** They hold only from `--reset`,
in this order, and come from the run in section 5.

| Step | Score line | What moved |
|---|---|---|
| 7 Small drag (Discard) | 26.5 → 16.0 | 1 session changed: Thursday T1 → Wednesday T0, Room 701 |
| 8 Drag onto MDM-I lab (Discard) | none | Nothing; official stays 26.5 |
| 9 Absence (Accept) | 26.5 → 18.5 | 5 sessions changed: three SE-Comp C practicals Thursday T1 → T3, and two SE-Comp C lectures swap Tuesday T0 and T1 |
| 10 Substitute (Accept) | 18.5 → 16.5 | 0 moved, 1 teacher changed; candidates Amey Ganesh Nile (AGN) −1.5, Aishwarya Nalawade (AN) −2.0 |
| 12 Clear | back to 26.5 | Exactly the committed timetable |
| 13 Generate | below the printed 21.5 | 83 sessions in a different slot from the committed timetable |

Anant Nimkar's load in step 14 is "6 h lectures + 8 h practicals = 14 h"; Generate does not change
who teaches what, so this one stays.

## 3. Likely questions

| Question | Short answer | Backed by |
|---|---|---|
| Why graph colouring? | Each session is a vertex, each clash (same teacher, same students, same room) is an edge, and a period is a colour, so a valid timetable is a colouring with no clash. Greedy Welsh-Powell alone leaves 8 of 156 real sessions unplaced, so backtracking with forward checking finishes the job. | `docs/algorithms.md` (Conflict graph, Welsh-Powell, Backtracking); `docs/evaluation-even-2025-26.md` § 1; DSGT, DAA |
| Why no machine learning? | Identical input must give identical output, and every result must be explainable. A learned model could not prove a move impossible or name the rules in the way. We rejected the reinforcement-learning route on purpose. | `docs/CONTEXT.md` § 2 rule 1; `CLAUDE.md` rule 1 |
| How does repair differ from solving again? | Repair freezes the timetable and frees only what the change touches, growing outwards if needed. Over the 25 changes both solved, of 30 drawn, repair moved about 4.5 sessions and regeneration about 88. In that run 3 repairs and 2 regenerations reached the 300 s limit; one of those repairs, change 29, finishes in about 10 s since S17c. | `docs/evaluation-even-2025-26.md` § 7 (S15e: 4.48 [1.93, 7.03] vs 87.76 [82.52, 93.00]); `docs/repair-even-2025-26.md` § S17c |
| What are the printed timetable's 36 conflicts? | A time-only check against our rules. 26 are one teacher with two divisions at once: lectures SPIT teaches to two divisions together, which we schedule one per division because our classrooms seat 80. 10 are TE practicals in slots held by fixed items. So they are not all SPIT's mistakes. Rooms cannot be checked: 58 printed sessions are in rooms outside our list. | `docs/evaluation-even-2025-26.md` § 3; `docs/real-baseline-even-2025-26.md`; D40, D24, D10, D28, D29 |
| What does a timeout mean? | No answer within the limit, and nothing else. It is never reported as impossible, the screen says "This does not prove it is impossible", and the official timetable stays. | D33; `frontend/src/lib/wording.ts`; `docs/evaluation-even-2025-26.md` § 9 |
| How were qualifications checked? | They come from SPIT's faculty–subject sheets, not from the solver, and Nidhi checked them by hand against `Faculty___Subjects.xlsx`. Chronos suggests and a coordinator decides. For 37 of 156 sessions nobody listed is free, and the screen then offers a repair. The sheets do not say lecture or practical for the six subjects here. | D53; `data/instances/even-2025-26/qualifications.json`; PR #71; `docs/evaluation-even-2025-26.md` § 9 |
| Why sub-rooms first, and why two attempts? | Filling one batch place of a split lab leaves its other places free, instead of blocking the whole lab; that took the committed score from −15.0 to 26.5. Each room order has cases it gets stuck on, so a fresh solve tries sub-rooms first for 5,000 search nodes, then rooms by id. The budget is a node count, so it is deterministic, and a verdict from the first attempt stands. | D58, D62; `docs/algorithms.md` (Backtracking); `docs/real-solve-even-2025-26.md` § S14u; DAA |
| Why is the deployed site slower? | It runs on Render's free instance, about 9 times slower than a laptop, and it sleeps when idle. A repair that takes 2 s here takes 20–70 s there. Upgrading is a later team decision. | D64, D55; `README.md` (Deploy) |
| Why does a repair lower the score? | Repair puts moving as little as possible first and never trades a move for score. So the timetable stays familiar, at some cost in points. | `docs/repair-even-2025-26.md` § Limits |
| What are the known limits? | No proof the score is the best possible: 26.5 is one seed at 1,000,000 moves, and seeds 0–4 at 200,000 average 12.9, below the printed 21.5. Repair keeps moves low but does not prove a minimum. Results cut by a wall-clock limit can differ between machines. SE and TE only (156 sessions), one semester, one department built. The generated week has 10 slots with no free classroom, against none printed over the same rooms. 11 of 15 printed lab percentages are reproduced, and the 4 mismatches are reported, not adjusted. | `docs/algorithms.md` (Limits and honest caveats); `docs/evaluation-even-2025-26.md` §§ 4, 8; `docs/CONTEXT.md` § 3 |

## 4. After the demo

### Laptop

The data must be reset before the next demo. In terminal 1, press Ctrl+C to stop uvicorn, then:

```powershell
python -m backend.app.demo_seed --reset
```

For another run, start uvicorn again as in section 1, press F5 in Chrome and log in. To finish:

```powershell
Remove-Item Env:CHRONOS_DEMO_PASSWORD
docker compose stop db
```

Stop the dev server with Ctrl+C in terminal 2. Stop only what you started, in its own terminal;
never kill processes by name.

### Production

**Only Nidhi, by hand (D59).** No agent and nobody else runs this. It is `README.md` Deploy step 2,
in a **new** PowerShell window, closed afterwards, when nobody is solving on the site. The angle
brackets are placeholders; never write the real values into the repository.

```powershell
.\.venv\Scripts\Activate.ps1

$pw = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Supabase database password')).Password
$env:DATABASE_URL = "postgresql+psycopg2://postgres.<project-ref>:$([uri]::EscapeDataString($pw))@<session-pooler-host>:5432/postgres?sslmode=require"
Remove-Variable pw
$env:CHRONOS_ALLOW_REMOTE_DB = "1"   # this window and this command only (D57, D59)

$env:CHRONOS_DEMO_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Demo password')).Password
python -m backend.app.demo_seed --reset

Remove-Item Env:CHRONOS_DEMO_PASSWORD*, Env:CHRONOS_ALLOW_REMOTE_DB, Env:DATABASE_URL
exit
```

## 5. Rehearsal record

**Browser rehearsal: not run.** On 2026-11-02 the Claude in Chrome extension was not connected, so
nobody has yet clicked through this script. Fill in the last column at the rehearsal by hand, and
fix the script wherever a click, name or expectation is wrong.

**What was checked instead, on 2026-11-02:**

- **Backend:** the calls of steps 1, 7–13, 14 and 15 ran in this order through the real API, on a
  scratch copy of the instance and a scratch local database (dropped afterwards), starting as
  `--reset` does. Every outcome is in section 2.1. After Clear, the official timetable equalled
  the committed one exactly. `demo-faculty` and `demo-student` got 403 on the audit log and on
  Generate.
- **Wording:** the clash text, diagnosis sentences, change text, comparison sentences, names, times
  and dropdown labels were printed by the frontend's own functions on the committed data.
- **Read from the code, not seen on screen:** the page layout, scrolling and jumps, drag behaviour,
  and which click opens what.
- **Deployed site:** `/api/health` and `/` answered 200.

| Step | Planned | Backend time (one run) | Measured by hand |
|---|---|---|---|
| 1 Log in | 0:20 | | |
| 2 Printed, 36 conflicts | 0:50 | | |
| 3 Generated, SE-Comp A | 0:50 | | |
| 4 Quality card | 0:30 | | |
| 5 Comparison card | 0:30 | | |
| 6 Rooms and teachers | 0:40 | | |
| 7 Small drag | 0:30 | 1.1 s | |
| 8 Drag onto MDM-I lab | 0:50 | 1.0 s | |
| 9 Absence | 0:35 | 1.8 s | |
| 10 Substitute | 0:45 | list 0.2 s, repair 0.2 s | |
| 11 Accepted changes, audit log | 0:30 | | |
| 12 Clear | 0:15 | | |
| 13 Generate | 0:45 | 13.5 s | |
| 14 Faculty view | 0:30 | | |
| 15 Student view | 0:20 | | |
| 16 Deployed site | 0:15 | | |
| **Total** | **8:55** | | |

Backend times are from the moment the request was sent until the job read as finished, polling
every 0.05 s. The page polls once a second, so it can show a result up to a second later.
