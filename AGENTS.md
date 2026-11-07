# AGENTS.md

Read `docs/CHALLENGE.md` first: it's the challenge text, and its "What a fix must respect" and "What solved looks like" lists are the acceptance criteria. Then read `PLAN.md`: it has the architecture, the data model and the build order. Then read `EVAL.md`, the cat identification check, which is built and re-run alongside the app. Work through the build order in §10 in sequence, and get each step working before starting the next.

## Conventions
- Python 3.11+, FastAPI, SQLite via stdlib `sqlite3`, and one static HTML/JS page with no build step. Don't add dependencies beyond those listed in PLAN.md §5 without a reason. **All AI runs on the OpenAI API (`openai`, `openai-agents`): no local models.** Pillow is only for resizing and cropping.
- Keep it small: no abstractions with a single implementation, and no config for values that never change. The model name comes from `OPENAI_MODEL`, and the key from `OPENAI_API_KEY` in `.env`.
- Never commit `.env`, real chat exports, private photos, or `eval_data/` as a whole. Only the Commons photos chosen for the demo are copied into `data/demo/photos/`.
- Never automate WhatsApp or any other app. The only input is an exported chat, a bot or a form.
- **The model reads, a fixed rule decides:** ask the model for specific observations (features, boxes, verdicts), and make decisions such as same cat, fixed or not, and alert severity in plain, tested code.
- A cat name in a message is only a hint, never an identity decision. For every photo, the agent still runs `match_cat()`; a possible match creates a suggestion, and two cats are merged only after recorded human confirmation.
- **A person confirms every merge of two cats and every adopted/missing/deceased change.** The AI only creates suggestions. No code path may merge cats or change `status` without a recorded human decision. Don't let the agent invent cats or facts that aren't in the messages.
- **Privacy:** every page and API route requires the team passcode, except `/healthz`, the sign-in page and the sponsor report link. The sponsor report never includes locations, volunteer names, phone numbers or photos.
- **Demo data** in `data/demo/`:
  - invented messages, colony nicknames and approximate locations, with no real addresses;
  - made-up volunteers with `305-555-01xx` numbers;
  - openly licensed Wikimedia Commons photos, with made-up cat names, each credited in `data/demo/PHOTO_SOURCES.md`.
  - **No private photos.** The organizers confirmed openly licensed public photos are fine.
- **API credits are limited ($50 total).** Cache each photo description by file hash, and never call the API twice for the same photo. Resize images to about 768 px on the long side before sending. During development, test on a small sample of about 10 messages and 10 photos, not the full demo set.
- Log the token use and estimated cost of every OpenAI call in one place (`costs.log` or a table), so we always know what's been spent and the demo can quote cost per 100 photos.
- Any non-trivial logic (the parser, matching decisions, alert rules) gets one small runnable `assert`-based test.
- Hosting is Render free plus Upstash Redis REST for anything that must survive a restart. Call Upstash with plain HTTP requests; no Redis client library is needed.
- Commit messages: short, plain, imperative.

## Run
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY and OPENAI_MODEL
uvicorn app.main:app --reload
```
