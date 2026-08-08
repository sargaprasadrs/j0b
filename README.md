# j0b — job hunting toolkit

A private toolkit for job hunting, built from the research in `jobfree.txt`
(how LazyApply, LoopCV, Jobright, Simplify, FastApply, AIApply work + their
open-source alternatives).

Two tools:

| Tool | What it does | Safety model |
|------|--------------|--------------|
| `coldmail/` | Finds startups hiring, resolves contact emails, writes polite + frank cold-application emails, and saves them as **Gmail drafts only** (never sends). | Drafts only — zero send paths. Uses your own Gmail via a persistent browser session. |
| `autoapply/` | Fetches jobs from legal APIs (Remotive/Jobicy, optional Adzuna), scores them against your resume, generates tailored cover letters (Ollama), and opens application forms **pre-filled for you to review and submit**. | Semi-auto — the tool NEVER clicks submit. ToS-safe, no LinkedIn scraping. |
| `webui/` | Small local web app on top of autoapply: upload your resume, set preferred roles / location / salary range / startup-only, run searches, score matches, tailor docs, track applications. | Runs locally (http://127.0.0.1:5000). Everything below the hood is the same safe autoapply pipeline. |

## Requirements
- Python 3.11+
- `pip install -r <tool>/requirements.txt`
- `python -m playwright install chromium` (for browser features)
- Optional: Ollama running locally (`ollama serve`) for AI-generated emails/cover letters

## Quick start

### Web UI (easiest — resume upload + filters + results)
```bash
cd webui
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000
# 1) upload your resume (PDF/DOCX/TXT) - skills are auto-detected
# 2) fill profile + filters: roles, location, salary min/max, startup-only
# 3) Search jobs -> Score vs resume -> Tailor -> open page & apply yourself
```

### coldmail (drafts only)
```bash
cd coldmail
python cli.py discover --keywords "python, ai" --max-companies 20
python cli.py resolve
python cli.py drafts --dry-run --no-ai     # preview locally
python cli.py gmail login                  # log in once (session persists)
python cli.py gmail draft --limit 10       # -> Gmail Drafts, never sends
```

### autoapply (semi-auto)
```bash
cd autoapply
python cli.py search --keywords "python, developer, software" --limit 40
python cli.py match
python cli.py tailor --top 10
python cli.py apply --job-id 3 --dry-run   # preview
python cli.py apply --job-id 3             # browser opens pre-filled, YOU submit
python cli.py status
```

## How to run the two CLI tools (if you prefer terminal)

### coldmail (drafts only)
```bash
cd coldmail
pip install -r requirements.txt
python -m playwright install chromium
python cli.py discover --keywords "python, ai" --max-companies 20  # find startups hiring
python cli.py resolve                                            # find contact emails
python cli.py drafts --dry-run --no-ai                           # preview locally
python cli.py gmail login                                        # log in once (persists)
python cli.py gmail draft --limit 10                             # -> Gmail Drafts, never sends
```

### autoapply (semi-auto)
```bash
cd autoapply
pip install -r requirements.txt
python -m playwright install chromium
python cli.py search --keywords "python, developer, software" --limit 40
python cli.py match
python cli.py tailor --top 10
python cli.py apply --job-id 3 --dry-run   # preview
python cli.py apply --job-id 3             # browser opens pre-filled, YOU submit
python cli.py status
```

The web UI (`webui/`) drives the same autoapply pipeline with a nicer interface — use whichever you prefer.

## Security notes
- `coldmail/data/browser_profile/` contains your **real Gmail login session**.
  It is git-ignored. Never commit, zip, or share it.
- Neither tool sends email or submits applications on its own. Review
  everything before you hit Send / Submit.
- Resolved contact emails marked `[GUESS]` are pattern guesses — verify them.

## Tests
```bash
# autoapply pre-fill logic (offline, uses local demo form)
cd autoapply && python tests/test_prefill.py

# web UI smoke + flow tests (server must be running on :5000)
cd webui && python tests/test_ui.py && python tests/test_flow.py
```

## Research
`jobfree.txt` — deep dive on how the commercial auto-apply tools work and
the open-source components you can build with.
