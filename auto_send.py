"""auto_send.py — fully-automated daily job-application DRAFTER.

Run every day (see run_daily.bat / install_scheduler.bat). Pipeline:

    fetch jobs -> score matches -> dedupe vs drafted.csv + applied.csv
    + vetoed.json -> resolve recipient emails (parallel) -> personalize email
    -> create a Gmail DRAFT via the Gmail API -> record in data/sent_emails.csv

DRAFTS ONLY. This script never sends email — every application lands in your
Gmail Drafts folder and you hit Send yourself. One-time setup (5 min):
    python gmail_setup.py   (see gmail_drafts.py for the Google Cloud steps)

Dedup criteria (so the same person is never contacted twice):
  * recipient email address  - never drafted to twice (exact match, normalized)
  * company                  - not re-contacted within company_cooldown_days
  * job id                   - the same posting is never re-drafted
  * applied.csv              - companies already applied to are skipped
  * vetoed.json              - language-gate / deal-breaker vetoes are skipped

Usage:
    python auto_send.py                # real run (creates Gmail drafts)
    python auto_send.py --dry-run      # plan only, nothing created
    python auto_send.py --limit 20     # cap the number drafted in this run
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "coldmail"))
sys.path.insert(0, str(ROOT / "autoapply"))

from autoapply.config import load_config            # noqa: E402
from autoapply.jobs import fetch_all                # noqa: E402
from autoapply.matcher import match_all             # noqa: E402
from autoapply.config import DATA_DIR as AA_DATA    # noqa: E402
from autoapply.filters import parse_exp_range, SENIOR_WORDS  # noqa: E402
from emailer import quick_recipient, generate_cold_email  # noqa: E402
from gmail_drafts import ensure_token, create_draft, gmail_account  # noqa: E402

DATA_DIR = ROOT / "data"
SENT_FILE = DATA_DIR / "sent_emails.csv"
LOG_FILE = DATA_DIR / "auto_send.log"

SENT_FIELDS = ["date", "company", "recipient", "job_id", "title", "url",
               "subject", "recipient_source", "status", "error"]


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# dedup helpers (pure, offline — unit-tested)
# ---------------------------------------------------------------------------

def _norm_key(email: str) -> str:
    return (email or "").strip().lower()


def _norm_company(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (company or "").lower())


def _parse_date(value: str) -> dt.date | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(value.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def load_sent(path: Path = SENT_FILE) -> dict:
    """sent_emails.csv -> {recipient: {date, company, job_id, ...}}.

    Only rows with status 'drafted' (or legacy 'sent') count for dedup;
    failed/error attempts are retried once the problem is fixed."""
    out: dict[str, dict] = {}
    if not Path(path).exists():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("status", "").strip().lower() not in ("drafted", "sent"):
                continue
            recipient = _norm_key(row.get("recipient", ""))
            if recipient:
                out[recipient] = row
    return out


def load_applied_companies(path: Path) -> set[str]:
    """applied.csv -> set of company keys with status == 'applied'."""
    out: set[str] = set()
    if not Path(path).exists():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("status", "").strip().lower() == "applied":
                out.add(_norm_company(row.get("company", "")))
    return out


def load_vetoed_companies(path: Path) -> set[str]:
    """vetoed.json -> set of company keys."""
    out: set[str] = set()
    if not Path(path).exists():
        return out
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return out
    for row in data or []:
        out.add(_norm_company(row.get("company", "")))
    return out


def company_last_sent(sent: dict, company: str) -> dt.date | None:
    """Most recent date this company was successfully emailed (by company key
    from the sent ledger rows — recipient addresses may vary)."""
    key = _norm_company(company)
    best: dt.date | None = None
    for row in sent.values():
        if _norm_company(row.get("company", "")) == key:
            d = _parse_date(row.get("date", ""))
            if d and (best is None or d > best):
                best = d
    return best


def filter_plan_candidates(matches: list[dict], cfg: dict, sent: dict,
                           applied: set[str], vetoed: set[str],
                           today: dt.date | None = None) -> tuple[list[dict], list[str]]:
    """Company/job-level dedup (no network). Returns (candidates, reasons)."""
    send = cfg.get("send", {}) or {}
    cooldown = int(send.get("company_cooldown_days", 45) or 45)
    min_score = int(send.get("min_score") or cfg.get("match", {}).get("min_score", 0))
    skip_senior = bool(send.get("skip_senior_roles", True))
    max_exp = int(send.get("max_experience_years", 3) or 99)
    senior_levels = {"senior", "lead", "principal", "staff", "expert", "architect"}
    today = today or dt.date.today()
    out: list[dict] = []
    skipped: list[str] = []
    for job in matches:
        company = (job.get("company") or "").strip()
        ck = _norm_company(company)
        if not ck:
            skipped.append(f"{job.get('title','?')}: no company name")
            continue
        if ck in vetoed:
            skipped.append(f"{company}: vetoed in matches")
            continue
        if ck in applied:
            skipped.append(f"{company}: already applied")
            continue
        # never draft senior/lead roles or postings requiring > max_exp years
        title = (job.get("title") or "").lower()
        if skip_senior and any(w in title for w in SENIOR_WORDS):
            skipped.append(f"{company}: senior/lead role ({job.get('title')})")
            continue
        seniority = (job.get("seniority") or "").strip().lower()
        if skip_senior and seniority in senior_levels:
            skipped.append(f"{company}: seniority '{seniority}'")
            continue
        lo, _hi = parse_exp_range(job)
        if lo is not None and lo > max_exp:
            skipped.append(f"{company}: requires {lo}+ yrs (max {max_exp})")
            continue
        if int(job.get("match_score", 0) or 0) < min_score:
            skipped.append(f"{company}: score {job.get('match_score')} < {min_score}")
            continue
        last = company_last_sent(sent, company)
        if last and (today - last).days < cooldown:
            skipped.append(f"{company}: last emailed {last} (cooldown {cooldown}d)")
            continue
        out.append(job)
    return out, skipped


def finalize_plan(candidates: list[dict], resolved: list[tuple[str, str]],
                  sent: dict, cfg: dict, limit: int) -> tuple[list[dict], list[str]]:
    """Recipient-level dedup + cap. resolved[i] == (recipient, source) for
    candidates[i]. Returns (plan, reasons) — plan items have 'to' + 'src'."""
    send = cfg.get("send", {}) or {}
    allow_guess = bool(send.get("allow_guessed_recipients", True))
    plan: list[dict] = []
    skipped: list[str] = []
    seen_recipients: set[str] = set()
    seen_companies: set[str] = set()
    for job, (to, src) in zip(candidates, resolved):
        if len(plan) >= limit:
            break
        company = job.get("company", "")
        ck = _norm_company(company)
        if not to:
            skipped.append(f"{company}: no recipient found")
            continue
        if src == "guess" and not allow_guess:
            skipped.append(f"{company}: guessed recipient {to} (not allowed)")
            continue
        if _norm_key(to) in sent:
            skipped.append(f"{company}: {to} already contacted")
            continue
        # never email the same address twice in one run, and never send two
        # emails to the same company in one run (different postings resolve
        # to the same inbox, e.g. hello@domain.com)
        if _norm_key(to) in seen_recipients:
            skipped.append(f"{company}: {to} already in this run")
            continue
        if ck in seen_companies:
            skipped.append(f"{company}: same company already in this run")
            continue
        seen_recipients.add(_norm_key(to))
        seen_companies.add(ck)
        item = dict(job)
        item["to"] = to
        item["src"] = src
        plan.append(item)
    return plan, skipped


# ---------------------------------------------------------------------------
# email construction
# ---------------------------------------------------------------------------

def build_mime(cfg: dict, to: str, subject: str, body: str,
               attach_path: str | None = None) -> EmailMessage:
    """Pure MIME construction (no network) — unit-tested."""
    sender = cfg.get("sender", {}) or {}
    from_addr = sender.get("email", "")
    from_name = sender.get("name", "") or from_addr
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    domain = from_addr.split("@")[-1] if "@" in from_addr else "localhost"
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(body)
    if attach_path and Path(attach_path).exists():
        data = Path(attach_path).read_bytes()
        msg.add_attachment(data, maintype="application", subtype="pdf",
                           filename=Path(attach_path).name)
    return msg


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------

def record_sent(rows: list[dict]) -> None:
    if not rows:
        return
    DATA_DIR.mkdir(exist_ok=True)
    exists = SENT_FILE.exists()
    with open(SENT_FILE, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SENT_FIELDS,
                                extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# main pipeline
# ---------------------------------------------------------------------------

def run(cfg: dict, dry_run: bool = False, limit: int | None = None,
        today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    send = cfg.get("send", {}) or {}
    max_per_run = int(send.get("max_emails_per_run", 100) or 100)
    cap = limit if limit else (10 if dry_run else max_per_run)
    attach = send.get("attach_resume", True)
    resume_path = (cfg.get("candidate", {}) or {}).get("resume_path", "")
    fallback_resume = AA_DATA / "resume.pdf"
    if attach and not (resume_path and Path(resume_path).exists()):
        resume_path = str(fallback_resume) if fallback_resume.exists() else ""
    engine = str(send.get("email_engine") or "").strip().lower()
    use_ai = engine in ("opencode", "ollama")
    delay = float(send.get("delay_between_seconds", 2) or 0)
    creds = None
    if not dry_run:
        try:
            creds = ensure_token()
        except RuntimeError as exc:
            log(f"Gmail API not ready:\n{exc}")
            return 1
        acct = gmail_account(creds)
        if acct:
            log(f"Gmail account: {acct} (drafts will appear in THIS inbox)")
        else:
            log("could not read Gmail account from token - drafts will be "
                "created for whichever account authorized token.json")

    log(f"=== auto-send run {'(DRY RUN - nothing will be sent)' if dry_run else ''} "
        f"target={cap} ===")

    # 1) fetch + score
    log("fetching jobs from enabled sources ...")
    fetch_all(cfg)
    log("scoring matches ...")
    matches = match_all(cfg)
    if not matches:
        log("no matches above the threshold - nothing to do today")
        return 0

    # 2) dedup (company/job level)
    sent = load_sent()
    applied = load_applied_companies(AA_DATA / "applied.csv")
    vetoed = load_vetoed_companies(AA_DATA / "vetoed.json")
    candidates, reasons = filter_plan_candidates(matches, cfg, sent, applied,
                                                 vetoed, today)
    for r in reasons:
        log(f"  skip: {r}")

    # 3) resolve recipients in parallel
    log(f"resolving recipient emails for {len(candidates)} candidates ...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        resolved = list(ex.map(
            lambda job: quick_recipient((job.get("company") or "").strip()),
            candidates))

    # 4) recipient-level dedup + cap
    plan, reasons2 = finalize_plan(candidates, resolved, sent, cfg, cap)
    for r in reasons2:
        log(f"  skip: {r}")
    log(f"send plan: {len(plan)} email(s)")

    # 5) personalize + send
    if not plan:
        log("nothing to send - try again tomorrow (new postings accumulate)")
        return 0

    ok_count = 0
    rows: list[dict] = []
    for i, job in enumerate(plan, 1):
        company = job.get("company", "")
        title = job.get("title", "")
        try:
            gen = generate_cold_email(cfg, job, use_ai=use_ai, resolve=False)
            if not gen.get("ok"):
                raise RuntimeError(gen.get("error", "generation failed"))
            subject, body = gen["subject"], gen["body"]
        except Exception as exc:  # noqa: BLE001
            log(f"  [{i}/{len(plan)}] {company}: personalize failed - {exc}")
            rows.append({"date": today.isoformat(), "company": company,
                         "recipient": job.get("to", ""), "job_id": job.get("id", ""),
                         "title": title, "url": job.get("url", ""),
                         "subject": "", "recipient_source": job.get("src", ""),
                         "status": "error", "error": str(exc)[:200]})
            continue

        if dry_run:
            log(f"  [dry] would draft to {job['to']} ({job.get('src','')}) "
                f"@{company}: {subject}")
            continue

        msg = build_mime(cfg, job["to"], subject, body, resume_path or None)
        log(f"  [{i}/{len(plan)}] creating Gmail draft to {job['to']} "
            f"({job.get('src','')}) @{company} ...")
        ok, detail = create_draft(creds, msg)
        if ok:
            ok_count += 1
            log(f"      draft saved (id {detail})")
        else:
            log(f"      FAILED: {detail}")
        rows.append({"date": today.isoformat(), "company": company,
                     "recipient": job.get("to", ""), "job_id": job.get("id", ""),
                     "title": title, "url": job.get("url", ""),
                     "subject": subject[:120], "recipient_source": job.get("src", ""),
                     "status": "drafted" if ok else "error",
                     "error": "" if ok else detail[:200]})
        if ok and delay:
            time.sleep(delay)

    if not dry_run:
        record_sent(rows)
        log(f"=== done: {ok_count}/{len(plan)} drafts saved to Gmail, "
            f"{sum(1 for r in rows if r['status'] == 'error')} errors "
            f"-> {SENT_FILE} ===")
    else:
        log(f"=== dry run done: {len(plan)} drafts would be created "
            f"(resume attachment: {'yes' if resume_path else 'no'}) ===")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily auto-draft job applications")
    parser.add_argument("--dry-run", action="store_true",
                        help="plan only - resolve recipients + build emails, create nothing")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap drafts this run (default: send.max_emails_per_run, "
                             "or 10 for --dry-run)")
    args = parser.parse_args(argv)

    # the merged app's single source of truth is the ROOT config.yaml (the
    # autoapply/coldmail stubs in subfolders are legacy standalone configs)
    cfg = load_config(ROOT / "config.yaml")
    mode = (cfg.get("send", {}) or {}).get("mode", "gmail_api")
    if not args.dry_run and mode != "gmail_api":
        log(f"config send.mode is '{mode}' - no drafts will be created. "
            "Set send.mode: gmail_api in config.yaml to save Gmail drafts "
            "(drafts only - nothing is ever sent).")
        return 1
    return run(cfg, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
