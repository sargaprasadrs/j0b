#!/usr/bin/env python3
"""j0b — unified job searcher + autoapply (web app, single program).

One local web app that drives everything the three original tools did:

  autoapply  -> fetch jobs, flexible filters (role / years of experience /
                location / salary / startup / sources), match vs resume,
                tailor docs, semi-auto browser apply (pre-fill, YOU submit)
  coldmail   -> cold application emails to companies, saved as Gmail DRAFTS
                in a real browser session (drafts only, never sends)
  webui      -> the AI agent panel (opencode brain + composio Gmail draft)

Run:  python app.py   ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import csv
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "autoapply"))
sys.path.insert(0, str(ROOT / "coldmail"))
sys.path.insert(0, str(ROOT / "webui"))

# Windows consoles default to cp1252; job titles from the feeds contain
# non-ASCII chars and the library logs would crash with UnicodeEncodeError.
# Force UTF-8 with replacement so prints can never 500 a request.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from flask import Flask, jsonify, render_template, request  # noqa: E402

import emailer                                                      # noqa: E402
from agent_backend import backend_from_config                      # noqa: E402

from autoapply.config import load_config, save_config              # noqa: E402
from autoapply import filters as flt                               # noqa: E402
from autoapply import jobs as jobs_mod                             # noqa: E402
from autoapply import matcher as matcher_mod                       # noqa: E402
from autoapply import resume as resume_mod                         # noqa: E402
from autoapply import tailor as tailor_mod                         # noqa: E402

AUTOAPPLY_ROOT = ROOT / "autoapply"
COLDMAIL_ROOT = ROOT / "coldmail"
CONFIG_PATH = ROOT / "config.yaml"
RESUME_DIR = AUTOAPPLY_ROOT / "data"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB resume

# shared, thread-safe agent backend (opencode + composio)
_agent_lock = threading.Lock()
_agent_backend = None


def _agent():
    global _agent_backend
    with _agent_lock:
        if _agent_backend is None:
            _agent_backend = backend_from_config(_cfg())
        return _agent_backend


def _candidate(cfg: dict) -> dict:
    return cfg.get("candidate", {})


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _cfg() -> dict:
    return load_config(CONFIG_PATH)


def _known_startups() -> set[str]:
    """Company names from coldmail's discovery (startup-only filter)."""
    csv_file = COLDMAIL_ROOT / "data" / "startups.csv"
    names: set[str] = set()
    if csv_file.exists():
        with open(csv_file, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("company"):
                    names.add(row["company"].strip())
    return names


def _salary_display(job: dict) -> str:
    rng = flt.parse_salary_range(job)
    if rng:
        lo, hi = rng
        cur = job.get("salaryCurrency") or "USD"
        return f"{cur} {lo:,} - {hi:,} /yr"
    return job.get("salary") or ""


def _find_job(job_id: str) -> dict | None:
    if not job_id:
        return None
    for j in (jobs_mod.load_jobs() + matcher_mod.load_matches()):
        if str(j.get("id", "")).startswith(job_id):
            return j
    return None


def _prefill_apply(job: dict) -> None:
    """Open the job page in a real browser, pre-fill profile fields, then
    stay open so the human reviews and submits. Never clicks submit."""
    from playwright.sync_api import sync_playwright
    from autoapply.apply_agent import _prefill_common_fields
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False,
                                        viewport={"width": 1280, "height": 900})
            page = browser.new_page()
            try:
                page.goto(job["url"],
                          timeout=_cfg().get("apply", {}).get("page_timeout", 45) * 1000,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                n = _prefill_common_fields(page, _cfg())
                print(f"[apply] pre-filled {n} field(s) for {job['company']} — "
                      "browser stays open for your review")
                while not page.is_closed():
                    page.wait_for_timeout(1000)
            except Exception as exc:  # noqa: BLE001
                print(f"[apply] browser error for {job['company']}: {exc}")
                time.sleep(6)
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        print(f"[apply] launch failed for {job['company']}: {exc}")


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# --------------------------------------------------------------------------
# config + resume
# --------------------------------------------------------------------------
@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = _cfg()
    return jsonify({
        "candidate": cfg.get("candidate", {}),
        "search": cfg.get("search", {}),
        "sources": cfg.get("sources", {}),
        "ollama": cfg.get("ollama", {}),
        "agent": cfg.get("agent", {}),
    })


@app.route("/api/config", methods=["POST"])
def post_config():
    cfg = _cfg()
    body = request.get_json(force=True, silent=True) or {}
    if "candidate" in body:
        cfg.setdefault("candidate", {}).update(body["candidate"])
    if "search" in body:
        cfg.setdefault("search", {}).update(body["search"])
    save_config(cfg, CONFIG_PATH)
    return jsonify({"ok": True})


@app.route("/api/resume", methods=["POST"])
def upload_resume():
    cfg = _cfg()
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "no file field"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "empty file"}), 400
    suffix = Path(f.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        return jsonify({"ok": False,
                        "error": "resume must be PDF/DOCX/TXT/MD"}), 400
    RESUME_DIR.mkdir(exist_ok=True)
    dest = RESUME_DIR / f"resume{suffix}"
    f.save(dest)
    cfg.setdefault("candidate", {})["resume_path"] = str(dest)
    save_config(cfg, CONFIG_PATH)
    text = resume_mod.parse_resume(dest)
    skills = resume_mod.extract_skills(text) if text else []
    email = resume_mod.extract_email(text)
    if email and not cfg["candidate"].get("email"):
        cfg["candidate"]["email"] = email
        save_config(cfg, CONFIG_PATH)
    return jsonify({
        "ok": True, "path": str(dest),
        "text_len": len(text), "skills": skills, "email_found": email,
    })


@app.route("/api/resume", methods=["GET"])
def resume_info():
    cfg = _cfg()
    path = cfg.get("candidate", {}).get("resume_path", "")
    text = resume_mod.parse_resume(path) if path else ""
    return jsonify({
        "path": path or "",
        "has_resume": bool(text),
        "text_preview": text[:800] if text else "",
        "skills": resume_mod.extract_skills(text) if text else [],
    })


# --------------------------------------------------------------------------
# search + filters (role / years of exp / location / salary / startup)
# --------------------------------------------------------------------------
@app.route("/api/search", methods=["POST"])
def search():
    cfg = _cfg()
    body = request.get_json(force=True, silent=True) or {}
    search_cfg = cfg.setdefault("search", {})

    if "keywords" in body:
        search_cfg["keywords"] = body["keywords"] or []
    if "limit" in body and body["limit"]:
        search_cfg["limit"] = int(body["limit"])
    if "locations" in body:
        search_cfg["locations"] = body["locations"] or []
    # years-of-experience filter (flexible); malformed input degrades to None
    for key in ("exp_min", "exp_max"):
        if key in body:
            val = body[key]
            if val in (None, ""):
                search_cfg[key] = None
                continue
            try:
                n = int(val)
                search_cfg[key] = n if n > 0 else None
            except (TypeError, ValueError):
                search_cfg[key] = None

    # enable/disable sources
    src_cfg = cfg.setdefault("sources", {})
    for key in ("remotive", "jobicy", "freehire"):
        if key in body.get("sources", {}):
            src_cfg.setdefault(key, {})["enabled"] = bool(body["sources"][key])

    save_config(cfg, CONFIG_PATH)
    jobs = jobs_mod.fetch_all(cfg)

    # post-filters: salary + startup
    startup_only = body.get("startup_only", False)

    def _as_int(v):
        if v in (None, ""):
            return None
        try:
            n = int(v)
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None

    sal_min = _as_int(body.get("salary_min"))
    sal_max = _as_int(body.get("salary_max"))

    if sal_min or sal_max:
        jobs = flt.filter_by_salary(jobs, sal_min, sal_max)

    known = _known_startups()
    view = []
    for j in jobs:
        startup = flt.is_startup(j["company"], known)
        if startup_only and not startup:
            continue
        view.append({
            **j,
            "salary_display": _salary_display(j),
            "exp_display": j.get("exp_display", ""),
            "startup": startup,
        })
    view.sort(key=lambda j: (not j["startup"], j["company"].lower()))
    return jsonify({"ok": True, "count": len(view), "jobs": view})


@app.route("/api/matches", methods=["GET"])
def matches():
    return jsonify({"ok": True, "matches": matcher_mod.load_matches()})


@app.route("/api/match", methods=["POST"])
def run_match():
    cfg = _cfg()
    mode = (request.get_json(force=True, silent=True) or {}).get("mode", "keywords")
    cfg.setdefault("match", {})["mode"] = mode
    save_config(cfg, CONFIG_PATH)
    matches = matcher_mod.match_all(cfg)
    return jsonify({"ok": True, "count": len(matches), "matches": matches})


# --------------------------------------------------------------------------
# tailoring + apply tracking
# --------------------------------------------------------------------------
@app.route("/api/tailor", methods=["POST"])
def tailor_one():
    cfg = _cfg()
    body = request.get_json(force=True, silent=True) or {}
    job_id = body.get("job_id", "")
    use_ai = bool(body.get("use_ai", True))
    job = _find_job(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    doc = tailor_mod.tailor_job(cfg, job, use_ai=use_ai)
    return jsonify({"ok": True, "job": job, "doc": doc})


@app.route("/api/log", methods=["POST"])
def log_status():
    body = request.get_json(force=True, silent=True) or {}
    job = body.get("job") or {}
    status = (body.get("status") or "").strip().lower()
    # tracker vocabulary extended for the funnel: drafted -> applied ->
    # interview -> offer -> hired, plus rejected/withdrawn/no_response
    if status not in ("drafted", "applied", "interview", "offer", "hired",
                      "rejected", "withdrawn", "no_response", "skipped"):
        return jsonify({"ok": False, "error": "bad status"}), 400
    from autoapply.apply_agent import _record
    _record(job, status)
    return jsonify({"ok": True})


@app.route("/api/status", methods=["GET"])
def status_log():
    log_file = AUTOAPPLY_ROOT / "data" / "applied.csv"
    rows = []
    if log_file.exists():
        with open(log_file, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    return jsonify({"ok": True, "rows": rows})


# --------------------------------------------------------------------------
# cold email -> Gmail draft (coldmail pipeline)
# --------------------------------------------------------------------------
@app.route("/api/email", methods=["POST"])
def cold_email():
    body = request.get_json(force=True, silent=True) or {}
    job = _find_job(body.get("job_id", ""))
    if job is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    result = emailer.generate_cold_email(
        _cfg(), job, use_ai=bool(body.get("use_ai", True)),
        resolve=bool(body.get("resolve", True)))
    if not result.get("ok"):
        return jsonify(result), 502
    return jsonify(result)


@app.route("/api/email/draft", methods=["POST"])
def cold_email_draft():
    """Create a Gmail DRAFT via the real browser session (never sends)."""
    body = request.get_json(force=True, silent=True) or {}
    to = (body.get("to") or "").strip()
    subject = (body.get("subject") or "").strip()
    text = (body.get("body") or "").strip()
    company = (body.get("company") or "").strip()
    if not (to and subject and text and company):
        return jsonify({"ok": False,
                        "error": "to, subject, body and company required"}), 400
    job = _find_job(body.get("job_id", ""))
    result = emailer.draft_emails_browser(_cfg(), [{
        "to": to, "subject": subject, "body": text, "company": company,
    }])
    if result.get("ok") and result.get("drafted") and job is not None:
        from autoapply.apply_agent import _record
        _record(job, "drafted")
    return jsonify(result)


@app.route("/api/email/gmail-login", methods=["POST"])
def cold_email_gmail_login():
    """One-time interactive Gmail login (persistent browser session)."""
    threading.Thread(target=emailer.gmail_login, daemon=True).start()
    return jsonify({"ok": True,
                    "msg": "Gmail login window opened — log in once; "
                           "the session persists for future drafts."})


# --------------------------------------------------------------------------
# semi-auto browser apply (pre-fill, YOU submit)
# --------------------------------------------------------------------------
@app.route("/api/apply/prefill", methods=["POST"])
def apply_prefill():
    body = request.get_json(force=True, silent=True) or {}
    job = _find_job(body.get("job_id", ""))
    if job is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    threading.Thread(target=_prefill_apply, args=(job,), daemon=True).start()
    return jsonify({
        "ok": True,
        "msg": f"Browser opened for {job['company']} — review the pre-filled "
               "form and submit it yourself, then log the outcome below.",
    })


# --------------------------------------------------------------------------
# AI agent backend (opencode brain + composio tools)
# --------------------------------------------------------------------------
@app.route("/api/agent/status", methods=["GET"])
def agent_status():
    return jsonify({"ok": True, "status": _agent().status()})


@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    body = request.get_json(force=True, silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "message required"}), 400
    result = _agent().chat(
        message=message,
        job=_find_job(body.get("job_id", "")),
        candidate=_candidate(_cfg()),
    )
    code = 200 if result.get("ok") else 502
    return jsonify({"ok": result.get("ok"), **result}), code


@app.route("/api/agent/interview", methods=["POST"])
def agent_interview():
    body = request.get_json(force=True, silent=True) or {}
    mode = (body.get("mode") or "prep").strip()
    if mode not in ("prep", "mock"):
        mode = "prep"
    result = _agent().interview_prep(
        job=_find_job(body.get("job_id", "")),
        candidate=_candidate(_cfg()),
        mode=mode,
        stage=(body.get("stage") or "").strip(),
    )
    code = 200 if result.get("ok") else 502
    return jsonify({"ok": result.get("ok"), **result}), code


@app.route("/api/report", methods=["POST"])
def report_dashboard():
    from autoapply.report import generate_report
    res = generate_report()
    return jsonify({"ok": True, "path": res["path"], "stats": res["stats"]})


@app.route("/tracker-report.html", methods=["GET"])
def tracker_report_page():
    """Serve the generated self-contained dashboard (autoapply/data/report.html)."""
    from flask import send_from_directory
    return send_from_directory(AUTOAPPLY_ROOT / "data", "report.html")


@app.route("/api/cv", methods=["POST"])
def make_cv():
    cfg = _cfg()
    body = request.get_json(force=True, silent=True) or {}
    job = _find_job(body.get("job_id", ""))
    if job is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    from autoapply.cv import build_documents
    res = build_documents(cfg, job, use_ai=bool(body.get("use_ai", True)))
    out = {"ok": res.get("ok", True), **res}
    code = 200 if out["ok"] else 502
    return jsonify(out), code


@app.route("/cv/<path:rel>", methods=["GET"])
def cv_file(rel):
    """Serve generated CV/cover PDFs + .tex sources (autoapply/data/cv)."""
    from flask import send_from_directory
    root = AUTOAPPLY_ROOT / "data" / "cv"
    return send_from_directory(root, rel)


@app.route("/api/agent/compose", methods=["POST"])
def agent_compose():
    body = request.get_json(force=True, silent=True) or {}
    result = _agent().compose_draft(
        job=_find_job(body.get("job_id", "")),
        candidate=_candidate(_cfg()),
        kind=(body.get("kind") or "followup"),
    )
    code = 200 if result.get("ok") else 502
    return jsonify({"ok": result.get("ok"), **result}), code


@app.route("/api/agent/draft", methods=["POST"])
def agent_draft():
    body = request.get_json(force=True, silent=True) or {}
    to = (body.get("to") or "").strip()
    subject = (body.get("subject") or "").strip()
    text = (body.get("body") or "").strip()
    if not (to and subject and text):
        return jsonify({"ok": False, "error": "to, subject and body required"}), 400
    return jsonify(_agent().draft_to_gmail(to=to, subject=subject, body=text))


@app.route("/api/agent/connect", methods=["POST"])
def agent_connect():
    body = request.get_json(force=True, silent=True) or {}
    app_name = (body.get("app") or "gmail").lower()
    return jsonify({
        "ok": True,
        "app": app_name,
        "instructions": _agent().composio.connect_instructions(app_name),
    })


if __name__ == "__main__":
    print("j0b unified job searcher + autoapply -> http://127.0.0.1:5000")
    # threaded=True so slow Ollama tailoring / drafts don't block requests
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
