"""Offline tests for LaTeX CV generation (cv.py).

Checks the .tex sources render correctly with escaped content; compilation is
only attempted when a LaTeX engine is present (skips otherwise).

Run:  python tests/test_cv.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoapply.cv import (CV_TEX, COVER_TEX, _tex_escape, latex_available,
                          build_documents)


def test_tex_escape():
    assert _tex_escape("") == ""
    assert "\\%" in _tex_escape("100% match")
    assert "\\_" in _tex_escape("a_b")
    assert "\\&" in _tex_escape("R&D")
    assert "\\{" in _tex_escape("{x}")


def test_tex_escape_single_pass_no_corruption():
    # backslash / caret / tilde insert LaTeX commands with braces; those braces
    # must NOT be re-escaped (the old two-pass escape corrupted them)
    out = _tex_escape(r"C:\path\file and ^caret and ~tilde")
    assert "\\textbackslash{}" in out
    assert "\\textasciicircum{}" in out
    assert "\\textasciitilde{}" in out
    assert "\\textbackslash\\{" not in out   # corruption pattern
    assert "\\textasciicircum\\{" not in out


def test_templates_have_placeholders():
    for token in ("%FIRST%", "%LAST%", "%EMAIL%", "%PROFILE%", "%SKILLS%"):
        assert token in CV_TEX
    for token in ("%FIRST%", "%LAST%", "%COMPANY%", "%COVER_BODY%"):
        assert token in COVER_TEX


def test_build_documents_writes_sources():
    cfg = {
        "candidate": {
            "name": "Sarga Prasad RS", "email": "s@x.com",
            "headline": "Full-stack developer", "summary": "I build web apps.",
            "skills": ["python", "react"], "years_of_exp": 4,
            "roles": ["full-stack engineer"], "languages": ["english: fluent"],
        },
        "ollama": {"base_url": "http://localhost:11434", "model": "deepseek-r1:8b"},
    }
    job = {"id": "j1", "title": "Senior Full-Stack Engineer", "company": "Acme",
           "location": "Remote", "url": "https://x", "source": "test",
           "description": "python react", "salary": "", "tags": ""}
    with tempfile.TemporaryDirectory() as tmp:
        from autoapply import cv as cv_mod
        original = cv_mod.CV_DIR
        try:
            cv_mod.CV_DIR = Path(tmp)
            res = build_documents(cfg, job, use_ai=False)
            assert res["cv_tex"] and Path(res["cv_tex"]).exists()
            assert res["cover_tex"] and Path(res["cover_tex"]).exists()
            cv_tex = Path(res["cv_tex"]).read_text(encoding="utf-8")
            cover_tex = Path(res["cover_tex"]).read_text(encoding="utf-8")
            assert "\\name{Sarga}{Prasad RS}" in cv_tex
            assert "I build web apps" in cv_tex          # profile statement
            assert "\\begin{itemize}" in cv_tex          # competencies
            assert "\\makelettertitle" in cover_tex
            assert "Acme" in cover_tex
            assert "Senior Full-Stack Engineer" in cover_tex  # role on the letter
        finally:
            cv_mod.CV_DIR = original


def test_latex_available_returns_tuple():
    engine, found = latex_available()
    assert isinstance(engine, (str, type(None)))
    assert isinstance(found, list)
    if engine:
        assert engine in ("lualatex", "xelatex", "pdflatex")


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
