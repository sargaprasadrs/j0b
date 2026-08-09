"""End-to-end flow test for the unified j0b web UI.

Requires Flask on 127.0.0.1:5000 (python app.py) and the live job feeds.
Uses template tailoring (fast, no AI).

Run:  cd <project root> && python app.py   (in another terminal)
      python tests/test_flow.py
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"


def main() -> None:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)

        # --- search with flexible filters ---
        page.fill("#f-keywords", "python")
        page.fill("#f-exp-min", "2")
        page.fill("#f-exp-max", "10")
        page.fill("#f-limit", "10")
        page.click("#btn-search")
        page.wait_for_selector("#results-card:not([hidden])", timeout=90000)
        page.wait_for_timeout(2000)
        jobs = page.locator(".job").count()
        count_text = page.text_content("#result-count") or ""
        exp_badges = page.locator(".badge.exp").count()
        email_btns = page.locator("button[data-act='email']").count()
        apply_btns = page.locator("button[data-act='apply']").count()
        print(f"search results:   {count_text}, rendered cards: {jobs}")
        print(f"exp badges:       {exp_badges}, cold-email btns: {email_btns}, apply btns: {apply_btns}")

        # --- cold email panel population (template body, no recipient resolve) ---
        email_ok = False
        if jobs > 0:
            page.click("button[data-act='email'] >> nth=0")
            page.wait_for_selector("#email-card:not([hidden])", timeout=20000)
            # template body is instant; recipient resolve may take a few seconds
            try:
                page.wait_for_function(
                    "document.querySelector('#email-subject').value.length > 0",
                    timeout=45000)
            except Exception:  # noqa: BLE001
                pass
            to = page.input_value("#email-to")
            subj = page.input_value("#email-subject")
            body = page.input_value("#email-body")
            line = page.text_content("#email-job-line") or ""
            print(f"email panel:      to={to!r} subject={subj[:40]!r} body_len={len(body)}")
            print(f"email line:       {line[:100]}")
            email_ok = bool(subj and len(body) > 50)

        print(f"console errors:   {errors if errors else 'none'}")
        ok = jobs > 0 and exp_badges >= 0 and email_btns > 0 and apply_btns > 0 and email_ok
        print("\nFLOW TEST:", "PASS" if ok else "FAIL")
        browser.close()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
