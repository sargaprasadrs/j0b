#!/usr/bin/env python3
"""j0b web UI backend (Flask).

Serves a small UI that drives the autoapply pipeline:
  - candidate profile + resume upload
  - job search with filters (roles, location, salary, startup-only)
  - match scoring, per-job tailoring
  - application tracking

Run:  cd webui && python app.py   ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "autoapply"))

from flask import Flask, jsonify, render_template, request  # noqa: E402

from autoapply.config import load_config, save_config  # noqa: E402
from autoapply import filters as flt                      # noqa: E402
from autoapply import jobs as jobs_mod                    # noqa: E402
from autoapply import matcher as matcher_mod              # noqa: E402
from autoapply import resume as resume_mod                # noqa: E402
from autoapply import tailor as tailor_mod                # noqa: E402

APP_ROOT = Path(__file__).resolve().parent
AUTOAPPLY_ROOT = APP_ROOT.parent / "autoapply"
COLDMAIL_ROOT = APP_ROOT.parent / "coldmail"
CONFIG_PATH = AUTOAPPLY_ROOT / "config.yaml"
RESUME_DIR = AUTOAPPLY_ROOT / "data"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB resume


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
    cand = cfg.get("candidate", {})
    return jsonify({
        "candidate": cand,
        "search": cfg.get("search", {}),
        "sources": cfg.get("sources", {}),
        "ollama": cfg.get("ollama", {}),
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
# search + filters
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

    # enable/disable sources
    src_cfg = cfg.setdefault("sources", {})
    for key in ("remotive", "jobicy"):
        if key in body.get("sources", {}):
            src_cfg.setdefault(key, {})["enabled"] = bool(body["sources"][key])

    save_config(cfg, CONFIG_PATH)
    jobs = jobs_mod.fetch_all(cfg)

    # post-filters
    startup_only = body.get("startup_only", False)
    sal_min = body.get("salary_min")
    sal_max = body.get("salary_max")
    if sal_min:
        sal_min = int(sal_min)
    if sal_max:
        sal_max = int(sal_max)

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
    if not job_id:
        return jsonify({"ok": False, "error": "job_id required"}), 400
    job = None
    for j in (jobs_mod.load_jobs() + matcher_mod.load_matches()):
        if str(j.get("id", "")).startswith(job_id):
            job = j
            break
    if job is None:
        return jsonify({"ok": False, "error": "job not found"}), 404
    doc = tailor_mod.tailor_job(cfg, job, use_ai=use_ai)
    return jsonify({"ok": True, "job": job, "doc": doc})


@app.route("/api/log", methods=["POST"])
def log_status():
    body = request.get_json(force=True, silent=True) or {}
    job = body.get("job") or {}
    status = (body.get("status") or "").strip().lower()
    if status not in ("applied", "skipped", "rejected"):
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


if __name__ == "__main__":
    print("j0b web UI -> http://127.0.0.1:5000")
    # threaded=True so slow Ollama tailoring doesn't block other requests
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
