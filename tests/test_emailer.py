"""Offline tests for the Gmail cold-email pipeline (emailer + gmail_drafter).

No network, no browser: recipient resolution is skipped (resolve=False),
email generation uses the template fallback (use_ai=False), and drafting is
exercised via dry-run.

Run:  python tests/test_emailer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "coldmail"))

import emailer  # noqa: E402
from coldmail.gmail_drafter import _compose_url, draft_emails  # noqa: E402

CFG = {
    "sender": {
        "name": "Sarga Prasad RS",
        "email": "candidate@example.com",
        "headline": "Full-stack developer & AI engineer",
        "summary": "I build web apps and AI tooling end to end.",
        "skills": ["python", "react"],
    },
    "outreach": {
        "ask": "I'd appreciate 10 minutes of your time.",
        "signoff": "Thanks,\n{sender_name}",
    },
    "ollama": {"base_url": "http://localhost:11434", "model": "m", "use_ai": False},
}


def _job(**kw) -> dict:
    base = {
        "id": "j1", "title": "Senior Python Engineer", "company": "Acme",
        "location": "Remote", "url": "https://example.com/job",
        "source": "test", "description": "python", "salary": "",
        "exp_display": "5+ yrs",
    }
    base.update(kw)
    return base


def test_compose_url_pins_authuser():
    url = _compose_url("a@b.com", "Hello there", "Body & more", authuser=0)
    assert "view=cm" in url and "fs=1" in url
    assert "authuser=0" in url          # default/first signed-in account
    assert "to=a%40b.com" in url        # recipient encoded
    assert "su=Hello%20there" in url
    assert "body=Body%20%26%20more" in url


def test_resolve_engine_selection():
    # no send section / use_ai False -> offline template (tests stay offline)
    assert emailer._resolve_engine(CFG, use_ai=False) == "template"
    assert emailer._resolve_engine(CFG, use_ai=True) == "template"
    # explicit engine wins
    cfg2 = {**CFG, "send": {"email_engine": "opencode"}}
    assert emailer._resolve_engine(cfg2, use_ai=True) == "opencode"
    # legacy flag maps to ollama
    cfg3 = {**CFG, "send": {"personalize_with_ai": True}}
    assert emailer._resolve_engine(cfg3, use_ai=True) == "ollama"


def test_generate_cold_email_template():
    res = emailer.generate_cold_email(CFG, _job(), use_ai=False, resolve=False)
    assert res["ok"] is True
    assert res["company"] == "Acme"
    assert res["to"] == ""                      # resolve=False -> no lookup
    assert res["recipient_source"] == ""
    assert "Acme" in res["subject"]
    assert "Sarga" in res["body"]               # template uses the sender name
    assert "Senior Python Engineer" in res["body"]  # role woven into the body


def test_generate_cold_email_notes_fallback_when_no_role():
    # without a role title, the location/exp/salary notes drive the email
    res = emailer.generate_cold_email(CFG, _job(title=""), use_ai=False,
                                      resolve=False)
    assert res["ok"] is True
    assert "Remote" in res["body"]


def test_generate_cold_email_includes_salary_and_exp_notes():
    job = _job(salary="80000-100000")
    res = emailer.generate_cold_email(CFG, job, use_ai=False, resolve=False)
    assert res["ok"] is True
    # notes are passed into the writer so the email can reference the role
    assert "Senior Python Engineer" in res["body"]


def test_generate_cold_email_mentions_jd_skills():
    # the email should explain fit against the posting's keywords
    cfg2 = {**CFG, "sender": {**CFG["sender"],
                               "skills": ["python", "fastapi", "docker", "postgres"]}}
    job = _job(description="python fastapi docker postgres backend")
    res = emailer.generate_cold_email(cfg2, job, use_ai=False, resolve=False)
    assert res["ok"] is True
    assert "calls for python, fastapi, docker, postgres" in res["body"]


def test_generate_cold_email_fit_fallback_without_skill_match():
    # no overlap between sender skills and the JD -> generic fit line, still fine
    job = _job(description="we need a COBOL mainframe specialist")
    res = emailer.generate_cold_email(CFG, job, use_ai=False, resolve=False)
    assert res["ok"] is True
    assert "Senior Python Engineer" in res["body"]


def test_draft_emails_dry_run_no_browser():
    emails = [{"to": "a@b.com", "subject": "S", "body": "B",
               "company": "Acme"}]
    out = draft_emails(emails, dry_run=True, max_drafts=1)
    assert out == []                             # nothing created in dry run


def test_quick_recipient_guess_and_unknown():
    assert emailer.quick_recipient("AB") == ("", "")     # slug too short
    # offline: stub the network so this never depends on DNS/connectivity
    original = emailer.requests.get
    try:
        emailer.requests.get = lambda *a, **k: (_ for _ in ()).throw(
            Exception("no network in tests"))
        to, src = emailer.quick_recipient("nonexistent-co-xyz")
        assert to == "" and src == ""                     # graceful failure
    finally:
        emailer.requests.get = original


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
