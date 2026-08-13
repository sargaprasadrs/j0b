"""Write cold emails into Gmail as DRAFTS using a real browser session.

Design principles:
  * NEVER clicks the Send button. Drafts only.
  * Persistent isolated browser profile (data/browser_profile) so you sign in
    ONCE and the session is reused. Your real Chrome profile is never touched.
  * Uses the real installed Chrome (channel="chrome") when available, falling
    back to Playwright's bundled Chromium.
  * If the profile is not signed in yet, the window STAYS OPEN and waits for
    you to sign in with your Gmail account (the account drafts will be sent
    from) — then the draft is created in the same session.

Requires:  python -m playwright install chromium
"""
from __future__ import annotations

import time
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from .config import DATA_DIR, ensure_data_dir

PROFILE_DIR = DATA_DIR / "browser_profile"
GMAIL = "https://mail.google.com/mail/u/0/#inbox"
VIEWPORT = {"width": 1280, "height": 860}
LOGIN_WAIT_S = 300  # how long to wait for the one-time sign-in


def _launch_persistent(p, headless: bool = False):
    """Open the real Chrome with the isolated profile dir (never the user's
    daily profile). Falls back to bundled Chromium if Chrome is missing."""
    opts = {"headless": headless, "viewport": VIEWPORT}
    try:
        return p.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="chrome", **opts)
    except Exception as exc:  # noqa: BLE001  (chrome missing / not launchable)
        print(f"[gmail] real Chrome unavailable ({exc}) - using bundled Chromium")
        return p.chromium.launch_persistent_context(str(PROFILE_DIR), **opts)


def _wait_for_logged_in(page, timeout_s: float = 600) -> bool:
    """Wait until the user has logged into Gmail manually.

    Returns False if the window is closed or the timeout passes, so callers
    can degrade gracefully instead of raising 'target closed' errors."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            url = page.url
            if "accounts.google.com" not in url and "mail.google.com" in url:
                # signed in if the sidebar / compose is present
                try:
                    page.wait_for_selector('div[role="navigation"], a[href*="#inbox"]',
                                           timeout=2000)
                    return True
                except PlaywrightTimeout:
                    pass
        except Exception:  # noqa: BLE001  (browser window closed by the user)
            print("[gmail] browser window was closed - stopping the wait.")
            return False
        time.sleep(1)
    return False


def login(timeout_s: float = 600) -> None:
    """Open Gmail once so the user logs in; session persists afterwards."""
    ensure_data_dir()
    PROFILE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        context = _launch_persistent(p)
        page = context.new_page()
        print("[gmail] opening Gmail - if you are not signed in, log in with "
              "your Gmail account in this window (happens once)...")
        page.goto(GMAIL)
        if _wait_for_logged_in(page, timeout_s):
            print("[gmail] logged in. Session saved to data/browser_profile")
            page.wait_for_timeout(1500)
        else:
            print("[gmail] login not detected after timeout - try again.")
        context.close()


def _compose_url(email: str, subject: str, body: str, authuser: int = 0) -> str:
    """Standalone Gmail compose URL.

    authuser=0 = the default/first account of the signed-in profile (the one
    you signed in with). If you ever sign in with several accounts, index 0
    is the first one — drafts go to that account's inbox."""
    return (
        "https://mail.google.com/mail/?view=cm&fs=1"
        f"&authuser={authuser}"
        f"&to={quote(email)}"
        f"&su={quote(subject)}"
        f"&body={quote(body)}"
    )


def _fill_if_empty(page, selector, value: str) -> bool:
    try:
        box = page.locator(selector).first
        box.wait_for(state="visible", timeout=8000)
        current = box.input_value() if box.evaluate(
            "el => el.tagName === 'TEXTAREA' || el.tagName === 'INPUT'"
        ) else (box.inner_text() or "")
        if not current.strip():
            box.fill(value)
        return True
    except Exception:  # noqa: BLE001
        return False


