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


def _jd_fit_line(cfg: dict, job: dict) -> str:
    """One sentence naming the JD keywords that match the candidate's skills.

    Empty string when nothing matches (the writer then falls back to a
    generic fit line). Case-insensitive, word-boundary matching.
    """
    sender = cfg.get("sender", {}) or {}
    cand = cfg.get("candidate", {}) or {}
    skills = sender.get("skills") or cand.get("skills") or []
    hay = ((job.get("description") or "") + " "
           + (job.get("tags") or "")).lower()
    hits: list[str] = []
    for s in skills:
        s = str(s or "").strip().lower()
        if s and s not in hits and re.search(rf"\b{re.escape(s)}\b", hay):
            hits.append(s)
    if not hits:
        return ""
    top = ", ".join(hits[:4])
    return (f"Your posting calls for {top} - I have built and shipped "
            "applications with all of them.")


def _resolve_engine(cfg: dict, use_ai: bool) -> str:
    """Pick the email-generation engine for this run.

    send.email_engine: opencode (tool-less agent) | ollama | template.
    Falls back to the old personalize_with_ai flag for back-compat. A caller
    passing use_ai=False always gets the offline template (tests / dry runs).
    """
    send = cfg.get("send", {}) or {}
    engine = str(send.get("email_engine") or "").strip().lower()
    if not engine:
        engine = "ollama" if send.get("personalize_with_ai") else "template"
    if not use_ai:
        engine = "template"
    return engine


def generate_cold_email(cfg: dict, job: dict, use_ai: bool = True,
                        resolve: bool = True) -> dict:
    """Build a cold application email for a matched job.

    The email names the candidate, references the specific role, and explains
    fit against the posting's keywords. Engine selection:
      opencode -> tool-less opencode agent writes subject+body (falls back to
                  the template if opencode is unreachable)
      ollama   -> local Ollama writes the body (writer template subject)
      template -> fast offline template

    Returns {'ok', 'to', 'subject', 'body', 'company', 'recipient_source'}.
    """
    company = job.get("company", "")
    role_title = job.get("title", "")
    notes = ", ".join(filter(None, [
        (job.get("location") or "").strip(),
        (job.get("exp_display") or "").strip(),
        (job.get("salary_display") or job.get("salary") or "").strip(),
    ]))
    engine = _resolve_engine(cfg, use_ai)
    subject, body, used = "", "", engine
    try:
        if engine == "opencode":
            try:
                from ai_email import generate_subject_body
                subject, body = generate_subject_body(cfg, job)
            except Exception as exc:  # noqa: BLE001
                used = f"opencode->template ({type(exc).__name__})"
                subject, body = "", ""
        if not subject or not body:
            body = generate_email(cfg, company=company, role_title=role_title,
                                  notes=notes,
                                  use_ai=(engine == "ollama" and use_ai),
                                  fit_line=_jd_fit_line(cfg, job))
            subject = build_subject(cfg, company, role_title)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"email generation failed: {exc}"}
    to, src = "", ""
    if resolve:
        to, src = quick_recipient(company)
    return {
        "ok": True, "to": to, "subject": subject, "body": body,
        "company": company, "recipient_source": src, "engine": used,
    }


def draft_emails_browser(cfg: dict, emails: list[dict]) -> dict:
    """Create Gmail drafts via the coldmail browser session (never sends)."""
    from coldmail.gmail_drafter import draft_emails
    expected = (cfg.get("sender", {}) or {}).get("email", "")
    try:
        succeeded = draft_emails(emails, dry_run=False,
                                 max_drafts=max(1, len(emails)),
                                 expected_email=expected)
        if succeeded:
            return {"ok": True, "drafted": succeeded,
                    "note": "DRAFTS ONLY — review in Gmail before sending."}
        return {
            "ok": False,
            "error": f"No draft was created — sign in to Gmail in the window "
                      f"that opened (use {expected or 'your Gmail account'}), "
                      "then click Create Gmail draft again.",
        }
    except Exception as exc:  # noqa: BLE001
        msg = f"gmail draft failed: {exc}"
        # coldmail's not-logged-in path trips a NameError internally; surface
        # the real fix instead of the traceback text
        if "not defined" in str(exc):
            msg = "Gmail draft failed — you are not logged in. Sign in to Gmail " \
                  "in the window that opened, then retry."
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
