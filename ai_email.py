"""ai_email.py — generate cold-application email subject + body with opencode.

Safety (per design):
  * The opencode session is created with NO tools (tools=[]) and a system
    prompt that forbids any action — it can only write text back to us.
  * No API keys, tokens or secrets are ever placed in the prompt. Only the
    candidate's profile, their resume text, and the job posting.
  * Nothing is sent or created by this module. The caller turns the returned
    text into a Gmail draft (see auto_send.py).

Fallback chain lives in emailer.generate_cold_email: opencode -> template.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "autoapply"))
sys.path.insert(0, str(ROOT / "webui"))

from autoapply.config import DATA_DIR as AA_DATA  # noqa: E402

CACHE_FILE = ROOT / "data" / "opencode_email_cache.json"

# The agent is a pure text generator. No tools, no actions, no external calls.
SYSTEM_PROMPT = """\
You are a plain-text email writer for a job seeker.

You have NO tools, NO shell, NO network access, and NO permissions. You must
NOT create, send, or modify anything. You cannot write files, cannot send
email, cannot call APIs. Your ONLY output is the text of the email itself.

Write a polite and frank cold-application email. Rules:
- Under 180 words. No markdown, no bullets, no emojis.
- Name the candidate in the first sentence.
- Reference the specific role and company.
- Use the candidate's resume data to explain why they fit THIS posting
  (match their skills/experience to keywords in the job description).
- End with a short, low-pressure ask and the candidate's name as signature.

Reply EXACTLY in this format and nothing else:

SUBJECT: <one short line>
BODY:
<the email body>
"""


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except OSError:
        pass


def _resume_text(cfg: dict) -> str:
    """Extract the candidate's resume text (their real skills/experience)."""
    try:
        from autoapply.resume import parse_resume
        rp = (cfg.get("candidate", {}) or {}).get("resume_path", "")
        if rp and Path(rp).exists():
            return parse_resume(rp) or ""
        fb = AA_DATA / "resume.pdf"
        if fb.exists():
            return parse_resume(str(fb)) or ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def _context_block(cfg: dict, job: dict, resume_text: str) -> str:
    cand = cfg.get("candidate", {}) or {}
    parts = [
        "CANDIDATE PROFILE",
        f"Name: {cand.get('name', '')}",
        f"Headline: {cand.get('headline', '')}",
        f"Summary: {cand.get('summary', '')}",
        f"Skills: {', '.join(cand.get('skills') or [])}",
        f"Education: {cand.get('education', '')}",
        f"Projects: {'; '.join(cand.get('projects') or [])}",
    ]
    if resume_text.strip():
        parts.append(f"RESUME TEXT (source of truth for experience):\n{resume_text.strip()[:3000]}")
    parts.append(
        "JOB POSTING\n"
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Description: {(job.get('description') or '')[:2500]}"
    )
    return "\n".join(parts)


def _parse_reply(reply: str) -> tuple[str, str]:
    """Parse 'SUBJECT: ...' / 'BODY: ...' out of the agent reply (defensive)."""
    reply = (reply or "").strip()
    # strip markdown fences if the model wrapped it anyway
    reply = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", reply).strip()
    m = re.search(r"^SUBJECT:\s*(.+?)\s*$", reply,
                  re.IGNORECASE | re.MULTILINE)
    bm = re.search(r"^BODY:[ \t]*(.+)$", reply,
                   re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if m and bm:
        return m.group(1).strip(), bm.group(1).strip()
    if m:
        return m.group(1).strip(), reply[m.end():].strip()
    lines = [ln for ln in reply.splitlines() if ln.strip()]
    if len(lines) >= 2:
        return lines[0].strip().lstrip("Subject:").strip(), "\n".join(lines[1:]).strip()
    return "", reply


def generate_subject_body(cfg: dict, job: dict, timeout: int = 180) -> tuple[str, str]:
    """Ask opencode (no tools) to write subject + body for one job.

    Raises on failure so the caller can fall back to the template. Cached per
    company::role so repeat runs never re-invoke the agent.
    """
    company = (job.get("company") or "").strip()
    role = (job.get("title") or "").strip()
    cache_key = f"{company}::{role}"
    cache = _load_cache()
    if cache_key in cache and cache[cache_key].get("subject") and cache[cache_key].get("body"):
        return cache[cache_key]["subject"], cache[cache_key]["body"]

    from webui.agent_backend import OpenCodeClient

    client = OpenCodeClient(timeout=timeout)
    ok, msg = client.available()
    if not ok:
        raise RuntimeError(f"opencode unavailable: {msg}")

    prompt = (
        "Write a cold application email for the candidate for this job.\n\n"
        f"{_context_block(cfg, job, _resume_text(cfg))}\n\n"
        "Now reply in EXACTLY this format (nothing else, no preamble):\n"
        "SUBJECT: <one short line>\n"
        "BODY:\n<email body>\n"
    )
    sid = client.create_session(title="j0b email writer", tools=[])
    try:
        reply = client.prompt(sid, prompt, system=SYSTEM_PROMPT)
    finally:
        # the server keeps the session; nothing destructive to clean up
        pass

    subject, body = _parse_reply(reply)
    if not subject or not body:
        raise RuntimeError("opencode returned no usable subject/body")
    cache[cache_key] = {"subject": subject, "body": body}
    _save_cache(cache)
    return subject, body
