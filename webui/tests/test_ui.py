"""Headless smoke test for the j0b web UI.

Requires the Flask server running on 127.0.0.1:5000.
Run:  cd webui && python tests/test_ui.py
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
        pill = page.text_content("#ollama-pill") or ""
        skills = page.input_value("#cand-skills")

        print(f"name field:        {name_val!r}")
        print(f"skills field:      {skills!r}")
        print(f"search btn:        {has_search_btn}")
        print(f"salary inputs:     {has_salary}")
        print(f"ollama pill:       {pill}")
        print(f"console errors:    {errors if errors else 'none'}")
        print(f"page errors:       {page_errors if page_errors else 'none'}")

        ok = (
            name_val.strip() != ""
            and has_search_btn
            and has_salary
            and "ollama" in pill.lower()
            and not errors
            and not page_errors
        )
        print("\nUI SMOKE TEST:", "PASS" if ok else "FAIL")
        browser.close()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
