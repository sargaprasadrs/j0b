"""Semi-auto application agent.

The tool opens the job's application page in a real browser, pre-fills
common fields (email, phone, name, links) from the candidate profile,
prints the tailored cover letter / resume summary for copy-paste, and then
STOPS. The human reviews and clicks submit. The tool NEVER clicks submit.

After the user finishes, it records their status (applied/skipped).
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import DATA_DIR, ensure_data_dir

APPLIED_FILE = DATA_DIR / "applied.csv"


def _input_attrs(el) -> str:
    attrs = []
    for a in ("id", "name", "placeholder", "aria-label", "autocomplete"):
        v = (el.get_attribute(a) or "").lower()
        if v:
            attrs.append(v)
    return " ".join(attrs)


def _prefill_common_fields(page, cfg: dict) -> int:
    """Fill obvious input fields by name/type heuristics. Returns count."""
    cand = cfg.get("candidate", {})
    name = cand.get("name", "") or ""
    parts = name.split()
    first, last = (parts[0] if parts else ""), " ".join(parts[1:])

    email_val, phone_val, linkedin_val = (
        cand.get("email", ""), cand.get("phone", ""), cand.get("linkedin", ""))

    filled = 0
    try:
        inputs = page.locator("input[type=text], input[type=email], input[type=tel], "
                              "input:not([type])")
        count = inputs.count()
        for i in range(count):
            el = inputs.nth(i)
            if not el.is_editable():
                continue
            attrs = _input_attrs(el)
            if not attrs.strip():
                continue
            # email / tel by type first
            etype = (el.get_attribute("type") or "").lower()
            if etype == "email" and email_val and "email" in attrs:
                el.fill(email_val); filled += 1; continue
            if etype == "tel" and phone_val and ("phone" in attrs or "tel" in attrs):
                el.fill(phone_val); filled += 1; continue
            # full name: explicit full-name markers, or placeholder == name
            if (name and (("fullname" in attrs or "full-name" in attrs or "full name" in attrs)
                          or "name" in attrs.split()
                          or ("full" in attrs and "name" in attrs))):
                # skip if this is clearly a first/last field
                if not ("first" in attrs or "last" in attrs or "surname" in attrs):
                    el.fill(name); filled += 1; continue
            # first name
            if first and ("firstname" in attrs or "first-name" in attrs
                          or ("first" in attrs and "name" in attrs)):
                el.fill(first); filled += 1; continue
            # last name
            if last and ("lastname" in attrs or "last-name" in attrs
                         or "surname" in attrs
                         or ("last" in attrs and "name" in attrs)):
                el.fill(last); filled += 1; continue
            # linkedin
            if linkedin_val and ("linkedin" in attrs or "linked-in" in attrs
                                 or "linked in" in attrs):
                el.fill(linkedin_val); filled += 1; continue
    except Exception as exc:  # noqa: BLE001
        print(f"[apply] prefill error: {exc}")
    return filled


def apply_to_job(cfg: dict, job: dict, tailored: dict | None = None,
                 dry_run: bool = False) -> None:
    """Semi-auto apply for a single matched job."""
    ensure_data_dir()
    print("\n" + "=" * 64)
    print(f"JOB: {job['title']}")
    print(f"AT : {job['company']} ({job['location']})")
    print(f"URL: {job['url']}")
    print(f"MATCH: {job.get('match_score', '?')}/100")
    print("=" * 64)

    if tailored:
        print("\n--- Tailored cover letter (copy-paste) ---\n")
        print(tailored.get("cover_letter", "")[:800])
        print("\n--- Tailored resume summary ---\n")
        print(tailored.get("resume_summary", "")[:400])
        print("\n--- full docs in:", tailored.get("file", "n/a"), "---")

    if dry_run:
        print("\n[apply] DRY RUN - not opening a browser. "
              "Run without --dry-run to pre-fill the form.\n")
        print("[apply] (dry run is not logged - nothing was recorded)")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False,
                                    viewport={"width": 1280, "height": 900})
        page = browser.new_page()
        try:
            page.goto(job["url"], timeout=cfg.get("apply", {}).get("page_timeout", 45) * 1000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            n = _prefill_common_fields(page, cfg)
            print(f"\n[apply] Pre-filled {n} field(s) from your profile.")
            print("[apply] >>> REVIEW THE FORM IN THE BROWSER AND CLICK "
                  "SUBMIT YOURSELF WHEN READY <<<")
            input(">>> Press Enter here AFTER you have submitted (or closed) it: ")
        except Exception as exc:  # noqa: BLE001
            print(f"[apply] browser error: {exc}")
            input(">>> The page may have failed to load. Press Enter to log "
                  "the outcome anyway: ")
        finally:
            browser.close()

    status = ""
    while status not in ("a", "s", "r"):
        raw = input("Log outcome: (a)pplied  (s)kipped  (r)ejected? ").strip().lower()
        status = raw[0] if raw else ""
        if raw and raw[0] in "asr":
            status = raw[0]
    label = {"a": "applied", "s": "skipped", "r": "rejected"}[status]
    _record(job, label)
    print(f"[apply] recorded: {label}\n")


def _record(job: dict, status: str) -> None:
    ensure_data_dir()
    row = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "url": job.get("url", ""),
        "score": job.get("match_score", ""),
        "status": status,
    }
    exists = APPLIED_FILE.exists()
    with open(APPLIED_FILE, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def show_status() -> None:
    if not APPLIED_FILE.exists():
        print("[status] no applications logged yet.")
        return
    with open(APPLIED_FILE, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            print(f"  {row['date']}  {row['status']:<9} "
                  f"{row['title'][:40]:<40} @ {row['company'][:20]}")
