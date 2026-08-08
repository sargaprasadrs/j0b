"""Filter helpers shared by the CLI and the web UI.

- parse_salary_range(): normalize messy salary strings/fields to an
  annual-USD (min, max) tuple, or None if unknown.
- is_startup(): heuristic to tag jobs from startups vs big corporates.
"""
from __future__ import annotations

import re

# companies that are clearly NOT startups (these pop up on job feeds a lot)
BIG_CORPS = {
    "sanofi", "telus", "telus digital", "intel", "accenture", "cognizant",
    "ibm", "dell", "amazon", "google", "microsoft", "meta", "tcs", "tata",
    "infosys", "wipro", "capgemini", "deloitte", "pwc", "kpmg", "ey",
    "ernst & young", "oracle", "salesforce", "sap", "cisco", "hp",
    "hp inc", "amd", "nvidia", "qualcomm", "samsung", "lg", "sony",
    "huawei", "lenovo", "asus", "acer", "adobe", "autodesk", "servicenow",
    "workday", "snowflake", "databricks", "palantir", "unity",
    "epic games", "ubisoft", "ea", "activision", "blizzard", "roblox",
}


def _to_number(tok: str) -> int | None:
    """Parse '$80k', '80k+', '1.2m', '100000' etc into an integer."""
    tok = tok.strip().replace(",", "").lower()
    if not tok:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kmb])", tok)
    if m:
        val = float(m.group(1))
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[m.group(2)]
        return int(val * mult)
    m = re.fullmatch(r"\$?(\d+(?:\.\d+)?)", tok)
    if m:
        return int(float(m.group(1)))
    return None


def parse_salary_range(job: dict) -> tuple[int, int] | None:
    """Return (min_annual_usd, max_annual_usd) or None when unknown.

    Handles Jobicy's numeric salaryMin/salaryMax fields and Remotive's
    free-text strings like '$80k - $100k' or '80000'.
    """
    lo = hi = None

    # 1) structured numeric fields (Jobicy)
    if job.get("salaryMin") is not None or job.get("salaryMax") is not None:
        lo = _to_number(str(job.get("salaryMin"))) if job.get("salaryMin") is not None else None
        hi = _to_number(str(job.get("salaryMax"))) if job.get("salaryMax") is not None else None
        # normalize to annual (jobicy uses salaryPeriod; assume yearly if absent)
        period = (job.get("salaryPeriod") or "").lower()
        if period in ("monthly", "month", "per month", "/mo"):
            lo = lo * 12 if lo else None
            hi = hi * 12 if hi else None
        elif period in ("weekly", "week", "per week", "/wk"):
            lo = lo * 52 if lo else None
            hi = hi * 52 if hi else None
        elif period in ("hourly", "hour", "per hour", "/hr"):
            lo = lo * 2080 if lo else None
            hi = hi * 2080 if hi else None
        if lo or hi:
            return (lo or hi, hi or lo)

    # 2) free-text salary (Remotive)
    raw = job.get("salary") or job.get("tags") or ""
    if isinstance(raw, str) and raw.strip():
        nums = [n for n in (_to_number(t) for t in re.split(r"[-–—/]", raw))
                if n is not None]
        if nums:
            return (min(nums), max(nums))
    return None


def filter_by_salary(jobs: list[dict], salary_min: int | None,
                     salary_max: int | None) -> list[dict]:
    """Keep jobs whose salary range overlaps [salary_min, salary_max]."""
    if not salary_min and not salary_max:
        return jobs
    out = []
    for job in jobs:
        rng = parse_salary_range(job)
        if rng is None:
            continue  # unknown salary: exclude when filtering by salary
        jlo, jhi = rng
        if salary_min and jhi < salary_min:
            continue
        if salary_max and jlo > salary_max:
            continue
        out.append(job)
    return out


def is_startup(company: str, known_startups: set[str] | None = None) -> bool:
    """True for companies that look like startups.

    - always True if the company is in known_startups (from coldmail)
    - always False for the BIG_CORPS blocklist
    - otherwise True (default assume startup-friendly)
    """
    key = (company or "").strip().lower()
    if not key:
        return False
    if known_startups and key in {s.lower() for s in known_startups}:
        return True
    if key in BIG_CORPS:
        return False
    return True
