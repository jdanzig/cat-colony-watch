# Cat Colony Watch: build plan

## 1. The problem

The full challenge text is in [`docs/CHALLENGE.md`](docs/CHALLENGE.md). **Read it first.** Its "What a fix must respect" and "What solved looks like" lists are the acceptance criteria for this project.

Mangrove Mews Cat Rescue is a made-up Miami rescue with a real problem. The founder, Beatriz, runs it after her day job with 20 volunteers and feeders and cares for **18 street cat colonies**. Updates arrive all day as WhatsApp messages, photos and shared locations. It all has to be recorded: which cats are fixed, which still need **TNR** (trap, neuter, return), who's sick, and who feeds each colony. Today it lives in group chats, a camera roll, a notebook and a spreadsheet only Beatriz understands. That causes three problems:
- two volunteers photograph the same cat, and she's counted twice;
- a pregnant cat's photo sinks under 200 messages;
- when a sponsor asks how many cats were fixed, Beatriz can only guess.

> "I just want anyone on my team to know, the same day, how each colony is doing and what it needs."

### Rules the fix must respect (from the brief)

| rule | how this plan meets it |
|---|---|
| Free, or close to it, and simple to run without technical help | Render free plus Upstash free, deployed with one click from a Blueprint (§4). A plain-language README for Beatriz. |
| Volunteers report from their phones, in a minute or two | A phone-first **Report** screen: one tap for "Fed", or a photo plus optional note for a sighting, with the location from the phone (§9). |
| Colony locations and feeders' names and phone numbers are seen only by the rescue's own people | **The whole app sits behind a team passcode.** The sponsor report and anything shared outside the team leave out locations, names and phone numbers (§4). |
| **A person confirms before two cats' records are merged, or before a cat is marked adopted or missing** | The AI only **suggests** a match or a status change. A person confirms each one with one tap. Nothing is merged automatically (§7c). |
| No automation of live WhatsApp chats | Input is only a chat saved with WhatsApp's **Export chat** option, or the app's own Report form. |
| Made-up messages, photos and locations only (the organizers clarified this means **no private photos**; openly licensed public photos are fine) | Demo messages, colony names and locations, and feeders' names and phone numbers are all invented. **Demo photos are openly licensed Wikimedia Commons photos,** credited in `data/demo/PHOTO_SOURCES.md`. No private photos (§10, step 1). |

### What a judge must see in the demo (from the brief)

1. A feeder's message, photo and shared location, sent from a phone, update the right colony and the right cat, with nobody retyping them.
2. Each colony's current state is clear: the number of cats, how many are fixed and how many are still waiting for TNR, which ones need a vet, and **who fed them last and when**.
3. The same cat, photographed by two volunteers, is counted once.
4. Urgent cases stand out the same day: a pregnant or injured cat, new kittens, or **a colony that has lost its feeder**.

The demo script (§11) shows each of the four in order.

## 2. Hackathon constraints

- **Submission deadline: Sun Nov 8, 2026, 4:45 PM EST.** The event runs Sat 12–9 PM and Sun 12–9 PM, but submissions close at 4:45 PM.
- The repo must be **public** with an **MIT** license by the deadline. The license is already in place, and the repo is private until just before submission.
- **Required technologies:** **Codex** (build with it), the **OpenAI API** and the **OpenAI Agents SDK**.
- **Judging,** each criterion out of 10:
  1. Fit to the "What solved looks like" list above.
  2. Originality.
  3. Strength of the use of Codex and the OpenAI platform.
  4. Feasibility and reasoning.
  5. Delivery of the presentation.
- **Presentation:** it's scored, but the format and time limit aren't on the public page; they're behind sign-in on the hackathon site. The event's own line is "Not slide decks. Shipped software," so plan on a **live demo of the deployed app**, with at most one or two slides.
- **Team:** solo.

### Budget: $100 in Codex credits and $50 in OpenAI API credits

- **API ($50) pays for the product:** photo descriptions, matching calls and the agent. The $50 has to cover development runs, the matching checks and the live demo.
  - **Cache every AI result by a hash of its input** (image hash plus prompt version). Re-running must never pay twice for the same thing. This is the biggest saving.
  - **Set a hard monthly spending limit** in the OpenAI dashboard, about $40, so a runaway loop can't drain the credits.
  - **Develop on a small sample** of about 10 messages and 10 photos. Run the full import only to check the end-to-end flow, and again for the demo.
  - **Use a cheaper model while developing**, and the better vision model for the matching checks and the demo. `OPENAI_MODEL` switches between them.
  - **Log the cost of every call**, so we always know what's been spent and can quote the cost per 100 photos in the pitch.
  - Resize images to about 768 px on the long side before sending.
