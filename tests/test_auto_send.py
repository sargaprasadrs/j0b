"""Offline tests for auto_send.py (dedup, plan building, MIME, secrets).

No network, no Gmail API, no browser. Run:  python tests/test_auto_send.py
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path


class Tmp:
    """Minimal tmp_path stand-in (tests run without pytest)."""
    def __init__(self):
        self._d = Path(tempfile.mkdtemp(prefix="auto_send_test_"))

    @property
    def path(self) -> Path:
        return self._d

    def cleanup(self):
        shutil.rmtree(self._d, ignore_errors=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auto_send  # noqa: E402

TODAY = dt.date(2026, 8, 13)

CFG = {
    "send": {
        "mode": "gmail_api",
        "max_emails_per_run": 100,
        "min_score": 40,
        "company_cooldown_days": 45,
        "allow_guessed_recipients": True,
    },
    "match": {"min_score": 30},
    "sender": {"name": "Sarga", "email": "candidate@example.com"},
    "candidate": {"resume_path": ""},
}


def _job(company="Acme", title="Python Engineer", score=80, jid="j1",
         url="https://example.com/job", description="python"):
    return {"id": jid, "title": title, "company": company,
            "location": "Remote", "url": url, "source": "test",
            "description": description, "salary": "", "exp_display": "2+ yrs",
            "match_score": score}


def _write_sent(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=auto_send.SENT_FIELDS,
                           extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _sent_row(company="Acme", recipient="hr@acme.com", days_ago=5,
              status="sent", job_id="j1"):
    return {"date": (TODAY - dt.timedelta(days=days_ago)).isoformat(),
            "company": company, "recipient": recipient, "job_id": job_id,
            "title": "x", "url": "u", "subject": "s",
            "recipient_source": "site", "status": status, "error": ""}


# ---------------------------------------------------------------------------
def test_norm_helpers():
    assert auto_send._norm_key("  HR@Acme.COM ") == "hr@acme.com"
    assert auto_send._norm_company("Acme Inc.") == "acmeinc"
    assert auto_send._norm_company("") == ""


def test_load_sent_only_counts_drafted():
    t = Tmp()
    try:
        path = t.path / "s.csv"
        _write_sent(path, [_sent_row(recipient="a@x.com", status="drafted"),
                           _sent_row(recipient="b@x.com", status="error"),
                           _sent_row(recipient="c@x.com", status="sent")])
        sent = auto_send.load_sent(path)
        assert "a@x.com" in sent   # drafted counts
        assert "c@x.com" in sent   # legacy 'sent' still counts
        assert "b@x.com" not in sent  # failed/error attempts are retried
    finally:
        t.cleanup()


def test_company_cooldown_blocks_recent():
    sent = {"hr@acme.com": _sent_row(days_ago=5)}
    cands, skipped = auto_send.filter_plan_candidates(
        [_job(score=80)], CFG, sent, set(), set(), today=TODAY)
    assert cands == []
    assert any("cooldown" in s for s in skipped)


def test_company_cooldown_expires():
    sent = {"hr@acme.com": _sent_row(days_ago=60)}
    cands, _ = auto_send.filter_plan_candidates(
        [_job(score=80)], CFG, sent, set(), set(), today=TODAY)
    assert len(cands) == 1


def test_applied_and_vetoed_companies_skipped():
    t = Tmp()
    try:
        root = t.path
        applied = root / "applied.csv"
        applied.write_text("date,company,title,url,score,status\n"
                           "2026-08-01,Acme,Py,http://x,50,applied\n",
                           encoding="utf-8")
        vetoed = root / "vetoed.json"
        vetoed.write_text(json.dumps([{"company": "Zeta"}]), encoding="utf-8")
        jobs = [_job(company="Acme", score=80), _job(company="Zeta", score=90),
                _job(company="Beta", score=70)]
        cands, skipped = auto_send.filter_plan_candidates(
            jobs, CFG, {}, auto_send.load_applied_companies(applied),
            auto_send.load_vetoed_companies(vetoed), today=TODAY)
        names = [c["company"] for c in cands]
        assert names == ["Beta"]
        assert any("already applied" in s for s in skipped)
        assert any("vetoed" in s for s in skipped)
    finally:
        t.cleanup()


def test_skips_senior_and_lead_roles():
    jobs = [_job(title="Senior DevOps Engineer", score=80),
            _job(title="Lead Python Engineer", score=75, jid="j2"),
            _job(title="Python Engineer", score=70, jid="j3")]
    cands, skipped = auto_send.filter_plan_candidates(
        jobs, CFG, {}, set(), set(), today=TODAY)
    assert [c["title"] for c in cands] == ["Python Engineer"]
    assert any("senior/lead role" in s for s in skipped)


def test_skips_roles_requiring_more_than_max_years():
    jobs = [_job(title="Backend Engineer",
                 description="5+ years of experience", score=80),
            _job(title="Backend Engineer",
                 description="3+ years of experience", score=80, jid="j2"),
            _job(title="Python Engineer", description="python", score=70,
                 jid="j3")]
    cands, skipped = auto_send.filter_plan_candidates(
        jobs, CFG, {}, set(), set(), today=TODAY)
    # 3+ years and unknown both pass; 5+ years is blocked
    assert len(cands) == 2
    assert any("5+ yrs" in s for s in skipped)


def test_seniority_gate_can_be_disabled():
    cfg_off = dict(CFG)
    cfg_off["send"] = dict(CFG["send"], skip_senior_roles=False)
    cands, _ = auto_send.filter_plan_candidates(
        [_job(title="Senior DevOps Engineer", score=80)], cfg_off, {},
        set(), set(), today=TODAY)
    assert len(cands) == 1


def test_score_threshold():
    jobs = [_job(score=90), _job(score=20)]
    cands, skipped = auto_send.filter_plan_candidates(
        jobs, CFG, {}, set(), set(), today=TODAY)
    assert len(cands) == 1
    assert any("< 40" in s for s in skipped)


def test_recipient_never_emailed_twice():
    # sent row is old enough that the company cooldown has passed, so the
    # recipient-level check is what blocks the repeat send
    sent = {"hr@acme.com": _sent_row(days_ago=60)}
    cands, _ = auto_send.filter_plan_candidates(
        [_job(score=80)], CFG, sent, set(), set(), today=TODAY)
    assert len(cands) == 1  # company cooldown passed
    plan, skipped = auto_send.finalize_plan(
        cands, [("hr@acme.com", "site")], sent, CFG, limit=10)
    assert plan == []
    assert any("already contacted" in s for s in skipped)


def test_guess_recipients_can_be_blocked():
    cands, _ = auto_send.filter_plan_candidates(
        [_job(score=80)], CFG, {}, set(), set(), today=TODAY)
    cfg_no_guess = dict(CFG)
    cfg_no_guess["send"] = dict(CFG["send"], allow_guessed_recipients=False)
    plan, skipped = auto_send.finalize_plan(
        cands, [("hello@acme.com", "guess")], {}, cfg_no_guess, limit=10)
    assert plan == []
    assert any("not allowed" in s for s in skipped)
    # allowed by default
    plan2, _ = auto_send.finalize_plan(
        cands, [("hello@acme.com", "guess")], {}, CFG, limit=10)
    assert len(plan2) == 1


def test_same_company_never_twice_in_one_run():
    # two postings from one company resolving to different inboxes must still
    # produce a single email - only the first may be emailed in a run
    cands = [_job(company="Lemon.io", title="DevOps", score=80),
             _job(company="Lemon.io", title="Graphic", score=70, jid="j2")]
    resolved = [("hello@lemonio.com", "guess"),
                ("careers@lemonio.com", "guess")]
    plan, skipped = auto_send.finalize_plan(cands, resolved, {}, CFG, limit=10)
    assert len(plan) == 1
    assert any("same company" in s for s in skipped)


def test_same_recipient_never_twice_in_one_run():
    cands = [_job(company="Alpha", score=80),
             _job(company="Beta", score=70, jid="j2")]
    # distinct companies, but the same person/address was resolved for both
    resolved = [("shared@agency.com", "site"),
                ("shared@agency.com", "site")]
    plan, skipped = auto_send.finalize_plan(cands, resolved, {}, CFG, limit=10)
    assert len(plan) == 1
    assert any("already in this run" in s for s in skipped)


def test_cap_respects_limit():
    cands = [_job(company=f"Co{i}", score=80 - i) for i in range(5)]
    resolved = [(f"hr@co{i}.com", "site") for i in range(5)]
    plan, _ = auto_send.finalize_plan(cands, resolved, {}, CFG, limit=2)
    assert len(plan) == 2


def test_build_mime_has_headers_and_attachment():
    t = Tmp()
    try:
        root = t.path
        pdf = root / "resume.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        msg = auto_send.build_mime(CFG, "hr@acme.com", "Subject here",
                                   "Hello body", str(pdf))
        assert msg["To"] == "hr@acme.com"
        assert msg["Subject"] == "Subject here"
        assert "Sarga" in msg["From"]
        assert "@" in msg["Message-ID"]
        payloads = list(msg.iter_attachments())
        assert len(payloads) == 1
        assert payloads[0].get_filename() == "resume.pdf"
        # no attachment when the file is missing
        msg2 = auto_send.build_mime(CFG, "hr@acme.com", "S", "B", "nope.pdf")
        assert list(msg2.iter_attachments()) == []
    finally:
        t.cleanup()


def test_gmail_drafts_encode_raw():
    import base64
    import gmail_drafts
    msg = auto_send.build_mime(CFG, "hr@acme.com", "S", "B")
    raw = gmail_drafts.encode_raw(msg)
    decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
    assert "To: hr@acme.com" in decoded
    assert "Subject: S" in decoded
    assert "\n\nB" in decoded.replace("\r\n", "\n")  # body after blank line


def test_gmail_drafts_requires_setup_without_client_secret():
    import gmail_drafts
    original = gmail_drafts.CLIENT_SECRET
    gmail_drafts.CLIENT_SECRET = Path("does-not-exist-client-secret.json")
    try:
        try:
            gmail_drafts.ensure_token()
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "client_secret.json" in str(exc)
    finally:
        gmail_drafts.CLIENT_SECRET = original


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
