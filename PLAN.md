# Cat Colony Watch: build plan

## 1. The problem (from the challenge brief)

Mangrove Mews Cat Rescue is a made-up Miami rescue with a real problem. The founder, Beatriz, runs it after her day job with 20 volunteers and feeders and cares for **18 street cat colonies**. Updates arrive all day as WhatsApp messages, photos and shared locations:

- a feeder texts about a new gray cat behind the laundromat;
- a volunteer sends photos of a limping calico;
- someone shares a location for a box of kittens.

It all has to be recorded: which cats are fixed, which still need **TNR** (trap, neuter, return), who's sick, and who feeds each colony. Today it lives in group chats, a camera roll, a notebook and a spreadsheet only Beatriz understands. That causes three problems:

- **Double counting:** two volunteers photograph the same cat, and she's counted twice.
- **Missed emergencies:** a pregnant cat's photo sinks under 200 messages, and she gives birth before they can trap her.
- **No reliable numbers:** when a sponsor asks how many cats they've fixed, Beatriz can only guess.

> "I just want anyone on my team to know, the same day, how each colony is doing and what it needs."

**What "solved" means:** anyone at Mangrove Mews can see each colony's current state and needs the same day, without digging through chats and photos. The whole job counts, from a messy message to a census the team can trust.

- **Minimum:** turn a made-up batch of messages, photos, shared locations and notes into a census of each colony and each cat, working end to end.
- **Stretch:** an agent that keeps the census current as new messages arrive, plus reports for sponsors or the city.
- **Rule:** messages must come from an approved bot, a phone form or an **exported chat**. Never use unauthorized automation, such as scraping WhatsApp.

## 2. Hackathon constraints

- **Submission deadline: Sun Nov 8, 2026, 4:45 PM EST.** The event runs Sat 12–9 PM and Sun 12–9 PM, but submissions close at 4:45 PM.
- The repo must be **public** with an **MIT** license by the deadline. The license is already in place.
- **Required technologies:** **Codex** (build with it), the **OpenAI API** and the **OpenAI Agents SDK**.
- **Judging,** each criterion out of 10:
  1. Fit to the "solved" definition above.
  2. Originality.
  3. Strength of the use of Codex and the OpenAI platform.
  4. Feasibility and reasoning.
  5. Delivery of the presentation.
- **Presentation:** it's scored (criterion 5), but the format and time limit aren't on the public page. The Judges and Submission tabs only show after signing in, so **sign in and join the hackathon as a team of one.** That's needed to submit anyway. Then read those tabs and update §11. The event's own line is "Not slide decks. Shipped software," so plan on a **live demo of the deployed app**, with at most one or two slides.
- **Team:** solo. Teams can have up to 5 people.

### Budget: $100 in Codex credits and $50 in OpenAI API credits

- **API ($50) pays for the product:** photo descriptions, matching calls and the agent. The $50 has to cover development runs, the matching test and the live demo.
  - **Cache every photo description by file hash** in SQLite. Re-running an import must not pay again for photos it has already seen. This is the biggest saving.
  - **Set a hard monthly spending limit** in the OpenAI dashboard, about $40, so a runaway loop can't drain the credits.
  - **Develop on a small sample** of 10 messages and 10 photos. Run the full 80-message import only to check the end-to-end flow, and again for the demo.
  - **Use a cheaper model while developing**, and the better vision model for the matching test and the demo. `OPENAI_MODEL` switches between them.
  - **Log the cost of every call**, so we always know what's been spent and can quote the cost per 100 photos in the pitch.
  - Keep images small: resize to about 768 px on the long side before sending.
- **Codex ($100) pays for building.** Give it one focused step from §10 at a time, not "build the whole app." Read its diffs instead of letting it loop on failing runs, and check the remaining balance after each step.
- **Stop rule:** if API spend passes $25 before Sunday, switch to the cheaper model everywhere and cut the live re-import from the demo. Show a run that was already processed.

## 3. The pitch in one line

Volunteers keep texting the way they already do. Cat Colony Watch turns the chat export into a live record of every colony and every cat. It recognizes repeat sightings of the same cat from photos, flags urgent cases (pregnant, injured, kittens) the same day, and produces a sponsor report whose numbers can be trusted.

**Honesty principle:** the AI *suggests* matches and *explains* why. When it's unsure, a volunteer confirms with one tap. That keeps the census trustworthy, which is the challenge's own word, and it scores on feasibility.

## 4. Who uses it, and where it runs

- **Both people, on both devices:**
  - **Volunteers and feeders, on phones:** report a sighting and see a colony's status.
  - **Beatriz, on a laptop or phone:** the dashboard, the review queue and reports.
  - Design every screen **for phones first**, so it also works on a laptop.
