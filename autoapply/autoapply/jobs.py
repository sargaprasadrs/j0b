"""Fetch jobs from free/legal APIs (no API keys required):

  * remotive     - https://remotive.com/api/remote-jobs (remote-only JSON)
  * jobicy       - https://jobicy.com/api/v2/remote-jobs (remote-only JSON)
  * freehire     - freehire.me aggregator (multi-market, full descriptions)
  * remoteok     - https://remoteok.com/api (remote-only, startup-heavy JSON)
  * weworkremotely- RSS feed of remote programming jobs (many startups)
  * startupjobs  - https://startup.jobs/feeds/jobs (THE startup source -
                   every posting is from a startup company; keyless RSS)
  * arbeitnow    - https://www.arbeitnow.com/api/job-board-api (EU/remote JSON)
  * adzuna       - optional, needs app_id/app_key (config sources.adzuna)

Output shape (dict):
    id, title, company, location, url, source, description, salary, tags

freehire (ported from ai-job-search's freehire-search skill):
    GET {base}/api/v1/agent/jobs/search returns postings from ~50 ATS
    platforms across many markets with full descriptions, structured skills
    and salary enrichment. See https://freehire.me/api/v1/jobs/facets for the
    live facet vocabularies (regions/countries/seniority/category/work_mode).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
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
        if j.get("salaryMin") is not None or j.get("salaryMax") is not None:
            salary = f"{j.get('salaryMin') or ''}-{j.get('salaryMax') or ''} {j.get('salaryCurrency','')}".strip("-")
        jobs.append({
            "id": _job_id("jobicy", j.get("url", "")),
            "title": (j.get("jobTitle") or "").strip(),
            "company": (j.get("companyName") or "").strip(),
            "location": (j.get("jobGeo") or "remote"),
            "url": j.get("url") or "",
            "source": "jobicy",
            "description": _clean(j.get("jobDescription", ""))[:4000],
            "salary": salary.strip(),
            "salaryMin": j.get("salaryMin"),
            "salaryMax": j.get("salaryMax"),
            "salaryCurrency": j.get("salaryCurrency", ""),
            "salaryPeriod": j.get("salaryPeriod", ""),
            "tags": f"{j.get('jobIndustry','')} | {j.get('jobLevel','')}",
        })
    return jobs


def fetch_freehire(cfg: dict, limit: int = 50) -> list[dict]:
    """Search the freehire.me aggregator (public JSON API, no API key).

    Facets come from sources.freehire: regions, countries, cities,
    seniority, category, skills, work_mode, jobage. The base URL is
    swappable (FREEHIRE_API_URL env or config) for a self-hosted instance.
    """
    fh = cfg.get("sources", {}).get("freehire", {})
    base = (fh.get("base_url") or "https://freehire.me").rstrip("/")
    jobs: list[dict] = []
    keywords = cfg.get("search", {}).get("keywords", [])
    params: dict = {
        "limit": min(int(limit or 25), 50),
        "offset": 0,
        "semantic_ratio": "0",  # plain keyword search; semantic is opt-in
        "include_description": "true",  # full text per hit, no follow-up fetch
        "description_format": "text",
    }
    q = " ".join(k for k in keywords if k and str(k).strip())[:200]
    if q:
        params["q"] = q
    jobage = fh.get("jobage")
    if jobage:
        params["posted_within_days"] = int(jobage)
    if fh.get("work_mode"):
        params["work_mode"] = fh["work_mode"]
    for key in ("regions", "countries", "cities", "seniority", "category",
                "skills"):
        for value in (fh.get(key) or []):
            if str(value).strip():
                params.setdefault(key, []).append(str(value).strip())
    try:
        r = requests.get(base + "/api/v1/agent/jobs/search", params=params,
                         headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [freehire] failed: {exc}")
        return jobs
    for j in data.get("data", []):
        enrich = j.get("enrichment") or {}
        cities = j.get("cities") or []
        location = (j.get("location") or "").strip()
        if not location and cities:
            location = ", ".join(cities)
        if not location and j.get("work_mode") == "remote":
            location = "Remote"
        salary = ""
        if enrich.get("salary_min") is not None or enrich.get("salary_max") is not None:
            cur = enrich.get("salary_currency") or ""
            parts = [p for p in (enrich.get("salary_min"), enrich.get("salary_max"))
                     if p is not None]
            salary = f"{cur} {parts[0]}" if len(parts) == 1 else \
                f"{cur} {parts[0]}-{parts[1]}"
        tags = ", ".join(j.get("skills") or [])
        if enrich.get("category"):
            tags = f"{enrich.get('category')} | {tags}".strip(" |")
        jobs.append({
            "id": _job_id("freehire", j.get("url", "")),
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company") or "").strip(),
            "location": location or "remote",
            "url": j.get("url") or "",
            "source": "freehire",
            "description": _clean(j.get("description", ""))[:4000],
            "salary": salary,
            "salaryMin": enrich.get("salary_min"),
            "salaryMax": enrich.get("salary_max"),
            "salaryCurrency": enrich.get("salary_currency") or "",
            "salaryPeriod": "yearly",
            "tags": tags,
            "seniority": enrich.get("seniority"),
            "work_mode": j.get("work_mode"),
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
            "salary": f"{j.get('salary_min') or ''}-{j.get('salary_max') or ''}",
            "salaryMin": j.get("salary_min"),
            "salaryMax": j.get("salary_max"),
            "salaryCurrency": "GBP",
            "salaryPeriod": "yearly",
            "tags": ", ".join(j.get("category", {}).get("label", "")),
        })
    return jobs


def _rss_items(url: str) -> list[ET.Element]:
    """Fetch an RSS 2.0 feed and return its <item> elements (never raises)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        return ET.fromstring(r.content).findall(".//item")
    except Exception as exc:  # noqa: BLE001
        print(f"  [rss] {url} failed: {exc}")
        return []