- **Codex ($100) pays for building.** Work one step from §10 at a time, not "build the whole app." Read the diffs instead of looping on failing runs, and check the remaining balance after each step.
- **Stop rule:** if API spend passes $25 before Sunday, switch to the cheaper model everywhere and demo from a run that's already processed.

## 3. The pitch in one line

Volunteers keep reporting the way they already do, from their phones. Cat Colony Watch turns those messages and photos into a live record of every colony and every cat. It recognizes the same cat across different volunteers' photos, puts urgent cases at the top the same day, and shows who fed each colony last. **The AI suggests; a person confirms every merge.**

## 4. Who uses it, and where it runs

- **Both people, on both devices:**
  - **Volunteers and feeders, on phones, out on the street:** they report in under a minute and can see a colony's status.
  - **Beatriz, on a laptop or phone:** the dashboard, the confirm queue and reports.
  - Design every screen **for phones first**, so it also works on a laptop.
- **Two ways in, one pipeline:**
  1. **Import a chat export:** the `.zip` that WhatsApp's **Export chat** option produces, with `_chat.txt` and photos. This brings in the history.
  2. **The Report screen** in the web app, which is the live input. Every report records who sent it (the volunteer picks their name once, and it's remembered on that phone) and when.
     - **"Fed":** a single tap, with the colony picked or guessed from the phone's location. This is the feeder visit log.
     - **"Sighting":** a photo from the phone camera (`<input type="file" accept="image/*" capture="environment">`), an optional note in English or Spanish, and the location from the browser.
     - **"Urgent":** the same as a sighting, but flagged by the volunteer, such as an injured cat or kittens.
     It feeds the same agent as an imported message. **This is the stretch goal "keeps the census current as new messages arrive."**
- **Privacy: only the rescue's own people see locations, names and phone numbers.**
  - **The whole app requires the team passcode** (`TEAM_PASSCODE`), entered once per phone and kept in a long-lived cookie. Without it, every page and API call returns the sign-in screen. That covers the map, colony pages, feeder names and phone numbers, and photos, since street photos can give away a location.
  - **A separate admin passcode** (`ADMIN_PASSCODE`) is needed for imports and the demo reset.
  - **The sponsor report** is the only thing shared outside the team. It shows counts only, such as cats fixed this year, colonies served and open needs, using colony **nicknames** and no locations, names, phone numbers or photos. It's reachable through a secret link (`/report/<token>`) that the team can share.
  - Give the judges the team passcode in the submission, so they can use the live app.
- **Hosting:** free only, nothing paid.
  - **One Render free web service** runs the FastAPI app, which serves both the API and the page. Deploy it from a **Blueprint** (`render.yaml`), so setup is a few clicks. Use: free plan, health check at `/healthz`, prompts for secret values, and **region `virginia`**, the closest to Miami.
  - Secrets (`OPENAI_API_KEY`, `OPENAI_MODEL`, `TEAM_PASSCODE`, `ADMIN_PASSCODE`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`) go in Render's environment settings, never in the repo.
  - **It sleeps after about 15 minutes idle,** and the first visit then takes up to a minute. Open the URL a few minutes before presenting.
  - **The disk is wiped on every restart or deploy,** so the data that must last goes in **Upstash Redis free**, through its REST API:
    - **SQLite stays the working database** that the app queries. It's rebuilt on every startup.
    - **Startup:** load the committed demo data and the **committed cache of AI results** (`data/demo/ai_cache.json`), which needs no API calls. Then **replay the change log from Upstash.**
    - **The change log** is every change made in the live app, appended as JSON to one Redis list: a report with the AI's results (so a replay never calls the API again), a confirm or reject decision, an alert marked done, an import. Photos from new reports, already resized to about 768 px, are stored under their file hash.
    - **Prefix every key with `ccw:`**, so the database could be shared with another project if ever needed.
    - **Without the Upstash variables** (local development), the log is a local JSON file instead.
    - **A demo reset** (admin passcode) clears the log and restores the known demo state, for use right before presenting.
  - **Protect the credits:** besides the passcodes, set a daily API spend cap in code (stop at $3 per day) alongside the dashboard limit.
- **Language:**
  - **Messages are in English and Spanish:** the demo chat mixes both, as Miami volunteers would. The model reads both with no extra work.
  - **The interface starts in English.** Keep all on-screen text in one dictionary (`ui_text.js`), so an **English/Español toggle** is a small stretch task.
- **README for Beatriz,** in plain language:
  - how to deploy (the Blueprint button and the values to paste in);
  - how to share the link and passcode with volunteers;
  - how to export a WhatsApp chat and import it;
  - what each screen is for.

## 5. Architecture

Keep it small: one Python app, one SQLite file and one HTML page.

```
Chat export (.zip)     Report screen (phone)
        │                     │
        ▼                     │
1. Parse   messages, senders, timestamps, photos, shared-location links
        │                     │
        └──────────┬──────────┘
                   ▼
2. Describe   OpenAI vision call per photo → structured JSON with a box per cat (§7a)
                   │
                   ▼
3. Agent      Agents SDK agent, one run per message or report, with tools (§7b)
              → colony, feeding, cat(s), health, needs, urgency
                   │
                   ▼
4. Match      per colony: compare each cat crop with that colony's known cats (§7c)
              → a SUGGESTION: same cat (strong or weak) / new cat
                   │
                   ▼
5. Confirm    a person confirms each merge and each adopted/missing change (one tap)
                   │
                   ▼
6. Alerts     plain rules over the records (§8)
                   │
                   ▼
7. UI         Today · Colonies (map + list) · Cat profiles · Confirm · Report · Sponsor report
```

**Stack:**
- Python 3.11+ with **FastAPI**, serving JSON and one static HTML/JS page. No frontend build step.
- **SQLite** through the stdlib `sqlite3`. No ORM.
- `openai` (vision and structured output) and `openai-agents` (the agent).
- **Leaflet** from a CDN for the map.
- **Pillow** only for resizing and cropping. **All the AI runs on the OpenAI API:** no local models.
- `httpx` or stdlib `urllib` for Upstash's REST API. No Redis client library is needed.
- The model is set by `OPENAI_MODEL`. Use a current vision-capable model and check the OpenAI docs for the current one.
- Secrets live in `.env`, which is gitignored. Commit a `.env.example`.

## 6. Data model (SQLite)

| table | key fields |
|---|---|
| `colonies` | id, name (a made-up nickname such as "Laundromat"), lat, lng, notes |
| `volunteers` | id, name, phone (made-up), role (`feeder` / `volunteer` / `admin`) |
| `colony_feeders` | colony_id, volunteer_id (who normally feeds each colony) |
| `cats` | id, colony_id, display_name ("Gray tabby, white chest"), description_json, tnr_status (`fixed` / `needs_tnr` / `unknown`), health (`ok` / `needs_vet`), health_note, pregnant (bool), **status** (`active` / `adopted` / `missing` / `deceased`), first_seen, last_seen, reference_photo |
| `photos` | id, path, report_id, description_json, crop_box, cat_id (null until confirmed or created) |
| `reports` | id, sent_at, volunteer_id, kind (`message` / `fed` / `sighting` / `urgent`), text, lat, lng, source (`import` / `app`), raw |
| `events` | id, colony_id, cat_id?, report_id, kind (`fed` / `sighting` / `tnr_done` / `health` / `kittens` / `need` / `status`), detail, at, volunteer_id |
| `suggestions` | id, kind (`same_cat` / `status_change`), photo_id or cat_id, candidate_cat_id or new_status, strength (`strong` / `weak`), feature_verdicts_json, reason, decided (`confirmed` / `rejected` / null), decided_by, decided_at |
| `alerts` | id, colony_id, cat_id?, kind, severity, text, created_at, resolved_at |

**Counting rule, which keeps "the same cat is counted once":** a photo with a pending `same_cat` suggestion doesn't create a new cat. It waits in the confirm queue and is shown on the suggested cat's profile as "1 unconfirmed sighting." A new cat record is created only when the match step finds no plausible candidate, or when a person taps "New cat." Colony counts include only `active` cats.

Every count in the UI and reports is computed from these tables, so the numbers agree everywhere.

## 7. AI steps in detail

### 7a. Photo description (OpenAI API, vision, structured output)
Make one call per photo. The output schema:
```json
{
  "cat_count": 1,
  "cats": [{
    "box": [0.12, 0.30, 0.55, 0.92],
    "view": "side" | "front" | "back" | "face",
    "coat_color": "gray", "pattern": "tabby", "markings": ["white chest", "white left front paw"],
    "eye_color": "yellow", "tail": "long, ringed",
    "ear_tip": "left" | "right" | "none" | "unclear",
    "apparent_health": ["limping right hind leg"],
    "looks_pregnant": true, "is_kitten": false
  }],
  "kittens_present": false,
  "photo_quality": "good" | "poor"
}
```
- An ear tip (a clipped ear) is the standard sign that a cat is already fixed. Use it to set `tnr_status`.
- `box` is the cat's bounding box as fractions of the photo (left, top, right, bottom). Pillow crops each cat out with it, so matching compares **cats, not backgrounds**: two cats photographed against the same laundromat wall must not match because of the wall. A photo with three cats becomes three crops.

### 7b. Message agent (Agents SDK)
One `Agent` reads each imported message or app report, with its photo descriptions, location and sender attached, and records it using tools. It returns a structured summary of what it did. The Report screen shows that summary to the volunteer.

The tools (`@function_tool`):
- `list_colonies()`: names and coordinates.
- `find_colony(lat, lng, text_hint)`: the nearest colony, or "none within 300 m".
- `log_feeding(colony_id, volunteer_id, at)`
- `list_cats(colony_id)`: the colony's active cats with their descriptions.
- `match_photo(photo_id, colony_id)`: runs §7c and **creates a suggestion**, or a new cat if nothing is plausible. It never merges.
- `record_event(kind, colony_id, cat_id?, detail)`
- `update_cat(cat_id, tnr_status?, health?, health_note?, pregnant?)`. Only these fields, never `status`.
- `suggest_status(cat_id, new_status, reason)`: adopted, missing or deceased, as a suggestion for a person to confirm.
- `raise_alert(kind, severity, colony_id, cat_id?, text)`

**Agent instructions, in short:** never invent cats or facts that aren't in the message. Merges and adopted/missing changes are only ever suggested. When unsure, suggest; don't decide.

### 7c. Same-cat matching
The method below is the expected default. **`EVAL.md` tunes it.**

**Principle: the model reads, a fixed rule decides, and a person confirms.** The vision model reports what it sees, feature by feature. Plain code turns that into a suggestion of a given strength. A person confirms every merge, as the brief requires. A model's own "I'm 90% sure" isn't trustworthy; a rule over specific observations can be tested and tuned.

1. **Narrow,** with no AI call: compare only against active cats in the same colony, or within about 300 m. Drop cats whose stored description has a clearly different coat color. Optional: rank the rest by text-embedding similarity of the descriptions (`text-embedding-3-small`, which is very cheap) and keep the top 3–5.
2. **Compare:** one vision call with the new cat's crop and the candidates' reference crops (usually 1–5). For each candidate it returns a verdict per feature:
   ```json
   {"candidate": "cat_17", "features": {
      "coat_color": "same", "pattern": "same", "markings": "same: white bib, torn left ear",
      "ear_tip": "same", "eye_color": "not visible", "tail": "different"},
    "contradictions": ["tail ringed in new photo, plain in reference"]}
   ```
3. **Decide the suggestion, in code:**
   - **Strong suggestion:** at least two specific markings agree and nothing contradicts. It's shown pre-selected, so one tap confirms, and "Confirm all strong matches" handles a batch.
   - **Weak suggestion:** some agreement, or anything unclear. It's shown side by side for a closer look.
   - **New cat:** every candidate has a clear contradiction, or there are no candidates. A new record is created; this is not a merge.
   - **Any contradiction rules out a strong suggestion.** Tune the thresholds on the `EVAL.md` results.

**Do not** send all photos in one call. Accuracy drops and results vary between runs.

**Check early:** whether the OpenAI API offers image embeddings. If it does, they could replace the text-embedding ranking in step 1. As far as we know it doesn't. Don't build on it without checking.

## 8. Alert rules (plain code, no AI)

| condition | severity | text |
|---|---|---|
| a cat `looks_pregnant` (or is reported pregnant) and isn't fixed | **urgent** | "Pregnant cat at {colony}: trap within days" |
| kittens reported or seen | **urgent** | "New kittens at {colony}: check for the mother" |
| health = needs_vet (injured or sick) | **urgent** | "{cat} needs a vet: {note}" |
| **a colony has lost its feeder:** no feeding logged for 2 days, or a feeder says they can't continue | **urgent** | "{colony} hasn't been fed since {day}" / "{feeder} can't feed {colony} anymore" |
| a feeder reports being out of food | high | "{colony} is out of food" |
| a new cat with no ear tip | normal | "New unfixed cat at {colony}: add to the TNR list" |
| suggestions waiting more than a day | normal | "{n} matches waiting to be confirmed" |

Alerts appear at the top of the app, sorted by severity and age, and each has a "Done" button.

## 9. UI (one page, phone-first, behind the team passcode)

1. **Today:** the alerts list, with urgent items first. This is the "same day" answer to Beatriz.
2. **Colonies:** a Leaflet map with 18 pins colored by the most urgent open alert, plus a list. A colony page shows:
   - **cats · fixed · waiting for TNR · needs a vet,** as four numbers at the top;
   - **"Last fed by Marta, today 7:10 AM,"** plus the feeding log;
   - its regular feeders, with names and phone numbers;
   - a card for each cat, which opens its **profile**: photos, status chips, last seen and a history of sightings and events.
3. **Confirm:** the queue of suggestions.
   - **"Same cat?"**: the new photo next to the suggested cat, the deciding markings ("same white bib, torn left ear"), and buttons for same, different and new cat. Strong suggestions are pre-selected, and a "Confirm all strong" button handles a batch.
   - **"Mark as adopted / missing?"**: the reason, with confirm and reject.
4. **Report:** the phone form from §4, with three big buttons: **Fed · Sighting · Urgent**. After sending, it shows what was recorded ("Logged feeding at Laundromat. Sighting of *Gray tabby, white chest*: matches Luna, waiting for confirmation"), so the volunteer sees right away that it worked. Aim for **under a minute** per report.

Admin only: **Import** a chat export `.zip`, with a progress line ("Processed 34 / 80"), and **Reset demo**. **Sponsor report:** the shareable counts-only page from §4.

## 10. Build order (do these in sequence; each step works before the next starts)

**Building and checking cat identification go together. Don't measure first and build later.** Build the real functions on the real API, check them right away on photos where we know which cat is which, and re-check every time a prompt or rule changes. See `EVAL.md`.

**Saturday (now → 9 PM)**

0. **Identification core plus its check, about 1.5 h.**
   - Write `describe_photo()` (§7a) and `match_cat()` (§7c, feature verdicts plus the suggestion rule) in the app's own module. These are the functions the app will call.
   - Write `eval/check_matching.py`. It runs them on the Wikimedia test photos in `eval_data/commons/`; if that folder is missing, `eval/fetch_commons.py` downloads it. It prints how often strong suggestions are right, the wrong-strong rate, the false-split rate and the cost.
   - Run it on a **small set first (5 cats, about $0.50)**. Fix the prompt or rule, run it again, then try the full set once.
   - Write each run's numbers into `eval/results/REPORT.md`.
1. **Demo data, about 1.5 h.** The messages, places and people are invented. The photos are openly licensed public photos, which the organizers confirmed is fine.
   - **`data/demo/colonies.json`:** 18 colonies with made-up nicknames ("Laundromat," "Church lot," "Marina dumpsters"). Use approximate points spread across Miami neighborhoods, **not real addresses**.
   - **`data/demo/volunteers.json`:** about 8 made-up volunteers and feeders, using the fictional `305-555-01xx` phone range, each assigned to colonies.
   - **Demo photos, from the Wikimedia set already in `eval_data/commons/`:**
     - pick about 12 cats for 5 detailed colonies, and give each a **made-up name**, not its real one;
     - use 2–4 photos of each, so repeat sightings by different volunteers really are the same cat;
     - include **look-alikes on purpose,** such as two red tabbies (Rum Tum Tugger and Caramel) or the two black cats (Cola and Miss Kitty) in one colony, so the confirm queue has something to show;
     - copy the chosen photos into `data/demo/photos/` and commit them;
     - list each photo's license, author and source page in `data/demo/PHOTO_SOURCES.md`, which CC licenses require, and link it from the README.
   - **Pregnant, limping and kittens come from the message text** ("está preñada," "she's limping on her back leg," "found 4 kittens in a box"), since pet photos rarely show these. The agent sets health and alerts from what the message says. If a Commons photo with kittens or a visibly pregnant cat turns up, use it.
   - **Keep the matching check honest:** when reporting `eval/check_matching.py` numbers, give them for the cats **not** used in the demo as well as for all cats, so tuning on demo cats can't inflate the score.
   - **`data/demo/_chat.txt`:** about 80 messages over 2 weeks, in WhatsApp's iOS export format, mixing English and Spanish, with the photos attached and shared-location links. Plant the brief's scenes:
     - two volunteers photograph the same cat on different days;
     - a new gray cat behind the laundromat;
     - a limping calico;
     - a shared location for a box of kittens;
     - a pregnant cat whose photo is buried mid-chat;
     - daily "fed" messages from feeders, then one colony with no feeding for 3 days;
     - a feeder who says she's moving away;
     - "Fixed today at the clinic 🎉" for some cats;
     - one cat that someone says has been adopted, which becomes a status suggestion.
2. **Parser, about 45 min.** `_chat.txt` → `reports`. Handle `<attached: …>` photo lines and Google Maps location links. Write one `assert`-based test on a sample of 10 lines.
3. **DB, the agent and its tools, about 2 h.** End-to-end import of the demo export into SQLite, then fill `ai_cache.json`.
4. **Alerts and the counting rule, about 30 min,** each with an `assert` test.
5. **Deploy to Render, about 45 min.** Do this tonight, so any hosting surprise has time to be fixed.
   - Set up the passcodes, the Upstash change log and seeding from demo data plus `ai_cache.json`.
   - **Check that a report added on the live site survives a manual redeploy.**

**Sunday (12 PM → 4:45 PM submission)**

6. **UI, about 2.5 h:** Today, Colonies with cat profiles, Confirm and Report, phone-first. Test Report on a real phone against the deployed URL. Re-run `eval/check_matching.py` after any change to prompts or rules.
7. **Sponsor report, about 30 min:** counts only, no locations, names, phone numbers or photos.
8. **Demo prep, about 1 h:**
   - README for Beatriz (§4) plus a short developer section, screenshots, the live URL and a "How we built it" note crediting Codex;
   - make the repo **public**;
   - the submission form, including the team passcode for judges. **Submit by 4:15 PM**, leaving a buffer.
   - Stretch, if there's time: the English/Español toggle.

Cut order if time runs short: Spanish toggle → map (keep the list) → sponsor report → chat import screen (keep a command-line import for the demo data).

## 11. Demo script (3 minutes, live on the deployed URL)

Each step shows one item from the brief's "What solved looks like" list.

1. **The problem, 20 s:** the messy chat, with hundreds of messages, photos and pins. Quote Beatriz.
2. **Urgent cases the same day (#4), 30 s:** Today shows "Pregnant cat at Laundromat: trap within days," from a photo buried mid-chat, "Church lot hasn't been fed since Tuesday," and new kittens.
3. **Colony state (#2), 30 s:** Laundromat shows 9 cats · 6 fixed · 3 waiting for TNR · 1 needs a vet, "last fed by Marta, today 7:10 AM," and the feeding log.
4. **Counted once (#3), 30 s:** two volunteers photographed the same cat. The Confirm queue shows them side by side with "same white bib, torn left ear." One tap, and it's one cat with two sightings. A look-alike pair is marked weak, so the app asks instead of guessing.
5. **Live from a phone (#1), 40 s:** on a phone, tap Report → Sighting, take a photo of a demo cat on screen, and send. It lands on the right colony and the right cat's profile in seconds, with nobody retyping anything. Then tap Fed, and "last fed" updates.
6. **Privacy and the sponsor report, 15 s:** the sponsor link shows "47 cats fixed this year" with no locations or names, and the app itself is behind the team passcode.
7. **How it's built, 15 s:**
   - OpenAI vision reads each cat feature by feature, a rule decides, and a person confirms;
   - an Agents SDK agent handles each message;
   - it was built with Codex and costs about $X per 100 photos;
   - the matching check measured how often a strong suggestion is right.

## 12. Open questions

- **After signing in on the hackathon site:** read the Judges and Submission tabs, and find the presentation format and length.
- **Ask the organizers:** how do judges evaluate Codex use, in the repo or in the demo?
- Which current OpenAI model has the best vision quality for the price? Check the docs.
- Is there an OpenAI image-embeddings endpoint? See §7c.
