"""gmail_drafts.py — create Gmail DRAFTS via the Gmail API. Never sends.

This is the ONLY Gmail action this project performs: users.drafts.create.
No email is ever sent automatically — every application lands in your Gmail
Drafts folder and you hit Send yourself.

One-time setup (about 5 minutes, do this once on your machine):

  1. Google Cloud console  https://console.cloud.google.com
     -> create a project (e.g. "j0b")
     -> APIs & Services -> Library -> enable "Gmail API"
  2. APIs & Services -> OAuth consent screen
     -> External -> add yourself as a test user
     -> (recommended) click "Publish app" so the refresh token never expires
        (in Testing mode tokens expire after 7 days)
  3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID
     -> Application type: "Desktop app"
     -> Download the JSON -> save it in the project root as client_secret.json
  4. Run once (opens your browser for a one-time Allow):
        python gmail_setup.py
     -> token.json is saved next to client_secret.json. Every later run reuses
        it silently — no browser, no password, nothing stored except that
        refresh token file (gitignored).

Scope used: gmail.compose (needed to create drafts). The code below only ever
calls drafts().create() — it is impossible for it to send.
"""
from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_FILE = ROOT / "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

SETUP_MSG = (
    "Gmail API is not set up yet. Do this once (5 min):\n"
    "  1. https://console.cloud.google.com  -> new project -> enable Gmail API\n"
    "  2. APIs & Services -> OAuth consent screen -> External -> add yourself "
    "as test user -> Publish app (so the token doesn't expire in 7 days)\n"
    "  3. Credentials -> Create credentials -> OAuth client ID -> 'Desktop app'\n"
    "     -> download JSON -> save as client_secret.json in this folder\n"
    "  4. Run:  python gmail_setup.py   (opens a browser - click Allow once)\n"
)


def encode_raw(msg) -> str:
    """URL-safe base64 of the MIME message, as required by drafts.create."""
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def ensure_token(force: bool = False):
    """Return a valid Credentials object (one-time browser consent if needed).

    Raises RuntimeError with setup instructions when client_secret.json is
    missing, or when the browser consent cannot run."""
    if not CLIENT_SECRET.exists():
        raise RuntimeError(SETUP_MSG)
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:  # noqa: BLE001  (corrupt/outdated token file)
            creds = None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:  # noqa: BLE001  (revoked token -> re-authorize)
            creds = None
    if creds and creds.valid and not force:
        return creds
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def gmail_account(creds) -> str:
    """Best-effort: return the email of the Gmail account the OAuth token is
    authorized for (users.getProfile - read-only). Returns '' on failure.

    Lets the daily run log WHICH account drafts are created from, so you can
    immediately spot a mismatch (e.g. you authorized a different Google
    account than the inbox you are checking)."""
    try:
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return str(service.users().getProfile(userId="me").execute()
                   .get("emailAddress", ""))
    except Exception:  # noqa: BLE001  (offline / transient - never block the run)
        return ""


def create_draft(creds, msg) -> tuple[bool, str]:
    """Create one Gmail draft from an EmailMessage (never sends).

    Attachments must be embedded in the raw MIME message itself - the Gmail
    API does NOT support media upload for users.drafts.create (it returns
    "Media type ... is not supported"). build_mime() already embeds the resume
    as a base64 part, so only the raw message is uploaded.

    Returns (ok, detail) where detail is the draft id on success or the error
    text on failure. Only users.drafts.create is ever called."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return False, ("Google API libraries missing - run: "
                       "pip install -r requirements.txt")
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        res = service.users().drafts().create(
            userId="me", body={"message": {"raw": encode_raw(msg)}}).execute()
        return True, str(res.get("id", ""))
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
