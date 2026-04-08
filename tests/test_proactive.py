"""Tests for proactive features: PreToolUse, PostToolUse, enhanced SessionStart."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data dir for cc-retrospect state."""
    data_dir = tmp_path / ".cc-retrospect"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def config(tmp_data_dir):
    from cc_retrospect.core import Config
    return Config(data_dir=tmp_data_dir)


class TestPreToolUse:
    """PreToolUse hook should intercept waste in real-time."""

    def test_webfetch_github_hint(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_pre_tool_use({
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://github.com/org/repo/issues/42"},
            })
        out = capsys.readouterr().out
        assert "gh" in out.lower() or "github" in out.lower()

    def test_no_hint_for_non_github_webfetch(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_pre_tool_use({
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://docs.python.org/3/library/json.html"},
            })
        out = capsys.readouterr().out
        assert out == ""

    def test_agent_simple_search_hint(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_pre_tool_use({
                "tool_name": "Agent",
                "tool_input": {"prompt": "search for the login function", "subagent_type": "Explore"},
            })
        out = capsys.readouterr().out
        assert "grep" in out.lower() or "search" in out.lower()

    def test_bash_chain_detection(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            # Simulate 5 consecutive Bash calls
            for i in range(5):
                run_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": f"cmd{i}"}})
        out = capsys.readouterr().out
        assert "consecutive" in out.lower() or "combining" in out.lower() or "bash" in out.lower()

    def test_no_hint_for_short_bash_chain(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "ls"}})
            run_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "pwd"}})
        out = capsys.readouterr().out
        assert "combining" not in out.lower()


class TestPostToolUse:
    """PostToolUse hook should track session health and nudge compact."""

    def test_compact_nudge_at_150(self, config, capsys):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        # Fast-forward to 149 messages
        live = _load_live_state(config)
        live["tool_count"] = 149
        _save_live_state(config, live)

        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_post_tool_use({"tool_name": "Read"})
        out = capsys.readouterr().out
        assert "compact" in out.lower() or "150" in out

    def test_no_nudge_before_150(self, config, capsys):
        from cc_retrospect.core import run_post_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_post_tool_use({"tool_name": "Read"})
        out = capsys.readouterr().out
        assert out == ""

    def test_subagent_warning(self, config, capsys):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        live = _load_live_state(config)
        live["subagent_count"] = 9  # one below threshold
        _save_live_state(config, live)

        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_post_tool_use({"tool_name": "Agent"})
        out = capsys.readouterr().out
        assert "subagent" in out.lower() or "agent" in out.lower()

    def test_tracks_tool_count(self, config):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state
        _init_live_state(config)
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_post_tool_use({"tool_name": "Read"})
            run_post_tool_use({"tool_name": "Edit"})
            run_post_tool_use({"tool_name": "Bash"})
        live = _load_live_state(config)
        assert live["tool_count"] == 3
        assert live["message_count"] == 0


class TestEnhancedSessionStart:
    """SessionStart should inject last-session summary + tips."""

    def test_injects_last_session_summary(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {
            "last_session_cost": 87.30,
            "last_session_duration_minutes": 192,
            "last_message_count": 350,
            "last_frustration_count": 5,
            "last_subagent_count": 2,
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        out = capsys.readouterr().out
        assert "cc-retrospect" in out
        assert "192" in out or "3h" in out  # duration
        assert "87" in out  # cost

    def test_first_run_shows_welcome(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        out = capsys.readouterr().out
        assert "Welcome" in out or out == ""  # Welcome if sessions found, empty if not

    def test_tips_for_long_expensive_session(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {
            "last_session_cost": 250.0,
            "last_session_duration_minutes": 300,
            "last_message_count": 500,
            "last_frustration_count": 8,
            "last_subagent_count": 15,
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        with patch("cc_retrospect.hooks.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        out = capsys.readouterr().out
        # Should mention: duration, cost, frustration, subagents
        assert "sonnet" in out.lower() or "model" in out.lower()
        assert "fresh" in out.lower() or "clear" in out.lower() or "session" in out.lower()


class TestDispatcher:
    """The single dispatch.py should route all commands."""

    def test_dispatch_map_complete(self):
        # Import the dispatch module to verify all commands are mapped
        sys.path.insert(0, str(ROOT / "scripts"))
        import importlib
        dispatch = importlib.import_module("dispatch")
        expected = {"stop_hook", "session_start_hook", "pre_tool_use", "post_tool_use",
                    "pre_compact", "post_compact", "user_prompt",
                    "cost", "habits", "health", "tips", "report", "compare", "waste", "hints",
                    "savings", "model", "digest", "status", "export", "trends", "learn",
                    "reset", "config", "uninstall"}
        assert expected == set(dispatch._DISPATCH.keys())
