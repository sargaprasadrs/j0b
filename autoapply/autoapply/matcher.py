"""Score jobs vs the candidate's resume + skills + profile.

keyword mode (fast, offline):
    base = 0.45 * title_hit + 0.40 * skill_coverage + 0.15 * seniority_hint
    score = base * (0.6 + 0.4 * profile_fit)  where profile_fit averages
            exp fit (years_of_exp), location fit (preferred_locations) and
            salary fit (desired_salary_min/max)
ai mode (slow, Ollama):
    asks the local LLM for a 0-100 fit score for the top-N keyword matches.

The final score blends the keyword base with the structured fit rubric from
``fit.py`` (ported from ai-job-search's 04-job-evaluation.md): Technical /
Experience / Location / Career-Alignment dimensions, a Language gate and
free-form deal-breakers. Hard gate failures veto the posting (score 0 +
reason written to vetoed.json); language flags are surfaced, not fatal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from .config import DATA_DIR, ensure_data_dir
from .jobs import load_jobs
from .resume import extract_skills
from . import fit as fit_mod

MATCHES_FILE = DATA_DIR / "matches.json"
VETOED_FILE = DATA_DIR / "vetoed.json"

TITLE_KEYWORDS = [
    "software", "developer", "engineer", "backend", "frontend", "fullstack",
    "full-stack", "python", "react", "node", "ml", "ai", "data", "devops",
]


def _title_score(job: dict, skills: list[str]) -> float:
    title = job["title"].lower()
    hits = sum(1 for k in TITLE_KEYWORDS if k in title)
    # bonus if a resume skill literally appears in the title
    for skill in skills:
        if skill in title:
            hits += 2
    return min(1.0, hits / 4)


def _skill_coverage(job: dict, skills: list[str]) -> float:
    if not skills:
        return 0.0
    desc = (job["description"] + " " + job.get("tags", "")).lower()
    hits = sum(1 for s in skills if re.search(rf"\b{re.escape(s)}\b", desc))
    return min(1.0, hits / max(1, len(skills)) * 2.0)


def _seniority_hint(job: dict) -> float:
    txt = f"{job['title']} {job['location']} {job.get('tags','')}".lower()
    senior = ["senior", "lead", "principal", "staff", "manager", "architect"]
    junior = ["junior", "entry", "intern", "graduate", "trainee"]
    if any(s in txt for s in senior):
        return 0.6
    if any(s in txt for s in junior):
        return 1.0
    return 0.8


# shared profile-fit helpers live in fit.py (single source of truth); these
# thin aliases keep the public names used by tests and callers stable.
_to_int = fit_mod._to_int
_exp_fit = fit_mod.exp_fit
_location_fit = fit_mod.location_fit
_salary_fit = fit_mod.salary_fit


def _keyword_score(job: dict, skills: list[str], cand: dict | None = None) -> int:
    cand = cand or {}
    base = (0.45 * _title_score(job, skills)
            + 0.40 * _skill_coverage(job, skills)
            + 0.15 * _seniority_hint(job))
    # profile fit (roles/exp handled via skills+seniority; here: exp/loc/salary)
    exp_fit = _exp_fit(job, _to_int(cand.get("years_of_exp")))
    loc_fit = _location_fit(job, cand.get("preferred_locations", []))
    sal_fit = _salary_fit(job, _to_int(cand.get("desired_salary_min")),
                          _to_int(cand.get("desired_salary_max")))
    profile = (exp_fit + loc_fit + sal_fit) / 3.0
    return int(round(base * (0.6 + 0.4 * profile) * 100))


def _ai_score(job: dict, cfg: dict, skills: list[str], cand: dict | None = None) -> int | None:
    cand = cand or {}
    oll = cfg.get("ollama", {})
    base = oll.get("base_url", "http://localhost:11434")
    model = oll.get("model", "deepseek-r1:8b")
    prompt = (
        "Rate fit 0-100 for this job vs this candidate. Only reply with the number.\n"
        f"Candidate skills: {', '.join(skills) or 'n/a'}\n"
        f"Candidate years of experience: {cand.get('years_of_exp') or 'n/a'}\n"
        f"Candidate preferred locations: {', '.join(cand.get('preferred_locations') or []) or 'any'}\n"
        f"Candidate desired salary (annual): {cand.get('desired_salary_min') or 'n/a'}"
        f" - {cand.get('desired_salary_max') or 'n/a'}\n"
        f"Candidate languages: {', '.join(cand.get('languages') or []) or 'n/a'}\n"
        f"Candidate deal-breakers: {', '.join(cand.get('deal_breakers') or []) or 'none'}\n"
        f"Job title: {job['title']} at {job['company']}\n"
        f"Job location: {job.get('location', '')}\n"
        f"Job description (first 1200 chars): {job['description'][:1200]}"
    )
    try:
        r = requests.post(base.rstrip("/") + "/api/generate",
                          json={"model": model, "prompt": prompt, "stream": False,
                                "options": {"temperature": 0.0, "num_predict": 300}},
                          timeout=150)
        if r.status_code != 200:
            return None
        # deepseek-r1 reasons first; take the LAST number in the response
        nums = re.findall(r"\b([0-9]{1,3})\b", r.json().get("response", ""))
        if nums:
            return min(100, int(nums[-1]))
    except Exception:  # noqa: BLE001
        pass
    return None


def match_all(cfg: dict) -> list[dict]:
    ensure_data_dir()
    jobs = load_jobs()
    if not jobs:
        print("[match] no jobs - run `python cli.py search` first")
        return []

    resume_path = cfg.get("candidate", {}).get("resume_path", "")
    from .resume import parse_resume
    text = parse_resume(resume_path)
    if not text:
        print("[match] WARNING: no resume text - using config skills only")
    skills = extract_skills(text) if text else cfg.get("candidate", {}).get("skills", [])
    print(f"[match] resume skills detected: {', '.join(skills) or 'none'}")

    cand = cfg.get("candidate", {})
    mode = cfg.get("match", {}).get("mode", "keywords")
    results = []
    vetoed = []
    for job in jobs:
        score = _keyword_score(job, skills, cand)
        # structured fit rubric (language gate + deal-breakers + dimensions)
        fit = fit_mod.evaluate(job, skills, cand)
        job["fit"] = fit
        job["verdict"] = fit["verdict"]
        job["veto"] = fit["veto"]
        if fit["veto"]:
            job["match_score"] = 0
            vetoed.append({"id": job["id"], "title": job["title"],
                           "company": job["company"], "url": job["url"],
                           "reason": fit["veto"]})
            results.append(job)
            continue
        if mode == "ai" and score >= 40:
            ai = _ai_score(job, cfg, skills, cand)
            if ai is not None:
                score = int(0.5 * score + 0.5 * ai)
        # blend keyword base with the structured rubric (50/50)
        score = int(0.5 * score + 0.5 * fit["overall"])
        sal_fit = fit_mod.salary_fit(
            job, fit_mod._to_int(cand.get("desired_salary_min")),
            fit_mod._to_int(cand.get("desired_salary_max")))
        if sal_fit < 1.0:
            score = int(score * sal_fit)
        job["match_score"] = score
        results.append(job)

    results.sort(key=lambda j: j["match_score"], reverse=True)
    min_score = cfg.get("match", {}).get("min_score", 30)
    kept = [j for j in results if j["match_score"] >= min_score]

    with open(MATCHES_FILE, "w", encoding="utf-8") as fh:
        json.dump(kept, fh, indent=2, ensure_ascii=False)
    with open(VETOED_FILE, "w", encoding="utf-8") as fh:
        json.dump(vetoed, fh, indent=2, ensure_ascii=False)
    print(f"[match] {len(jobs)} jobs scored -> {len(kept)} above threshold "
          f"(min {min_score}) -> {MATCHES_FILE}")
    if vetoed:
        print(f"[match] {len(vetoed)} vetoed (language gate / deal-breakers) "
              f"-> {VETOED_FILE}")
    for j in kept[:12]:
        print(f"  {j['match_score']:>3}  {j['title'][:42]:<42} @ {j['company'][:24]}")
    return kept


def load_matches() -> list[dict]:
    if not MATCHES_FILE.exists():
        return []
    return json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
