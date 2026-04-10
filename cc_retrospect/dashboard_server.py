"""Persistent localhost dashboard server for cc-retrospect.

Runs on 127.0.0.1:7731 as a background daemon.
- Serves dashboard.html and data.js from ~/.cc-retrospect/
- /api/reload   — regenerate data.js from live session data
- /api/reports  — list saved report snapshots
- /api/config   — GET/POST ~/.cc-retrospect/config.env
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

PORT = int(os.environ.get("CC_RETROSPECT_PORT", "7731"))
_data_dir: Path = Path.home() / ".cc-retrospect"
logger = logging.getLogger("cc_retrospect.server")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if os.environ.get("CC_RETROSPECT_SERVER_LOG"):
            logger.info(fmt, *args)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._file(_data_dir / "dashboard.html", "text/html")
        elif p == "/data.js":
            self._file(_data_dir / "data.js", "application/javascript")
        elif p.startswith("/reports/"):
            name = p[9:]
            self._file(_data_dir / "reports" / name, _mime(name))
        elif p == "/api/reports":
            self._json(_list_reports())
        elif p == "/api/config":
            self._json({"config": _read_config()})
        elif p == "/api/reload":
            self._reload()
        elif p == "/api/sessions":
            self._reload_and_respond_sessions()
        elif p == "/api/health":
            self._json({"status": "ok", "port": PORT, "data_dir": str(_data_dir)})
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/config":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            _write_config(body.get("config", ""))
            self._json({"ok": True})
        elif p == "/api/reload":
            self._reload()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _reload(self):
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from cc_retrospect.dashboard import generate_dashboard
            from cc_retrospect.config import load_config
            cfg = load_config()
            data_json = generate_dashboard(cfg)
            (_data_dir / "data.js").write_text(f"const D = {data_json};\n", encoding="utf-8")
            self._json({"ok": True})
        except (OSError, ImportError, ValueError) as e:
            self._json({"ok": False, "error": str(e)}, 500)

    def _reload_and_respond_sessions(self):
        try:
            from cc_retrospect.config import load_config
            from cc_retrospect.cache import load_all_sessions
            cfg = load_config()
            sessions = load_all_sessions(cfg)
            data = [s.model_dump() for s in sessions[-100:]]
            self._json({"sessions": data, "count": len(sessions)})
        except (OSError, ImportError, ValueError) as e:
            self._json({"error": str(e)}, 500)

    def _file(self, path: Path, mime: str):
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(data))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def _mime(name: str) -> str:
    if name.endswith(".js"):
        return "application/javascript"
    if name.endswith(".html"):
        return "text/html"
    return "text/plain"


def _list_reports() -> list[dict]:
    reports_dir = _data_dir / "reports"
    if not reports_dir.exists():
        return []
    out = []
    for f in sorted(reports_dir.glob("dashboard-*.html"), reverse=True):
        stamp = f.stem.replace("dashboard-", "")
        data_name = f"data-{stamp}.js"
        out.append({
            "name": f.stem,
            "date": stamp.replace("_", " ").replace("-", "/", 2),
            "html_url": f"/reports/{f.name}",
            "data_url": f"/reports/{data_name}" if (reports_dir / data_name).exists() else None,
        })
    return out


def _read_config() -> str:
    p = _data_dir / "config.env"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return (
        "# cc-retrospect config\n"
        "# Pricing ($ per million tokens)\n"
        "# PRICING__SONNET__INPUT_PER_MTOK=3.0\n"
        "# PRICING__SONNET__OUTPUT_PER_MTOK=15.0\n"
        "# PRICING__OPUS__INPUT_PER_MTOK=15.0\n"
        "# PRICING__OPUS__OUTPUT_PER_MTOK=75.0\n\n"
        "# Budget thresholds ($)\n"
        "# BUDGET__WARNING__THRESHOLD=75\n"
        "# BUDGET__CRITICAL__THRESHOLD=200\n"
        "# BUDGET__SEVERE__THRESHOLD=400\n"
    )


def _write_config(content: str):
    (_data_dir / "config.env").write_text(content, encoding="utf-8")


def pid_file() -> Path:
    return _data_dir / "dashboard.pid"


def is_running() -> bool:
    p = pid_file()
    if not p.exists():
        return False
    try:
        pid = int(p.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        p.unlink(missing_ok=True)
        return False


def start_server():
    """Fork a daemon server process. Returns immediately."""
    import subprocess
    _data_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, __file__, str(_data_dir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file().write_text(str(proc.pid))


def stop_server():
    """Kill the running server if any."""
    p = pid_file()
    if not p.exists():
        return
    try:
        pid = int(p.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        pass
    p.unlink(missing_ok=True)


def ensure_running():
    """Start server if not already running."""
    if not is_running():
        start_server()
        import time; time.sleep(0.6)  # brief wait for bind


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _data_dir = Path(sys.argv[1])
    httpd = HTTPServer(("127.0.0.1", PORT), _Handler)
    def _shutdown(sig, frame):
        httpd.shutdown()
        pid_file().unlink(missing_ok=True)
        sys.exit(0)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    httpd.serve_forever()