def fetch_remoteok(limit: int = 50) -> list[dict]:
    """Remote OK (https://remoteok.com/api) - keyless JSON feed. Remote-only
    and startup-heavy. Returns a JSON array where the first element is a
    metadata/legal record and the rest are jobs."""
    jobs: list[dict] = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [remoteok] failed: {exc}")
        return jobs
    if not isinstance(data, list):
        return jobs
    for j in data[1:limit + 1]:
        if not isinstance(j, dict) or not (j.get("position") or "").strip():
            continue
        lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
        salary = ""
        if lo or hi:
            def _usd(v: int) -> str:
                return f"${v/1000:.0f}k" if v >= 1000 else f"${v}"
            salary = f"{_usd(lo)}-{_usd(hi)}/yr" if lo and hi else \
                f"{_usd(lo) or _usd(hi)}/yr"
        jobs.append({
            "id": _job_id("remoteok", j.get("url", "") or j.get("slug", "")),
            "title": (j.get("position") or "").strip(),
            "company": (j.get("company") or "").strip(),
            "location": (j.get("location") or "Remote").strip(),
            "url": j.get("url") or j.get("apply_url") or "",
            "source": "remoteok",
            "description": _clean(j.get("description", ""))[:4000],
            "salary": salary,
            "salaryMin": lo or None,
            "salaryMax": hi or None,
            "salaryCurrency": "USD",
            "salaryPeriod": "yearly",
            "tags": ", ".join(j.get("tags") or []),
        })
    return jobs


def fetch_weworkremotely(limit: int = 50) -> list[dict]:
    """We Work Remotely - keyless RSS feed of remote programming jobs
    (https://weworkremotely.com/categories/remote-programming-jobs.rss).
    Titles are "Company: Job Title"; <region> is the location."""
    jobs: list[dict] = []
    for item in _rss_items(
            "https://weworkremotely.com/categories/remote-programming-jobs.rss"):
        if len(jobs) >= limit:
            break
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        if ":" in title:
            company, _, role = title.partition(":")
            company, role = company.strip(), role.strip()
        else:
            company, role = "", title
        if not role:
            continue
        region = (item.findtext("region") or "Remote").strip()
        jobs.append({
            "id": _job_id("weworkremotely", link),
            "title": role,
            "company": company,
            "location": region or "Remote",
            "url": link,
            "source": "weworkremotely",
            "description": _clean(item.findtext("description") or "")[:4000],
            "salary": "",
            "tags": (item.findtext("category") or "").strip(),
        })
    return jobs


