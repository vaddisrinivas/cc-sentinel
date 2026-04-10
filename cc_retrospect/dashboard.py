"""Generate and serve a dashboard from cc-retrospect data."""
from __future__ import annotations

import json
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from cc_retrospect.config import Config, load_config
from cc_retrospect.cache import load_all_sessions
from cc_retrospect.dashboard_server import PORT, ensure_running

DASHBOARD_HTML = (Path(__file__).parent / "dashboard_template.html").read_text(encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def generate_dashboard(config: Config | None = None, days: int = 30) -> str:
    """Generate dashboard JSON string with embedded data."""
    try:
        return _build_dashboard_data(config, days)
    except Exception as e:
        return json.dumps({
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "error": str(e),
            "state": {}, "sessions": [], "trends": [], "compactions": [],
            "budget_tiers": [], "days": days, "reports": [],
            "tool_usage": {}, "hourly_activity": [0]*24, "cost_by_day": {},
            "model_recommendation": {},
        }, default=str)


def _build_dashboard_data(config: Config | None = None, days: int = 30) -> str:
    """Build dashboard data JSON string."""
    config = config or load_config()

    from cc_retrospect.utils import _filter_sessions
    all_sessions_unfiltered = load_all_sessions(config)
    all_sessions = _filter_sessions(all_sessions_unfiltered, days=days, config=config)
    # Sort by date descending and exclude noise
    sessions = sorted(
        [s for s in all_sessions if s.start_ts],
        key=lambda s: s.start_ts, reverse=True,
    )

    state = _load_json(config.data_dir / "state.json")
    trends = _load_jsonl(config.data_dir / "trends.jsonl")
    compactions = _load_jsonl(config.data_dir / "compactions.jsonl")

    # Calculate today's cost from full session data (not state.json which only covers hook-fired sessions)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_cost = sum(
        s.total_cost for s in all_sessions_unfiltered
        if (s.start_ts or "")[:10] == today_str
    )
    today_by_project: dict[str, float] = {}
    for s in all_sessions_unfiltered:
        if (s.start_ts or "")[:10] == today_str:
            today_by_project[s.project] = today_by_project.get(s.project, 0) + s.total_cost
    state["today_cost"] = today_cost
    state["today_date"] = today_str
    # Replace entirely — stale entries from state.json cause overflow bars
    state["projects"] = {
        proj: {"today_date": today_str, "today_cost": cost}
        for proj, cost in today_by_project.items()
    }

    budget_tiers = [
        {"label": "Warning", "threshold": config.budget.warning.threshold, "color": "#d29922"},
        {"label": "Critical", "threshold": config.budget.critical.threshold, "color": "#d18616"},
        {"label": "Severe", "threshold": config.budget.severe.threshold, "color": "#f85149"},
    ]

    # Build reports list for Reports tab
    reports: list[dict] = []
    reports_dir = config.data_dir / "reports"
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("dashboard-*.html"), reverse=True):
            stamp = f.stem.replace("dashboard-", "")
            data_name = f"data-{stamp}.js"
            reports.append({
                "name": f.stem,
                "date": stamp.replace("_", " ").replace("-", "/", 2),
                "html_url": f"/reports/{f.name}",
                "data_url": f"/reports/{data_name}" if (reports_dir / data_name).exists() else None,
            })

    # Aggregate: tool usage
    tool_usage: dict[str, int] = {}
    for s in sessions:
        for tool, count in (s.tool_counts or {}).items():
            tool_usage[tool] = tool_usage.get(tool, 0) + count

    # Aggregate: hourly activity (24 buckets)
    hourly_activity = [0] * 24
    for s in sessions:
        if s.start_ts:
            try:
                hour = int(s.start_ts[11:13])
                hourly_activity[hour] += 1
            except (ValueError, IndexError):
                pass

    # Aggregate: cost by day
    cost_by_day: dict[str, float] = defaultdict(float)
    for s in sessions:
        day = (s.start_ts or "")[:10]
        if day:
            cost_by_day[day] += s.total_cost

    model_rec = _load_json(config.data_dir / "model_recommendation.json")

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "state": state,
        "sessions": [s.model_dump() for s in sessions],
        "trends": trends,
        "compactions": compactions,
        "budget_tiers": budget_tiers,
        "days": days,
        "reports": reports,
        "tool_usage": dict(sorted(tool_usage.items(), key=lambda x: -x[1])[:20]),
        "hourly_activity": hourly_activity,
        "cost_by_day": dict(sorted(cost_by_day.items())),
        "model_recommendation": model_rec,
    }

    data_json = json.dumps(data, default=str)
    return data_json


def run_dashboard(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Refresh data.js, ensure server is running, open browser."""
    payload = payload or {}
    config = config or load_config()
    days = payload.get("days", 30)

    data_json = generate_dashboard(config, days=days)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    data_dir = config.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    # Write latest data.js (server serves this at /data.js)
    (data_dir / "data.js").write_text(f"const D = {data_json};\n", encoding="utf-8")

    # Write latest dashboard.html template
    (data_dir / "dashboard.html").write_text(DASHBOARD_HTML, encoding="utf-8")

    # Save timestamped snapshot
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / f"data-{stamp}.js").write_text(f"const D = {data_json};\n", encoding="utf-8")
    snap_html = reports_dir / f"dashboard-{stamp}.html"
    snap_html.write_text(
        DASHBOARD_HTML.replace('src="data.js"', f'src="data-{stamp}.js"'),
        encoding="utf-8",
    )

    # Ensure server is running (starts once, persists)
    ensure_running()

    url = f"http://127.0.0.1:{PORT}/"
    print(f"Dashboard: {url}", file=sys.stderr)
    webbrowser.open(url)
    return 0
