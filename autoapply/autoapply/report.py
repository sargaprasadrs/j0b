"""Self-contained HTML dashboard from the application tracker.

Ported from ai-job-search's ``/html-report`` command. Reads ``applied.csv``,
normalises statuses into six buckets, computes funnel stats and writes a
single offline HTML file: inline CSS, hand-drawn inline SVG charts, and a
client-side filterable table. No server, no CDN, no dependencies.

Run:  python cli.py report   (writes autoapply/data/report.html)
"""
from __future__ import annotations

import csv
import json
import math
import time
from pathlib import Path

from .config import DATA_DIR, ensure_data_dir

REPORT_FILE = DATA_DIR / "report.html"

# canonical buckets -> colour (from the reference dashboard)
STATUS_BUCKETS = {
    "Drafted": "#64748b",
    "Active": "#3b82f6",
    "Interview": "#f59e0b",
    "Offer": "#8b5cf6",
    "Hired": "#22c55e",
    "Rejected/Closed": "#ef4444",
}
_NORMALISE = {
    "drafted": "Drafted",
    "applied": "Active",
    "interview": "Interview",
    "offer": "Offer",
    "hired": "Hired",
    "rejected": "Rejected/Closed",
    "no_response": "Rejected/Closed",
    "no response": "Rejected/Closed",
    "withdrawn": "Rejected/Closed",
    "offer_declined": "Rejected/Closed",
    "offer declined": "Rejected/Closed",
    "skipped": "Rejected/Closed",
}


def normalise_status(raw: str) -> str:
    return _NORMALISE.get((raw or "").strip().lower(), "Rejected/Closed")


