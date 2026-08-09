# j0b — job hunting toolkit

A private toolkit for job hunting, built from the research in `jobfree.txt`
(how LazyApply, LoopCV, Jobright, Simplify, FastApply, AIApply work + their
open-source alternatives).

Two tools:

| Tool | What it does | Safety model |
|------|--------------|--------------|
| `coldmail/` | Finds startups hiring, resolves contact emails, writes polite + frank cold-application emails, and saves them as **Gmail drafts only** (never sends). | Drafts only — zero send paths. Uses your own Gmail via a persistent browser session. |
| `autoapply/` | Fetches jobs from legal APIs (Remotive/Jobicy/freehire.me, optional Adzuna), scores them against your resume with a structured fit framework (language gate, deal-breakers, 5-dimension rubric), generates tailored cover letters (Ollama) + optional **LaTeX CV/cover PDFs**, and opens application forms **pre-filled for you to review and submit**. | Semi-auto — the tool NEVER clicks submit. ToS-safe, no LinkedIn scraping. |
| `webui/` | Small local web app on top of autoapply: upload your resume, set preferred roles / location / salary range / startup-only, run searches, score matches, tailor docs, track applications. | Runs locally (http://127.0.0.1:5000). Everything below the hood is the same safe autoapply pipeline. |

The web UI also ships an **AI agent backend** (`webui/agent_backend.py`)
built on **opencode** (the agent brain, driven over its HTTP server API) +
**Composio** (authenticated tools like Gmail). The agent can summarize/score
jobs, write tailored follow-ups and cold outreach, and create a **Gmail draft
via Composio — it never sends**. When opencode is unreachable it falls back to
your local Ollama model (no tools).

Your candidate profile can hold **target roles, years of experience, desired
salary range, preferred locations, languages, deal-breakers, STAR examples and
education** (plus name/headline/summary/skills). These feed the match score
(experience / location / salary fit), the AI agent's context, and tailored
cover letters.

Several pieces are **ported from [ai-job-search](https://github.com/MadsLorentzen/ai-job-search)**
(the Claude Code job-hunting framework that got its author hired):

- **freehire.me job source** — a multi-market, tech-focused job aggregator
  (public JSON API, no API key) alongside Remotive/Jobicy. ~50 ATS platforms,
  structured skills/salary data, facet filters (region/country/seniority/
  category/work_mode). See `autoapply/config.yaml` → `sources.freehire`.
- **Fit evaluation framework** (`autoapply/autoapply/fit.py`) — port of the
  repo's `04-job-evaluation.md`: a **language gate** (hard-fails postings that
  require a language you don't declare, flags bars above your level), free-form
  **deal-breakers** that veto a posting (e.g. "on-call"), and structured
  Technical / Experience / Location / Career-Alignment dimensions with the
  reference verdict thresholds (Strong 75+ … Poor <30). Vetoed jobs land in
  `data/vetoed.json` with the exact reason.
- **Interview prep** — the AI agent builds a **prep pack** (likely questions,
  STAR answer sketches from your `star_examples`, questions to ask, honest
  gaps) or runs a **mock interview** (roleplay protocol from the repo's
  `07-interview-prep.md`).
- **HTML tracker report** (`autoapply/autoapply/report.py`) — port of the
  repo's `/html-report`: one self-contained offline dashboard (stat cards,
  inline-SVG charts, filterable table) from `data/applied.csv`. Run
  `python cli.py report --open` or the button in the web UI tracker.
- **LaTeX CV + cover letter** (`autoapply/autoapply/cv.py`) — moderncv banking
  style, ported from the repo's templates. Compiles with lualatex (fallback
  xelatex/pdflatex), verifies page counts with pypdf (CV ≤ 2 pages, cover 1
  page). No LaTeX installed? It still writes the `.tex` sources and tells you
  what to install.

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

### AI agent panel (opencode + Composio)
The "AI agent" card at the bottom of the web UI talks to an opencode server
(HTTP API, default `http://127.0.0.1:4096`). If none is running, `opencode
serve` is started automatically for you.

```bash
# opencode must be installed and logged in to a model provider (as usual)
opencode login
```

Composio enables the agent's only outbound action — a **Gmail draft**:
```bash
pip install composio            # already in webui/requirements.txt
composio add gmail              # one-time OAuth connect (or click "connect Gmail" in the UI)
export COMPOSIO_API_KEY=your_key
```

Without a Composio key the agent still works for analysis and email writing
(read-only, falls back to Ollama if opencode is down). With a key, "Create
Gmail draft" saves a draft to your inbox for you to review and send —
matching j0b's drafts-only safety model.

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
python cli.py cv --job-id 3                # LaTeX CV + cover letter PDFs (needs LaTeX)
python cli.py report --open                # HTML application-tracker dashboard
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

# fit framework, HTML report, LaTeX sources (all offline)
cd autoapply && python tests/test_fit.py && python tests/test_report.py && python tests/test_cv.py

# agent backend unit tests (offline — stubs opencode/composio, no server needed)
cd webui && python tests/test_agent.py
```

## LaTeX CV (optional)
Install a TeX distribution (TeX Live, MiKTeX, or TinyTeX) so `lualatex` is on
your PATH. Then `python cli.py cv --job-id 3` compiles a tailored CV + cover
letter into `autoapply/data/cv/<company>-<role>/` and verifies the page counts.
The cover letter reuses the tailored letter you generated (cache), and the CV
content is written from your profile + resume only — never fabricated.

## Research
`jobfree.txt` — deep dive on how the commercial auto-apply tools work and
the open-source components you can build with.
