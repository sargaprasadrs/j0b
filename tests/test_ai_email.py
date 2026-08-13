"""Offline tests for ai_email.py (reply parsing + prompt safety).

No opencode server, no network. Run:  python tests/test_ai_email.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_email  # noqa: E402

CFG = {
    "candidate": {
        "name": "Sarga Prasad RS",
        "headline": "Full-Stack Engineer",
        "summary": "Builds web + AI apps.",
        "skills": ["python", "fastapi", "react"],
        "education": "B.Tech IT",
        "projects": ["OperaiQ", "UtilixVerse"],
        "resume_path": "",
    },
    "agent": {"composio": {"api_key": "sk-SECRET-KEY-NEVER-LEAK"}},
}

JOB = {
    "title": "Backend Engineer",
    "company": "Acme",
    "location": "Remote",
    "description": "Python, FastAPI and PostgreSQL to build AI document tools.",
}


def test_parse_reply_with_markers():
    reply = "Some preamble\nSUBJECT: Backend Engineer at Acme\nBODY:\nHi Acme team,\n\nI'm Sarga.\n"
    subject, body = ai_email._parse_reply(reply)
    assert subject == "Backend Engineer at Acme"
    assert body.startswith("Hi Acme team,")
    assert "Sarga" in body


def test_parse_reply_strips_markdown_fences():
    reply = "```\nSUBJECT: Hello\nBODY:\nBody text\n```"
    subject, body = ai_email._parse_reply(reply)
    assert subject == "Hello"
    assert body == "Body text"


def test_parse_reply_fallback_first_line():
    reply = "Quick question from a developer - Acme\n\nHi team,\n\nBody here."
    subject, body = ai_email._parse_reply(reply)
    assert "Acme" in subject
    assert "Hi team" in body


def test_context_block_includes_profile_and_job():
    block = ai_email._context_block(CFG, JOB, resume_text="Built OperaiQ with FastAPI.")
    assert "Sarga Prasad RS" in block
    assert "Backend Engineer" in block
    assert "Built OperaiQ with FastAPI" in block  # resume data is fed in


def test_context_block_never_leaks_secrets():
    block = ai_email._context_block(CFG, JOB, resume_text="")
    assert "sk-SECRET-KEY-NEVER-LEAK" not in block
    assert "api_key" not in block


def main() -> None:
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL  {name}\n{traceback.format_exc()}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
