#!/usr/bin/env python3
"""coldmail CLI - cold-email drafting tool (Gmail drafts only, never sends).

Commands:
  discover              find startups hiring (Jobicy/Remotive feeds)
  resolve               resolve contact emails from company websites
  drafts --dry-run      preview emails locally (no browser, no Gmail)
  drafts --collect      write email files into data/drafts/ (no Gmail)
  gmail login           log into Gmail once (persistent session)
  gmail draft --limit N create Gmail drafts (NEVER sends)

Examples:
  python cli.py discover --keywords "python, ai" --max-companies 10
  python cli.py resolve
  python cli.py drafts --dry-run
  python cli.py gmail login
  python cli.py gmail draft --limit 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from coldmail import discovery as discovery_mod          # noqa: E402
from coldmail.config import DATA_DIR, load_config          # noqa: E402
from coldmail.gmail_drafter import draft_emails, login     # noqa: E402
from coldmail.writer import build_subject, generate_email, write_draft_file  # noqa: E402


def _split_keywords(raw: list[str]) -> list[str]:
    """Normalize ['python, ai'] -> ['python', 'ai'] (split on commas)."""
    out = []
    for item in raw or []:
        for part in item.split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def cmd_discover(args) -> None:
    cfg = load_config(args.config)
    keywords = _split_keywords(args.keywords or cfg.get("discovery", {}).get("keywords", []))
    max_c = args.max_companies or cfg.get("discovery", {}).get("max_companies", 20)
    sources = cfg.get("discovery", {}).get("sources", ["jobicy", "remotive"])
    discovery_mod.discover(keywords, max_c, sources)


def cmd_resolve(args) -> None:
    from coldmail.resolver import resolve_all
    resolve_all()


def _collect_emails(cfg: dict, use_ai: bool = True) -> list[dict]:
    rows = discovery_mod.load_startups()
    if not rows:
        sys.exit("data/startups.csv is empty - run `python cli.py discover` first")
    emails = []
    for row in rows:
        if row.get("needs_email") == "yes" or not row.get("contact_email"):
            continue
        if row.get("drafted") == "yes":
            continue
        body = generate_email(
            cfg,
            company=row["company"],
            role_title=row.get("role_title", ""),
            notes=row.get("notes", ""),
            use_ai=use_ai,
        )
        subject = build_subject(cfg, row["company"], row.get("role_title", ""))
        emails.append({
            "to": row["contact_email"],
            "subject": subject,
            "body": body,
            "company": row["company"],
        })
    return emails


def cmd_drafts(args) -> None:
    cfg = load_config(args.config)
    emails = _collect_emails(cfg, use_ai=not args.no_ai)
    if not emails:
        print("No pending drafts. Run discover + resolve first, "
              "or clear 'drafted' flags in data/startups.csv.")
        return
    if args.dry_run or args.collect:
        if args.dry_run:
            draft_emails(emails, dry_run=True, max_drafts=len(emails))
        if args.collect:
            for em in emails:
                p = write_draft_file(cfg, em["company"], em["to"],
                                     em["subject"], em["body"])
                print(f"  wrote {p}")
        print(f"\n{len(emails)} email(s) generated.")
    else:
        sys.exit("use --dry-run to preview or `gmail draft` to write to Gmail")


def cmd_gmail(args) -> None:
    cfg = load_config(args.config)
    if args.action == "login":
        login()
    elif args.action == "draft":
        emails = _collect_emails(cfg, use_ai=not args.no_ai)
        if not emails:
            print("No pending drafts. Run discover + resolve first, "
                  "or clear 'drafted' flags in data/startups.csv.")
            return
        max_d = args.limit or cfg.get("outreach", {}).get("max_drafts", 10)
        print(f"Will create up to {max_d} draft(s) in your Gmail. "
              "DRAFTS ONLY - nothing is sent.\n")
        succeeded = draft_emails(emails, dry_run=False, max_drafts=max_d)
        # mark ONLY the ones that actually succeeded, so failures are retried
        rows = discovery_mod.load_startups()
        for row in rows:
            if row["company"] in succeeded:
                row["drafted"] = "yes"
        discovery_mod.save_startups(rows)
    else:
        sys.exit("usage: cli.py gmail login|draft")


def main() -> None:
    parser = argparse.ArgumentParser(description="coldmail - Gmail drafts only")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--keywords", nargs="*", default=[])
    p_discover.add_argument("--max-companies", type=int, default=0)
    p_discover.set_defaults(func=cmd_discover)

    p_resolve = sub.add_parser("resolve")
    p_resolve.set_defaults(func=cmd_resolve)

    p_drafts = sub.add_parser("drafts")
    p_drafts.add_argument("--dry-run", action="store_true")
    p_drafts.add_argument("--collect", action="store_true")
    p_drafts.add_argument("--no-ai", action="store_true",
                          help="skip Ollama, use the template")
    p_drafts.set_defaults(func=cmd_drafts)

    p_gmail = sub.add_parser("gmail")
    p_gmail.add_argument("action", choices=["login", "draft"])
    p_gmail.add_argument("--limit", type=int, default=0)
    p_gmail.add_argument("--no-ai", action="store_true",
                          help="skip Ollama, use the template")
    p_gmail.set_defaults(func=cmd_gmail)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
