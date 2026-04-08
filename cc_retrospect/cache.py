"""cc-retrospect cache — Session cache management and live state."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

from cc_retrospect.config import Config
from cc_retrospect.models import SessionSummary, LiveSessionState
from cc_retrospect.parsers import iter_jsonl, analyze_session

logger = logging.getLogger("cc_retrospect")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically using temp file + os.replace to avoid corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, suffix='.tmp', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        temp_path = f.name
    try:
        os.replace(temp_path, path)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def _is_valid_session_id(session_id: str) -> bool:
    """Validate session ID format."""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', session_id))


def load_all_sessions(config: Config, project_filter: str | None = None) -> list[SessionSummary]:
    from cc_retrospect.parsers import iter_project_sessions
    from cc_retrospect.utils import display_project

    cache_path = config.data_dir / "sessions.jsonl"
    cached: dict[str, SessionSummary] = {}
    if cache_path.exists():
        for entry in iter_jsonl(cache_path):
            try:
                s = SessionSummary.model_validate(entry)
                cached[s.session_id] = s
            except Exception as e:
                logger.debug("Skipping malformed cache entry: %s", e)
    sessions, new_summaries = [], []
    for proj_name, jsonl_path in iter_project_sessions(config.claude_dir):
        if project_filter and project_filter.lower() not in display_project(proj_name).lower():
            continue
        key = jsonl_path.stem
        if key in cached:
            sessions.append(cached[key])
        else:
            summary = analyze_session(jsonl_path, proj_name, config)
            sessions.append(summary); new_summaries.append(summary)
    if new_summaries:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "a", encoding="utf-8") as f:
            for s in new_summaries: f.write(s.model_dump_json() + "\n")
    return sessions


# --- Live session state ---

def _live_state_path(config: Config) -> Path:
    return config.data_dir / "live_session.json"


def _init_live_state(config: Config) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    _live_state_path(config).write_text(LiveSessionState().model_dump_json())


def _load_live_state(config: Config) -> LiveSessionState:
    path = _live_state_path(config)
    if path.exists():
        try: return LiveSessionState.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as e: logger.debug("Failed to load live state: %s", e)
    return LiveSessionState()


def _save_live_state(config: Config, state) -> None:
    if isinstance(state, dict): state = LiveSessionState(**{k: v for k, v in state.items() if k in LiveSessionState.model_fields})
    try: _live_state_path(config).write_text(state.model_dump_json())
    except OSError as e: logger.debug("Could not write live state: %s", e)
