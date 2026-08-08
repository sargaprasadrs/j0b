#!/usr/bin/env python3
"""autoapply CLI - semi-auto job application assistant.

Commands:
  search [--keywords ...] [--limit N]   fetch matched jobs from legal APIs
  match [--mode keywords|ai]            score jobs vs your resume
  tailor [--top N] [--no-ai]            generate per-job cover letter + summary
  apply  --job-id N [--dry-run]         semi-auto apply (pre-fill, YOU submit)
  status                                 show application log

Examples:
  python cli.py search --keywords "python, ai" --limit 40
  python cli.py match
  python cli.py tailor --top 10
  python cli.py apply --job-id 3 --dry-run
  python cli.py apply --job-id 3
  python cli.py status
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from autoapply.config import load_config                     # noqa: E402
from autoapply.jobs import fetch_all, load_jobs               # noqa: E402
from autoapply.matcher import load_matches, match_all         # noqa: E402
from autoapply.tailor import tailor_top                       # noqa: E402


def _split_keywords(raw: list[str]) -> list[str]:
    out = []
    for item in raw or []:
        for part in item.split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def cmd_search(args) -> None:
    cfg = load_config(args.config)
    if args.keywords:
        kw = _split_keywords(args.keywords)
        if kw:
            cfg.setdefault("search", {})["keywords"] = kw
    if args.limit:
        cfg.setdefault("search", {})["limit"] = args.limit
    fetch_all(cfg)


def cmd_match(args) -> None:
    cfg = load_config(args.config)
    if args.mode:
        cfg.setdefault("match", {})["mode"] = args.mode
    match_all(cfg)


def cmd_tailor(args) -> None:
    cfg = load_config(args.config)
    tailor_top(cfg, top=args.top, use_ai=not args.no_ai)


def _pick_job(matches: list[dict], job_id: str) -> dict | None:
    """Accept a 1-based index (as shown by `match`) or an id prefix."""
    if job_id.isdigit():
        idx = int(job_id)
        if 1 <= idx <= len(matches):
            return matches[idx - 1]
    for m in matches:
        if str(m.get("id", "")).startswith(job_id):
            return m
    return None


def cmd_apply(args) -> None:
    cfg = load_config(args.config)
    matches = load_matches()
    if not matches:
        sys.exit("no matches - run `python cli.py search` + `python cli.py match`")
    job = _pick_job(matches, args.job_id)
    if job is None:
        print("job not found. Available (index + id):")
        for i, m in enumerate(matches, 1):
            print(f"  {i}. {m['id']}  {m['title'][:44]} @ {m['company'][:20]}")
        sys.exit("pick an index or id prefix from the list")
    tailored = None
    if not args.dry_run:
        from autoapply.tailor import tailor_job
        tailored = tailor_job(cfg, job)
    from autoapply.apply_agent import apply_to_job
    apply_to_job(cfg, job, tailored=tailored, dry_run=args.dry_run)


def cmd_status(args) -> None:
    from autoapply.apply_agent import show_status
    show_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="autoapply - semi-auto apply")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search")
    p_search.add_argument("--keywords", nargs="*", default=[])
    p_search.add_argument("--limit", type=int, default=0)
    p_search.set_defaults(func=cmd_search)

    p_match = sub.add_parser("match")
    p_match.add_argument("--mode", choices=["keywords", "ai"], default="")
    p_match.set_defaults(func=cmd_match)

    p_tailor = sub.add_parser("tailor")
    p_tailor.add_argument("--top", type=int, default=10)
    p_tailor.add_argument("--no-ai", action="store_true")
    p_tailor.set_defaults(func=cmd_tailor)

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--job-id", required=True)
    p_apply.add_argument("--dry-run", action="store_true")
    p_apply.set_defaults(func=cmd_apply)

    p_status = sub.add_parser("status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
