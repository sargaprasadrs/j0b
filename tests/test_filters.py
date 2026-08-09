"""Offline tests for the years-of-experience filter (filters.py).

Run:  python tests/test_filters.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "autoapply"))

from autoapply.filters import exp_display, filter_by_exp, parse_exp_range  # noqa: E402


def _job(**kw) -> dict:
    base = {
        "id": "x", "title": "Software Engineer", "company": "Acme",
        "location": "remote", "url": "https://example.com/job",
        "source": "test", "description": "", "salary": "", "tags": "",
    }
    base.update(kw)
    return base


def test_parse_explicit_range():
    assert parse_exp_range(_job(title="Senior Engineer (5-8 yrs)")) == (5, 8)
    assert parse_exp_range(_job(title="Engineer - 3 to 5 years")) == (3, 5)
    assert parse_exp_range(_job(title="Engineer (2–4 yrs)")) == (2, 4)


def test_parse_plus_and_minimum():
    assert parse_exp_range(_job(description="We need 3+ years of experience.")) == (3, None)
    assert parse_exp_range(_job(description="Minimum 5 years experience required.")) == (5, None)
    assert parse_exp_range(_job(description="At least 2 years of work experience")) == (2, None)


def test_parse_absolute_years():
    assert parse_exp_range(_job(description="5 years of professional experience")) == (5, 5)
    assert parse_exp_range(_job(description="requires 7 yrs experience")) == (7, 7)


def test_parse_seniority_fallback():
    assert parse_exp_range(_job(title="Senior Backend Engineer")) == (3, None)
    assert parse_exp_range(_job(title="Lead Frontend Engineer")) == (3, None)
    assert parse_exp_range(_job(title="Junior Developer")) == (None, 2)
    assert parse_exp_range(_job(title="Software Engineer Intern")) == (None, 2)


def test_parse_unknown():
    assert parse_exp_range(_job(title="Backend Engineer")) == (None, None)
    assert parse_exp_range(_job(title="Engineer", description="no experience info here")) == (None, None)


def test_seniority_field_used():
    job = _job(title="Engineer", seniority="Senior")
    assert parse_exp_range(job) == (3, None)


def test_exp_display():
    assert exp_display(_job(title="Senior Engineer (5-8 yrs)")) == "5-8 yrs"
    assert exp_display(_job(description="3+ years of experience")) == "3+ yrs"
    assert exp_display(_job(title="Junior Developer")) == "≤2 yrs"
    assert exp_display(_job(title="Backend Engineer")) == ""


def test_filter_by_exp_attaches_metadata():
    jobs = [_job(id="a", title="Senior Engineer (5-8 yrs)")]
    out = filter_by_exp(jobs, None, None)
    assert out[0]["exp_range"] == [5, 8]
    assert out[0]["exp_display"] == "5-8 yrs"


def test_filter_by_exp_min():
    jobs = [
        _job(id="a", title="Senior Engineer (5-8 yrs)"),
        _job(id="b", title="Junior Developer"),
        _job(id="c", title="Backend Engineer"),
        _job(id="d", title="Unknown Co", description="no info"),
    ]
    ids = [j["id"] for j in filter_by_exp(jobs, exp_min=3, exp_max=10)]
    assert "a" in ids and "c" in ids and "d" in ids      # senior + unknown kept
    assert "b" not in ids                                 # junior tops out at 2 < 3


def test_filter_by_exp_max():
    jobs = [
        _job(id="a", title="Senior Engineer (5-8 yrs)"),
        _job(id="b", title="Junior Developer"),
        _job(id="d", title="Unknown Co", description="no info"),
    ]
    ids = [j["id"] for j in filter_by_exp(jobs, exp_max=2)]
    assert ids == ["b", "d"]                              # junior + unknown only


def test_filter_no_criteria_keeps_all():
    jobs = [_job(id="a", title="Senior Engineer (5-8 yrs)"),
            _job(id="b", title="Backend Engineer")]
    assert len(filter_by_exp(jobs, None, None)) == 2


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
