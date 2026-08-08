# coldmail — cold-email drafting tool (drafts only, never sends)
#
# Sends ZERO emails. Finds startups hiring, resolves a contact email,
# writes a polite + frank personalized cold email, and saves it as a
# Gmail DRAFT in YOUR account (sargaprasadrs@gmail.com by default) for
# you to review and send yourself.

## 1. Install
#   pip install -r requirements.txt
#   python -m playwright install chromium

## 2. Configure
#   Edit config.yaml: your name/email/headline/skills + outreach keywords.

## 3. Discover startups hiring
#   python cli.py discover --keywords "python, ai, developer" --max-companies 20
#   (pulls companies from Jobicy + Remotive job feeds; you can also add
#    rows manually to data/startups.csv)

## 4. Resolve contact emails (best effort, from company websites)
#   python cli.py resolve
#   (writes contact_email + email_source into data/startups.csv;
#    rows without an email are flagged needs_email=yes)

## 5. Preview the drafts locally (safe, no browser)
#   python cli.py drafts --dry-run

## 6. Log into Gmail once (opens a real browser; you log in manually)
#   python cli.py gmail login
#   (session is saved to data/browser_profile for later runs)

## 7. Write the drafts into your Gmail account (NEVER sends)
#   python cli.py gmail draft --limit 10
#   (opens compose windows with the content pre-filled, waits for Gmail's
#    autosave, closes the tab. Each email lands in Gmail -> Drafts.
#    The tool NEVER clicks Send.)

## 8. Review in Gmail, then send manually.

## SECURITY / WARNINGS
- data/browser_profile/ contains your real Gmail login session. It is
  git-ignored (.gitignore) - NEVER commit, zip, or share this folder.
- This tool NEVER sends email. If you want to be extra safe, double-check
  the Drafts folder after a run.
- Emails are cached in data/email_cache.json keyed by company+role. If you
  edit config.yaml (summary, ask, name), delete that cache file or run the
  generator again after clearing it to regenerate fresh emails.
- deepseek-r1:8b is slow (~80s/email). Use `--no-ai` for instant template
  drafts, or switch config.yaml ollama.model to a faster model.

## NOTES
- "Find them for me" pulls companies from Jobicy/Remotive job feeds (free,
  legal). These skew toward whoever is posting right now - not only small
  startups. The reliable path is your own data/startups.csv.
- Resolved emails are best-effort: [site] = found on their website,
  [GUESS] = hello@/founders@/careers@ pattern - ALWAYS verify before sending.
