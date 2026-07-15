#!/usr/bin/env python3
"""Visualize testbench results grouped by combo.

Reads results.csv (written by `bench.py report`), aggregates per combo —
valid runs only, matching bench.py's scoring rules — and writes a single
self-contained HTML file with inline-SVG charts:

    pass rate by combo, pass-rate heatmap (combo x task), median wall time,
    median tokens, run validity (valid vs invalid), and a summary table.

Usage:
    viz.py [results.csv] [-o viz.html]

Stdlib only, Python 3.10+.
"""

import argparse
import csv
import html
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Reference dataviz palette (validated set; see matching light/dark CSS below).
SEQ_RAMP = [  # blue, steps 100 -> 700, light -> dark
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]

BAR_H = 22          # bar thickness (<= 24px)
GAP = 2             # surface gap between touching marks
LABEL_W = 170       # left gutter for combo names
CHART_W = 640


# ---------------------------------------------------------------- data

def load_rows(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            r["pass_rate"] = float(r["pass_rate"])
            r["wall_s"] = float(r["wall_s"])
            r["tokens_total"] = int(r["tokens_total"])
            r["invalid"] = r["invalid"] == "True"
            r["requests"] = int(r["requests"])
            r["budget_spent"] = int(r["budget_spent"]) if r["budget_spent"] else None
            # SAIA charges per request, not per token. budget_spent is the
            # actual charge (budget-delta, counts failed requests too); fall
            # back to the DB request count when the delta is unavailable,
            # same as bench.py's report.
            r["charged"] = r["budget_spent"] if r["budget_spent"] is not None else r["requests"]
            rows.append(r)
    return rows


def load_combo_descriptions():
    try:
        matrix = json.loads((ROOT / "matrix.json").read_text())
        return {name: c.get("description", "") for name, c in matrix["combos"].items()}
    except (OSError, KeyError, ValueError):
        return {}


def aggregate(rows):
    """Per-combo stats. Scores come from valid runs only (same rule as bench.py)."""
    combos = {}
    for r in rows:
        c = combos.setdefault(r["combo"], {"runs": [], "valid": []})
        c["runs"].append(r)
        if not r["invalid"]:
            c["valid"].append(r)
    for name, c in combos.items():
        v = c["valid"]
        c["name"] = name
        c["n_runs"] = len(c["runs"])
        c["n_valid"] = len(v)
        c["pass_rate"] = statistics.mean(r["pass_rate"] for r in v) if v else None
        c["wall_s"] = statistics.median(r["wall_s"] for r in v) if v else None
        c["tokens"] = statistics.median(r["tokens_total"] for r in v) if v else None
        c["charged"] = statistics.median(r["charged"] for r in v) if v else None
        c["flags"] = Counter(
            flag for r in c["runs"] if r["flags"] for flag in r["flags"].split(";")
        )
    # one shared order across every chart: best mean pass rate first
    return sorted(combos.values(),
                  key=lambda c: (c["pass_rate"] is None, -(c["pass_rate"] or 0)))


def cell_stats(rows):
    """(combo, task) -> mean pass rate over valid runs, or None."""
    cells = {}
    for r in rows:
        if not r["invalid"]:
            cells.setdefault((r["combo"], r["task"]), []).append(r["pass_rate"])
    return {k: statistics.mean(v) for k, v in cells.items()}


# ---------------------------------------------------------------- svg helpers

def esc(s):
    return html.escape(str(s), quote=True)


def fmt_tokens(n):
    if n is None:
        return "–"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def fmt_secs(s):
    return "–" if s is None else f"{s:.0f}s"


def fmt_pct(v):
    return "–" if v is None else f"{v * 100:.0f}%"


def fmt_int(v):
    return "–" if v is None else f"{v:,.0f}"


def hbar_path(x, y, w, h, r=4):
    """Horizontal bar: square at the baseline (left), 4px rounded data-end."""
    r = min(r, w, h / 2)
    if w <= 0:
        return ""
    return (f"M{x:.1f},{y:.1f} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} "
            f"v{h - 2 * r:.1f} a{r},{r} 0 0 1 -{r},{r} h-{w - r:.1f} z")


def nice_max(v):
    if v <= 0:
        return 1
    mag = 10 ** (len(str(int(v))) - 1)
    for m in (1, 2, 2.5, 4, 5, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def relative_luminance(hexcolor):
    def chan(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def hbar_chart(combos, key, fmt, domain_max=None, unit=""):
    """One-series horizontal bar chart (fill = series-1), direct-labeled tips."""
    values = [c[key] for c in combos]
    vmax = domain_max if domain_max is not None else nice_max(max((v or 0) for v in values))
    row_h = BAR_H + 14
    plot_w = CHART_W - LABEL_W - 60
    h = len(combos) * row_h + 26
    parts = [f'<svg viewBox="0 0 {CHART_W} {h}" role="img">']
    # hairline gridlines + ticks
    for i in range(5):
        gx = LABEL_W + plot_w * i / 4
        tick = vmax * i / 4
        parts.append(f'<line x1="{gx:.1f}" y1="0" x2="{gx:.1f}" y2="{h - 24}" class="grid"/>')
        parts.append(f'<text x="{gx:.1f}" y="{h - 8}" class="tick" text-anchor="middle">'
                     f'{fmt(tick)}</text>')
    for i, c in enumerate(combos):
        y = i * row_h + 6
        v = c[key]
        parts.append(f'<text x="{LABEL_W - 10}" y="{y + BAR_H / 2 + 4}" class="cat" '
                     f'text-anchor="end">{esc(c["name"])}</text>')
        if v is None:
            parts.append(f'<text x="{LABEL_W + 6}" y="{y + BAR_H / 2 + 4}" class="muted">'
                         f'no valid runs</text>')
            continue
        w = plot_w * v / vmax
        tip = (f'{c["name"]} — {fmt(v)}{unit}\n'
               f'{c["n_valid"]} valid of {c["n_runs"]} runs')
        parts.append(f'<path d="{hbar_path(LABEL_W, y, w, BAR_H)}" class="bar" '
                     f'tabindex="0" data-tip="{esc(tip)}"/>')
        parts.append(f'<text x="{LABEL_W + w + 8}" y="{y + BAR_H / 2 + 4}" class="val">'
                     f'{fmt(v)}</text>')
    parts.append(f'<line x1="{LABEL_W}" y1="0" x2="{LABEL_W}" y2="{h - 24}" class="axis"/>')
    parts.append("</svg>")
    return "".join(parts)


def heatmap(combos, tasks, cells, counts):
    """combo x task grid, sequential blue ramp on mean pass rate."""
    cell_w = (CHART_W - LABEL_W - 10) / len(tasks)
    cell_h = 34
    top = 24
    h = top + len(combos) * (cell_h + GAP)
    parts = [f'<svg viewBox="0 0 {CHART_W} {h}" role="img">']
    for j, t in enumerate(tasks):
        parts.append(f'<text x="{LABEL_W + j * cell_w + cell_w / 2:.1f}" y="14" '
                     f'class="tick" text-anchor="middle">{esc(t)}</text>')
    for i, c in enumerate(combos):
        y = top + i * (cell_h + GAP)
        parts.append(f'<text x="{LABEL_W - 10}" y="{y + cell_h / 2 + 4}" class="cat" '
                     f'text-anchor="end">{esc(c["name"])}</text>')
        for j, t in enumerate(tasks):
            x = LABEL_W + j * cell_w
            v = cells.get((c["name"], t))
            n = counts.get((c["name"], t), 0)
            if v is None:
                tip = f'{c["name"]} × {t}: no valid runs'
                parts.append(f'<rect x="{x:.1f}" y="{y}" width="{cell_w - GAP:.1f}" '
                             f'height="{cell_h}" rx="4" class="cell-empty" tabindex="0" '
                             f'data-tip="{esc(tip)}"/>')
                parts.append(f'<text x="{x + cell_w / 2:.1f}" y="{y + cell_h / 2 + 4}" '
                             f'class="muted" text-anchor="middle">–</text>')
                continue
            fill = SEQ_RAMP[round(v * (len(SEQ_RAMP) - 1))]
            ink = "#ffffff" if relative_luminance(fill) < 0.45 else "#0b0b0b"
            tip = f'{c["name"]} × {t}\nmean pass rate {fmt_pct(v)} over {n} valid run(s)'
            parts.append(f'<rect x="{x:.1f}" y="{y}" width="{cell_w - GAP:.1f}" '
                         f'height="{cell_h}" rx="4" fill="{fill}" tabindex="0" '
                         f'data-tip="{esc(tip)}"/>')
            parts.append(f'<text x="{x + cell_w / 2:.1f}" y="{y + cell_h / 2 + 4}" '
                         f'fill="{ink}" class="cellval" text-anchor="middle">'
                         f'{fmt_pct(v)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def validity_chart(combos):
    """Stacked valid/invalid run counts per combo. Emphasis: valid in the
    accent hue, invalid in the de-emphasis gray."""
    row_h = BAR_H + 14
    plot_w = CHART_W - LABEL_W - 60
    vmax = max(c["n_runs"] for c in combos)
    h = len(combos) * row_h + 6
    parts = [f'<svg viewBox="0 0 {CHART_W} {h}" role="img">']
    for i, c in enumerate(combos):
        y = i * row_h + 6
        parts.append(f'<text x="{LABEL_W - 10}" y="{y + BAR_H / 2 + 4}" class="cat" '
                     f'text-anchor="end">{esc(c["name"])}</text>')
        n_inv = c["n_runs"] - c["n_valid"]
        w_valid = plot_w * c["n_valid"] / vmax
        w_inv = plot_w * n_inv / vmax
        tip = f'{c["name"]}\n{c["n_valid"]} valid, {n_inv} invalid runs'
        if c["n_valid"]:
            parts.append(f'<rect x="{LABEL_W}" y="{y}" width="{max(w_valid - GAP, 1):.1f}" '
                         f'height="{BAR_H}" rx="2" class="bar" tabindex="0" '
                         f'data-tip="{esc(tip)}"/>')
        if n_inv:
            parts.append(f'<rect x="{LABEL_W + w_valid:.1f}" y="{y}" width="{w_inv:.1f}" '
                         f'height="{BAR_H}" rx="2" class="bar-dim" tabindex="0" '
                         f'data-tip="{esc(tip)}"/>')
        parts.append(f'<text x="{LABEL_W + w_valid + w_inv + 8:.1f}" '
                     f'y="{y + BAR_H / 2 + 4}" class="val">{c["n_valid"]}/{c["n_runs"]}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- page

CSS = """
:root {
  color-scheme: light;
  --plane: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --de-emph: #c3c2b7;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --plane: #0d0d0d; --surface: #1a1a19;
    --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --de-emph: #52514e;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d; --surface: #1a1a19;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --de-emph: #52514e;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px; background: var(--plane); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1400px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 4px; }
.sub { color: var(--ink-2); margin: 0 0 20px; }
.kpis { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
.tile {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 16px; min-width: 130px;
}
.tile .label { color: var(--ink-2); font-size: 12px; }
.tile .value { font-size: 26px; font-weight: 600; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px; overflow-x: auto;
}
.card.wide { grid-column: 1 / -1; }
.card h2 { font-size: 14px; margin: 0 0 2px; }
.card .note { color: var(--muted); font-size: 12px; margin: 0 0 10px; }
.card svg { width: 100%; height: auto; display: block; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px;
  color: var(--ink-2); margin-bottom: 8px; }
.legend > span { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.legend .sw { width: 10px; height: 10px; border-radius: 2px; flex: none; }
svg .grid { stroke: var(--grid); stroke-width: 1; }
svg .axis { stroke: var(--axis); stroke-width: 1; }
svg .bar { fill: var(--series-1); outline: none; }
svg .bar-dim { fill: var(--de-emph); outline: none; }
svg .bar:hover, svg .bar:focus, svg .bar-dim:hover, svg .bar-dim:focus,
svg rect[data-tip]:hover, svg rect[data-tip]:focus { opacity: 0.85; }
svg .cell-empty { fill: var(--surface); stroke: var(--grid); outline: none; }
svg text { font: 12px system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink-2); }
svg .tick { fill: var(--muted); font-variant-numeric: tabular-nums; }
svg .val { fill: var(--ink-2); font-variant-numeric: tabular-nums; }
svg .muted { fill: var(--muted); }
svg .cellval { font-weight: 600; font-variant-numeric: tabular-nums; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--grid); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
th { color: var(--ink-2); font-weight: 600; }
tbody tr:hover { background: color-mix(in srgb, var(--series-1) 6%, transparent); }
.desc { color: var(--muted); }
#tip {
  position: fixed; display: none; pointer-events: none; z-index: 10;
  background: var(--ink); color: var(--plane); border-radius: 6px;
  padding: 6px 10px; font-size: 12px; white-space: pre-line; max-width: 320px;
}
details { margin-top: 20px; }
summary { cursor: pointer; color: var(--ink-2); }
"""

JS = """
const tip = document.getElementById('tip');
function show(e) {
  tip.textContent = e.target.dataset.tip;
  tip.style.display = 'block';
  move(e);
}
function move(e) {
  const x = e.clientX ?? e.target.getBoundingClientRect().right;
  const y = e.clientY ?? e.target.getBoundingClientRect().top;
  tip.style.left = Math.min(x + 14, innerWidth - tip.offsetWidth - 8) + 'px';
  tip.style.top = Math.min(y + 14, innerHeight - tip.offsetHeight - 8) + 'px';
}
function hide() { tip.style.display = 'none'; }
for (const el of document.querySelectorAll('[data-tip]')) {
  el.addEventListener('mouseenter', show);
  el.addEventListener('mousemove', move);
  el.addEventListener('mouseleave', hide);
  el.addEventListener('focus', show);
  el.addEventListener('blur', hide);
}
"""


def summary_table(combos, descriptions):
    head = ("<tr><th>combo</th><th class=num>runs</th><th class=num>valid</th>"
            "<th class=num>mean pass rate</th><th class=num>median wall</th>"
            "<th class=num>median requests charged</th>"
            "<th class=num>median tokens</th><th>top flags</th></tr>")
    body = []
    for c in combos:
        flags = ", ".join(f"{f} ×{n}" for f, n in c["flags"].most_common(2)) or "–"
        desc = descriptions.get(c["name"], "")
        body.append(
            f'<tr><td title="{esc(desc)}">{esc(c["name"])}</td>'
            f'<td class=num>{c["n_runs"]}</td><td class=num>{c["n_valid"]}</td>'
            f'<td class=num>{fmt_pct(c["pass_rate"])}</td>'
            f'<td class=num>{fmt_secs(c["wall_s"])}</td>'
            f'<td class=num>{fmt_int(c["charged"])}</td>'
            f'<td class=num>{fmt_tokens(c["tokens"])}</td>'
            f'<td class=desc>{esc(flags)}</td></tr>')
    return f"<table><thead>{head}</thead><tbody>{''.join(body)}</tbody></table>"


def runs_table(rows):
    head = ("<tr><th>run</th><th>task</th><th>combo</th><th class=num>pass rate</th>"
            "<th class=num>wall</th><th class=num>requests charged</th>"
            "<th class=num>tokens</th><th>valid</th><th>flags</th></tr>")
    body = []
    for r in sorted(rows, key=lambda r: r["run_id"]):
        charged = fmt_int(r["charged"])
        if r["budget_spent"] is None:
            charged = f"~{charged}"  # DB fallback, same convention as report.md
        body.append(
            f'<tr><td>{esc(r["run_id"])}</td><td>{esc(r["task"])}</td>'
            f'<td>{esc(r["combo"])}</td><td class=num>{fmt_pct(r["pass_rate"])}</td>'
            f'<td class=num>{fmt_secs(r["wall_s"])}</td>'
            f'<td class=num>{charged}</td>'
            f'<td class=num>{fmt_tokens(r["tokens_total"])}</td>'
            f'<td>{"no" if r["invalid"] else "yes"}</td>'
            f'<td class=desc>{esc(r["flags"] or "–")}</td></tr>')
    return f"<table><thead>{head}</thead><tbody>{''.join(body)}</tbody></table>"


def card(title, note, body, wide=False):
    cls = "card wide" if wide else "card"
    return (f'<div class="{cls}"><h2>{esc(title)}</h2>'
            f'<p class="note">{esc(note)}</p>{body}</div>')


def build_html(rows, csv_name):
    combos = aggregate(rows)
    tasks = sorted({r["task"] for r in rows})
    cells = cell_stats(rows)
    counts = Counter((r["combo"], r["task"]) for r in rows if not r["invalid"])
    descriptions = load_combo_descriptions()

    n_valid = sum(c["n_valid"] for c in combos)
    best = next((c for c in combos if c["pass_rate"] is not None), None)
    kpis = [
        ("runs", str(len(rows))),
        ("valid runs", f"{n_valid} ({n_valid / len(rows) * 100:.0f}%)"),
        ("combos", str(len(combos))),
        ("tasks", str(len(tasks))),
        ("SAIA requests charged", fmt_int(sum(r["charged"] for r in rows))),
    ]
    if best:
        kpis.append(("best combo (mean pass rate)",
                     f'{best["name"]} · {fmt_pct(best["pass_rate"])}'))
    kpi_html = "".join(
        f'<div class="tile"><div class="label">{esc(k)}</div>'
        f'<div class="value">{esc(v)}</div></div>' for k, v in kpis)

    legend = ('<div class="legend">'
              '<span><span class="sw" style="background:var(--series-1)"></span>valid</span>'
              '<span><span class="sw" style="background:var(--de-emph)"></span>'
              'invalid — excluded from scores</span></div>')

    cards = "".join([
        card("Mean pass rate by combo", "valid runs only; combos ordered best-first",
             hbar_chart(combos, "pass_rate", fmt_pct, domain_max=1.0)),
        card("Pass rate by combo × task", "mean over valid runs; – means no valid run yet",
             heatmap(combos, tasks, cells, counts)),
        card("Median wall time by combo", "seconds per run, valid runs only",
             hbar_chart(combos, "wall_s", fmt_secs, unit="")),
        card("Median SAIA requests charged by combo",
             "SAIA charges per request, not per token — this is the comparable "
             "cost; budget-delta where available, else DB request count",
             hbar_chart(combos, "charged", fmt_int, unit=" requests")),
        card("Median tokens by combo", "total tokens per run, valid runs only",
             hbar_chart(combos, "tokens", fmt_tokens)),
        card("Run validity by combo", "all recorded runs", legend + validity_chart(combos)),
        card("Summary", "hover a combo name for its description",
             summary_table(combos, descriptions), wide=True),
    ])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>testbench results by combo</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>opencode SAIA testbench — results by combo</h1>
<p class="sub">generated from {esc(csv_name)} · score aggregates use valid runs only,
matching bench.py's exclusion of provider/budget failures</p>
<div class="kpis">{kpi_html}</div>
<div class="cards">{cards}</div>
<details><summary>all runs ({len(rows)})</summary>{runs_table(rows)}</details>
</main>
<div id="tip"></div>
<script>{JS}</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", nargs="?", default=str(ROOT / "results.csv"),
                    help="results csv (default: results.csv next to this script)")
    ap.add_argument("-o", "--out", default=str(ROOT / "viz.html"),
                    help="output html file (default: viz.html next to this script)")
    args = ap.parse_args()

    rows = load_rows(args.csv)
    if not rows:
        raise SystemExit(f"no rows in {args.csv}")
    out = Path(args.out)
    out.write_text(build_html(rows, Path(args.csv).name))
    print(f"wrote {out} ({len(rows)} runs, "
          f"{sum(1 for r in rows if not r['invalid'])} valid)")


if __name__ == "__main__":
    main()
