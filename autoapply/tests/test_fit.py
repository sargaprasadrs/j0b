"""Offline tests for the fit evaluation framework (fit.py).

Covers the language gate (hard fail / flag / pass), deal-breaker vetoes and
the structured scoring dimensions.

Run:  python tests/test_fit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoapply.fit import (deal_breaker_hits, evaluate, language_gate,
                           parse_languages)


def _job(**kw) -> dict:
    base = {
        "id": "x", "title": "Software Engineer", "company": "Acme",
        "location": "remote", "url": "https://example.com/job",
        "source": "test", "description": "python react", "salary": "", "tags": "",
    }
    base.update(kw)
    return base


def test_parse_languages():
    assert parse_languages(["english: fluent", "hindi (native)"]) == [
        {"name": "english", "level": "fluent"},
        {"name": "hindi", "level": "native"},
    ]
    assert parse_languages([]) == []
    assert parse_languages(["german - b2"]) == [{"name": "german", "level": "b2"}]


def test_language_gate_skipped_when_no_profile():
    gate = language_gate(_job(), [])
    assert gate["verdict"] == "pass"


def test_language_gate_fail_undeclared():
    gate = language_gate(_job(description="We require fluent German and English."),
                         [{"name": "english", "level": "fluent"}])
    assert gate["verdict"] == "fail"
    assert "german" in gate["note"]


def test_language_gate_pass_declared_at_level():
    gate = language_gate(_job(description="Fluent English required."),
                         [{"name": "english", "level": "fluent"}])
    assert gate["verdict"] == "pass"


def test_language_gate_flag_higher_bar():
    gate = language_gate(_job(description="Native English speaker required."),
                         [{"name": "english", "level": "b2"}])
    assert gate["verdict"] == "flag"


def test_language_gate_must_communicate_pattern():
    gate = language_gate(_job(description="You must communicate in Spanish with the team."),
                         [{"name": "english", "level": "fluent"}])
    assert gate["verdict"] == "fail"
    assert "spanish" in gate["note"]


def test_deal_breaker_hits():
    job = _job(description="We offer great pay. On-call rotation every 4th weekend.")
    hits = deal_breaker_hits(job, ["on-call", "requires relocation"])
    assert hits == ["on-call"]
    assert deal_breaker_hits(job, []) == []
    assert deal_breaker_hits(_job(description="no mention"), ["on-call"]) == []


def test_evaluate_veto_on_dealbreaker():
    job = _job(description="Requires relocation to Berlin.")
    res = evaluate(job, ["python"], {"deal_breakers": ["requires relocation"],
                                     "languages": [{"name": "english", "level": "fluent"}]})
    assert res["veto"] and "requires relocation" in res["veto"]


def test_evaluate_veto_on_language():
    job = _job(description="Fluent Japanese required.")
    res = evaluate(job, ["python"], {"languages": [{"name": "english", "level": "fluent"}]})
    assert res["veto"] and "japanese" in res["veto"]


def test_evaluate_dimensions_and_verdict():
    job = _job(title="Senior Full-Stack Engineer",
               description="python react node postgres typescript docker")
    cand = {"skills": ["python", "react", "node", "postgres"],
            "years_of_exp": 6, "roles": ["full-stack engineer"],
            "languages": [{"name": "english", "level": "fluent"}],
            "preferred_locations": ["remote"]}
    res = evaluate(job, ["python", "react", "node", "postgres"], cand)
    dims = res["dimensions"]
    assert dims["technical"] >= 80
    assert dims["experience"] >= 80          # senior + 6 years
    assert dims["alignment"] >= 80           # target role in title
    assert res["overall"] >= 75              # Strong Fit
    assert res["verdict"] == "Strong Fit"
    assert res["veto"] is None
    assert res["language"]["verdict"] == "pass"


def test_evaluate_poor_fit():
    job = _job(title="Junior Tester", description="manual qa spreadsheet")
    cand = {"skills": ["python", "react"], "years_of_exp": 6,
            "roles": ["ai engineer"], "preferred_locations": ["remote"]}
    res = evaluate(job, ["python", "react"], cand)
    assert res["overall"] < 60
    assert res["verdict"] != "Strong Fit"


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
