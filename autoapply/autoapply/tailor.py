"""Generate per-job tailored documents: cover letter + resume summary.

Uses Ollama when available (with cache), falls back to a template so the
tool always works offline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from .config import DATA_DIR, ensure_data_dir

TAILORED_DIR = DATA_DIR / "tailored"
CACHE_FILE = DATA_DIR / "tailor_cache.json"


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _ollama(base_url: str, model: str, system: str, prompt: str,
            timeout: float = 150) -> str | None:
    try:
        r = requests.post(
            base_url.rstrip("/") + "/api/generate",
            json={"model": model, "system": system, "prompt": prompt,
                  "stream": False, "options": {"temperature": 0.6,
                                               "num_predict": 500}},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        text = (r.json().get("response") or "").strip()
        text = text.split(" response")[-1] if " response" in text else text
        lines = text.splitlines()
        if lines and lines[0].strip().lower().startswith(("subject", "dear")):
            text = "\n".join(lines[1:]).strip()
        return text or None
    except Exception:  # noqa: BLE001
        return None


def _system_prompt(cfg: dict) -> str:
    cand = cfg.get("candidate", {})
    locs = ", ".join(cand.get("preferred_locations", [])) or "anywhere"
    sal = ""
    lo, hi = cand.get("desired_salary_min"), cand.get("desired_salary_max")
    if lo or hi:
        sal = f" Desired salary: {lo or '?'}-{hi or '?'}/yr."
    roles = ", ".join(cand.get("roles", [])) or "software engineer"
    return (
        "You are an honest job-application writing assistant. Polite and "
        "frank, no hype, no buzzwords, no 'I hope this email finds you "
        "well'. Concrete and specific. Plain text, no markdown.\n"
        f"Candidate: {cand.get('name','[NAME]')} - {cand.get('headline','')}.\n"
        f"Target roles: {roles}. Experience: {cand.get('years_of_exp') or 'n/a'} years."
        f" Preferred locations: {locs}.{sal}\n"
        f"Skills: {', '.join(cand.get('skills', [])) or 'n/a'}.\n"
        f"Summary: {cand.get('summary','')}."
    )


def _slug(job: dict) -> str:
    raw = f"{job['company']}-{job['title']}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:60]


def tailor_job(cfg: dict, job: dict, resume_text: str = "", use_ai: bool = True
               ) -> dict:
    """Returns {'cover_letter': str, 'resume_summary': str}."""
    ensure_data_dir()
    TAILORED_DIR.mkdir(exist_ok=True)
    slug = _slug(job)
    key = f"{job['id']}:{slug}"
    cache = _load_cache()
    if key in cache:
        return cache[key]

    cand = cfg.get("candidate", {})
    system = _system_prompt(cfg)
    oll = cfg.get("ollama", {})
    base = oll.get("base_url", "http://localhost:11434")
    model = oll.get("model", "deepseek-r1:8b")

    job_blurb = (f"Title: {job['title']}\nCompany: {job['company']}\n"
                 f"Location: {job['location']}\n"
                 f"Description: {job['description'][:1500]}")

    result = {"cover_letter": "", "resume_summary": "", "slug": slug}

    if use_ai:
        cl = _ollama(base, model, system,
                     f"Write a cover letter (max 180 words) for this job. {job_blurb}")
        rs = _ollama(base, model, system,
                     f"Write a 3-bullet resume summary (max 60 words total) "
                     f"tailored to this job. {job_blurb}")
        if cl:
            result["cover_letter"] = cl
        if rs:
            result["resume_summary"] = rs

    # fallback template
    if not result["cover_letter"]:
        result["cover_letter"] = (
            f"Hi {job['company']} team,\n\n"
            f"I'm {cand.get('name','[NAME]')} - {cand.get('headline','a developer')}. "
            f"I'm applying for the {job['title']} role.\n\n"
            f"Relevant background: {cand.get('summary','')}\n\n"
            "I work well in small teams, ship end-to-end, and care about "
            "maintainable code. I'd welcome a conversation about the role.\n\n"
            "Thanks,\n" + cand.get("name", "[NAME]")
        )
    if not result["resume_summary"]:
        skills = ", ".join(cand.get("skills", [])) or "development"
        result["resume_summary"] = (
            f"- {cand.get('headline','Developer')} with hands-on {skills}\n"
            f"- Built and shipped production software end to end\n"
            f"- Strong fit for {job['title']} at {job['company']}"
        )

    cache[key] = result
    _save_cache(cache)

    out_file = TAILORED_DIR / f"{slug}.txt"
    out_file.write_text(
        f"# {job['title']} @ {job['company']}\n"
        f"# url: {job['url']}\n"
        f"# match score: {job.get('match_score','?')}\n\n"
        f"## Cover letter\n{result['cover_letter']}\n\n"
        f"## Resume summary\n{result['resume_summary']}\n",
        encoding="utf-8",
    )
    result["file"] = str(out_file)
    return result


def tailor_top(cfg: dict, top: int = 10, use_ai: bool = True) -> list[dict]:
    from .matcher import load_matches
    matches = load_matches()
    if not matches:
        print("[tailor] no matches - run `python cli.py match` first")
        return []
    resume_text = ""
    rp = cfg.get("candidate", {}).get("resume_path", "")
    if rp:
        from .resume import parse_resume
        resume_text = parse_resume(rp)
    results = []
    for job in matches[:top]:
        print(f"[tailor] {job['title'][:44]} @ {job['company'][:22]} ...")
        results.append(tailor_job(cfg, job, resume_text, use_ai))
    print(f"[tailor] done. {len(results)} tailored in {TAILORED_DIR}")
    return results
