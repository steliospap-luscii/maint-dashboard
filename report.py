"""Render monthly snapshots into a single self-contained HTML report.

No external assets: all CSS is inline and every chart is hand-drawn SVG, so the
file opens anywhere (browser, screen-share, dropped into Notion as an export)
with no network access and no CSP surprises.
"""

from __future__ import annotations

import html
from datetime import datetime

# --- palette (professional light theme) ----------------------------------
INK = "#1f2430"
MUTED = "#6b7280"
BORDER = "#e6e8ef"
CARDBG = "#ffffff"
PAGEBG = "#f5f6fa"
ACCENT = "#5b6cff"
GOOD = "#16a34a"
WARN = "#d97706"
BAD = "#dc2626"

# Deeper shades than the chart palette so the white A–E letter stays legible
# (white on mid-tone green/amber fails contrast).
RATING = {1: ("A", "#15803d"), 2: ("B", "#3f6212"), 3: ("C", "#854d0e"),
          4: ("D", "#c2410c"), 5: ("E", "#b91c1c")}
SEVERITY = {"critical": "#7f1d1d", "high": "#dc2626", "medium": "#d97706", "low": "#ca8a04"}


def _month_label(ym: str) -> str:
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%b %y")
    except ValueError:
        return ym


def _fmt(v, unit="", decimals=1):
    if v is None:
        return "—"
    if isinstance(v, float):
        if decimals == 0 or v == int(v):
            return f"{int(round(v)):,}{unit}"
        return f"{v:,.{decimals}f}{unit}"
    return f"{v:,}{unit}"


# --- SVG line chart -------------------------------------------------------

