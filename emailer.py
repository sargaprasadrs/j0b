"""emailer.py — cold application emails + Gmail drafts for matched jobs.

Bridges the coldmail library into the unified j0b web app:

* generate_cold_email()  — polite, frank application email for a matched
  job (coldmail writer, Ollama when available, template fallback), with a
  best-effort recipient resolved from the company's website.
* draft_emails_browser() — creates Gmail DRAFTS in a real browser session
  (coldmail gmail_drafter). Drafts only — nothing is ever sent.
* gmail_login()          — one-time interactive login so the persistent
  browser session can create drafts later.

This module never sends email. The user reviews every draft in Gmail.
"""
from __future__ import annotations

import re
import sys
import threading
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "coldmail"))

from coldmail.resolver import _norm_email  # noqa: E402  (reused normalizer)
from coldmail.writer import build_subject, generate_email  # noqa: E402

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) j0b/1.0"}
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# one Gmail login browser at a time (double-clicks would open several)
_login_lock = threading.Lock()


def _slugify(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (company or "").lower())


def quick_recipient(company: str, timeout: float = 5.0) -> tuple[str, str]:
    """Best-effort (email, source) for a company.

    source in {'site', 'guess', ''}: 'site' = found on the company website,
    'guess' = hello@domain pattern, '' = nothing found (fill in manually).
    """
    slug = _slugify(company)
    if len(slug) < 3:
        return "", ""
    for base in (f"https://{slug}.com", f"https://www.{slug}.com"):
        try:
            r = requests.get(base, headers=HEADERS, timeout=timeout,
                             allow_redirects=True)
            if r.status_code < 400:
                emails = []
                for e in EMAIL_RE.findall(r.text):
                    e = _norm_email(e)  # banned domains, placeholders, images
                    if e:
                        emails.append(e)
                emails = list(dict.fromkeys(emails))
                preferred = [e for e in emails if any(
                    k in e for k in ("hire", "jobs", "career", "founder",
                                     "team", "hello", "contact", "hr"))]
                if preferred:
                    return preferred[0], "site"
                if emails:
                    return emails[0], "site"
                return f"hello@{slug}.com", "guess"
        except Exception:  # noqa: BLE001
            continue
    return "", ""


def generate_cold_email(cfg: dict, job: dict, use_ai: bool = True,
                        resolve: bool = True) -> dict:
    """Build a cold application email for a matched job.

    Returns {'ok', 'to', 'subject', 'body', 'company', 'recipient_source'}.
    """
    company = job.get("company", "")
    role_title = job.get("title", "")
    notes = ", ".join(filter(None, [
        (job.get("location") or "").strip(),
        (job.get("exp_display") or "").strip(),
        (job.get("salary_display") or job.get("salary") or "").strip(),
    ]))
    try:
        body = generate_email(cfg, company=company, role_title=role_title,
                              notes=notes, use_ai=use_ai)
        subject = build_subject(cfg, company, role_title)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"email generation failed: {exc}"}
    to, src = "", ""
    if resolve:
        to, src = quick_recipient(company)
    return {
        "ok": True, "to": to, "subject": subject, "body": body,
        "company": company, "recipient_source": src,
    }


def draft_emails_browser(cfg: dict, emails: list[dict]) -> dict:
    """Create Gmail drafts via the coldmail browser session (never sends)."""
    from coldmail.gmail_drafter import draft_emails
    try:
        succeeded = draft_emails(emails, dry_run=False,
                                 max_drafts=max(1, len(emails)))
        return {"ok": bool(succeeded), "drafted": succeeded,
                "note": "DRAFTS ONLY — review in Gmail before sending."}
    except Exception as exc:  # noqa: BLE001
        msg = f"gmail draft failed: {exc}"
        # coldmail's not-logged-in path trips a NameError internally; surface
        # the real fix instead of the traceback text
        if "not defined" in str(exc):
            msg = "Gmail draft failed — you are not logged in. Click " \
                  "'Login to Gmail (once)' first, then retry."
        return {"ok": False, "error": msg}


def gmail_login(timeout_s: float = 600) -> bool:
    """Open Gmail once so the user logs in; the session persists afterwards.

    Returns True if a login browser was opened, False if one is already in
    progress (double-click guard)."""
    if not _login_lock.acquire(blocking=False):
        return False
    try:
        from coldmail.gmail_drafter import login
        login(timeout_s=timeout_s)
        return True
    finally:
        _login_lock.release()