def fetch_startupjobs(limit: int = 50, workplace: str = "remote") -> list[dict]:
    """Startup Jobs (https://startup.jobs) - keyless RSS feed of live startup
    jobs (every posting is from a startup company). Titles are
    "Job Title at Company". No API key needed: startup.jobs/feeds/jobs.
    workplace: 'remote' | 'on-site' | 'hybrid' (RSS feed filter)."""
    jobs: list[dict] = []
    feed = "https://startup.jobs/feeds/jobs"
    if workplace and str(workplace).strip():
        feed += f"?workplace={str(workplace).strip().lower()}"
    for item in _rss_items(feed):
        if len(jobs) >= limit:
            break
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title:
            continue
        if " at " in title:
            role, _, company = title.rpartition(" at ")
            role, company = role.strip(), company.strip()
        else:
            role, company = title, ""
        if not role:
            continue
        tags = ", ".join((c.text or "").strip() for c in item.findall("category"))
        jobs.append({
            "id": _job_id("startupjobs", link or title),
            "title": role,
            "company": company,
            "location": "Remote",
            "url": link,
            "source": "startupjobs",
            "description": _clean(item.findtext("description") or "")[:4000],
            "salary": "",
            "tags": tags,
        })
    return jobs


def fetch_arbeitnow(limit: int = 50) -> list[dict]:
    """Arbeitnow (https://www.arbeitnow.com/api/job-board-api) - keyless JSON
    feed of jobs in Germany/EU incl. remote. No API key required."""
    jobs: list[dict] = []
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api",
                         params={"limit": min(int(limit or 25), 50)},
                         headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as exc:  # noqa: BLE001
        print(f"  [arbeitnow] failed: {exc}")
        return jobs
    for j in data[:limit]:
        location = (j.get("location") or "").strip()
        if j.get("remote"):
            location = f"{location} (remote)".strip() or "Remote"
        if not location:
            location = "Remote"
        slug = j.get("slug") or ""
        jobs.append({
            "id": _job_id("arbeitnow", slug or j.get("url", "")),
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company_name") or "").strip(),
            "location": location,
            "url": f"https://www.arbeitnow.com/jobs/{slug}" if slug \
                else (j.get("url") or ""),
            "source": "arbeitnow",
            "description": _clean(j.get("description", ""))[:4000],
            "salary": "",
            "tags": ", ".join(j.get("tags") or []),
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
    if src_cfg.get("freehire", {}).get("enabled", True):
        print("[jobs] freehire ...")
        raw += fetch_freehire(cfg, limit)
        time.sleep(0.4)
    if src_cfg.get("remoteok", {}).get("enabled", True):
        print("[jobs] remoteok ...")
        raw += fetch_remoteok(limit)
        time.sleep(0.4)
    if src_cfg.get("weworkremotely", {}).get("enabled", True):
        print("[jobs] weworkremotely ...")
        raw += fetch_weworkremotely(limit)
        time.sleep(0.4)
    if src_cfg.get("startupjobs", {}).get("enabled", True):
        print("[jobs] startupjobs (startup companies) ...")
        workplace = src_cfg.get("startupjobs", {}).get("workplace", "remote")
        raw += fetch_startupjobs(limit, workplace)
        time.sleep(0.4)
    if src_cfg.get("arbeitnow", {}).get("enabled", True):
        print("[jobs] arbeitnow ...")
        raw += fetch_arbeitnow(limit)
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
    # years-of-experience filter (search.exp_min / search.exp_max); also
    # attaches exp_range + exp_display to every job for the UI
    from .filters import filter_by_exp
    jobs = filter_by_exp(jobs, cfg.get("search", {}).get("exp_min"),
                         cfg.get("search", {}).get("exp_max"))

    with open(JOBS_FILE, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2, ensure_ascii=False)
    print(f"[jobs] {len(raw)} raw -> {len(jobs)} matched+deduped -> {JOBS_FILE}")
    return jobs


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
