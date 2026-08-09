"""Offline tests for the HTML tracker report (report.py).

Uses a temporary applied.csv so the real tracker is untouched.

Run:  python tests/test_report.py
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import autoapply.report as report


def _write_csv(path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "company", "title", "url",
                                           "score", "status"])
        w.writeheader()
        w.writerows([
            {"date": "2026-01-01", "company": "Acme", "title": "Engineer",
             "url": "https://jobicy.com/job/1", "score": "80", "status": "applied"},
            {"date": "2026-02-01", "company": "Beta & Sons", "title": "Dev <ML>",
             "url": "https://linkedin.com/jobs/view/2", "score": "70", "status": "interview"},
            {"date": "2026-03-01", "company": "Gamma", "title": "SRE",
             "url": "https://freehire.me/jobs/x", "score": "", "status": "offer"},
            {"date": "2026-03-05", "company": "Delta", "title": "QA",
             "url": "https://example.com/3", "score": "40", "status": "rejected"},
        ])


def test_normalise_status():
    assert report.normalise_status("applied") == "Active"
    assert report.normalise_status("Interview") == "Interview"
    assert report.normalise_status("no_response") == "Rejected/Closed"
    assert report.normalise_status("no response") == "Rejected/Closed"
    assert report.normalise_status("skipped") == "Rejected/Closed"
    assert report.normalise_status("whatever") == "Rejected/Closed"


def test_compute_stats():
    rows = [
        {"status": "applied"}, {"status": "interview"}, {"status": "offer"},
        {"status": "hired"}, {"status": "rejected"}, {"status": "no_response"},
    ]
    stats = report.compute_stats(rows)
    assert stats["total"] == 6
    assert stats["counts"]["Active"] == 1
    assert stats["counts"]["Interview"] == 1
    assert stats["counts"]["Offer"] == 1
    assert stats["counts"]["Hired"] == 1
    assert stats["counts"]["Rejected/Closed"] == 2
    # funnel: reached interview = Interview + Offer + Hired = 3
    assert stats["funnel"]["Interview"] == 3
    assert stats["interview_rate"] == 50.0


def test_generate_report_offline():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        log = tmp_path / "applied.csv"
        _write_csv(log)
        # point report.py at the temp CSV
        original = report.DATA_DIR
        try:
            report.DATA_DIR = tmp_path
            out = tmp_path / "report.html"
            res = report.generate_report(out)
            assert res["ok"]
            assert out.exists()
            html = out.read_text(encoding="utf-8")
            assert "Job Search Dashboard" in html
            assert "Acme" in html
            assert "<svg" in html and "role=\"img\"" in html
            assert "&amp;" in html or "Beta &amp; Sons" in html  # escaping works
            # hostile chars from the CSV are escaped, not injected
            assert "<ML>" not in html
            assert "&lt;ML&gt;" in html
            # fully self-contained: no external scripts or stylesheets
            assert '<script src=' not in html
            assert '<link rel="stylesheet"' not in html
        finally:
            report.DATA_DIR = original


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
