"""Headless smoke test for the unified j0b web UI (root app.py).

Requires the Flask server running on 127.0.0.1:5000.
Run:  cd <project root> && python app.py   (in another terminal)
      python tests/test_ui.py
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"


def main() -> None:
    errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(2500)

        name_val = page.input_value("#cand-name")
        has_search_btn = page.is_visible("#btn-search")
        has_salary = page.is_visible("#f-sal-min")
        has_exp = page.is_visible("#f-exp-min") and page.is_visible("#f-exp-max")
        # the email panel card is hidden until a job is selected: assert the
        # elements exist in the DOM (they are the integration points)
        has_email_btn = page.locator("#btn-gmail-login").count() == 1
        has_compose_btn = page.locator("#btn-email-draft-browser").count() == 1
        has_draft_composio = page.locator("#btn-email-draft-composio").count() == 1
        pill = page.text_content("#ollama-pill") or ""

        print(f"name field:        {name_val!r}")
        print(f"exp filter inputs: {has_exp}")
        print(f"salary inputs:     {has_salary}")
        print(f"email panel:       {has_email_btn and has_compose_btn and has_draft_composio}")
        print(f"search btn:        {has_search_btn}")
        print(f"ollama pill:       {pill}")
        print(f"console errors:    {errors if errors else 'none'}")
        print(f"page errors:       {page_errors if page_errors else 'none'}")
        print("(email/apply buttons appear per job after a search)")

        ok = (
            name_val.strip() != ""
            and has_search_btn
            and has_salary
            and has_exp
            and has_email_btn
            and has_compose_btn
            and has_draft_composio
            and "ollama" in pill.lower()
            and not errors
            and not page_errors
        )
        print("\nUI SMOKE TEST:", "PASS" if ok else "FAIL")
        browser.close()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
