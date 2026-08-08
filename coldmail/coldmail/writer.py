"""Generate polite + frank cold-application emails.

Uses a local Ollama LLM when available (personalized per company/role),
and falls back to a strong hand-written template otherwise.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .config import DATA_DIR, ensure_data_dir

DRAFTS_DIR = DATA_DIR / "drafts"
CACHE_FILE = DATA_DIR / "email_cache.json"


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _ollama_generate(base_url: str, model: str, system: str, prompt: str,
                     timeout: float = 150) -> str | None:
    """Call Ollama. deepseek-r1 is slow (~80s) - give it room."""
    try:
        r = requests.post(
            base_url.rstrip("/") + "/api/generate",
            json={"model": model, "system": system, "prompt": prompt,
                  "stream": False, "options": {"temperature": 0.7,
                                                   "num_predict": 400}},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        text = (data.get("response") or "").strip()
        # strip think blocks some reasoning models output
        # strip a leading Subject: line if the model emitted one
        lines = text.splitlines()
        if lines and lines[0].strip().lower().startswith("subject:"):
            text = chr(10).join(lines[1:]).strip()
        text = text.split(" response")[-1] if " response" in text else text
        return text or None
    except Exception:  # noqa: BLE001
        return None


def _build_system_prompt(cfg: dict) -> str:
    sender = cfg.get("sender", {})
    return (
        "You write concise, honest cold emails for job applications. "
        "Tone: polite and frank - direct, no hype, no begging, no buzzwords, "
        "no 'I hope this email finds you well'. Short sentences. "
        "Under 150 words. No markdown, no subject line, just the body text "
        "starting with a greeting and ending with a signature.\n"
        f"The candidate's name is {sender.get('name','[NAME]')}. "
        f"Their headline: {sender.get('headline','')}. "
        f"Their summary: {sender.get('summary','')}. "
        f"Their skills: {', '.join(sender.get('skills', [])) or 'n/a'}."
    )


def generate_email(cfg: dict, company: str, role_title: str, notes: str = "",
                   site_text: str = "", use_ai: bool = True) -> str:
    """Return the plain-text email body for one startup (cached per company)."""
    sender = cfg.get("sender", {})
    sender_name = sender.get("name", "[Your Name]")
    ask = cfg.get("outreach", {}).get("ask", "")
    signoff = cfg.get("outreach", {}).get("signoff", "Thanks,\n{sender_name}")

    cache_key = f"{company}::{role_title}"
    cache = _load_cache()
    if cache_key in cache:
        return cache[cache_key]

    # Try Ollama for a personalized version
    oll = cfg.get("ollama", {})
    base_url = oll.get("base_url", "http://localhost:11434")
    model = oll.get("model", "deepseek-r1:8b")
    ai_default = oll.get("use_ai", True)
    use_ai = use_ai and ai_default
    if use_ai:
        system = _build_system_prompt(cfg)
        prompt = (
            f"Write a polite and frank cold application email to {company}. "
            f"Their open role / what they do: {role_title or notes or 'not specified'}. "
            "Structure: greeting, one line on who you are and what you're asking, "
            "one or two lines on relevant experience, one line on why this company, "
            f"then the ask: '{ask}'. End with signature '{sender_name}'."
        )
        body = _ollama_generate(base_url, model, system, prompt)
        if body:
            cache[cache_key] = body.strip()
            _save_cache(cache)
            return body.strip()

    # ---- Template fallback (polite + frank) ----
    what = role_title.strip() or notes.strip() or "your work"
    lines = [
        f"Hi {company} team,",
        "",
        f"I'm {sender_name} - {sender.get('headline','a developer')}. "
        "I'm writing directly because I'd rather send one honest email "
        "than a hundred applications that look the same.",
        "",
        f"What I can do: {sender.get('summary','')}".strip(),
        "",
        f"I'm interested in {what}. If there's a problem I can help with - "
        "even if it's not a formal open role - I'd like to talk.",
        "",
        ask.strip(),
        "",
        signoff.replace("{sender_name}", sender_name),
    ]
    return "\n".join(lines)


def write_draft_file(cfg: dict, company: str, email: str, subject: str,
                     body: str) -> Path:
    """Persist the draft to data/drafts/ so nothing is lost."""
    ensure_data_dir()
    DRAFTS_DIR.mkdir(exist_ok=True)
    slug = "".join(c for c in company.lower() if c.isalnum() or c == "-")[:40]
    path = DRAFTS_DIR / f"{slug}.txt"
    path.write_text(
        f"To: {email}\nSubject: {subject}\n\n{body}\n", encoding="utf-8"
    )
    return path


def build_subject(cfg: dict, company: str, role_title: str) -> str:
    headline = cfg.get("sender", {}).get("headline", "")
    role = role_title.strip() if role_title.strip() else "opportunities"
    return f"Quick question from a developer - {company} ({role})"
