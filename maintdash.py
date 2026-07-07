#!/usr/bin/env python3
"""maint-dashboard — a local, presentable maintenance-health dashboard.

Fetches codebase-health metrics from SonarCloud + GitHub, stores one snapshot
per month, and renders a self-contained HTML report with trend charts you can
screen-share to Product Owners or paste into the monthly tactical.

Usage:
  maintdash serve      # launch the local interactive web app (Flask)
  maintdash snapshot   # fetch current metrics, store this month's snapshot
  maintdash backfill   # create monthly snapshots from real SonarCloud history
  maintdash report     # build HTML from stored snapshots and open it
  maintdash run        # snapshot + report (the usual one-liner)
  maintdash show       # print the latest snapshot as text (no fetch)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import report as report_mod
import sources

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"config not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text())


def current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def snapshot(cfg: dict) -> dict:
    print(f"→ snapshot for {current_month()}")
    token = sources.sonar_token(cfg.get("sonar"))
    if not token:
        sys.exit("no SonarCloud token (set the configured env var, or add it to the Keychain entry)")

    sonar = sources.fetch_sonar(cfg["sonar"], token)
    if sonar:
        print(f"  ✓ sonar: coverage {sonar.get('coverage')}%  tests {sonar.get('tests')}  "
              f"smells {sonar.get('code_smells')}  debt {sonar.get('sqale_debt_ratio')}%")
    github = sources.fetch_github(cfg["github"])
    if github:
        dep = github.get("dependabot") or {}
        print(f"  ✓ github: branches {github.get('open_branches')}  dependabot {dep.get('total')}")

    baselines = sources.fetch_baselines(cfg["github"])
    if baselines:
        print(f"  ✓ baselines: {baselines['total']} deferred "
              f"(detekt {baselines['detekt']} · lint {baselines['lint']})")

    snap = {
        "month": current_month(),
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sonar": sonar,
        "github": github,
        "baselines": baselines,
    }
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / f"{snap['month']}.json"
    out.write_text(json.dumps(snap, indent=2))
    print(f"  saved {out.relative_to(ROOT)}")
    return snap


def _next_month_start(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return f"{y:04d}-{m:02d}-01"


def backfill(cfg: dict):
    """Create monthly snapshots for the current year from real SonarCloud
    analysis history. Existing snapshots are kept (never overwritten), so the
    live current-month snapshot — with its GitHub + gate data — is preserved.
    Backfilled months carry Sonar metrics only; GitHub has no historical API."""
    token = sources.sonar_token(cfg.get("sonar"))
    if not token:
        sys.exit("no SonarCloud token")
    year_start = datetime.now().strftime("%Y-01-01")
    hist = sources.fetch_sonar_history(cfg["sonar"], token, year_start)
    if not hist:
        sys.exit("no history returned")

    all_dates = sorted(d for pts in hist.values() for d, _ in pts)
    first_month = all_dates[0][:7]
    now = datetime.now()
    proj_url = f'{cfg["sonar"]["base_url"].rstrip("/")}/dashboard?id={cfg["sonar"]["project_key"]}'
    label = cfg.get("project_label", cfg["sonar"]["project_key"])

    DATA_DIR.mkdir(exist_ok=True)
    ym, created, kept = first_month, 0, 0
    while ym <= now.strftime("%Y-%m"):
        path = DATA_DIR / f"{ym}.json"
        if path.exists():
            kept += 1
            print(f"  = {ym}  kept (already exists)")
        else:
            cutoff = _next_month_start(ym)  # take each metric as-of end of month
            by_metric = {}
            for metric, pts in hist.items():
                elig = sorted((d, v) for d, v in pts if d < cutoff)
                if elig:
                    by_metric[metric] = elig[-1][1]
            if by_metric:
                sonar = sources.assemble_sonar(by_metric, label, proj_url)
                snap = {"month": ym, "captured_at": None, "backfilled": True,
                        "sonar": sonar, "github": None}
                path.write_text(json.dumps(snap, indent=2))
                created += 1
                print(f"  + {ym}  coverage {sonar.get('coverage')}%  tests {sonar.get('tests')}  "
                      f"smells {sonar.get('code_smells')}  bugs {sonar.get('bugs')}")
            else:
                print(f"  ~ {ym}  no analysis yet, skipped")
        ym = _next_month_start(ym)[:7]
    print(f"backfill: {created} created, {kept} kept")


def load_snapshots() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    snaps = []
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            snaps.append(json.loads(f.read_text()))
        except (ValueError, OSError):
            print(f"  ! skipping unreadable snapshot {f.name}")
    snaps.sort(key=lambda s: s.get("month", ""))
    return snaps


def build_report(cfg: dict) -> Path:
    snaps = load_snapshots()
    if not snaps:
        sys.exit("no snapshots yet — run `maintdash snapshot` first")
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    html_body = report_mod.build_report(snaps, cfg, generated)
    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / f"maintenance-{snaps[-1]['month']}.html"
    # Wrap the body (build_report emits <title>/<style>/content) in a minimal doc.
    out.write_text(f"<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
                   f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
                   f"</head>\n<body>\n{html_body}\n</body>\n</html>\n")
    print(f"→ report: {out}")
    return out


def serve(port: str):
    """Launch the Flask web app under the project venv, provisioning it on first
    run so `maintdash serve` works even though the CLI itself is stdlib-only."""
    venv_py = ROOT / ".venv" / "bin" / "python"
    if not venv_py.exists():
        print("→ first run: creating .venv …")
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    if subprocess.run([str(venv_py), "-c", "import flask"], capture_output=True).returncode != 0:
        print("→ installing Flask into .venv …")
        subprocess.run([str(venv_py), "-m", "pip", "install", "-q", "flask"], check=True)
    env = dict(os.environ, MAINTDASH_PORT=str(port))
    subprocess.run([str(venv_py), str(ROOT / "app.py")], cwd=str(ROOT), env=env, check=False)


def show():
    snaps = load_snapshots()
    if not snaps:
        sys.exit("no snapshots yet")
    latest = snaps[-1]
    print(json.dumps(latest, indent=2))


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    cfg = load_config()

    if cmd == "serve":
        serve(args[1] if len(args) > 1 else "8765")
    elif cmd == "snapshot":
        snapshot(cfg)
    elif cmd == "backfill":
        backfill(cfg)
    elif cmd == "report":
        out = build_report(cfg)
        subprocess.run(["open", str(out)], check=False)
    elif cmd == "run":
        snapshot(cfg)
        out = build_report(cfg)
        subprocess.run(["open", str(out)], check=False)
    elif cmd == "show":
        show()
    else:
        print(__doc__)
        sys.exit(0 if cmd in ("-h", "--help", "help") else 2)


if __name__ == "__main__":
    main()
