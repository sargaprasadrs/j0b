"""Fetch jobs from free/legal APIs: Remotive, Jobicy, optional Adzuna.

Output shape (dict):
    id, title, company, location, url, source, description, salary, tags
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .config import DATA_DIR, ensure_data_dir

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) autoapply/0.1"}
JOBS_FILE = DATA_DIR / "jobs.json"


def _clean(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def _job_id(source: str, url: str) -> str:
    return hashlib.sha1(f"{source}:{url}".encode()).hexdigest()[:12]


def _matches(job: dict, keywords: list[str], locations: list[str]) -> bool:
    hay = " ".join([job["title"], job["company"], job["description"],
                    job["location"]]).lower()
    kw_ok = not keywords or any(k.strip().lower() in hay for k in keywords)
    loc_ok = not locations or any(
        l.strip().lower() in job["location"].lower() for l in locations)
    return kw_ok and loc_ok


# --------------------------------------------------------------------------
def fetch_remotive(limit: int = 50) -> list[dict]:
    jobs: list[dict] = []
    try:
        r = requests.get("https://remotive.com/api/remote-jobs",
                         params={"limit": min(limit, 50)}, headers=HEADERS,
                         timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [remotive] failed: {exc}")
        return jobs
    for j in data.get("jobs", []):
        jobs.append({
            "id": _job_id("remotive", j.get("url", "")),
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company_name") or "").strip(),
            "location": (j.get("candidate_required_location") or "remote"),
            "url": j.get("url") or "",
            "source": "remotive",
            "description": _clean(j.get("description", ""))[:4000],
            "salary": (j.get("salary") or "").strip(),
            "tags": ", ".join(j.get("tags") or []),
        })
    return jobs


def fetch_jobicy(limit: int = 50) -> list[dict]:
    jobs: list[dict] = []
    try:
        r = requests.get("https://jobicy.com/api/v2/remote-jobs",
                         params={"count": min(limit, 50), "tag": "software-development"},
                         headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [jobicy] failed: {exc}")
        return jobs
    for j in data.get("jobs", []):
        salary = ""
        if j.get("salaryMin") or j.get("salaryMax"):
            salary = f"{j.get('salaryMin')}-{j.get('salaryMax')} {j.get('salaryCurrency','')}"
        jobs.append({
            "id": _job_id("jobicy", j.get("url", "")),
            "title": (j.get("jobTitle") or "").strip(),
            "company": (j.get("companyName") or "").strip(),
            "location": (j.get("jobGeo") or "remote"),
            "url": j.get("url") or "",
            "source": "jobicy",
            "description": _clean(j.get("jobDescription", ""))[:4000],
            "salary": salary.strip(),
            "tags": f"{j.get('jobIndustry','')} | {j.get('jobLevel','')}",
        })
    return jobs


def fetch_adzuna(cfg: dict, limit: int = 50) -> list[dict]:
    ad = cfg.get("sources", {}).get("adzuna", {})
    app_id, app_key = ad.get("app_id", ""), ad.get("app_key", "")
    if not app_id or not app_key:
        return []
    jobs: list[dict] = []
    country = ad.get("country", "gb")
    kw = "+".join(cfg.get("search", {}).get("keywords", ["developer"])[:3])
    try:
        r = requests.get(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
            params={"app_id": app_id, "app_key": app_key, "results_per_page": limit,
                    "what": kw, "content-type": "application/json"},
            headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [adzuna] failed: {exc}")
        return jobs
    for j in data.get("results", []):
        jobs.append({
            "id": _job_id("adzuna", j.get("redirect_url", "")),
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company", {}).get("display_name") or "").strip(),
            "location": (j.get("location", {}).get("display_name") or ""),
            "url": j.get("redirect_url") or "",
            "source": "adzuna",
            "description": _clean(j.get("description", ""))[:4000],
            "salary": f"{j.get('salary_min')}-{j.get('salary_max')}",
            "tags": ", ".join(j.get("category", {}).get("label", "")),
        })
    return jobs


# --------------------------------------------------------------------------
def fetch_all(cfg: dict) -> list[dict]:
    """Fetch from enabled sources, dedupe by company+title."""
    ensure_data_dir()
    src_cfg = cfg.get("sources", {})
    limit = cfg.get("search", {}).get("limit", 40)
    keywords = cfg.get("search", {}).get("keywords", [])
    locations = cfg.get("search", {}).get("locations", [])

    raw: list[dict] = []
    if src_cfg.get("remotive", {}).get("enabled", True):
        print("[jobs] remotive ...")
        raw += fetch_remotive(limit)
        time.sleep(0.4)
    if src_cfg.get("jobicy", {}).get("enabled", True):
        print("[jobs] jobicy ...")
        raw += fetch_jobicy(limit)
        time.sleep(0.4)
    if src_cfg.get("adzuna", {}).get("enabled", False):
        print("[jobs] adzuna ...")
        raw += fetch_adzuna(cfg, limit)
        time.sleep(0.4)

    seen: dict[str, dict] = {}
    for job in raw:
        if not _matches(job, keywords, locations):
            continue
        key = f"{job['company'].lower()}::{job['title'].lower()}"
        if key in seen:
            continue
        seen[key] = job

    jobs = list(seen.values())
    with open(JOBS_FILE, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2, ensure_ascii=False)
    print(f"[jobs] {len(raw)} raw -> {len(jobs)} matched+deduped -> {JOBS_FILE}")
    return jobs


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
