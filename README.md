# j0b — job searcher + autoapply (single program)

One local web app that merges the three tools that used to live in
`autoapply/`, `coldmail/` and `webui/` into a single program:

| Capability | What it does | Safety model |
|------------|--------------|--------------|
| **Job search** | Fetches jobs from free/legal APIs (Remotive, Jobicy, freehire.me, optional Adzuna) | Read-only |
| **Flexible filters** | **Role / keywords**, **years of experience (min–max)**, **location**, **salary (min–max)**, startup-only, per-source toggles | — |
| **Matching** | Scores jobs vs your resume + profile (experience / location / salary fit, language gate, deal-breakers, 5-dimension rubric) | Offline |
| **Gmail autoapply** | Generates a polite cold application email for a matched job and saves it as a **Gmail DRAFT** in a real browser session | **Drafts only — never sends.** You review & hit send |
| **Browser apply** | Opens the job page pre-filled from your profile so you review and submit yourself | Semi-auto — never clicks submit |
| **Tailoring / CV** | Per-job cover letter + resume summary (Ollama or template), optional LaTeX CV + cover PDFs | — |
| **AI agent** | opencode brain + Composio tools: summarize/score jobs, interview prep, mock interview, Gmail draft | Drafts only |
| **Tracker** | Logs every application/draft; self-contained HTML dashboard + funnel stats | Local CSV |

The three folders remain as **internal libraries** under the hood — the whole
program is driven from the project root.

## Quick start

```bash
pip install -r requirements.txt
python -m playwright install chromium     # for Gmail drafts + browser apply
python app.py                              # -> http://127.0.0.1:5000
```

Then, in the web app:

1. **Profile** — fill name/email/roles/years/salary/locations, upload your
   resume (skills are auto-detected).
2. **Filters** — set role keywords, **experience min/max**, location, salary
   min/max, startup-only, sources → **Search jobs**.
3. **Score vs resume** — rank the results, then per job:
   - **✉ Cold email** → generates an application email (and a best-effort
     recipient) → click **Login to Gmail (once)** the first time, then
     **Create Gmail draft (browser)**. Review the draft in Gmail and send it
     yourself. Drafts only — nothing is sent automatically.
   - **💻 Apply** → opens the job page pre-filled from your profile; you
     review and submit yourself.
   - **✍ Tailor** → cover letter + resume summary (and LaTeX CV PDFs if you
     have TeX installed).
4. Log outcomes (applied / interview / offer / hired / skipped / rejected)
   and generate the **HTML tracker report**.

### Gmail drafts (cold-application emails)

- First time: click **🔑 Login to Gmail (once)** — a browser opens, you log
  in once, and the session persists (`coldmail/data/browser_profile`).
- **Drafts only**: the tool creates drafts, never sends. Always review in
  Gmail before hitting Send yourself.

### AI agent panel

The agent talks to an opencode server (HTTP API, default
`http://127.0.0.1:4096`; started automatically if missing). It can also
create a Gmail draft via **Composio**:

```bash
pip install composio
composio add gmail              # one-time OAuth connect (or the UI button)
export COMPOSIO_API_KEY=your_key
```

Without Composio the agent still works for analysis + email writing
(falls back to your local Ollama model).

## Configuration

Everything lives in **one file**: `config.yaml` at the project root.

- `candidate` — your profile (name, roles, years of experience, salary
  range, locations, languages, deal-breakers, STAR examples…)
- `search` — `keywords`, `locations`, `limit`, `exp_min`, `exp_max`
- `sources` — enable/disable Remotive / Jobicy / freehire (facets) / Adzuna
- `sender` + `outreach` — who the cold emails come from and the ask/signoff
- `ollama`, `agent`, `apply` — local LLM, agent backend, browser timeouts

## Security notes

- `coldmail/data/browser_profile/` contains your **real Gmail login
  session** — it is git-ignored. Never commit, zip, or share it.
- The tool never sends email and never submits applications on its own.
- Recipients flagged as "guessed" (`hello@domain`) are pattern guesses —
  verify them before sending.

## Tests

```bash
# offline: exp filter, fit framework, report, LaTeX sources, agent backend
python tests/test_filters.py
cd autoapply && python tests/test_fit.py && python tests/test_report.py && python tests/test_cv.py
cd webui && python tests/test_agent.py

# browser smoke tests (server must be running on :5000)
python tests/test_ui.py
```

## Research

`jobfree.txt` — deep dive on how the commercial auto-apply tools
(LazyApply, LoopCV, Jobright, Simplify, FastApply, AIApply) work and the
open-source components they are built from. `job.txt` — a sample of 100
startup jobs (Cutshort, India) for testing the filters.
