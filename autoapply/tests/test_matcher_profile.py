"""Offline tests for candidate-profile-aware matching helpers.

Run:  python tests/test_matcher_profile.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoapply.matcher import _exp_fit, _keyword_score, _location_fit, _salary_fit


def _job(**kw) -> dict:
    base = {
        "id": "x", "title": "Software Engineer", "company": "Acme",
        "location": "remote", "url": "https://example.com/job",
        "source": "test", "description": "python react", "salary": "", "tags": "",
    }
    base.update(kw)
    return base


def test_exp_fit():
    senior = _job(title="Senior Backend Engineer")
    junior = _job(title="Junior Developer")
    plain = _job(title="Backend Engineer")
    assert _exp_fit(senior, 6) == 1.0          # senior + experienced
    assert _exp_fit(senior, 1) == 0.6          # senior + too junior
    assert _exp_fit(junior, 8) == 0.6          # junior + overqualified
    assert _exp_fit(junior, 2) == 1.0
    assert _exp_fit(plain, 3) == 1.0
    assert _exp_fit(plain, 1) == 0.85
    assert _exp_fit(plain, None) == 0.85       # unknown years = neutral


def test_location_fit():
    remote_job = _job(location="Remote")
    bang_job = _job(location="Bengaluru, India")
    assert _location_fit(remote_job, ["remote"]) == 1.0
    assert _location_fit(remote_job, ["bangalore"]) == 0.7   # remote job, city pref = neutral-ish
    # wants remote, on-site job -> penalty
    assert _location_fit(_job(location="Mumbai"), ["remote"]) == 0.6
    # city match
    assert _location_fit(bang_job, ["bengaluru", "remote"]) == 1.0
    assert _location_fit(bang_job, ["hyderabad"]) == 0.7
    # no preference = neutral
    assert _location_fit(remote_job, []) == 1.0
    assert _location_fit(remote_job, None) == 1.0


def test_salary_fit():
    job_80_100 = _job(salary="80000-100000", salaryMin=80000, salaryMax=100000, salaryCurrency="USD", salaryPeriod="yearly")
    assert _salary_fit(job_80_100, 90_000, None) == 1.0
    assert _salary_fit(job_80_100, None, 70_000) == 0.55    # above desired max
    assert _salary_fit(job_80_100, 120_000, None) == 0.55   # below desired min
    assert _salary_fit(job_80_100, None, None) == 1.0
    assert _salary_fit(_job(salary=""), 90_000, None) == 1.0  # unknown salary = neutral


def test_match_all_fit_integration():
    """match_all attaches the fit rubric, vetoes hard fails and writes vetoed.json."""
    import json
    import tempfile
    from pathlib import Path

    import autoapply.matcher as matcher_mod
    import autoapply.jobs as jobs_mod

    cfg = {
        "candidate": {
            "skills": ["python", "react"], "years_of_exp": 5,
            "roles": ["full-stack engineer"],
            "languages": ["english: fluent"],
            "deal_breakers": ["on-call"],
            "preferred_locations": ["remote"],
        },
        "match": {"mode": "keywords", "min_score": 30},
        "ollama": {"base_url": "http://localhost:11434", "model": "m"},
    }
    jobs = [
        _job(id="good", title="Senior Full-Stack Engineer", location="Remote",
             description="python react node postgres typescript",
             salary="80000-100000"),
        _job(id="lang", title="Backend Engineer", location="Remote",
             description="python. Fluent Japanese required."),
        _job(id="db", title="DevOps Engineer", location="Remote",
             description="terraform kubernetes. On-call rotation."),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        orig_dir, orig_m, orig_v = (matcher_mod.DATA_DIR, matcher_mod.MATCHES_FILE,
                                    matcher_mod.VETOED_FILE)
        orig_jobs_file = jobs_mod.JOBS_FILE
        try:
            matcher_mod.DATA_DIR = tmp_path
            matcher_mod.MATCHES_FILE = tmp_path / "matches.json"
            matcher_mod.VETOED_FILE = tmp_path / "vetoed.json"
            jobs_mod.JOBS_FILE = tmp_path / "jobs.json"  # load_jobs reads this
            kept = matcher_mod.match_all(cfg)
        finally:
            matcher_mod.DATA_DIR, matcher_mod.MATCHES_FILE, matcher_mod.VETOED_FILE = (
                orig_dir, orig_m, orig_v)
            jobs_mod.JOBS_FILE = orig_jobs_file

        ids = [j["id"] for j in kept]
        assert "good" in ids
        assert "lang" not in ids and "db" not in ids      # vetoed out
        good = next(j for j in kept if j["id"] == "good")
        assert good["veto"] is None
        assert good["verdict"] in ("Strong Fit", "Good Fit")
        assert good["match_score"] >= 55
        assert "fit" in good and "dimensions" in good["fit"]

        vetoed = json.loads((tmp_path / "vetoed.json").read_text(encoding="utf-8"))
        reasons = " ".join(v["reason"] for v in vetoed)
        assert "japanese" in reasons.lower()
        assert "on-call" in reasons


def test_keyword_score_uses_profile():
    cand = {"years_of_exp": 6, "preferred_locations": ["remote"],
            "desired_salary_min": 50_000}
    good = _job(title="Senior Full-Stack Engineer", location="Remote",
                description="python react node postgres", salary="80000-100000")
    bad_loc = _job(title="Senior Full-Stack Engineer", location="Mumbai, India",
                   description="python react node postgres", salary="80000-100000")
    s_good = _keyword_score(good, ["python", "react"], cand)
    s_bad = _keyword_score(bad_loc, ["python", "react"], cand)
    assert s_good > s_bad            # remote preference honoured
    assert 0 <= s_good <= 100 and 0 <= s_bad <= 100
    # neutral profile does not hurt score
    s_neutral = _keyword_score(good, ["python", "react"], {})
    assert s_neutral >= s_bad


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
