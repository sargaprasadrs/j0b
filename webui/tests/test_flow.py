"""End-to-end flow test: search -> results -> tailor modal.

Requires Flask on 127.0.0.1:5000. Uses template tailoring (fast, no AI).
Run:  cd webui && python tests/test_flow.py
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

        # --- search ---
        page.fill("#f-keywords", "python, developer")
        page.fill("#f-limit", "15")
        page.click("#btn-search")
        page.wait_for_selector("#results-card:not([hidden])", timeout=60000)
        page.wait_for_timeout(2000)
        count_text = page.text_content("#result-count") or ""
        jobs = page.locator(".job").count()
        print(f"search results:   {count_text}, rendered cards: {jobs}")

        # --- tailor (template mode via API is instant; click first Tailor) ---
        if jobs > 0:
            # open modal -> tick fast template -> click Generate (deterministic)
            page.click(".job button[data-act='tailor'] >> nth=0")
            page.wait_for_selector("#tailor-modal:not([hidden])", timeout=10000)
            page.check("#tailor-template")
            page.click("#btn-generate")
            # wait for the docs to finish generating (template mode is instant)
            page.wait_for_function(
                "!document.querySelector('#tailor-title').textContent.startsWith('Tailoring')",
                timeout=20000)
            modal_title = page.text_content("#tailor-title") or ""
            print(f"tailor modal:     {modal_title[:60]}")

        # --- tracker card visibility ---
        tracker = page.is_visible("#tracker-card")
        print(f"tracker card:     {tracker} (hidden when empty)")

        print(f"console errors:   {errors if errors else 'none'}")
        ok = jobs > 0 and "Tailoring" not in (page.text_content("#tailor-title") or "")
        print("\nFLOW TEST:", "PASS" if ok else "FAIL")
        browser.close()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
