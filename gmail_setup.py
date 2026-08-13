"""gmail_setup.py — one-time interactive setup for the Gmail API draft path.

Run once after saving client_secret.json (see gmail_drafts.py for the steps):

    python gmail_setup.py

Opens your browser, you click Allow once, and token.json is saved. From then
on auto_send.py creates drafts silently every day. Nothing is ever sent.
"""
from __future__ import annotations

import sys

import gmail_drafts


def main() -> int:
    try:
        gmail_drafts.ensure_token(force=True)
    except RuntimeError as exc:
        print(f"[gmail] {exc}")
        return 1
    print("[gmail] OK - Gmail API is authorized. Drafts will be saved to your "
          "Gmail Drafts folder; nothing is ever sent automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
