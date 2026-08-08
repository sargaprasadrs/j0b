"""Best-effort contact-email resolution for discovered startups.

Strategy (in order of preference):
  1. mailto: links scraped from the company website
  2. common contact pages (/contact, /about, /team, /careers, /contact-us)
  3. a polite heuristic guess (hello@ / founders@ / careers@) clearly
     flagged as a GUESS so you can verify before sending.

The tool NEVER sends email, so a guess just means: review the draft
recipient before you hit Send yourself.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .discovery import load_startups, save_startups

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) coldmail/0.1"}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# emails we never want to guess or use
BANNED = {"sentry.io", "example.com", "wixpress.com", "sentry.wixpress.com"}
CONTACT_PATHS = ["", "contact", "contact-us", "about", "about-us", "team", "careers", "jobs"]
# local-part placeholders that indicate a template address, not a real one
PLACEHOLDER_LOCAL = {"name", "yourname", "firstname", "lastname", "email", "user",
                     "username", "mail", "contact", "someone", "john", "jane"}
PLACEHOLDER_DOMAIN = {"example", "yourdomain", "domain", "email", "company", "test"}


def _norm_email(email: str) -> str:
    email = email.strip().strip(".").lower()
    if any(b in email for b in BANNED):
        return ""
    if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
        return ""
    local, _, domain = email.partition("@")
    if not local or not domain:
        return ""
    local_base = re.sub(r"[^a-z]+", "", local)
    if local_base in PLACEHOLDER_LOCAL:
        return ""
    dom_base = domain.split(".")[0]
    if dom_base in PLACEHOLDER_DOMAIN:
        return ""
    if "@" in domain or " " in email:
        return ""
    return email


def _extract_mailtos(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = href.split(":", 1)[1].split("?")[0]
            addr = _norm_email(addr)
            if addr:
                found.append(addr)
    # also plain emails in the page text
    for m in EMAIL_RE.findall(html):
        addr = _norm_email(m)
        if addr:
            found.append(addr)
    return list(dict.fromkeys(found))


def _fetch(url: str, timeout: float = 8) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code < 400 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except Exception:  # noqa: BLE001
        pass
    return None


def _guess_emails(domain: str) -> list[str]:
    """Guesses based on the domain; flagged in email_source as GUESS."""
    root = domain.split(":")[0].split("/")[0]
    if not re.match(r"^[a-zA-Z0-9.-]+(\.[a-zA-Z]{2,})+$", root):
        return []
    return [f"hello@{root}", f"founders@{root}", f"careers@{root}"]


def resolve_company(company: str, website: str) -> tuple[str, str]:
    """Returns (email, source). source in {'site','guess',''}."""
    if website:
        parsed = urlparse(website if "://" in website else "https://" + website)
        base = f"{parsed.scheme}://{parsed.netloc}"
        emails: list[str] = []
        for path in CONTACT_PATHS:
            url = urljoin(base + "/", path)
            html = _fetch(url)
            if html:
                emails += _extract_mailtos(html)
                if emails:
                    break
            time.sleep(0.3)
        emails = list(dict.fromkeys(emails))
        if emails:
            # prefer contact-ish addresses over sales/support bots
            preferred = [e for e in emails
                         if any(k in e for k in
                                ("hire", "jobs", "career", "founder",
                                 "team", "hello", "contact"))]
            return (preferred or emails)[0], "site"
        # fall back to guesses
        domain = parsed.netloc
        guesses = _guess_emails(domain)
        if guesses:
            return guesses[0], "guess"
    return "", ""


def resolve_all() -> None:
    rows = load_startups()
    if not rows:
        print("[resolve] nothing in data/startups.csv - run discover first")
        return
    updated = 0
    for row in rows:
        if row.get("contact_email") and row.get("needs_email") == "no":
            continue  # already resolved
        company = row["company"]
        email, source = resolve_company(company, row.get("website", ""))
        if email:
            row["contact_email"] = email
            row["email_source"] = source
            row["needs_email"] = "no"
            tag = "GUESS" if source == "guess" else "site"
            print(f"  {company:<28} -> {email:<40} [{tag}]")
        else:
            row["needs_email"] = "yes"
            print(f"  {company:<28} -> (none found - add manually)")
        updated += 1
    save_startups(rows)
    n_ok = sum(1 for r in rows if r.get("needs_email") == "no")
    print(f"[resolve] done. {n_ok}/{len(rows)} have an email. "
          f"Edit data/startups.csv to fill the rest.")