def line_chart(series, y_min=None, y_max=None, color=ACCENT, unit="", goal=None, decimals=1):
    """series: list of (ym, value|None). Returns an SVG string scaled to 100% width."""
    W, H = 520, 190
    pl, pr, pt, pb = 46, 16, 18, 30
    vals = [v for _, v in series if v is not None]
    if not vals:
        return '<div class="empty">no data yet</div>'
    # The goal is NOT folded into the auto-range: a far-off goal (e.g. 100%
    # coverage vs 10% actual) would flatten the trend. The KPI card carries the
    # goal number; on the chart it's only drawn if it lands inside the range.
    lo = y_min if y_min is not None else min(vals)
    hi = y_max if y_max is not None else max(vals)
    if hi == lo:               # single distinct value (e.g. only one month yet):
        pad = max(1.0, abs(hi) * 0.06)  # spread the axis so labels stay distinct
        if y_min is None:
            lo -= pad
        if y_max is None:
            hi += pad
        if hi == lo:
            hi = lo + 1
    span = hi - lo
    if y_min is None:          # pad only the ends the caller didn't pin
        lo -= span * 0.10
    if y_max is None:
        hi += span * 0.16      # headroom for the last-value callout

    plot_w, plot_h = W - pl - pr, H - pt - pb
    n = len(series)

    def x(i):
        return pl if n == 1 else pl + i / (n - 1) * plot_w

    def y(v):
        return pt + (1 - (v - lo) / (hi - lo)) * plot_h

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" preserveAspectRatio="xMidYMid meet" role="img">']

    # gridlines + y labels
    for t in range(4):
        gy = pt + t / 3 * plot_h
        gv = hi - t / 3 * (hi - lo)
        parts.append(f'<line x1="{pl}" y1="{gy:.1f}" x2="{W-pr}" y2="{gy:.1f}" stroke="{BORDER}" stroke-width="1"/>')
        parts.append(f'<text x="{pl-8}" y="{gy+4:.1f}" text-anchor="end" class="ax">{_fmt(gv, "", decimals)}</text>')

    # goal line
    if goal is not None and lo <= goal <= hi:
        gy = y(goal)
        parts.append(f'<line x1="{pl}" y1="{gy:.1f}" x2="{W-pr}" y2="{gy:.1f}" stroke="{GOOD}" '
                     f'stroke-width="1.5" stroke-dasharray="5 4" opacity="0.7"/>')
        parts.append(f'<text x="{W-pr}" y="{gy-5:.1f}" text-anchor="end" class="goal">goal {_fmt(goal, unit, 0)}</text>')

    # area + line, split across gaps of missing months
    seg = []
    segments = []
    for i, (_, v) in enumerate(series):
        if v is None:
            if seg:
                segments.append(seg); seg = []
        else:
            seg.append((x(i), y(v)))
    if seg:
        segments.append(seg)

    for s in segments:
        if len(s) >= 2:
            pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in s)
            area = f"{s[0][0]:.1f},{pt+plot_h:.1f} " + pts + f" {s[-1][0]:.1f},{pt+plot_h:.1f}"
            parts.append(f'<polygon points="{area}" fill="{color}" opacity="0.08"/>')
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5" '
                         f'stroke-linejoin="round" stroke-linecap="round"/>')
        for px, py in s:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" fill="{color}"/>')

    # last value callout
    last_i = max(i for i, (_, v) in enumerate(series) if v is not None)
    lv = series[last_i][1]
    lx, ly = x(last_i), y(lv)
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4.5" fill="{color}"/>')
    parts.append(f'<text x="{lx:.1f}" y="{ly-12:.1f}" text-anchor="middle" class="val" fill="{color}">'
                 f'{_fmt(lv, unit, decimals)}</text>')

    # x labels (thin them out if crowded)
    step = max(1, n // 6)
    for i, (ym, _) in enumerate(series):
        if i % step == 0 or i == n - 1:
            parts.append(f'<text x="{x(i):.1f}" y="{H-8}" text-anchor="middle" class="ax">{_month_label(ym)}</text>')

    parts.append("</svg>")
    return "".join(parts)


def stacked_bar(successful, skipped, failed):
    total = (successful or 0) + (skipped or 0) + (failed or 0)
    if total == 0:
        return '<div class="empty">no test data</div>'
    segs = [("passing", successful or 0, GOOD), ("skipped", skipped or 0, WARN), ("failing", failed or 0, BAD)]
    bar, legend, x = [], [], 0.0
    for label, val, col in segs:
        w = val / total * 100
        if w > 0:
            bar.append(f'<div style="width:{w:.2f}%;background:{col}" title="{label}: {val}"></div>')
        legend.append(f'<span class="lg"><i style="background:{col}"></i>{label} '
                      f'<b>{_fmt(val,"",0)}</b></span>')
        x += w
    return (f'<div class="stack">{"".join(bar)}</div>'
            f'<div class="legend">{"".join(legend)}</div>')


def rating_badge(v):
    letter, col = RATING.get(v, ("?", MUTED))
    return f'<span class="rating" style="background:{col}">{letter}</span>'


# --- KPI cards ------------------------------------------------------------

def kpi_card(label, cur, prev, unit="", decimals=1, higher_better=True, goal=None):
    val = _fmt(cur, unit, decimals)
    delta_html = ""
    if cur is not None and prev is not None and isinstance(cur, (int, float)):
        diff = cur - prev
        if abs(diff) < 1e-9:
            delta_html = f'<span class="delta flat">▬ no change</span>'
        else:
            improving = (diff > 0) == higher_better
            col = GOOD if improving else BAD
            arrow = "▲" if diff > 0 else "▼"
            delta_html = (f'<span class="delta" style="color:{col}">{arrow} '
                          f'{_fmt(abs(diff), unit, decimals)} vs last</span>')
    goal_html = f'<span class="cgoal">goal {_fmt(goal, unit, 0)}</span>' if goal is not None else ""
    return (f'<div class="card kpi"><div class="klabel">{label}{goal_html}</div>'
            f'<div class="kval">{val}</div>{delta_html}</div>')


# --- page assembly --------------------------------------------------------

def build_report(snapshots: list[dict], cfg: dict, generated_at: str) -> str:
    """snapshots: chronologically sorted list of snapshot dicts."""
    goals = cfg.get("goals", {})
    latest = snapshots[-1]
    prev = snapshots[-2] if len(snapshots) > 1 else None
    s = latest.get("sonar") or {}
    ps = (prev or {}).get("sonar") or {} if prev else {}
    g = latest.get("github") or {}
    pg = (prev or {}).get("github") or {} if prev else {}

    def sonar_series(key):
        return [(snap["month"], (snap.get("sonar") or {}).get(key)) for snap in snapshots]

    def gh_series(key):
        return [(snap["month"], (snap.get("github") or {}).get(key)) for snap in snapshots]

    def dep_total(gd):
        return (gd or {}).get("total") if gd else None

    month_title = _month_label(latest["month"]).replace(" ", " 20") if len(latest["month"]) == 7 else latest["month"]
    try:
        month_title = datetime.strptime(latest["month"], "%Y-%m").strftime("%B %Y")
    except ValueError:
        month_title = latest["month"]

    proj = html.escape(cfg.get("project_label", s.get("project_name", "")))

    # KPI row
    kpis = "".join([
        kpi_card("Overall coverage", s.get("coverage"), ps.get("coverage"), "%",
                 higher_better=True, goal=goals.get("coverage_pct")),
        kpi_card("New-code coverage", s.get("new_coverage"), ps.get("new_coverage"), "%",
                 higher_better=True, goal=goals.get("new_coverage_pct")),
        kpi_card("Tech-debt ratio", s.get("sqale_debt_ratio"), ps.get("sqale_debt_ratio"), "%",
                 higher_better=False, goal=goals.get("max_debt_ratio_pct")),
        kpi_card("Unit tests", s.get("tests"), ps.get("tests"), decimals=0, higher_better=True),
        kpi_card("Open branches", g.get("open_branches"), pg.get("open_branches"), decimals=0,
                 higher_better=False),
        kpi_card("Dependabot alerts", dep_total(g.get("dependabot")), dep_total(pg.get("dependabot")),
                 decimals=0, higher_better=False),
    ])

    # ratings strip
    ratings = "".join([
        f'<div class="rblock">{rating_badge(s.get("reliability_rating"))}'
        f'<div><b>Reliability</b><span>{_fmt(s.get("bugs"),"",0)} bugs</span></div></div>',
        f'<div class="rblock">{rating_badge(s.get("security_rating"))}'
        f'<div><b>Security</b><span>{_fmt(s.get("vulnerabilities"),"",0)} vulns · '
        f'{_fmt(s.get("security_hotspots"),"",0)} hotspots</span></div></div>',
        f'<div class="rblock">{rating_badge(s.get("sqale_rating"))}'
        f'<div><b>Maintainability</b><span>{_fmt(s.get("code_smells"),"",0)} smells · '
        f'{_fmt(s.get("duplication"),"%")} dup</span></div></div>',
        f'<div class="rblock"><span class="rating" style="background:#4338ca">Σ</span>'
        f'<div><b>Codebase size</b><span>{_fmt(s.get("ncloc"),"",0)} lines</span></div></div>',
    ])

    # charts
    def chart_card(title, sub, svg):
        return (f'<div class="card"><div class="chdr"><h3>{title}</h3><span>{html.escape(sub)}</span></div>{svg}</div>')

    debt_hours = None
    if s.get("sqale_index_min") is not None:
        debt_hours = round(s["sqale_index_min"] / 60, 1)

    charts = "".join([
        chart_card("Coverage trend", "overall code %, monthly", line_chart(
            sonar_series("coverage"), y_min=0, color=ACCENT, unit="%",
            goal=goals.get("coverage_pct"))),
        chart_card("Tech-debt ratio", f"SonarCloud SQALE · ~{_fmt(debt_hours,'h') if debt_hours else '—'} remediation",
                   line_chart(sonar_series("sqale_debt_ratio"), y_min=0,
                              y_max=goals.get("max_debt_ratio_pct"), color=WARN, unit="%",
                              goal=goals.get("max_debt_ratio_pct"), decimals=1)),
        chart_card("Code smells", "total maintainability findings", line_chart(
            sonar_series("code_smells"), color="#8b5cf6", decimals=0)),
        chart_card("Bugs & vulnerabilities", "reliability + security findings", line_chart(
            sonar_series("bugs"), color=BAD, decimals=0)),
        chart_card("Open branches", "unmerged heads on the repo", line_chart(
            gh_series("open_branches"), color="#0891b2", decimals=0)),
        chart_card("Unit tests", "total test count over time", line_chart(
            sonar_series("tests"), color=GOOD, decimals=0)),
    ])

    # test breakdown + dependabot
    passing = None
    if s.get("tests") is not None:
        passing = s["tests"] - (s.get("skipped_tests") or 0) - (s.get("test_failures") or 0) - (s.get("test_errors") or 0)
    test_panel = stacked_bar(passing, s.get("skipped_tests"),
                             (s.get("test_failures") or 0) + (s.get("test_errors") or 0))

    dep = g.get("dependabot") or {}
    dep_rows = ""
    if dep:
        for sev in ["critical", "high", "medium", "low"]:
            cnt = dep.get(sev, 0)
            dep_rows += (f'<div class="deprow"><span class="dot" style="background:{SEVERITY[sev]}"></span>'
                         f'<span class="dsev">{sev.title()}</span><b>{cnt}</b></div>')
    else:
        dep_rows = '<div class="empty">no data</div>'

    # quality gate (neutral, informational)
    gate = s.get("gate_status", "NONE")
    gconds = s.get("gate_conditions") or []
    cond_items = "".join(
        f'<li><code>{html.escape(str(c.get("metric","")))}</code> '
        f'{html.escape(str(c.get("actual","")))} (limit {html.escape(str(c.get("threshold","")))})</li>'
        for c in gconds[:8]
    ) or "<li>no failing conditions</li>"

    sonar_url = s.get("url", "#")

    return f"""<title>Maintenance Health — {html.escape(month_title)}</title>
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:{PAGEBG}; color:{INK};
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
.wrap {{ max-width:1120px; margin:0 auto; padding:32px 24px 64px; }}
header {{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap;
  gap:12px; margin-bottom:24px; }}
h1 {{ font-size:26px; margin:0; letter-spacing:-.4px; }}
.sub {{ color:{MUTED}; font-size:14px; margin-top:4px; }}
.pill {{ background:{CARDBG}; border:1px solid {BORDER}; border-radius:999px; padding:6px 14px;
  font-size:13px; color:{MUTED}; }}
h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.8px; color:{MUTED};
  margin:32px 0 12px; }}
.grid {{ display:grid; gap:16px; }}
.kpis {{ grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); }}
.charts {{ grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); }}
.card {{ background:{CARDBG}; border:1px solid {BORDER}; border-radius:14px; padding:18px 20px;
  box-shadow:0 1px 2px rgba(16,24,40,.04); }}
.kpi .klabel {{ font-size:13px; color:{MUTED}; display:flex; justify-content:space-between; align-items:center; gap:6px; }}
.cgoal {{ font-size:11px; color:{MUTED}; background:{PAGEBG}; padding:2px 7px; border-radius:6px; }}
.kval {{ font-size:30px; font-weight:650; letter-spacing:-.6px; margin:6px 0 2px; }}
.delta {{ font-size:12.5px; font-weight:600; }}
.delta.flat {{ color:{MUTED}; font-weight:500; }}
.ratings {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
.rblock {{ display:flex; align-items:center; gap:14px; background:{CARDBG}; border:1px solid {BORDER};
  border-radius:14px; padding:16px 18px; }}
.rating {{ width:42px; height:42px; border-radius:11px; color:#fff; font-weight:800; font-size:20px;
  text-shadow:0 1px 2px rgba(0,0,0,.5); display:flex; align-items:center; justify-content:center; flex:0 0 auto; }}
.rblock b {{ display:block; font-size:14px; }}
.rblock span {{ color:{MUTED}; font-size:12.5px; }}
.chdr {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }}
.chdr h3 {{ margin:0; font-size:15px; }}
.chdr span {{ color:{MUTED}; font-size:12px; }}
svg.chart {{ width:100%; height:auto; display:block; }}
.chart text.ax {{ fill:{MUTED}; font-size:11px; }}
.chart text.val {{ font-size:13px; font-weight:700; }}
.chart text.goal {{ fill:{GOOD}; font-size:10.5px; }}
.empty {{ color:{MUTED}; font-size:13px; padding:24px 0; text-align:center; }}
.two {{ display:grid; grid-template-columns:1.4fr 1fr; gap:16px; }}
.stack {{ display:flex; height:26px; border-radius:8px; overflow:hidden; margin:8px 0 14px; }}
.stack div {{ height:100%; }}
.legend {{ display:flex; gap:18px; flex-wrap:wrap; font-size:13px; color:{MUTED}; }}
.lg i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; }}
.lg b {{ color:{INK}; }}
.deprow {{ display:flex; align-items:center; gap:10px; padding:7px 0; border-bottom:1px solid {BORDER}; }}
.deprow:last-child {{ border-bottom:none; }}
.dot {{ width:10px; height:10px; border-radius:50%; }}
.dsev {{ flex:1; }}
.deprow b {{ font-variant-numeric:tabular-nums; }}
.gate {{ display:flex; align-items:center; gap:8px; font-size:13px; color:{MUTED}; margin-bottom:8px; }}
.gate .tag {{ background:{PAGEBG}; border:1px solid {BORDER}; border-radius:6px; padding:2px 8px;
  font-weight:600; color:{INK}; }}
.gate ul {{ margin:8px 0 0; padding-left:18px; color:{MUTED}; font-size:12.5px; }}
.gate code {{ background:{PAGEBG}; padding:1px 5px; border-radius:4px; font-size:11.5px; }}
a {{ color:{ACCENT}; text-decoration:none; }}
footer {{ margin-top:36px; color:{MUTED}; font-size:12px; text-align:center; }}
</style>
<div class="wrap">
  <header>
    <div>
      <h1>Maintenance Health</h1>
      <div class="sub">{proj} · {html.escape(month_title)}</div>
    </div>
    <div class="pill">{len(snapshots)} month{"s" if len(snapshots)!=1 else ""} tracked · <a href="{html.escape(sonar_url)}">SonarCloud ↗</a></div>
  </header>

  <h2>This month at a glance</h2>
  <div class="grid kpis">{kpis}</div>

  <h2>Codebase health ratings</h2>
  <div class="ratings">{ratings}</div>

  <h2>Trends</h2>
  <div class="grid charts">{charts}</div>

  <h2>Test suite & security</h2>
  <div class="two">
    <div class="card">
      <div class="chdr"><h3>Test breakdown</h3><span>{_fmt(s.get('test_success_density'),'%')} success density</span></div>
      {test_panel}
    </div>
    <div class="card">
      <div class="chdr"><h3>Dependabot</h3><span>open alerts by severity</span></div>
      {dep_rows}
    </div>
  </div>

  <h2>Quality gate</h2>
  <div class="card gate-card">
    <div class="gate">SonarCloud new-code gate: <span class="tag">{html.escape(gate)}</span>
      <span>— informational; fails on new-code rules developers resolve, not overall health.</span></div>
    <div class="gate"><ul>{cond_items}</ul></div>
  </div>

  <footer>Generated {html.escape(generated_at)} · maint-dashboard · data from SonarCloud + GitHub</footer>
</div>
"""
