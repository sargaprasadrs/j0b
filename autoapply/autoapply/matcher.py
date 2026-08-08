"""Score jobs vs the candidate's resume + skills.

keyword mode (fast, offline):
    score = 0.45 * title_hit + 0.40 * skill_coverage + 0.15 * seniority_hint
ai mode (slow, Ollama):
    asks the local LLM for a 0-100 fit score for the top-N keyword matches.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from .config import DATA_DIR, ensure_data_dir
from .jobs import load_jobs
from .resume import extract_skills

MATCHES_FILE = DATA_DIR / "matches.json"

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


def _keyword_score(job: dict, skills: list[str]) -> int:
    raw = (0.45 * _title_score(job, skills)
           + 0.40 * _skill_coverage(job, skills)
           + 0.15 * _seniority_hint(job))
    return int(round(raw * 100))


def _ai_score(job: dict, cfg: dict, skills: list[str]) -> int | None:
    oll = cfg.get("ollama", {})
    base = oll.get("base_url", "http://localhost:11434")
    model = oll.get("model", "deepseek-r1:8b")
    prompt = (
        "Rate fit 0-100 for this job vs this candidate. Only reply with the number.\n"
        f"Candidate skills: {', '.join(skills) or 'n/a'}\n"
        f"Job title: {job['title']} at {job['company']}\n"
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

    mode = cfg.get("match", {}).get("mode", "keywords")
    results = []
    for job in jobs:
        score = _keyword_score(job, skills)
        if mode == "ai" and score >= 40:
            ai = _ai_score(job, cfg, skills)
            if ai is not None:
                score = int(0.5 * score + 0.5 * ai)
        job["match_score"] = score
        results.append(job)

    results.sort(key=lambda j: j["match_score"], reverse=True)
    min_score = cfg.get("match", {}).get("min_score", 30)
    kept = [j for j in results if j["match_score"] >= min_score]

    with open(MATCHES_FILE, "w", encoding="utf-8") as fh:
        json.dump(kept, fh, indent=2, ensure_ascii=False)
    print(f"[match] {len(jobs)} jobs scored -> {len(kept)} above threshold "
          f"(min {min_score}) -> {MATCHES_FILE}")
    for j in kept[:12]:
        print(f"  {j['match_score']:>3}  {j['title'][:42]:<42} @ {j['company'][:24]}")
    return kept


def load_matches() -> list[dict]:
    if not MATCHES_FILE.exists():
        return []
    return json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
