"""Headless test: pre-fill logic against tests/demo_form.html.

Run:  python tests/test_prefill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from autoapply.apply_agent import _prefill_common_fields
from autoapply.config import load_config


def main() -> None:
    cfg = load_config()
    cfg["candidate"].update({
        "name": "Sarga Prasad RS",
        "email": "sargaprasadrs@gmail.com",
        "phone": "+91 90000 00000",
        "linkedin": "https://linkedin.com/in/sarga",
    })
    form = Path(__file__).resolve().parent / "demo_form.html"
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto(form.as_uri())
        page.wait_for_timeout(500)
        n = _prefill_common_fields(page, cfg)
        print("prefilled fields:", n)
        for sel in ("#full_name", "#email", "#phone", "#linkedin"):
            print(f"  {sel} = {page.input_value(sel)!r}")
        b.close()


if __name__ == "__main__":
    main()