def draft_emails(emails: list[dict], dry_run: bool = False,
                 delay_s: float = 6.0, max_drafts: int = 10,
                 expected_email: str = "") -> list[str]:
    """emails: [{'to','subject','body','company'}]. Creates Gmail drafts.

    dry_run=True only prints what would be drafted (no browser).
    If the profile is not signed in yet, the browser stays open and waits for
    the one-time sign-in, then creates the drafts in the same session.
    Returns the list of company names whose drafts were actually created,
    so the caller can mark only successes as 'drafted'.
    """
    ensure_data_dir()
    if dry_run:
        print("[gmail] DRY RUN - no browser, no drafts. Preview: \n")
        for i, em in enumerate(emails[:max_drafts], 1):
            print(f"--- draft {i}/{len(emails[:max_drafts])} -> {em['to']} ---")
            print(f"Subject: {em['subject']}\n")
            print(em["body"][:400])
            print("\n" + "=" * 60 + "\n")
        print(f"[gmail] dry run done. Would create {min(len(emails), max_drafts)} drafts.")
        return []

    PROFILE_DIR.mkdir(exist_ok=True)
    created = 0
    succeeded: list[str] = []
    skipped = []
    with sync_playwright() as p:
        context = _launch_persistent(p)
        page = context.new_page()
        print("[gmail] opening Gmail...")
        page.goto(GMAIL)

        # short probe first so the sign-in message appears quickly when needed
        if not _wait_for_logged_in(page, timeout_s=10):
            who = f" with {expected_email}" if expected_email else ""
            print(f"[gmail] NOT signed in yet. Sign in{who} in this browser "
                  f"window (this happens once). Waiting up to "
                  f"{LOGIN_WAIT_S} seconds for you...\n")
            if not _wait_for_logged_in(page, timeout_s=LOGIN_WAIT_S):
                print("[gmail] sign-in not detected after the wait - closing. "
                      "Try again and complete the sign-in (or use `gmail login`).")
                context.close()
                return []
        print("[gmail] signed in.\n")

        for em in emails:
            if created >= max_drafts:
                skipped.append(em["company"])
                continue
            company = em["company"]
            print(f"[gmail] drafting for {company} -> {em['to']} ...")
            tab = context.new_page()
            try:
                tab.goto(_compose_url(em["to"], em["subject"], em["body"], authuser=0),
                         timeout=45000)
                tab.wait_for_timeout(2500)

                # make sure fields are filled (some browsers drop URL params)
                _fill_if_empty(tab, 'div[role="dialog"] input[name="to"]', em["to"])
                _fill_if_empty(tab, 'div[role="dialog"] input[name="subjectbox"]',
                               em["subject"])
                try:
                    body_box = tab.locator(
                        'div[role="dialog"] div[contenteditable="true"][role="textbox"]'
                    ).first
                    body_box.wait_for(state="visible", timeout=5000)
                    if not (body_box.inner_text() or "").strip():
                        body_box.fill(em["body"])
                except Exception:  # noqa: BLE001
                    pass

                # wait for Gmail autosave indicator ("Draft saved")
                saved = False
                deadline = time.time() + delay_s + 4
                while time.time() < deadline:
                    try:
                        if tab.locator(
                            'div[role="dialog"] span:has-text("Draft saved"), '
                            'div[role="dialog"] span:has-text("Saving")'
                        ).first.is_visible():
                            saved = True
                            break
                    except Exception:  # noqa: BLE001
                        pass
                    time.sleep(0.5)

                # extra wait so autosave definitely commits
                tab.wait_for_timeout(int(delay_s * 1000))
                print(f"    draft saved: {company} {'(confirmed)' if saved else '(waited)'}")
                created += 1
                succeeded.append(company)
            except Exception as exc:  # noqa: BLE001
                print(f"    FAILED for {company}: {exc}")
            finally:
                tab.close()

        context.close()

    print(f"\n[gmail] done. {created} draft(s) created in your Gmail "
          f"(Drafts folder). {'skipped (limit): ' + str(skipped) if skipped else ''}")
    print("[gmail] REVIEW EVERYTHING IN GMAIL BEFORE SENDING ANYTHING YOURSELF.")
    return succeeded
