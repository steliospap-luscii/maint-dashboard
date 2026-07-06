"""Local interactive web app for the maintenance dashboard.

Reuses the same data pipeline as the CLI (maintdash/sources/report): the browser
talks to this local Flask server, which fetches from SonarCloud/GitHub, stores
monthly snapshots, and can regenerate the shareable PO report on demand.

Run via `maintdash serve` (which launches it under the project venv).
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, send_file

import maintdash

app = Flask(__name__)
# Don't let the browser cache styles.css / app.js — otherwise edits to the UI
# silently show stale (a hard-reload would be needed on every change).
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/data")
def api_data():
    """All stored snapshots (chronological) plus config — the app's data feed."""
    return jsonify({
        "config": maintdash.load_config(),
        "snapshots": maintdash.load_snapshots(),
    })


@app.post("/api/snapshot")
def api_snapshot():
    """Fetch fresh metrics and store this month's snapshot."""
    try:
        snap = maintdash.snapshot(maintdash.load_config())
    except SystemExit as e:  # snapshot() exits on missing token
        return jsonify({"ok": False, "error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "month": snap["month"],
                    "snapshots": maintdash.load_snapshots()})


@app.post("/api/report")
def api_report():
    """Regenerate the self-contained PO report from stored snapshots."""
    try:
        out = maintdash.build_report(maintdash.load_config())
    except SystemExit as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "path": str(out)})


@app.get("/report")
def report_view():
    """Serve the shareable report (build one first if none exists)."""
    reports = sorted(maintdash.REPORTS_DIR.glob("*.html"))
    if not reports:
        maintdash.build_report(maintdash.load_config())
        reports = sorted(maintdash.REPORTS_DIR.glob("*.html"))
    return send_file(reports[-1])


if __name__ == "__main__":
    port = int(os.environ.get("MAINTDASH_PORT", "8765"))
    if os.environ.get("MAINTDASH_OPEN", "1") == "1":
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"→ maint-dashboard web app on http://127.0.0.1:{port}  (Ctrl-C to stop)")
    app.run(host="127.0.0.1", port=port, threaded=True)