def _esc(value) -> str:
    return (str(value or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _host(url: str) -> str:
    """Derive a human channel label from a job url (or 'other')."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url or "").hostname or "").lower()
    except Exception:  # noqa: BLE001
        host = ""
    known = {"linkedin": "linkedin", "indeed": "indeed", "glassdoor": "glassdoor",
             "remotive": "remotive", "jobicy": "jobicy", "freehire": "freehire",
             "adzuna": "adzuna", "weworkremotely": "weworkremotely",
             "greenhouse": "greenhouse", "lever": "lever", "ashbyhq": "ashby",
             "workable": "workable", "bamboohr": "bamboohr", "smartrecruiters": "smartrecruiters"}
    for key, label in known.items():
        if key in host:
            return label
    if host:
        return host.split(".")[-2] if "." in host else host
    return "other"


def load_rows() -> list[dict]:
    log_file = DATA_DIR / "applied.csv"
    rows: list[dict] = []
    if not log_file.exists():
        return rows
    with open(log_file, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    return rows


def compute_stats(rows: list[dict]) -> dict:
    """Stats over *submitted* rows (Drafted excluded, per the reference spec)."""
    normalised = []
    for r in rows:
        b = normalise_status(r.get("status", ""))
        normalised.append({**r, "bucket": b})
    counts = {k: 0 for k in STATUS_BUCKETS}
    for r in normalised:
        counts[r["bucket"]] += 1
    total = len(normalised) - counts["Drafted"]
    resolved = total - counts["Active"]
    channels: dict[str, int] = {}
    for r in normalised:
        ch = _host(r.get("url", ""))
        channels[ch] = channels.get(ch, 0) + 1
    reached_interview = counts["Interview"] + counts["Offer"] + counts["Hired"]
    return {
        "rows": normalised,
        "counts": counts,
        "total": total,
        "resolved": resolved,
        "channels": channels,
        "funnel": {
            "Applied": total,
            "Interview": reached_interview,
            "Offer": counts["Offer"] + counts["Hired"],
            "Hired": counts["Hired"],
        },
        "interview_rate": round(100 * reached_interview / total, 1) if total else 0.0,
        "rejection_rate": round(100 * (counts["Rejected/Closed"]) / resolved, 1)
        if resolved else 0.0,
    }


# ---------------------------------------------------------------------------
# inline SVG charts
# ---------------------------------------------------------------------------

def _doughnut(counts: dict) -> str:
    total = sum(counts.values())
    if not total:
        return '<svg role="img" aria-label="No applications yet" viewBox="0 0 200 200" width="200" height="200"><text x="100" y="100" text-anchor="middle" fill="#94a3b8" font-size="13">no data</text></svg>'
    r, cx, cy = 70, 100, 100
    pieces, start = [], -90.0
    for label, count in counts.items():
        if not count:
            continue
        frac = count / total
        sweep = frac * 360
        a1, a2 = start, start + sweep
        x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
        x2, y2 = cx + r * math.cos(math.radians(a2)), cy + r * math.sin(math.radians(a2))
        large = 1 if sweep > 180 else 0
        pieces.append(
            f'<path d="M {cx} {cy} L {x1:.1f} {y1:.1f} A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
            f'fill="{STATUS_BUCKETS[label]}" stroke="#0b1220" stroke-width="1">'
            f'<title>{_esc(label)}: {count}</title></path>')
        start = a2
    return (f'<svg role="img" aria-label="Status breakdown: '
            f'{", ".join(f"{c} {l}" for l, c in counts.items() if c)}" '
            f'viewBox="0 0 200 200" width="200" height="200">{"".join(pieces)}</svg>')


def _hbar(labels: list[str], values: list[int], maxv: int, colour: str,
          width: int = 240) -> str:
    if maxv <= 0:
        return ""
    bars = []
    for label, value in zip(labels, values):
        w = int(width * value / maxv) if value else 4
        bars.append(
            f'<div class="hbar-row"><span class="hbar-label">{_esc(label)}</span>'
            f'<div class="hbar-track"><div class="hbar-fill" style="width:{w}px;'
            f'background:{colour}"></div></div>'
            f'<span class="hbar-val">{value}</span></div>')
    return "".join(bars)


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------

def render_html(stats: dict) -> str:
    c = stats["counts"]
    cards = []
    order = [("Active", "Active"), ("Drafted", "Drafted"), ("Interview", "Interview"),
             ("Offer", "Offer"), ("Hired", "Hired"), ("Rejected/Closed", "Rejected/Closed")]
    for label, key in order:
        cards.append(
            f'<div class="stat-card" style="border-left-color:{STATUS_BUCKETS[key]}">'
            f'<div class="stat-num">{c[key]}</div><div class="stat-label">{label}</div></div>')

    channels = sorted(stats["channels"].items(), key=lambda kv: -kv[1])
    chan_labels = [k for k, _ in channels]
    chan_vals = [v for _, v in channels]
    chan_max = max(chan_vals) if chan_vals else 1

    funnel = stats["funnel"]
    funnel_labels = list(funnel.keys())
    funnel_vals = list(funnel.values())
    funnel_max = max(funnel_vals) if funnel_vals else 1

    legend = "".join(
        f'<span class="legend"><i style="background:{STATUS_BUCKETS[k]}"></i>{_esc(k)} '
        f'({v})</span>' for k, v in c.items() if v)

    rows_html = []
    for r in sorted(stats["rows"], key=lambda x: (x.get("date") or "", x.get("company") or ""),
                    reverse=True):
        status = normalise_status(r.get("status", ""))
        color = STATUS_BUCKETS[status]
        url = (r.get("url") or "").strip()
        source = (f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(_host(url))}</a>'
                  if url.startswith("http") else "—")
        score = r.get("score") or ""
        rows_html.append(
            f'<tr data-status="{_esc(status)}">'
            f'<td>{_esc(r.get("date") or "—")}</td>'
            f'<td class="company">{_esc(r.get("company") or "—")}</td>'
            f'<td>{_esc(r.get("title") or "—")}</td>'
            f'<td>{_esc(r.get("channel") or _host(url))}</td>'
            f'<td><span class="badge" style="background:{color}22;color:{color};'
            f'border-color:{color}66">{_esc(status)}</span></td>'
            f'<td>{_esc(score or "—")}</td>'
            f'<td>{source}</td></tr>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Search Dashboard</title>
<style>
  :root {{ --bg:#0b1220; --card:#111a2e; --border:#1f2b45; --text:#e6edf7; --muted:#8fa3bf; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         background:var(--bg); color:var(--text); padding:24px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .gen {{ color:var(--muted); font-size:12px; margin-bottom:20px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:12px; margin-bottom:20px; }}
  .stat-card {{ background:var(--card); border:1px solid var(--border); border-left:4px solid #3b82f6;
               border-radius:8px; padding:14px 16px; box-shadow:0 4px 12px rgba(0,0,0,.25); }}
  .stat-num {{ font-size:28px; font-weight:700; }}
  .stat-label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  .charts {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:20px; }}
  .chart-card {{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:16px; }}
  .chart-card h3 {{ margin:0 0 12px; font-size:14px; color:var(--muted); }}
  .legend {{ font-size:12px; color:var(--muted); margin-right:12px; }}
  .legend i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; }}
  .hbar-row {{ display:flex; align-items:center; gap:8px; margin:6px 0; font-size:12px; }}
  .hbar-label {{ width:110px; color:var(--muted); text-align:right; }}
  .hbar-track {{ flex:1; background:#0f1830; border-radius:4px; height:14px; }}
  .hbar-fill {{ height:14px; border-radius:4px; min-width:4px; }}
  .hbar-val {{ width:34px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--border);
          border-radius:8px; overflow:hidden; font-size:13px; }}
  th, td {{ padding:8px 10px; text-align:left; border-bottom:1px solid var(--border); }}
  th {{ color:var(--muted); font-weight:600; cursor:pointer; }}
  tr:nth-child(even) {{ background:#0f1830; }}
  a {{ color:#58a6ff; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px;
           border:1px solid; }}
  .filters {{ display:flex; gap:10px; margin:12px 0; flex-wrap:wrap; }}
  .filters input, .filters select {{ background:var(--bg); color:var(--text);
        border:1px solid var(--border); border-radius:6px; padding:6px 10px; font-size:13px; }}
  .company {{ font-weight:600; }}
  @media (max-width:900px) {{ .charts {{ grid-template-columns:1fr; }} body {{ padding:12px; }} }}
</style>
</head>
<body>
<h1>🔍 Job Search Dashboard</h1>
<div class="gen">Generated: {_esc(time.strftime('%Y-%m-%d %H:%M'))} · j0b report · {stats["total"]} applications · funnel: {stats["interview_rate"]}% past resume screen · rejection rate: {stats["rejection_rate"]}%</div>

<div class="cards">{''.join(cards)}</div>

<div class="charts">
  <div class="chart-card"><h3>Status breakdown</h3>{_doughnut(c)}{legend}</div>
  <div class="chart-card"><h3>By channel</h3>{_hbar(chan_labels, chan_vals, chan_max, "#3b82f6")}</div>
  <div class="chart-card"><h3>Application funnel</h3>{_hbar(funnel_labels, funnel_vals, funnel_max, "#f59e0b")}</div>
  <div class="chart-card"><h3>Status counts</h3>{_hbar(list(c.keys()), list(c.values()), max(c.values()) or 1, "#8b5cf6")}</div>
</div>

<div class="filters">
  <input id="q" type="search" placeholder="Search company / role / channel…">
  <select id="status-filter"><option value="">all statuses</option>
    {"".join(f'<option value="{_esc(k)}">{_esc(k)}</option>' for k in STATUS_BUCKETS)}</select>
</div>

<table>
  <thead><tr><th>Date</th><th>Company</th><th>Role</th><th>Channel</th><th>Status</th><th>Fit</th><th>Source</th></tr></thead>
  <tbody>{''.join(rows_html)}</tbody>
</table>
<p class="gen">Generated by j0b · ai-job-search inspired · {_esc(time.strftime('%Y-%m-%dT%H:%M:%S'))}</p>

<script>
(function () {{
  const q = document.getElementById('q');
  const status = document.getElementById('status-filter');
  const rows = Array.from(document.querySelectorAll('tbody tr'));
  const apply = () => {{
    const needle = q.value.toLowerCase();
    const st = status.value;
    rows.forEach(r => {{
      const text = r.textContent.toLowerCase();
      const okStatus = !st || r.dataset.status === st;
      r.style.display = (okStatus && text.includes(needle)) ? '' : 'none';
    }});
  }};
  q.addEventListener('input', apply);
  status.addEventListener('change', apply);
}})();
</script>
</body>
</html>
"""


def generate_report(out_path: Path | None = None) -> dict:
    """Write the dashboard HTML. Returns {path, stats, ok}."""
    ensure_data_dir()
    rows = load_rows()
    stats = compute_stats(rows)
    html = render_html(stats)
    path = Path(out_path) if out_path else REPORT_FILE
    path.write_text(html, encoding="utf-8")
    return {"path": str(path), "ok": True, "stats": {
        "total": stats["total"],
        "counts": stats["counts"],
        "interview_rate": stats["interview_rate"],
        "rejection_rate": stats["rejection_rate"],
    }}


if __name__ == "__main__":
    import sys
    res = generate_report()
    print(json.dumps(res, indent=2))
    sys.exit(0)
