"""Structured fit evaluation, ported from MadsLorentzen/ai-job-search
(``04-job-evaluation.md``) and adapted to j0b's offline/heuristic style.

Three pieces:

* **Language gate** — a posting that requires a language the candidate does not
  work in is a *hard fail* (veto). A posting whose stated bar reads higher than
  the declared level is *flagged*, not failed — the human is the tiebreaker.
* **Deal-breakers** — free-form phrases from the profile (e.g. "on-call",
  "requires relocation"). Any hit vetoes the posting.
* **Scoring dimensions** — Technical Skills / Experience / Career Alignment
  (the reference weights Behavioral Fit 15%; we have no behavioral data yet so
  the remaining weights are renormalised), plus Location (pass/fail-ish) and an
  optional Salary check. Output is an overall 0-100 score + a verdict using the
  reference thresholds (Strong 75+ / Good 60-74 / Moderate 45-59 / Weak 30-44 /
  Poor <30).

Everything here is pure and offline — no network calls.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# language gate
# ---------------------------------------------------------------------------

# Common working languages. English is deliberately included: if the posting
# demands English and the candidate did not declare it, that is a real gap.
LANGUAGES = [
    "english", "spanish", "german", "french", "italian", "portuguese",
    "dutch", "swedish", "norwegian", "danish", "finnish", "polish", "czech",
    "ukrainian", "russian", "turkish", "arabic", "hebrew", "hindi", "tamil",
    "telugu", "kannada", "malayalam", "marathi", "bengali", "urdu", "punjabi",
    "mandarin", "chinese", "cantonese", "japanese", "korean", "thai",
    "vietnamese", "indonesian", "malay", "greek", "hungarian", "romanian",
    "bulgarian", "serbian", "croatian", "slovak", "slovenian", "estonian",
    "latvian", "lithuanian", "icelandic", "persian", "farsi", "swahili",
    "filipino", "tagalog",
]

_HIGH_BAR = ("native", "fluent", "c1", "c2", "business", "advanced",
             "professional", "proficient", "near-native", "mother tongue")
_HIGH_LEVEL = ("native", "fluent", "c1", "c2", "advanced", "professional",
               "business", "near-native", "mother tongue")


def parse_languages(raw) -> list[dict]:
    """Turn config languages (list of 'english: fluent' strings OR already
    parsed {'name': .., 'level': ..} dicts) into [{'name', 'level'}]."""
    out: list[dict] = []
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip().lower()
            if name:
                out.append({"name": name,
                            "level": str(item.get("level") or "").strip().lower()})
            continue
        text = str(item or "").strip()
        if not text:
            continue
        name, _, level = text.partition(":")
        if not level:
            name, _, level = text.partition("(")
            level = level.rstrip(")")
        if not level:
            name, _, level = text.partition("-")
        name = name.strip().lower()
        if name:
            out.append({"name": name, "level": level.strip().lower()})
    return out


def _lang_pattern(name: str) -> re.Pattern:
    n = re.escape(name)
    return re.compile(
        rf"(?:"
        rf"fluent\s+(?:in\s+)?{n}"
        rf"|native\s+(?:in\s+)?{n}"
        rf"|proficien(?:t|cy)\s+(?:in\s+)?{n}"
        rf"|business[- ]?level\s+{n}"
        rf"|advanced\s+{n}"
        rf"|professional\s+{n}"
        rf"|conversational\s+{n}"
        rf"|working\s+knowledge\s+of\s+{n}"
        rf"|{n}\s+(?:is\s+)?required"
        rf"|{n}\s*\(?(?:c1|c2|b2|native|fluent|proficient|advanced)\)?"
        rf"|(?:c1|c2|b2)\s+{n}"
        rf"|must\s+communicate\s+in\s+{n}"
        rf"|must\s+(?:speak|write|read|know)\s+{n}"
        rf")",
        re.IGNORECASE,
    )


def _snippet(text: str, match: re.Match, radius: int = 34) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end].strip()


def language_gate(job: dict, languages: list) -> dict:
    """Classify a posting's language requirements.

    Returns {'verdict': 'pass'|'flag'|'fail', 'note': str}. A 'fail' is a hard
    veto; 'flag' proceeds but must be surfaced to the user. All requirements
    are collected first so a hard fail (undeclared language) always wins over
    a flag/pass regardless of the LANGUAGES list order.
    """
    if not languages:
        return {"verdict": "pass",
                "note": "no language profile declared - gate skipped"}
    declared = {l["name"] for l in languages}
    levels = {l["name"]: l["level"] for l in languages}
    text = " ".join([job.get("title", ""), job.get("location", ""),
                     job.get("tags", ""), job.get("description", "")])
    lowered = text.lower()
    fails: list[str] = []
    flags: list[str] = []
    for name in LANGUAGES:
        for m in _lang_pattern(name).finditer(text):
            snippet = _snippet(lowered, m)
            if name not in declared:
                fails.append(f"posting requires {name}: \"{snippet}\" - "
                             f"not in your declared languages")
                break  # one reason per language is enough
            # declared: compare the posting's bar with the declared level
            bar_high = any(w in snippet for w in _HIGH_BAR)
            lvl = levels[name]
            level_high = any(w in lvl for w in _HIGH_LEVEL)
            if bar_high and not level_high:
                flags.append(f"{name}: posting asks \"{snippet}\" but your "
                             f"declared level is \"{lvl or 'n/a'}\" - your call")
                break
    if fails:
        return {"verdict": "fail", "note": fails[0]}
    if flags:
        return {"verdict": "flag", "note": flags[0]}
    return {"verdict": "pass", "note": "no language hard-requirements found"}


# ---------------------------------------------------------------------------
# deal-breakers
# ---------------------------------------------------------------------------

def deal_breaker_hits(job: dict, deal_breakers: list) -> list[str]:
    """Return the deal-breaker phrases that appear in the posting (veto)."""
    if not deal_breakers:
        return []
    text = " ".join([job.get("title", ""), job.get("location", ""),
                     job.get("tags", ""), job.get("description", "")]).lower()
    hits = []
    for phrase in deal_breakers:
        p = str(phrase or "").strip()
        if p and p.lower() in text:
            hits.append(p)
    return hits


# ---------------------------------------------------------------------------
# scoring dimensions
# ---------------------------------------------------------------------------

def _to_int(value) -> int | None:
    try:
        n = int(value or 0)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def exp_fit(job: dict, years: int | None) -> float:
    """1.0 aligned, 0.6 badly misaligned; neutral 0.85 when unknown."""
    if not years:
        return 0.85
    txt = f"{job.get('title', '')} {job.get('location', '')} {job.get('tags', '')}".lower()
    senior = ["senior", "lead", "principal", "staff", "manager", "architect"]
    junior = ["junior", "entry", "intern", "graduate", "trainee"]
    if any(s in txt for s in senior):
        return 1.0 if years >= 3 else 0.6
    if any(s in txt for s in junior):
        return 1.0 if years <= 5 else 0.6
    return 0.85 if 1 <= years <= 2 else 1.0


def location_fit(job: dict, locations: list) -> float:
    """0-1 location fit vs the candidate's preferred locations."""
    locs = [l.strip().lower() for l in (locations or []) if l and l.strip()]
    if not locs:
        return 1.0
    job_loc = (job.get("location") or "").lower()
    wants_remote = "remote" in locs
    is_remote = "remote" in job_loc or "anywhere" in job_loc
    if wants_remote and is_remote:
        return 1.0
    if any(l in job_loc for l in locs if l != "remote"):
        return 1.0
    if wants_remote:
        return 0.6  # candidate wants remote, this role is on-site
    return 0.7


