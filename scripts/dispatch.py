#!/usr/bin/env python3
"""cc-retrospect unified dispatcher. One script handles all hooks and commands.

Usage:
  Hooks (receive JSON on stdin):
    python3 dispatch.py stop_hook
    python3 dispatch.py session_start_hook
    python3 dispatch.py pre_tool_use
    python3 dispatch.py post_tool_use

  Commands (no stdin):
    python3 dispatch.py cost
    python3 dispatch.py habits
    python3 dispatch.py health
    python3 dispatch.py tips
    python3 dispatch.py report
    python3 dispatch.py compare
    python3 dispatch.py waste
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from cc_retrospect.core import (
    run_cost, run_habits, run_health, run_tips,
    run_report, run_compare, run_waste, run_hints,
    run_savings, run_model_efficiency, run_digest,
    run_stop_hook, run_session_start_hook,
    run_pre_tool_use, run_post_tool_use,
    run_pre_compact, run_post_compact,
)

_DISPATCH = {
    # Hooks (read stdin)
    "stop_hook": run_stop_hook,
    "session_start_hook": run_session_start_hook,
    "pre_tool_use": run_pre_tool_use,
    "post_tool_use": run_post_tool_use,
    "pre_compact": run_pre_compact,
    "post_compact": run_post_compact,
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
}

_HOOKS = {"stop_hook", "session_start_hook", "pre_tool_use", "post_tool_use", "pre_compact", "post_compact"}


def _read_payload() -> dict:
    try:
        raw = sys.stdin.read().strip()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in _DISPATCH:
        print(f"Usage: dispatch.py <{'|'.join(sorted(_DISPATCH))}>" , file=sys.stderr)
        return 1

    cmd = sys.argv[1]
    payload = _read_payload() if cmd in _HOOKS else {}
    return _DISPATCH[cmd](payload)


if __name__ == "__main__":
    raise SystemExit(main())
