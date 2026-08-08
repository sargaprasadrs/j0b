"""Discover startups hiring right now via free job-feed APIs.

Writes data/startups.csv with columns:
    company, website, role_title, source_url, notes, contact_email,
    email_source, needs_email, drafted
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

import requests

from .config import DATA_DIR, ensure_data_dir

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) coldmail/0.1"}
STARTUPS_CSV = DATA_DIR / "startups.csv"
FIELDS = [
    "company",
    "website",
    "role_title",
    "source_url",
    "notes",
    "contact_email",
    "email_source",
    "needs_email",
    "drafted",
]


# ---------------------------------------------------------------------------
# Feed fetchers
# ---------------------------------------------------------------------------
def fetch_jobicy(max_jobs: int = 100) -> list[dict]:
    """Jobicy v2 remote-jobs API - free, no key."""
    jobs: list[dict] = []
    url = "https://jobicy.com/api/v2/remote-jobs"
    params = {"count": min(max_jobs, 50), "tag": "software-development"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [jobicy] failed: {exc}")
        return jobs

    for job in data.get("jobs", []):
        company = (job.get("companyName") or "").strip()
        if not company:
            continue
        jobs.append(
            {
                "company": company,
                "role_title": (job.get("jobTitle") or "").strip(),
                "source_url": job.get("url") or "",
                "description": (job.get("jobDescription") or ""),
                "geo": (job.get("jobGeo") or ""),
                "level": (job.get("jobLevel") or ""),
            }
        )
    return jobs


def fetch_remotive(max_jobs: int = 100) -> list[dict]:
    """Remotive API - free, no key. Supports ?search= keyword."""
    jobs: list[dict] = []
    try:
        r = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"limit": min(max_jobs, 50)},
            headers=HEADERS,
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [remotive] failed: {exc}")
        return jobs

    for job in data.get("jobs", []):
        company = (job.get("company_name") or "").strip()
        if not company:
            continue
        jobs.append(
            {
                "company": company,
                "role_title": (job.get("title") or "").strip(),
                "source_url": job.get("url") or "",
                "description": (job.get("description") or ""),
                "geo": (job.get("candidate_required_location") or ""),
                "level": "",
            }
        )
    return jobs


def _company_website(company: str) -> str:
    """Best-effort: derive a website from the company name.

    Tries a few obvious patterns and a DuckDuckGo lookup.
    """
    slug = re.sub(r"[^a-z0-9]+", "", company.lower())
    if len(slug) < 3:
        return ""
    candidates = [f"https://{slug}.com", f"https://www.{slug}.com"]
    for url in candidates:
        try:
            r = requests.get(url, headers=HEADERS, timeout=6, allow_redirects=True)
            if r.status_code < 400:
                return url.rstrip("/")
        except Exception:  # noqa: BLE001
            continue
    # DuckDuckGo fallback
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{company} official website"},
            headers=HEADERS,
            timeout=10,
        )
        m = re.search(r'href="(https?://[^"]+)"', r.text)
        if m:
            return m.group(1).split("//")[1].split("/")[0]
    except Exception:  # noqa: BLE001
        pass
    return ""


def _matches_keywords(job: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = f"{job['company']} {job['role_title']} {job.get('description','')}".lower()
    return any(kw.strip().lower() in hay for kw in keywords)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def load_startups() -> list[dict]:
    ensure_data_dir()
    if not STARTUPS_CSV.exists():
        return []
    with open(STARTUPS_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_startups(rows: list[dict]) -> None:
    ensure_data_dir()
    # ensure all field columns exist
    for row in rows:
        for field in FIELDS:
            row.setdefault(field, "")
    with open(STARTUPS_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  saved {len(rows)} rows -> {STARTUPS_CSV}")


def discover(keywords: list[str] | None = None, max_companies: int = 20,
             sources: list[str] | None = None) -> None:
    """Fetch job feeds, keep unique startups matching keywords."""
    keywords = [k for k in (keywords or []) if k]
    sources = sources or ["jobicy", "remotive"]

    raw: list[dict] = []
    if "jobicy" in sources:
        print("[discover] fetching jobicy ...")
        raw += fetch_jobicy()
        time.sleep(0.5)
    if "remotive" in sources:
        print("[discover] fetching remotive ...")
        raw += fetch_remotive()
        time.sleep(0.5)

    print(f"[discover] {len(raw)} raw jobs")

    # dedupe by company, preferring the job that best matches keywords
    seen: dict[str, dict] = {}
    for job in raw:
        company = job["company"]
        if not _matches_keywords(job, keywords):
            continue
        if company in seen:
            continue
        seen[company] = job
        if len(seen) >= max_companies:
            break

    rows = []
    for company, job in seen.items():
        website = _company_website(company)
        rows.append(
            {
                "company": company,
                "website": website,
                "role_title": job["role_title"],
                "source_url": job["source_url"],
                "notes": f"{job.get('geo','')} | {job.get('level','')}".strip(" |"),
                "contact_email": "",
                "email_source": "",
                "needs_email": "yes",
                "drafted": "no",
            }
        )
        print(f"  + {company:<28} {website or '(no website found)'}")

    if not rows:
        print("[discover] no startups matched your keywords. Try broader keywords.")
        return
    save_startups(rows)
    print(f"[discover] done. {len(rows)} startups in data/startups.csv")
