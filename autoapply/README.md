# autoapply — semi-auto job application assistant
#
# Philosophy: the tool does the tedious 90% (finding jobs, matching your
# resume, tailoring documents) and opens the application form with fields
# pre-filled. YOU review and click submit. Nothing is ever auto-submitted.
# This keeps you compliant with job-board ToS and ban-free (the Simplify
# model from jobfree.txt).

## 1. Install
#   pip install -r requirements.txt
#   python -m playwright install chromium

## 2. Configure
#   Edit config.yaml: resume path, name, email, headline, skills,
#   search keywords, Ollama model.

## 3. Fetch matching jobs (free legal APIs: Remotive + Jobicy)
#   python cli.py search --keywords "python, ai" --limit 40
#   -> data/jobs.json (saved, deduped)

## 4. Parse your resume + score each job against it
#   python cli.py match
#   -> data/matches.json (ranked, with match score)
#   (use --mode ai for Ollama-scored fits - slower, ~80s/job)

## 5. Tailor documents per job (Ollama; template fallback)
#   python cli.py tailor --top 10          # AI cover letters + summaries
#   python cli.py tailor --top 10 --no-ai  # instant template versions
#   -> data/tailored/<slug>.txt

## 6. Semi-auto apply: opens the application page, pre-fills common
#    fields, waits for YOU to review + submit
#   python cli.py apply --job-id 3 --dry-run   # preview first (not logged)
#   python cli.py apply --job-id 3             # opens browser, you submit
#   (--job-id can be the 1-based number from `match` or an id prefix)

## 7. Track status
#   python cli.py status
#   -> data/applied.csv (kanban-style log: applied/skipped/rejected)

## NOTES
- Legal & safe: Remotive/Jobicy need no API key. LinkedIn is NOT scraped.
- The tool NEVER clicks the final submit button. You do.
- match --mode ai uses Ollama with deepseek-r1:8b (slow). Default keyword
  mode is instant and offline.
- Adzuna: drop app_id/app_key into config.yaml for extra coverage (optional).
- Pre-fill is best-effort heuristic (name/email/phone/linkedin by
  input type + id/name/placeholder). Some ATS forms will still need manual
  entry - that's expected and safe.
- Test the pre-fill logic offline: python tests/test_prefill.py
  (uses tests/demo_form.html, a local file - no network needed)

## SECURITY
- data/ holds your matches, tailored docs, and application log. It is
  git-ignored (.gitignore). Keep your resume local.