- **Two ways in, one pipeline:**
  1. **Import a chat export:** the `.zip` with `_chat.txt` and photos. This brings in the history.
  2. **"Report a sighting" form** in the web app. It's the live input:
     - a photo, from the phone camera (`<input type="file" accept="image/*" capture="environment">`);
     - an optional note, in English or Spanish;
     - the location, from the browser's geolocation, or by picking a colony.
     It feeds the same agent as an imported message. **This is the stretch goal "keeps the census current as new messages arrive."**
- **Hosting:** free only, nothing paid.
  - **One Render free web service** runs the FastAPI app, which serves both the API and the static page. No separate frontend host such as Netlify is needed.
  - Put `render.yaml` in the repo and the deploy steps in the README.
  - Secrets (`OPENAI_API_KEY`, `OPENAI_MODEL`, `APP_PASSCODE`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`) go in Render's environment settings, never in the repo.
  - **Render free limits** and how we handle them:
    - **It sleeps after about 15 minutes idle,** and the first visit then takes up to a minute. Open the URL a few minutes before presenting.
    - **The disk is wiped on every restart or deploy.** Data is kept with **Render free plus Upstash Redis free**, through Upstash's REST API with `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`. Both accounts already exist.
      - **SQLite stays the working database** that the app queries. It's rebuilt on every startup.
      - **Startup:** load the committed demo data and the **committed cache of AI results** (`data/demo/ai_cache.json`), so no API calls are needed. Then **replay the change log from Upstash.**
      - **The change log** is every change made in the live app, appended as JSON to one Redis list: a new sighting (with the AI's results, so a replay never calls the API again), a review decision, an alert marked done, an import. Photos from new sightings, already resized to about 768 px, are stored under their file hash.
      - **Prefix every key with `ccw:`**, so the database could be shared with another project if ever needed.
      - **Without the Upstash variables** (local development), the log is a local JSON file instead.
      - **A demo reset** clears the log and restores the known demo state. It's passcode-protected, for use right before presenting.
      - Write `render.yaml`: free plan, health check at `/healthz`, Upstash values prompted for by the Blueprint. Use **region `virginia`**, the closest to Miami.
  - **Protect the credits on a public URL:**
    - importing and reporting require a passcode (`APP_PASSCODE`), while viewing is open;
    - set a daily API spend cap in code, for example stop at $3 per day, as well as the dashboard limit.
- **Language:**
  - **Messages are in English and Spanish:** the demo chat mixes both, as Miami volunteers would. The model reads both with no extra work.
  - **The interface starts in English.** Keep all on-screen text in one dictionary (`ui_text.js`), so an **English/Español toggle** is a small stretch task.
  - AI-written text such as alert wording and reasons stays in English for now.

## 5. Architecture

Keep it small: one Python app, one SQLite file, and one HTML page.

```
WhatsApp chat export (.zip: _chat.txt + photos)
        │
        ▼
1. Parse        plain Python: messages, senders, timestamps, attached photos, shared-location links
        │
        ▼
2. Describe     OpenAI vision call, one per photo → structured JSON (see §7a)
        │
        ▼
3. Extract      Agents SDK agent, one run per message (or small batch) with tools → colony, cat(s), event, need, urgency
        │
        ▼
4. Match        per colony: compare the new sighting with that colony's known cats → same / new / unsure (+ reason)
        │
        ├── confident → attach the sighting to the existing cat or create a new cat
        └── unsure    → review queue ("Same cat?" card, volunteer decides)
        │
        ▼
5. Alerts       plain rules over the records (see §8)
        │
        ▼
6. UI           colony map and list, colony page with cat cards, alerts, review queue, sponsor report
```

**Stack:**
- Python 3.11+ with **FastAPI**, serving JSON and one static HTML/JS page. No frontend build step.
- **SQLite** through the stdlib `sqlite3`. No ORM.
- `openai` (vision and structured output) and `openai-agents` (the agent).
- **Leaflet** from a CDN for the map.
- **Pillow** only for resizing and cropping images before they're sent. **All the AI runs on the OpenAI API:** no local models.
- The model is set by the `OPENAI_MODEL` environment variable. Use a current vision-capable model and check the OpenAI docs for the current one.
- Secrets live in `.env` (`OPENAI_API_KEY`), which is gitignored. Commit a `.env.example`.

## 6. Data model (SQLite)

| table | key fields |
|---|---|
| `colonies` | id, name ("Laundromat on NW 7th"), lat, lng, feeder(s), notes |
| `cats` | id, colony_id, display_name ("Gray tabby, white chest"), description_json, tnr_status (`fixed` / `needs_tnr` / `unknown`), health (`ok` / `sick` / `injured`), pregnant (bool), first_seen, last_seen, reference_photo |
| `photos` | id, path, message_id, description_json, cat_id (null until matched), match_confidence, match_reason |
| `messages` | id, sent_at, sender, text, location_lat, location_lng, raw |
| `events` | id, cat_id / colony_id, message_id, kind (`sighting` / `tnr_done` / `health` / `kittens` / `fed` / `need`), detail, at |
| `alerts` | id, colony_id, cat_id, kind, severity, text, created_at, resolved_at |
| `review_queue` | id, photo_id, candidate_cat_ids, reason, decided_cat_id, decided_by, decided_at |

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
An ear tip (a clipped ear) is the standard sign that a cat is already fixed. Use it to set `tnr_status`.

`box` is the cat's bounding box as fractions of the photo (left, top, right, bottom). Pillow crops each cat out with it, so matching compares **cats, not backgrounds**: two cats photographed against the same laundromat wall must not match because of the wall. A photo with three cats becomes three crops and three sightings.

### 7b. Message agent (Agents SDK)
One `Agent` reads each message, with its photo descriptions and location attached, and records it using tools. It returns a structured summary of what it did.

The tools (`@function_tool`):
- `list_colonies()`: names and coordinates.
- `find_colony(lat, lng, text_hint)`: the nearest colony, or "none within 300 m".
- `create_colony(name, lat, lng)`
- `list_cats(colony_id)`: the candidate cats with their descriptions.
- `match_photo(photo_id, colony_id)`: runs step 7c and returns same / new / unsure with a reason.
- `record_event(kind, colony_id, cat_id?, detail)`
- `update_cat(cat_id, tnr_status?, health?, pregnant?)`
- `raise_alert(kind, severity, colony_id, cat_id?, text)`

Agent instructions, in short: never invent cats or facts that aren't in the message. When unsure, queue the case for review; don't guess.

### 7c. Same-cat matching
The method below is the expected default. **`EVAL.md` decides the final method and threshold.**

**Principle: the model reads, a fixed rule decides.** The vision model reports what it sees, feature by feature. Plain code turns that into same / new / unsure. A model's own "I'm 90% sure" isn't trustworthy; a rule over specific observations can be tested and tuned.

1. **Narrow,** with no AI call: compare only against cats in the same colony, or within about 300 m. Drop cats whose stored description has a clearly different coat color. Optional: rank the rest by text-embedding similarity of the descriptions (`text-embedding-3-small`, which is very cheap) and keep the top 3–5.
2. **Compare:** one vision call with the new cat's crop and the candidates' reference crops (usually 1–5). For each candidate it returns a verdict per feature:
   ```json
   {"candidate": "cat_17", "features": {
      "coat_color": "same", "pattern": "same", "markings": "same: white bib, torn left ear",
      "ear_tip": "same", "eye_color": "not visible", "tail": "different"},
    "contradictions": ["tail ringed in new photo, plain in reference"]}
   ```
3. **Decide, in code:**
   - **Match** when the distinctive features agree (at least two specific markings agree) and nothing contradicts.
   - **New** when there's a clear contradiction with every candidate.
   - **Everything else goes to review.**
   - Tune the thresholds on the `EVAL.md` results. **Any contradiction always blocks an automatic match.**

**Do not** send all photos in one call. Accuracy drops and results vary between runs. See §10, step 0.

**Check early:** whether the OpenAI API offers image embeddings. If it does, they could replace the text-embedding ranking in step 1. As far as we know it doesn't. Don't build on it without checking.

## 8. Alert rules (plain code, no AI)

| condition | severity | text |
|---|---|---|
| a cat `looks_pregnant` and `tnr_status != fixed` | **urgent** | "Pregnant cat at {colony}: trap within days" |
| kittens reported or seen | **urgent** | "Kittens at {colony}: check for mother, consider pickup" |
| health = injured / sick | **high** | "{cat} looks {issue}: vet check" |
| new cat with no ear tip | normal | "New unfixed cat at {colony}: add to TNR list" |
| a colony has had no update for 7+ days | normal | "No news from {colony} in {n} days" |
| a message mentions being out of food or a feeder who can't make it | high | the extracted need |

Alerts appear at the top of the app, sorted by severity and age, and each has a "Done" button.

## 9. UI (one page, phone-first)

1. **Today:** the alerts list, with urgent items first. This is the "same day" answer to Beatriz.
2. **Colonies:** a Leaflet map with 18 pins colored by worst open alert, plus a list. A colony page shows:
   - counts: cats, fixed, needs TNR, sick;
   - its feeder or feeders;
   - its last update;
   - a cat card for each cat: photo, name, status chips, last seen, and the timeline of sightings.
3. **Review:** "Same cat?" cards with the new photo next to the candidate, the AI's reason, and three buttons: same, different, new cat.

4. **Report a sighting:** the phone form from §4: photo, note and location. After submitting, it shows what the agent did ("Added a sighting of *Gray tabby, white chest* at Laundromat colony; new alert: looks pregnant"), so the volunteer sees right away that it worked.

There's also an **Import** button to upload a chat export `.zip`, with a progress line for each message ("Processed 34 / 80"). And a **Sponsor report** page: cats fixed this period, colonies served and open needs, as a printable page.

## 10. Build order (do these in sequence; each step works before the next starts)

**Saturday (now → 9 PM)**

**Building and checking cat identification go together. Don't measure first and build later.** Build the real functions on the real API, check them right away on photos where we know which cat is which, and re-check every time a prompt or rule changes. See `EVAL.md`.

0. **Identification core plus its check, about 1.5 h.**
   - Write `describe_photo()` (§7a) and `match_cat()` (§7c, feature verdicts plus a code rule) in the app's own module. These are the functions the app will call.
   - Write `eval/check_matching.py`. It runs them on the downloaded test photos and prints accuracy, the false-merge rate, the review rate and the cost.
   - Run it on a **small set first (5 cats, about $0.50)**. Fix the prompt or rule, run it again, then try the full set once.
   - Write each run's numbers into `eval/results/REPORT.md`.
1. **Mock data, about 1 h.** Write `data/demo/_chat.txt` in the WhatsApp iOS export format, with about 80 messages over 2 weeks across 5 detailed colonies (list all 18 by name and location). The messages mix English and Spanish.
   - **Use photos from `eval_data/commons/`:** about 12 of the cats become demo cats spread across the colonies. Copy the photos you use into `data/demo/photos/`, and list each one's license and author in `data/demo/PHOTO_SOURCES.md`, which CC licenses require.
   - Pick look-alikes on purpose, such as two red tabbies in one colony, so the review queue has something to show.
   - Plant the challenge's scenes:
   - two volunteers photograph the same calico on different days;
   - a gray cat behind the laundromat;
   - a limping calico;
   - a box of kittens sent as a shared location;
   - a pregnant cat whose photo is buried mid-chat;
   - a feeder who's out of food;
   Write `data/demo/colonies.json` too.
2. **Parser, about 45 min.** `_chat.txt` → `messages`. Handle `<attached: …>` photo lines and Google Maps location links. Write one `assert`-based test on a sample of 10 lines.
3. **Photo description and DB, about 1 h.**
4. **Agent and tools, about 2 h.** End-to-end import of the demo export into SQLite.
5. **Alerts, about 30 min.**
5b. **Deploy to Render, about 30 min.** Do this tonight, not tomorrow, so any hosting surprise has time to be fixed. Seed the database from the demo data and `ai_cache.json` on startup, then replay the Upstash log. Set the passcode. Check that a sighting added on the live site survives a manual redeploy.

**Sunday (12 PM → 4:45 PM submission)**

6. **UI, about 2.5 h:** the Today, Colonies, Review and Report-a-sighting screens, phone-first. Re-run `eval/check_matching.py` after any change to prompts or rules.
7. **Sponsor report, about 30 min.**
8. **Demo prep, about 1 h:**
   - README with screenshots, the live URL, Render deploy steps and a "How we built it" note crediting Codex.
   - The submission form. **Submit by 4:15 PM**, leaving a buffer.
   - Stretch, if there's time: the English/Español toggle.

Cut order if time runs short: Spanish toggle → map (keep the list) → sponsor report → Report-a-sighting form (keep the import).

## 11. Demo script (3 minutes, live on the deployed URL)

1. **The problem, 30 s:** show the messy chat: hundreds of messages, photos and pins. Quote Beatriz.
2. **Import, 30 s:** drop in the export and watch it process.
3. **Today, 30 s:** "Pregnant calico at Laundromat colony: trap within days" is at the top, from a photo buried under 200 messages.
4. **Colony page, 30 s:** 9 cats, 6 fixed, 3 need TNR. Open the calico's card: two volunteers' photos, one cat, with the reason "same torn left ear, same white bib."
5. **Review, 20 s:** the AI wasn't sure about two black cats, so it asked. A volunteer taps once.
6. **Live report, 20 s:** on a phone, report a sighting with a photo of one of the demo cats. It lands on that cat's card within seconds.
7. **Sponsor report, 15 s:** "47 cats fixed this year," and every number traces back to a photo or message.
8. **How it's built, 15 s:** OpenAI vision for the photos (the model reads, a rule decides), an Agents SDK agent for the messages, built with Codex. Mention the cost per 100 photos.

## 12. Open questions

- **After signing in:** read the Judges and Submission tabs, and find the presentation format and length.
- **Ask the organizers:** how do judges evaluate Codex use, in the repo or in the demo?
- Which current OpenAI model has the best vision quality for the price? Check the docs.
- Is there an OpenAI image-embeddings endpoint? See §7c.
