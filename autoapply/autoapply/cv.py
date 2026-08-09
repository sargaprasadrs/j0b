"""LaTeX CV + cover letter generation with PDF compile & verify.

Ported from ai-job-search (``cv/main_example.tex`` = moderncv banking style,
``cover_letters/cover.cls`` = custom letter class). Two deliberate changes:

* The cover letter uses **moderncv's built-in letter support** instead of the
  repo's ``cover.cls`` -- that class needs bundled Lato/Raleway fonts and
  ``fontspec`` (xelatex-only). moderncv letters compile anywhere moderncv does,
  with no extra assets, so the whole pipeline runs on a stock LaTeX install.
* Page-count verification uses **pypdf** (already a j0b dependency) instead of
  ``pdftotext``.

Engine order: ``lualatex`` (the reference engine for moderncv; pdflatex often
fails on modern MiKTeX with fontawesome5 font-expansion errors), then
``xelatex``, then ``pdflatex``.

If no LaTeX engine is installed the module degrades gracefully: it still
writes the .tex sources and returns setup instructions.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .config import DATA_DIR, ensure_data_dir

CV_DIR = DATA_DIR / "cv"

CV_TEX = r"""%% j0b CV -- moderncv banking (ported from ai-job-search)
\documentclass[11pt,a4paper,sans]{moderncv}
\moderncvstyle{banking}
\moderncvcolor{blue}
\renewcommand*{\firstnamestyle}[1]{{\fontsize{34}{36}\bfseries\upshape\color{color1}#1}}
\renewcommand*{\lastnamestyle}[1]{{\fontsize{34}{36}\bfseries\upshape\color{color1}#1}}
\renewcommand*{\sectionstyle}[1]{{\sectionfont\color{color1}#1}}
\usepackage[utf8]{inputenc}
\usepackage[scale=0.80]{geometry}
\usepackage{hyperref}
\hypersetup{colorlinks=true, linkcolor=blue, urlcolor=blue,
            pdftitle={%NAME% - CV}}

% personal data
\name{%FIRST%}{%LAST%}
\email{%EMAIL%}
\phone[mobile]{%PHONE%}
\extrainfo{%EXTRA%}

\begin{document}

\makecvtitle

\vspace{6pt}
\small{%PROFILE%}

\section{Core Competencies}
\vspace{1pt}
\begin{itemize}
%SKILLS%
\end{itemize}

\section{Professional Experience}
\vspace{3pt}
\begin{itemize}
\item{\cventry{%YEARS%}{%ROLE%}{%COMPANY%}{}{}{%EXPERIENCE%}}
\end{itemize}

%EDUCATION%

\section{Languages}
\vspace{1pt}
\begin{itemize}
\item %LANGUAGES%.
\end{itemize}

\section{References}
\vspace{1pt}
\begin{itemize}
\item Available upon request.
\end{itemize}

\end{document}
"""

COVER_TEX = r"""%% j0b cover letter -- moderncv letter (ported from ai-job-search)
\documentclass[11pt,a4paper,sans]{moderncv}
\moderncvstyle{banking}
\moderncvcolor{blue}
\name{%FIRST%}{%LAST%}
\email{%EMAIL%}
\phone[mobile]{%PHONE%}

\begin{document}

\recipient{%COMPANY%}{%COMPANY_ADDRESS%}
\date{\today}
\opening{Dear Hiring Team,}
\closing{Kind regards,}

\makelettertitle

%COVER_BODY%

\makeletterclosing

\end{document}
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}


def _tex_escape(text: str) -> str:
    """Escape a plain-text value for safe inclusion in a LaTeX document.

    Single-pass substitution: the inserted LaTeX commands (e.g. the braces in
    ``\textbackslash{}``) are never re-scanned, so input containing backslashes,
    carets or tildes cannot corrupt the escaping.
    """
    if not text:
        return ""
    text = re.sub(r"\n\s*\n", "\n\n", text.strip())  # keep blank-line breaks
    return re.sub(r"[\\{}$&#%_^~]",
                  lambda m: _TEX_SPECIALS[m.group(0)], text)


def _split_name(name: str) -> tuple[str, str]:
    parts = (name or "").strip().split()
    if not parts:
        return "Your", "Name"
    return parts[0], " ".join(parts[1:]) or ""


def _skills_items(skills: list[str]) -> str:
    if not skills:
        return r"\item \textbf{Development}: general software development."
    groups = [skills[i:i + 8] for i in range(0, len(skills), 8)]
    out = []
    for i, group in enumerate(groups, 1):
        out.append(r"\item \textbf{Skill Group " + str(i) + "}: "
                   + ", ".join(_tex_escape(s) for s in group) + ".")
    return "\n".join(out)


def _languages_line(languages: list) -> str:
    if not languages:
        return "English (professional)"
    parts = []
    for lang in languages:
        text = str(lang or "").strip()
        if text:
            parts.append(_tex_escape(text))
    return ", ".join(parts) if parts else "English (professional)"


def latex_available() -> tuple[str | None, list[str]]:
    """Return (engine, found_engines). Engine: lualatex > xelatex > pdflatex."""
    found = []
    for engine in ("lualatex", "xelatex", "pdflatex"):
        if shutil.which(engine):
            found.append(engine)
    return (found[0] if found else None), found


def _ollama_or_none(cfg: dict, system: str, prompt: str) -> str | None:
    from .tailor import _ollama
    oll = cfg.get("ollama", {})
    base = oll.get("base_url", "http://localhost:11434")
    model = oll.get("model", "deepseek-r1:8b")
    return _ollama(base, model, system, prompt, timeout=120)


def _cv_content(cfg: dict, job: dict, resume_text: str, use_ai: bool) -> dict:
    """Tailored profile statement + experience bullets (honest, from sources)."""
    cand = cfg.get("candidate", {})
    name = cand.get("name", "") or "[NAME]"
    summary = cand.get("summary", "") or ""
    skills = cand.get("skills", []) or []
    years = cand.get("years_of_exp", "")
    system = (
        "You write CV content for a job application. HONESTY RULE: you may only "
        "use facts from the candidate profile and resume text provided. Never "
        "invent skills, titles, employers or numbers. Plain text, no markdown."
    )
    job_blurb = (f"Target job: {job['title']} at {job['company']}.\n"
                 f"Description: {job['description'][:1200]}")
    profile = summary
    experience = ""
    if use_ai:
        if not summary:
            got = _ollama_or_none(
                cfg, system,
                f"Write a 3-4 line professional profile statement for this "
                f"candidate based ONLY on: resume text:\n{resume_text[:2000]}\n"
                f"{job_blurb}")
            if got:
                profile = got.strip().replace("\n", " ")
        got = _ollama_or_none(
            cfg, system,
            f"Write 3-5 concise CV achievement bullets for this candidate "
            f"tailored to the target job, based ONLY on the resume text and "
            f"summary. One bullet per line, each starting with '- '. "
            f"Resume text:\n{resume_text[:3000]}\nSummary: {summary}\n{job_blurb}")
        if got:
            experience = got.strip()
    if not experience:
        exp_lines = []
        if summary:
            exp_lines.append(f"- {summary}")
        exp_lines.append(f"- Hands-on skills: {', '.join(skills[:10]) or 'development'}")
        if years:
            exp_lines.append(f"- {years}+ years of experience in {', '.join((cand.get('roles') or [])[:2]) or 'software engineering'}")
        experience = "\n".join(exp_lines)
    if not profile:
        profile = (f"{name} - {cand.get('headline', 'a developer')} with "
                   f"{', '.join(skills[:6]) or 'software development'} experience.")
    return {"profile": profile, "experience": experience, "name": name}


def _render_files(cfg: dict, job: dict, resume_text: str, use_ai: bool,
                  out_dir: Path) -> dict:
    cand = cfg.get("candidate", {})
    content = _cv_content(cfg, job, resume_text, use_ai)
    first, last = _split_name(cand.get("name", ""))
    email = cand.get("email", "") or "your@email.com"
    phone = cand.get("phone", "") or ""
    extra = ", ".join(x for x in [cand.get("linkedin", ""), cand.get("github", "")]
                      if x)
    education = cand.get("education", "") or ""

    # experience bullets -> LaTeX itemize (like the reference template)
    exp_lines = [l.strip() for l in content["experience"].splitlines() if l.strip()]
    if exp_lines:
        items = "\n".join(r"\item " + _tex_escape(l.lstrip("- ").strip())
                           for l in exp_lines)
        exp_tex = ("\\vspace{1pt}\n\\begin{itemize}\n" + items
                   + "\n\\end{itemize}")
    else:
        exp_tex = ""

    cv = (CV_TEX.replace("%NAME%", _tex_escape(first + " " + last))
          .replace("%FIRST%", _tex_escape(first))
          .replace("%LAST%", _tex_escape(last))
          .replace("%EMAIL%", _tex_escape(email))
          .replace("%PHONE%", _tex_escape(phone))
          .replace("%EXTRA%", _tex_escape(extra))
          .replace("%PROFILE%", _tex_escape(content["profile"]))
          .replace("%SKILLS%", _skills_items(cand.get("skills", []) or []))
          .replace("%YEARS%", _tex_escape(str(cand.get("years_of_exp", "") or "")))
          .replace("%ROLE%", _tex_escape((cand.get("roles") or [""])[0] or "Professional"))
          .replace("%COMPANY%", _tex_escape("Experience"))
          .replace("%EXPERIENCE%", exp_tex)
          .replace("%LANGUAGES%", _languages_line(cand.get("languages", []))))

    if education:
        edu = (r"\section{Education}\vspace{1pt}\begin{itemize}\item "
               + _tex_escape(education) + r"\end{itemize}")
    else:
        edu = r"% \section{Education} (add candidate.education to your profile)"

    # cover letter body: reuse the tailored cover letter when present
    body = _cover_body(cfg, job)
    cover = (COVER_TEX.replace("%FIRST%", _tex_escape(first))
             .replace("%LAST%", _tex_escape(last))
             .replace("%EMAIL%", _tex_escape(email))
             .replace("%PHONE%", _tex_escape(phone))
             .replace("%COMPANY%", _tex_escape(job.get("company", "")))
             .replace("%COMPANY_ADDRESS%", _tex_escape(job.get("location", "")))
             .replace("%COVER_BODY%", body))

    cv = cv.replace("%EDUCATION%", edu)
    (out_dir / "cv.tex").write_text(cv, encoding="utf-8")
    (out_dir / "cover.tex").write_text(cover, encoding="utf-8")
    return {"cv_tex": str(out_dir / "cv.tex"), "cover_tex": str(out_dir / "cover.tex"),
            "profile": content["profile"], "experience": content["experience"]}


def _cover_body(cfg: dict, job: dict) -> str:
    """Cover letter paragraphs, from the tailor cache when present.

    Never triggers a fresh AI generation here (that can take minutes): reuses
    the tailored letter the user already generated, or falls back to the fast
    template letter. No network calls in this function.
    """
    try:
        from . import tailor as tailor_mod
        cache = tailor_mod._load_cache()
        key = f"{job['id']}:{tailor_mod._slug(job)}"
        cached = cache.get(key) or {}
        text = (cached.get("cover_letter") or "").strip()
        if not text:
            doc = tailor_mod.tailor_job(cfg, job, use_ai=False)  # template, offline
            text = (doc.get("cover_letter") or "").strip()
        if text:
            paras = [p.strip() for p in text.split("\n\n") if p.strip()]
            if not paras:  # single-paragraph fallback
                paras = [text.replace("\n", " ")]
            # strip a leading "Dear ..." line so \opening handles the greeting
            if paras and re.match(r"(?i)^dear\b", paras[0]):
                paras = paras[1:] or paras
            return "\n\n".join("\\lettercontent{" + _tex_escape(p) + "}"
                               for p in paras)
    except Exception:  # noqa: BLE001
        pass
    cand = cfg.get("candidate", {})
    return (f"\\lettercontent{{I'm {_tex_escape(cand.get('name', '[NAME]'))} "
            f"({_tex_escape(cand.get('headline', 'a developer'))}) and I'm "
            f"applying for the {_tex_escape(job.get('title', 'role'))} role.}}\n\n"
            f"\\lettercontent{{{_tex_escape(cand.get('summary', ''))}}}\n\n"
            f"\\lettercontent{{I look forward to hearing from you.}}")


def _compile(engine: str, tex_path: Path, timeout: int = 180) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error",
             tex_path.name],
            cwd=str(tex_path.parent), capture_output=True, text=True,
            timeout=timeout)
        if proc.returncode != 0:
            tail = "\n".join(proc.stdout.splitlines()[-12:])
            return False, tail or proc.stderr[-400:]
        return True, ""
    except FileNotFoundError:
        return False, f"{engine} not found"
    except subprocess.TimeoutExpired:
        return False, f"{engine} timed out after {timeout}s"


def _page_count(pdf_path: Path) -> int | None:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:  # noqa: BLE001
        return None


def build_documents(cfg: dict, job: dict, use_ai: bool = True) -> dict:
    """Generate tailored LaTeX CV + cover letter, compile and verify.

    Returns a dict with paths, page counts and a verdict. Never raises on a
    missing LaTeX install -- it degrades to sources + install instructions.
    """
    ensure_data_dir()
    slug = re.sub(r"[^a-z0-9]+", "-", f"{job.get('company','x')}-{job.get('title','x')}".lower()).strip("-")[:60]
    out_dir = CV_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    resume_text = ""
    rp = cfg.get("candidate", {}).get("resume_path", "")
    if rp:
        try:
            from .resume import parse_resume
            resume_text = parse_resume(rp) or ""
        except Exception:  # noqa: BLE001
            resume_text = ""

    files = _render_files(cfg, job, resume_text, use_ai, out_dir)
    engine, found = latex_available()
    result: dict = {
        "ok": True,
        "engine": engine,
        "latex_installed": engine is not None,
        **files,
        "cv_pdf": None, "cover_pdf": None,
        "cv_pages": None, "cover_pages": None,
        "warnings": [],
    }
    if not engine:
        result["ok"] = False
        result["latex_installed"] = False
        result["warnings"].append(
            "No LaTeX engine found (lualatex/xelatex/pdflatex). Install TeX "
            "Live / MiKTeX / TinyTeX, then re-run to compile. The .tex sources "
            "below are ready to compile.")
        return result

    cv_ok, cv_err = _compile(engine, out_dir / "cv.tex")
    cover_ok, cover_err = _compile(engine, out_dir / "cover.tex")
    for name, ok, err in (("cv", cv_ok, cv_err), ("cover", cover_ok, cover_err)):
        if not ok:
            result["ok"] = False
            result["warnings"].append(f"{name}.tex failed to compile: {err[:300]}")
    cv_pdf, cover_pdf = out_dir / "cv.pdf", out_dir / "cover.pdf"
    if cv_pdf.exists():
        result["cv_pdf"] = str(cv_pdf)
        result["cv_pages"] = _page_count(cv_pdf)
        if result["cv_pages"] and result["cv_pages"] > 2:
            result["warnings"].append(
                f"CV is {result['cv_pages']} pages (target: 2) - trim the "
                "experience bullets or edit cv.tex and recompile.")
    if cover_pdf.exists():
        result["cover_pdf"] = str(cover_pdf)
        result["cover_pages"] = _page_count(cover_pdf)
        if result["cover_pages"] and result["cover_pages"] > 1:
            result["warnings"].append(
                f"Cover letter is {result['cover_pages']} pages (target: 1).")
    return result
