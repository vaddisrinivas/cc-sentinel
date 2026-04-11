#!/usr/bin/env python3
"""cc-retrospect unified dispatcher.

Usage:
  Hooks (receive JSON on stdin):
    python3 dispatch.py stop_hook
    python3 dispatch.py session_start_hook
    python3 dispatch.py pre_tool_use
    python3 dispatch.py post_tool_use
    python3 dispatch.py pre_compact
    python3 dispatch.py post_compact
    python3 dispatch.py user_prompt

  Commands (no stdin, optional flags):
    python3 dispatch.py cost [--help] [--json] [--project NAME] [--days N] [--verbose]
    python3 dispatch.py reset
    python3 dispatch.py config [--json]
    python3 dispatch.py trends --backfill
    python3 dispatch.py status
    python3 dispatch.py [--help] [--version]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from cc_retrospect.core import (
    run_cost, run_habits, run_health, run_tips,
    run_report, run_compare, run_waste, run_hints,
    run_savings, run_model_efficiency, run_digest,
    run_status, run_export, run_trends, run_learn,
    run_reset, run_config, run_uninstall, run_all, run_dashboard, run_chains,
    run_stop_hook, run_session_start_hook,
    run_pre_tool_use, run_post_tool_use,
    run_pre_compact, run_post_compact, run_user_prompt,
)

_DISPATCH = {
    # Hooks (read stdin)
    "stop_hook": run_stop_hook,
    "session_start_hook": run_session_start_hook,
    "pre_tool_use": run_pre_tool_use,
    "post_tool_use": run_post_tool_use,
    "pre_compact": run_pre_compact,
    "post_compact": run_post_compact,
    "user_prompt": run_user_prompt,
    # Commands (no stdin)
    "cost": run_cost,
    "habits": run_habits,
    "health": run_health,
    "tips": run_tips,
    "report": run_report,
    "compare": run_compare,
    "waste": run_waste,
    "hints": run_hints,
    "savings": run_savings,
    "model": run_model_efficiency,
    "digest": run_digest,
    "status": run_status,
    "export": run_export,
    "trends": run_trends,
    "learn": run_learn,
    "reset": run_reset,
    "config": run_config,
    "uninstall": run_uninstall,
    "all": run_all,
    "dashboard": run_dashboard,
    "chains": run_chains,
}

_HOOKS = {"stop_hook", "session_start_hook", "pre_tool_use", "post_tool_use", "pre_compact", "post_compact", "user_prompt"}


def _read_payload() -> dict:
    try:
        raw = sys.stdin.read().strip()
    except (OSError, ValueError):
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _parse_cli_flags() -> dict:
    """Parse --json, --project NAME, --days N, --backfill, --exclude, --verbose from sys.argv."""
    payload: dict = {}
    args = sys.argv[2:]  # skip script name and command
    i = 0
    while i < len(args):
        if args[i] == "--json":
            payload["json"] = True
        elif args[i] == "--backfill":
            payload["backfill"] = True
        elif args[i] == "--verbose":
            payload["verbose"] = True
            os.environ["CC_RETROSPECT_LOG_LEVEL"] = "DEBUG"
        elif args[i] == "--project" and i + 1 < len(args):
            payload["project"] = args[i + 1]
            i += 1
        elif args[i] == "--days" and i + 1 < len(args):
            try:
                payload["days"] = int(args[i + 1])
            except ValueError:
                pass
            i += 1
        elif args[i] == "--exclude" and i + 1 < len(args):
            payload["exclude"] = args[i + 1]
            i += 1
        i += 1
    return payload


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(f"Usage: dispatch.py <{'|'.join(sorted(_DISPATCH))}>")
        print("Flags: --help, --version, --verbose, --json, --project NAME, --days N, --exclude PATTERN")
        return 0 if len(sys.argv) >= 2 else 1

    cmd = sys.argv[1]

    if cmd == "--version":
        from cc_retrospect import __version__
        print(f"cc-retrospect {__version__}")
        return 0

    if cmd not in _DISPATCH:
        print(f"Usage: dispatch.py <{'|'.join(sorted(_DISPATCH))}>" , file=sys.stderr)
        return 1

    if cmd in _HOOKS:
        payload = _read_payload()
    else:
        payload = _parse_cli_flags()
    return _DISPATCH[cmd](payload)


if __name__ == "__main__":
    raise SystemExit(main())
