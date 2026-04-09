"""Generate and serve a dashboard from cc-retrospect data."""
from __future__ import annotations

import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from cc_retrospect.config import Config, load_config
from cc_retrospect.cache import load_all_sessions
from cc_retrospect.dashboard_template import DASHBOARD_HTML


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
    """Generate dashboard HTML string with embedded data."""
    config = config or load_config()

    from cc_retrospect.utils import _filter_sessions
    all_sessions = load_all_sessions(config)
    all_sessions = _filter_sessions(all_sessions, days=days, config=config)
    # Sort by date descending and exclude noise
    sessions = sorted(
        [s for s in all_sessions if s.start_ts],
        key=lambda s: s.start_ts, reverse=True,
    )

    state = _load_json(config.data_dir / "state.json")
    trends = _load_jsonl(config.data_dir / "trends.jsonl")
    compactions = _load_jsonl(config.data_dir / "compactions.jsonl")

    budget_tiers = [
        {"label": "Warning", "threshold": config.budget.warning.threshold, "color": "#d29922"},
        {"label": "Critical", "threshold": config.budget.critical.threshold, "color": "#d18616"},
        {"label": "Severe", "threshold": config.budget.severe.threshold, "color": "#f85149"},
    ]

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "state": state,
        "sessions": [s.model_dump() for s in sessions],
        "trends": trends,
        "compactions": compactions,
        "budget_tiers": budget_tiers,
        "days": days,
    }

    data_json = json.dumps(data, default=str)
    return DASHBOARD_HTML.replace("__DATA_JSON__", data_json)


def run_dashboard(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Generate dashboard HTML file and open in browser."""
    payload = payload or {}
    config = config or load_config()
    days = payload.get("days", 30)

    html_content = generate_dashboard(config, days=days)

    # Always write the latest dashboard
    out_path = config.data_dir / "dashboard.html"
    out_path.write_text(html_content, encoding="utf-8")

    # Persist a timestamped snapshot + raw JSON so reports accumulate
    reports_dir = config.data_dir / "reports"
    reports_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    snapshot_path = reports_dir / f"dashboard-{stamp}.html"
    snapshot_path.write_text(html_content, encoding="utf-8")

    # Write raw data JSON (reusable without re-parsing sessions)
    # Template embeds data as: const D = __DATA_JSON__;
    script_start = html_content.find('const D = ') + len('const D = ')
    script_end = html_content.find(';\n', script_start)
    if script_start > len('const D = ') and script_end > script_start:
        (reports_dir / f"data-{stamp}.json").write_text(
            html_content[script_start:script_end], encoding="utf-8"
        )

    url = out_path.resolve().as_uri()
    print(f"Dashboard: {url}", file=sys.stderr)
    print(f"Snapshot:  {snapshot_path.resolve().as_uri()}", file=sys.stderr)
    webbrowser.open(url)
    return 0