def salary_fit(job: dict, salary_min: int | None, salary_max: int | None) -> float:
    """1.0 inside the desired range, 0.55 clearly outside, 1.0 unknown."""
    if not salary_min and not salary_max:
        return 1.0
    from .filters import parse_salary_range
    rng = parse_salary_range(job)
    if rng is None:
        return 1.0  # unknown salary: don't guess
    jlo, jhi = rng
    if salary_min and jhi < salary_min:
        return 0.55
    if salary_max and jlo > salary_max:
        return 0.55
    return 1.0


def _career_alignment(job: dict, roles: list) -> float:
    """0-1 overlap between target roles and the posting's title/description."""
    roles = [r for r in (roles or []) if str(r or "").strip()]
    if not roles:
        return 0.7  # no target roles declared: neutral
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()
    hits = sum(1 for r in roles if str(r).lower() in text)
    return min(1.0, hits / max(1, len(roles)) + 0.2)


def evaluate(job: dict, skills: list[str], cand: dict | None = None) -> dict:
    """Run the full framework against one job.

    Returns a dict with dimensions (0-100 each), an overall 0-100 score, a
    verdict, per-gate results and notes.
    """
    cand = cand or {}
    skills = [s for s in (skills or []) if s]

    # -- gates -------------------------------------------------------------
    language = language_gate(job, parse_languages(cand.get("languages", [])))
    dealbreakers = deal_breaker_hits(job, cand.get("deal_breakers", []))

    # -- dimensions (0-100) ------------------------------------------------
    desc = (job.get("description", "") + " " + job.get("tags", "")).lower()
    tech = min(1.0, sum(1 for s in skills if re.search(rf"\b{re.escape(s)}\b", desc))
               / max(1, len(skills)) * 2.0) if skills else 0.0
    years = _to_int(cand.get("years_of_exp"))
    exp = exp_fit(job, years)
    loc = location_fit(job, cand.get("preferred_locations", []))
    alignment = _career_alignment(job, cand.get("roles", []))

    dims = {
        "technical": round(tech * 100),
        "experience": round(exp * 100),
        "location": round(loc * 100),
        "alignment": round(alignment * 100),
    }

    # reference weights: tech 30 / exp 25 / behavioral 15 / alignment 30.
    # behavioral data is not collected yet, so renormalise the rest to 100.
    overall = round(0.353 * tech * 100 + 0.294 * exp * 100 + 0.353 * alignment * 100)
    if loc < 0.6:
        overall = int(overall * 0.85)  # location mismatch drags the score

    # salary: optional penalty applied in matcher (kept separate here)
    sal_fit = salary_fit(job, _to_int(cand.get("desired_salary_min")),
                         _to_int(cand.get("desired_salary_max")))

    verdict = ("Strong Fit" if overall >= 75 else "Good Fit" if overall >= 60
               else "Moderate Fit" if overall >= 45 else "Weak Fit"
               if overall >= 30 else "Poor Fit")

    notes = []
    if language["verdict"] == "flag":
        notes.append(language["note"])
    if loc < 0.6:
        notes.append("location mismatch with your preferences")
    for db in dealbreakers:
        notes.append(f"deal-breaker: \"{db}\"")

    return {
        "dimensions": dims,
        "overall": overall,
        "verdict": verdict,
        "language": language,
        "dealbreakers": dealbreakers,
        "notes": notes,
        "veto": (f"language: {language['note']}" if language["verdict"] == "fail"
                 else (f"deal-breaker: {', '.join(dealbreakers)}"
                       if dealbreakers else None)),
    }
