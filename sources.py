"""Data sources for the maintenance dashboard.

SonarCloud is read over HTTPS with a token pulled from the macOS Keychain
(the same `devhub` service the TUI uses) or the SONAR_TOKEN env var. GitHub is
read through the already-authenticated `gh` CLI, so there is no second token to
manage. Every fetch degrades gracefully: a failing source yields None rather
than aborting the whole snapshot.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# SonarCloud metric keys we snapshot. new_* metrics arrive under `periods`,
# everything else under `value` — see _measure_value below.
SONAR_METRICS = [
    "coverage", "new_coverage",
    "tests", "skipped_tests", "test_failures", "test_errors", "test_success_density",
    "code_smells", "new_code_smells",
    "security_hotspots", "bugs", "vulnerabilities",
    "reliability_rating", "security_rating", "sqale_rating",
    "sqale_debt_ratio", "sqale_index",
    "ncloc", "duplicated_lines_density", "cognitive_complexity",
]


# --- token handling -------------------------------------------------------

def sonar_token(sonar_cfg: dict | None = None) -> str | None:
    """Resolve the SonarCloud token. On macOS the login Keychain is canonical;
    the env var is the fallback (and the only path on Linux/Windows, where the
    `security` CLI simply isn't present so we fall through to it).

    Keychain wins over the env var so a stale SONAR_TOKEN in a shell profile
    can't shadow the known-good token and 401 the whole snapshot. Both the
    Keychain service/account and the env var name are configurable per project.
    """
    cfg = sonar_cfg or {}
    kc = cfg.get("keychain") or {}
    service = kc.get("service", "devhub")
    account = kc.get("account", "sonar-token")
    env_name = cfg.get("token_env", "SONAR_TOKEN")
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass  # non-macOS or no such entry — fall through to the env var
    env = os.environ.get(env_name)
    return env.strip() if env else None


# --- SonarCloud -----------------------------------------------------------

def _sonar_get(base_url: str, path: str, params: dict, token: str) -> dict:
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{base_url}{path}?{query}"
    # SonarCloud accepts the token as HTTP Basic username with an empty password.
    auth = base64.b64encode(f"{token}:".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth}",
        "User-Agent": "maint-dashboard/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _measure_value(measure: dict):
    """A measure carries its number under `value`, or under periods[0].value
    for new-code metrics. Return a float, or None."""
    if "value" in measure:
        try:
            return float(measure["value"])
        except (TypeError, ValueError):
            return None
    periods = measure.get("periods") or measure.get("period")
    if isinstance(periods, list) and periods:
        try:
            return float(periods[0]["value"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(periods, dict) and "value" in periods:
        try:
            return float(periods["value"])
        except (TypeError, ValueError):
            return None
    return None


def fetch_sonar(cfg: dict, token: str) -> dict | None:
    base = cfg["base_url"].rstrip("/")
    project = cfg["project_key"]
    try:
        measures_resp = _sonar_get(
            base, "/api/measures/component",
            {"component": project, "metricKeys": ",".join(SONAR_METRICS)}, token,
        )
    except Exception as e:  # noqa: BLE001 — any failure degrades to no snapshot
        print(f"  ! sonar measures failed: {e}")
        return None

    component = measures_resp.get("component", {})
    by_metric = {m["metric"]: _measure_value(m) for m in component.get("measures", [])}

    # Quality gate is a separate, always-readable endpoint. Kept as neutral
    # context (it fails on new-code rules devs fix), not a red alarm.
    gate_status, gate_conditions = "NONE", []
    try:
        gate = _sonar_get(base, "/api/qualitygates/project_status", {"projectKey": project}, token)
        status = gate.get("projectStatus", {})
        gate_status = status.get("status", "NONE")
        for c in status.get("conditions", []):
            if c.get("status") == "ERROR":
                gate_conditions.append({
                    "metric": c.get("metricKey"),
                    "actual": c.get("actualValue"),
                    "threshold": c.get("errorThreshold"),
                    "comparator": c.get("comparator"),
                })
    except Exception as e:  # noqa: BLE001
        print(f"  ! sonar gate failed: {e}")

    return assemble_sonar(by_metric, component.get("name", project),
                          f"{base}/dashboard?id={project}", gate_status, gate_conditions)


def assemble_sonar(by_metric: dict, project_name: str, url: str,
                   gate_status: str = "NONE", gate_conditions=None) -> dict:
    """Map a {metric: value} dict into the snapshot's sonar schema. Shared by
    live fetch and history backfill so both produce identical shapes."""
    def as_int(v):
        return int(v) if v is not None else None

    return {
        "project_name": project_name,
        "url": url,
        "gate_status": gate_status,
        "gate_conditions": gate_conditions or [],
        "coverage": by_metric.get("coverage"),
        "new_coverage": by_metric.get("new_coverage"),
        "tests": as_int(by_metric.get("tests")),
        "skipped_tests": as_int(by_metric.get("skipped_tests")),
        "test_failures": as_int(by_metric.get("test_failures")),
        "test_errors": as_int(by_metric.get("test_errors")),
        "test_success_density": by_metric.get("test_success_density"),
        "code_smells": as_int(by_metric.get("code_smells")),
        "new_code_smells": as_int(by_metric.get("new_code_smells")),
        "security_hotspots": as_int(by_metric.get("security_hotspots")),
        "bugs": as_int(by_metric.get("bugs")),
        "vulnerabilities": as_int(by_metric.get("vulnerabilities")),
        "reliability_rating": as_int(by_metric.get("reliability_rating")),
        "security_rating": as_int(by_metric.get("security_rating")),
        "sqale_rating": as_int(by_metric.get("sqale_rating")),
        "sqale_debt_ratio": by_metric.get("sqale_debt_ratio"),
        "sqale_index_min": as_int(by_metric.get("sqale_index")),
        "ncloc": as_int(by_metric.get("ncloc")),
        "duplication": by_metric.get("duplicated_lines_density"),
        "cognitive_complexity": as_int(by_metric.get("cognitive_complexity")),
    }


def fetch_sonar_history(cfg: dict, token: str, from_date: str) -> dict | None:
    """Return {metric: [(date, float), ...]} of real analysis history since
    from_date (YYYY-MM-DD). Used to backfill monthly snapshots."""
    base = cfg["base_url"].rstrip("/")
    project = cfg["project_key"]
    try:
        resp = _sonar_get(base, "/api/measures/search_history", {
            "component": project, "metrics": ",".join(SONAR_METRICS),
            "from": from_date, "ps": 1000,
        }, token)
    except Exception as e:  # noqa: BLE001
        print(f"  ! sonar history failed: {e}")
        return None
    out = {}
    for m in resp.get("measures", []):
        pts = []
        for h in m.get("history", []):
            v = h.get("value")
            if v is not None:
                try:
                    pts.append((h["date"][:10], float(v)))
                except (KeyError, ValueError):
                    pass
        if pts:
            out[m["metric"]] = pts
    return out


# --- GitHub (via gh CLI) --------------------------------------------------

def _gh(args: list[str]) -> str | None:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            return out.stdout
        print(f"  ! gh {' '.join(args)} exited {out.returncode}: {out.stderr.strip()[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"  ! gh {' '.join(args)} failed: {e}")
    return None


def fetch_github(cfg: dict) -> dict | None:
    owner, repo = cfg["owner"], cfg["repo"]
    result = {"open_branches": None, "dependabot": None}

    query = ('query($o:String!,$r:String!){repository(owner:$o,name:$r)'
             '{refs(refPrefix:"refs/heads/"){totalCount}}}')
    raw = _gh(["api", "graphql", "-f", f"query={query}", "-f", f"o={owner}", "-f", f"r={repo}"])
    if raw:
        try:
            result["open_branches"] = json.loads(raw)["data"]["repository"]["refs"]["totalCount"]
        except (KeyError, ValueError):
            pass

    raw = _gh(["api", f"/repos/{owner}/{repo}/dependabot/alerts?state=open&per_page=100"])
    if raw:
        try:
            alerts = json.loads(raw)
            counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            for a in alerts:
                sev = a.get("security_advisory", {}).get("severity", "").lower()
                if sev in counts:
                    counts[sev] += 1
            counts["total"] = len(alerts)
            result["dependabot"] = counts
        except (KeyError, ValueError, TypeError):
            pass

    if result["open_branches"] is None and result["dependabot"] is None:
        return None
    return result


def fetch_baselines(cfg: dict) -> dict | None:
    """Count the *deferred maintenance backlog* — issues suppressed in the repo's
    detekt / Android Lint baseline files. These are the style/complexity/
    maintainability findings that live outside SonarCloud (by design), so Sonar's
    smell count doesn't reflect them.

    Counts DISTINCT issue IDs across all baseline files (union, not sum): a repo
    keeps per-variant baselines (-debug/-main/-legacy) that overlap heavily, so
    summing would double-count. Union by issue identity is dedup-correct.
    """
    owner, repo = cfg["owner"], cfg["repo"]
    raw = _gh(["api", f"/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"])
    if not raw:
        return None
    try:
        tree = json.loads(raw)
    except ValueError:
        return None
    blobs = {t["path"]: t["sha"] for t in tree.get("tree", []) if t.get("type") == "blob"}
    detekt_files = [p for p in blobs if p.rsplit("/", 1)[-1].startswith("detekt-baseline") and p.endswith(".xml")]
    lint_files = [p for p in blobs if "lint-baseline" in p.rsplit("/", 1)[-1] and p.endswith(".xml")]
    if not detekt_files and not lint_files:
        return None

    def content(sha: str) -> str:
        b = _gh(["api", f"/repos/{owner}/{repo}/git/blobs/{sha}"])
        if not b:
            return ""
        try:
            return base64.b64decode(json.loads(b)["content"]).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return ""

    # detekt baseline: each suppressed finding is a <ID>Rule:signature$hash</ID>
    detekt_ids = set()
    for p in detekt_files:
        detekt_ids.update(re.findall(r"<ID>(.*?)</ID>", content(p and blobs[p]), re.S))

    # Android Lint baseline: <issue id=..><location file= line=/></issue>
    lint_ids = set()
    for p in lint_files:
        try:
            root = ET.fromstring(content(blobs[p]))
        except ET.ParseError:
            continue
        for iss in root.findall("issue"):
            loc = iss.find("location")
            lint_ids.add((iss.get("id"),
                          loc.get("file") if loc is not None else "",
                          loc.get("line") if loc is not None else ""))

    return {"detekt": len(detekt_ids), "lint": len(lint_ids),
            "total": len(detekt_ids) + len(lint_ids)}
