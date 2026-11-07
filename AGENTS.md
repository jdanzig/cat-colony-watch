# AGENTS.md

Read `PLAN.md` first. It has the problem, the architecture, the data model and the build order. Work through the build order in §9 in sequence, and get each step working before starting the next.

## Conventions
- Python 3.11+, FastAPI, SQLite via stdlib `sqlite3`, and one static HTML/JS page with no build step. Don't add dependencies beyond those listed in PLAN.md §4 without a reason.
- Keep it small: no abstractions with a single implementation, and no config for values that never change. The model name comes from `OPENAI_MODEL`, and the key from `OPENAI_API_KEY` in `.env`.
- Never commit `.env`, real chat exports or real people's photos. Demo data in `data/demo/` is made up or openly licensed; record each photo's source in `data/demo/PHOTO_SOURCES.md`.
- Never automate WhatsApp or any other app. The only input is an exported chat, a bot or a form.
- AI output is a suggestion. Uncertain matches go to the review queue and are never merged automatically. Don't let the agent invent cats or facts that aren't in the messages.
- Log the token use and estimated cost of every OpenAI call in one place, so the demo can quote cost per 100 photos.
- Any non-trivial logic (the parser, matching decisions, alert rules) gets one small runnable `assert`-based test.
- Commit messages: short, plain, imperative.

## Run
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY and OPENAI_MODEL
uvicorn app.main:app --reload
```
