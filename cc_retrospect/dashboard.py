"""Generate and serve a dashboard from cc-retrospect data."""
from __future__ import annotations

import json
import signal
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
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
    """Generate dashboard and serve on localhost."""
    payload = payload or {}
    config = config or load_config()
    days = payload.get("days", 30)

    html_content = generate_dashboard(config, days=days)

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))

        def log_message(self, format, *args):
            pass  # silence request logs

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"
    print(f"Dashboard: {url} (Ctrl+C to stop)", file=sys.stderr)

    # Open browser after short delay
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    # Handle Ctrl+C gracefully
    def _shutdown(sig, frame):
        print("\nDashboard stopped.", file=sys.stderr)
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
