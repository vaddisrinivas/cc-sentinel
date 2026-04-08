"""Tests for new features: savings, model efficiency, trends, status, export,
digest, budget alerts, compaction hooks, first-run onboarding, daily digest."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _make_summary(**overrides):
    from cc_retrospect.core import SessionSummary
    defaults = dict(
        session_id="test-sess", project="testproj",
        start_ts="2026-04-05T10:00:00Z", end_ts="2026-04-05T11:00:00Z",
        duration_minutes=60.0, message_count=50,
        user_message_count=20, assistant_message_count=30,
        total_input_tokens=100_000, total_output_tokens=50_000,
        total_cache_creation_tokens=500_000, total_cache_read_tokens=5_000_000,
        total_cost=10.0, model_breakdown={"claude-opus-4-6": 10.0},
        tool_counts={"Bash": 5}, tool_chains=[], subagent_count=0,
        mega_prompt_count=0, frustration_count=0, frustration_words={},
        webfetch_domains={}, entrypoint="claude-desktop", cwd="/test", git_branch="main",
    )
    defaults.update(overrides)
    return SessionSummary(**defaults)


@pytest.fixture
def tmp_data_dir(tmp_path):
    d = tmp_path / ".cc-retrospect"
    d.mkdir()
    return d


@pytest.fixture
def config(tmp_data_dir):
    from cc_retrospect.core import Config
    return Config(data_dir=tmp_data_dir)


# ---------------------------------------------------------------------------
# SavingsAnalyzer
# ---------------------------------------------------------------------------

class TestSavingsAnalyzer:
    def test_empty_sessions(self):
        from cc_retrospect.core import SavingsAnalyzer, default_config
        result = SavingsAnalyzer().analyze([], default_config())
        assert result.title == "Savings Projections"

    def test_model_switch_savings(self):
        from cc_retrospect.core import SavingsAnalyzer, default_config
        sessions = [_make_summary(
            model_breakdown={"claude-opus-4-6": 500.0},
            tool_counts={"Read": 5, "Bash": 3},
            total_cost=500.0,
            start_ts="2026-04-01T10:00:00Z",
        ), _make_summary(
            session_id="s2",
            model_breakdown={"claude-opus-4-6": 300.0},
            tool_counts={"Read": 3},
            total_cost=300.0,
            start_ts="2026-04-05T10:00:00Z",
        )]
        result = SavingsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("sonnet" in d for d in descs)
        assert any("/mo" in r.estimated_savings for r in result.recommendations)

    def test_long_sessions_savings(self):
        from cc_retrospect.core import SavingsAnalyzer, default_config
        sessions = [_make_summary(duration_minutes=300, total_cost=200.0, start_ts="2026-04-01T10:00:00Z"),
                    _make_summary(session_id="s2", duration_minutes=250, total_cost=150.0, start_ts="2026-04-05T10:00:00Z")]
        result = SavingsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("break" in d or "long" in d for d in descs)

    def test_subagent_savings(self):
        from cc_retrospect.core import SavingsAnalyzer, default_config
        sessions = [_make_summary(subagent_count=30, start_ts="2026-04-01T10:00:00Z"),
                    _make_summary(session_id="s2", subagent_count=25, start_ts="2026-04-05T10:00:00Z")]
        result = SavingsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("agent" in d or "grep" in d for d in descs)

    def test_webfetch_savings(self):
        from cc_retrospect.core import SavingsAnalyzer, default_config
        sessions = [_make_summary(webfetch_domains={"github.com": 20}, start_ts="2026-04-01T10:00:00Z"),
                    _make_summary(session_id="s2", webfetch_domains={"github.com": 15}, start_ts="2026-04-05T10:00:00Z")]
        result = SavingsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("gh" in d or "webfetch" in d for d in descs)

    def test_oversized_prompt_savings(self):
        from cc_retrospect.core import SavingsAnalyzer, default_config
        sessions = [_make_summary(mega_prompt_count=20, start_ts="2026-04-01T10:00:00Z"),
                    _make_summary(session_id="s2", mega_prompt_count=15, start_ts="2026-04-05T10:00:00Z")]
        result = SavingsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("file" in d or "paste" in d for d in descs)

    def test_total_savings_row(self):
        from cc_retrospect.core import SavingsAnalyzer, default_config
        sessions = [_make_summary(
            model_breakdown={"claude-opus-4-6": 500.0},
            tool_counts={"Read": 5},
            total_cost=500.0,
            duration_minutes=300,
            start_ts="2026-04-01T10:00:00Z",
        ), _make_summary(session_id="s2", start_ts="2026-04-05T10:00:00Z")]
        result = SavingsAnalyzer().analyze(sessions, default_config())
        row_labels = [r[0] for s in result.sections for r in s.rows]
        assert "Total potential monthly savings" in row_labels


# ---------------------------------------------------------------------------
# ModelAnalyzer
# ---------------------------------------------------------------------------

class TestModelAnalyzer:
    def test_empty_sessions(self):
        from cc_retrospect.core import ModelAnalyzer, default_config
        result = ModelAnalyzer().analyze([], default_config())
        assert result.title == "Model Efficiency"

    def test_efficiency_score(self):
        from cc_retrospect.core import ModelAnalyzer, default_config
        sessions = [
            _make_summary(model_breakdown={"claude-opus-4-6": 100.0}, tool_counts={"Read": 5}),
            _make_summary(session_id="s2", model_breakdown={"claude-opus-4-6": 50.0}, tool_counts={"Agent": 3, "Read": 2}),
        ]
        result = ModelAnalyzer().analyze(sessions, default_config())
        row_labels = [r[0] for s in result.sections for r in s.rows]
        assert "Model efficiency score" in row_labels

    def test_mismatch_recommendation(self):
        from cc_retrospect.core import ModelAnalyzer, default_config
        sessions = [_make_summary(
            model_breakdown={"claude-opus-4-6": 200.0},
            tool_counts={"Read": 10, "Bash": 5},
            total_cost=200.0,
        )]
        result = ModelAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("sonnet" in d for d in descs)


# ---------------------------------------------------------------------------
# TrendAnalyzer + _update_trends
# ---------------------------------------------------------------------------

class TestTrendAnalyzer:
    def test_no_trends_yet(self, config):
        from cc_retrospect.core import TrendAnalyzer
        result = TrendAnalyzer().analyze([], config)
        assert any("no trend" in r.description.lower() for r in result.recommendations)

    def test_with_trend_data(self, config):
        from cc_retrospect.core import TrendAnalyzer
        trends = [
            {"week": "2026-W13", "cost": 5000, "sessions": 200, "avg_duration": 40, "frustrations": 30, "subagents": 100, "model_efficiency": 75, "compactions": 3},
            {"week": "2026-W14", "cost": 3000, "sessions": 180, "avg_duration": 35, "frustrations": 20, "subagents": 80, "model_efficiency": 82, "compactions": 5},
        ]
        (config.data_dir / "trends.jsonl").write_text("\n".join(json.dumps(t) for t in trends) + "\n")
        result = TrendAnalyzer().analyze([], config)
        assert any("W14" in r[0] for s in result.sections for r in s.rows)
        assert any("down" in r.description.lower() for r in result.recommendations)

    def test_spending_up_warning(self, config):
        from cc_retrospect.core import TrendAnalyzer
        trends = [
            {"week": "2026-W13", "cost": 1000, "sessions": 50, "avg_duration": 30, "frustrations": 5, "subagents": 10, "model_efficiency": 90, "compactions": 0},
            {"week": "2026-W14", "cost": 2000, "sessions": 80, "avg_duration": 40, "frustrations": 10, "subagents": 20, "model_efficiency": 70, "compactions": 2},
        ]
        (config.data_dir / "trends.jsonl").write_text("\n".join(json.dumps(t) for t in trends) + "\n")
        result = TrendAnalyzer().analyze([], config)
        assert any("up" in r.description.lower() for r in result.recommendations)

    def test_update_trends_creates_file(self, tmp_path):
        from cc_retrospect.core import _update_trends, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "testproj"
        proj_dir.mkdir(parents=True)
        # Write a real JSONL session file so load_all_sessions finds it
        now = datetime.now(timezone.utc)
        session_data = [
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
             "usage": {"input_tokens": 1000, "output_tokens": 500}},
             "timestamp": now.isoformat(), "sessionId": "trend-test-1"},
        ]
        (proj_dir / "trend-test-1.jsonl").write_text("\n".join(json.dumps(d) for d in session_data))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        _update_trends(cfg)
        trends_path = data_dir / "trends.jsonl"
        assert trends_path.exists()
        entries = [json.loads(line) for line in trends_path.read_text().strip().split("\n")]
        assert len(entries) == 1
        assert entries[0]["cost"] > 0

    def test_update_trends_idempotent(self, tmp_path):
        from cc_retrospect.core import _update_trends, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "testproj"
        proj_dir.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        session_data = [
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
             "usage": {"input_tokens": 1000, "output_tokens": 500}},
             "timestamp": now.isoformat(), "sessionId": "trend-test-2"},
        ]
        (proj_dir / "trend-test-2.jsonl").write_text("\n".join(json.dumps(d) for d in session_data))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        _update_trends(cfg)
        _update_trends(cfg)  # second call should be no-op
        entries = [json.loads(line) for line in (data_dir / "trends.jsonl").read_text().strip().split("\n")]
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# run_status
# ---------------------------------------------------------------------------

class TestRunStatus:
    def test_shows_data_dir(self, config, capsys):
        from cc_retrospect.core import run_status
        run_status(config=config)
        out = capsys.readouterr().out
        assert "Data directory" in out
        assert "exists" in out

    def test_shows_session_count(self, config, capsys):
        from cc_retrospect.core import run_status
        s = _make_summary()
        (config.data_dir / "sessions.jsonl").write_text(s.model_dump_json() + "\n")
        run_status(config=config)
        out = capsys.readouterr().out
        assert "Cached sessions: 1" in out

    def test_shows_pydantic_version(self, config, capsys):
        from cc_retrospect.core import run_status
        run_status(config=config)
        out = capsys.readouterr().out
        assert "pydantic:" in out


# ---------------------------------------------------------------------------
# run_export
# ---------------------------------------------------------------------------

class TestRunExport:
    def test_exports_json(self, config, capsys):
        from cc_retrospect.core import run_export
        s = _make_summary()
        (config.data_dir / "sessions.jsonl").write_text(s.model_dump_json() + "\n")
        # Need a claude_dir with projects so load_all_sessions can scan
        (config.claude_dir / "projects").mkdir(parents=True, exist_ok=True)
        run_export(config=config)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) >= 1


# ---------------------------------------------------------------------------
# run_digest
# ---------------------------------------------------------------------------

class TestRunDigest:
    def test_no_sessions(self, tmp_path, capsys):
        from cc_retrospect.core import run_digest, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        (claude_dir / "projects").mkdir(parents=True)
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        run_digest(config=cfg)
        out = capsys.readouterr().out
        assert "No sessions found" in out

    def test_with_sessions(self, config, capsys):
        from cc_retrospect.core import run_digest
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT12:00:00Z")
        s = _make_summary(start_ts=yesterday, total_cost=50.0)
        (config.data_dir / "sessions.jsonl").write_text(s.model_dump_json() + "\n")
        (config.claude_dir / "projects").mkdir(parents=True, exist_ok=True)
        run_digest(config=config)
        out = capsys.readouterr().out
        assert "Daily Digest" in out
        assert "sessions" in out.lower()


# ---------------------------------------------------------------------------
# Compaction hooks
# ---------------------------------------------------------------------------

class TestCompactionHooks:
    def test_pre_compact_logs_event(self, config):
        from cc_retrospect.core import run_pre_compact, _init_live_state
        _init_live_state(config)
        run_pre_compact({"session_id": "s1", "compact_reason": "manual"}, config=config)
        path = config.data_dir / "compactions.jsonl"
        assert path.exists()
        events = [json.loads(line) for line in path.read_text().strip().split("\n")]
        assert len(events) == 1
        assert events[0]["phase"] == "pre"
        assert events[0]["reason"] == "manual"

    def test_post_compact_logs_tokens_freed(self, config):
        from cc_retrospect.core import run_post_compact
        run_post_compact({"session_id": "s1", "compact_reason": "window_full", "tokens_freed": 50000}, config=config)
        path = config.data_dir / "compactions.jsonl"
        assert path.exists()
        events = [json.loads(line) for line in path.read_text().strip().split("\n")]
        assert len(events) == 1
        assert events[0]["tokens_freed"] == 50000

    def test_pre_compact_increments_compaction_count(self, config):
        from cc_retrospect.core import run_pre_compact, _init_live_state, _load_live_state
        _init_live_state(config)
        run_pre_compact({"session_id": "s1"}, config=config)
        live = _load_live_state(config)
        assert live.compaction_count == 1


# ---------------------------------------------------------------------------
# Budget alerting in stop_hook
# ---------------------------------------------------------------------------

class TestBudgetAlert:
    def _make_claude_dir(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-Users-test-Projects-myapp"
        proj_dir.mkdir(parents=True)
        dest = proj_dir / "sess-001.jsonl"
        dest.write_bytes((FIXTURES / "sample_session.jsonl").read_bytes())
        return claude_dir

    def test_budget_tracked_in_state(self, tmp_path):
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = self._make_claude_dir(tmp_path)
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        run_stop_hook({"session_id": "sess-001", "cwd": "/test"}, config=cfg)
        state = json.loads((data_dir / "state.json").read_text())
        assert "today_cost" in state
        assert "today_date" in state
        assert state["today_cost"] > 0

    def test_budget_accumulates_same_day(self, tmp_path):
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = self._make_claude_dir(tmp_path)
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        run_stop_hook({"session_id": "sess-001", "cwd": "/test"}, config=cfg)
        first_cost = json.loads((data_dir / "state.json").read_text())["today_cost"]
        # Run again — cost should accumulate
        run_stop_hook({"session_id": "sess-001", "cwd": "/test"}, config=cfg)
        second_cost = json.loads((data_dir / "state.json").read_text())["today_cost"]
        assert second_cost > first_cost


# ---------------------------------------------------------------------------
# First-run onboarding
# ---------------------------------------------------------------------------

class TestFirstRunOnboarding:
    def test_welcome_with_no_sessions(self, tmp_path, capsys):
        from cc_retrospect.core import run_session_start_hook, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        (claude_dir / "projects").mkdir(parents=True)
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        run_session_start_hook({"cwd": "/test"}, config=cfg)
        out = capsys.readouterr().out
        assert "Welcome" in out
        assert "No session data" in out

    def test_welcome_creates_state(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        (config.claude_dir / "projects").mkdir(parents=True, exist_ok=True)
        run_session_start_hook({"cwd": "/test"}, config=config)
        assert (config.data_dir / "state.json").exists()


# ---------------------------------------------------------------------------
# Daily digest in session_start
# ---------------------------------------------------------------------------

class TestDailyDigest:
    def test_shows_digest_on_new_day(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        # State from yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1))
        state = {
            "last_session_cost": 50.0,
            "last_session_duration_minutes": 30,
            "last_message_count": 20,
            "last_frustration_count": 0,
            "last_subagent_count": 0,
            "last_ts": yesterday.isoformat(),
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        # Add a session from yesterday for the digest to find
        s = _make_summary(start_ts=yesterday.strftime("%Y-%m-%dT12:00:00Z"), total_cost=50.0)
        (config.data_dir / "sessions.jsonl").write_text(s.model_dump_json() + "\n")
        (config.claude_dir / "projects").mkdir(parents=True, exist_ok=True)
        run_session_start_hook({"cwd": "/test"}, config=config)
        out = capsys.readouterr().out
        assert "Yesterday" in out

    def test_no_digest_same_day(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {
            "last_session_cost": 50.0,
            "last_session_duration_minutes": 30,
            "last_message_count": 20,
            "last_frustration_count": 0,
            "last_subagent_count": 0,
            "last_ts": datetime.now(timezone.utc).isoformat(),
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        run_session_start_hook({"cwd": "/test"}, config=config)
        out = capsys.readouterr().out
        assert "Yesterday" not in out


# ---------------------------------------------------------------------------
# _should_show_daily_digest
# ---------------------------------------------------------------------------

class TestShouldShowDailyDigest:
    def test_true_when_last_session_was_yesterday(self, config):
        from cc_retrospect.core import _should_show_daily_digest
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1))
        state = {"last_ts": yesterday.isoformat()}
        (config.data_dir / "state.json").write_text(json.dumps(state))
        assert _should_show_daily_digest(config) is True

    def test_false_when_last_session_was_today(self, config):
        from cc_retrospect.core import _should_show_daily_digest
        state = {"last_ts": datetime.now(timezone.utc).isoformat()}
        (config.data_dir / "state.json").write_text(json.dumps(state))
        assert _should_show_daily_digest(config) is False

    def test_false_when_no_state(self, config):
        from cc_retrospect.core import _should_show_daily_digest
        assert _should_show_daily_digest(config) is False

    def test_false_when_no_last_ts(self, config):
        from cc_retrospect.core import _should_show_daily_digest
        (config.data_dir / "state.json").write_text(json.dumps({}))
        assert _should_show_daily_digest(config) is False


# ---------------------------------------------------------------------------
# run_user_prompt — oversized prompt interception
# ---------------------------------------------------------------------------

class TestRunUserPrompt:
    def test_short_prompt_no_hint(self, config, capsys):
        from cc_retrospect.core import run_user_prompt, _init_live_state
        _init_live_state(config)
        run_user_prompt({"prompt": "fix the bug"}, config=config)
        assert capsys.readouterr().out == ""

    def test_mega_paste_detected(self, config, capsys):
        from cc_retrospect.core import run_user_prompt, _init_live_state
        _init_live_state(config)
        # Lots of newlines = paste
        prompt = "line\n" * 600
        run_user_prompt({"prompt": prompt}, config=config)
        out = capsys.readouterr().out
        assert "paste" in out.lower() or "file" in out.lower()

    def test_very_long_prompt_detected(self, config, capsys):
        from cc_retrospect.core import run_user_prompt, _init_live_state
        _init_live_state(config)
        # Long but low newline density
        prompt = "x" * 4000
        run_user_prompt({"prompt": prompt}, config=config)
        out = capsys.readouterr().out
        assert "long" in out.lower() or "file" in out.lower()

    def test_tracks_message_count(self, config):
        from cc_retrospect.core import run_user_prompt, _init_live_state, _load_live_state
        _init_live_state(config)
        run_user_prompt({"prompt": "hello"}, config=config)
        run_user_prompt({"prompt": "world"}, config=config)
        live = _load_live_state(config)
        assert live.message_count == 2

    def test_tracks_mega_count(self, config):
        from cc_retrospect.core import run_user_prompt, _init_live_state, _load_live_state
        _init_live_state(config)
        run_user_prompt({"prompt": "x" * 2000}, config=config)
        live = _load_live_state(config)
        assert live.mega_prompt_count == 1

    def test_non_string_prompt_handled(self, config):
        from cc_retrospect.core import run_user_prompt, _init_live_state
        _init_live_state(config)
        rc = run_user_prompt({"prompt": 12345}, config=config)
        assert rc == 0

    def test_hint_suppressed_when_off(self, config, capsys):
        from cc_retrospect.core import run_user_prompt, _init_live_state
        config.hints.user_prompt = False
        _init_live_state(config)
        run_user_prompt({"prompt": "line\n" * 600}, config=config)
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# run_learn, generate_style, generate_learnings, analyze_user_messages
# ---------------------------------------------------------------------------

class TestUserProfile:
    def test_analyze_empty_data(self, tmp_path):
        from cc_retrospect.core import analyze_user_messages, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        (claude_dir / "projects").mkdir(parents=True)
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        profile = analyze_user_messages(cfg)
        assert profile.total_messages == 0
        assert profile.median_length == 0

    def test_analyze_with_fixture(self, tmp_path):
        from cc_retrospect.core import analyze_user_messages, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        proj = claude_dir / "projects" / "testproj"
        proj.mkdir(parents=True)
        # Write some user + assistant messages
        entries = [
            {"type": "user", "message": {"content": "fix the bug"}, "timestamp": "2026-04-05T10:00:00Z", "sessionId": "s1"},
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [], "usage": {"input_tokens": 100, "output_tokens": 50}}, "timestamp": "2026-04-05T10:00:05Z", "sessionId": "s1"},
            {"type": "user", "message": {"content": "no thats wrong"}, "timestamp": "2026-04-05T10:01:00Z", "sessionId": "s1"},
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [], "usage": {"input_tokens": 100, "output_tokens": 50}}, "timestamp": "2026-04-05T10:01:05Z", "sessionId": "s1"},
            {"type": "user", "message": {"content": "thanks"}, "timestamp": "2026-04-05T10:02:00Z", "sessionId": "s1"},
        ]
        (proj / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in entries))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        profile = analyze_user_messages(cfg)
        assert profile.total_messages == 3
        assert profile.correction_count >= 1
        assert profile.gratitude_rate > 0

    def test_skips_subagent_sessions(self, tmp_path):
        from cc_retrospect.core import analyze_user_messages, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        proj = claude_dir / "projects" / "testproj" / "subdir" / "subagents"
        proj.mkdir(parents=True)
        entries = [
            {"type": "user", "message": {"content": "should be skipped"}, "timestamp": "2026-04-05T10:00:00Z", "sessionId": "s1"},
        ]
        (proj / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in entries))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        profile = analyze_user_messages(cfg)
        assert profile.total_messages == 0


class TestGenerateStyle:
    def test_terse_user(self):
        from cc_retrospect.core import generate_style, UserProfile
        profile = UserProfile(median_length=50, correction_count=15,
                              mega_prompt_pct=20, frustration_rate=5,
                              approval_signals={"do it": 10, "yes": 5})
        style = generate_style(profile)
        assert "concise" in style.lower()
        assert "no X" in style
        assert "do it" in style
        assert "paste" in style.lower()

    def test_verbose_user(self):
        from cc_retrospect.core import generate_style, UserProfile
        profile = UserProfile(median_length=500)
        style = generate_style(profile)
        assert "detail" in style.lower()

    def test_always_has_compression_section(self):
        from cc_retrospect.core import generate_style, UserProfile
        style = generate_style(UserProfile())
        assert "Output Compression" in style


class TestGenerateLearnings:
    def test_basic_output(self):
        from cc_retrospect.core import generate_learnings, UserProfile
        profile = UserProfile(
            total_messages=100, median_length=80,
            single_word_pct=15, correction_count=10,
            frustration_rate=5, frustration_words={"ugh": 3},
            approval_signals={"yes": 10},
            peak_hours=[10, 14, 22],
            avg_session_duration=45, avg_session_messages=80,
            top_cost_driver="model_choice", cache_hit_rate=92.5,
            top_openers=[("check", 20), ("fix", 15)],
            tool_after_frustration={"Read": 5},
        )
        learnings = generate_learnings(profile)
        assert "Communication Style" in learnings
        assert "Correction Pattern" in learnings
        assert "Approval Signals" in learnings
        assert "Frustration Response" in learnings
        assert "Work Patterns" in learnings
        assert "Cost Awareness" in learnings
        assert "model choice" in learnings.lower()

    def test_empty_profile(self):
        from cc_retrospect.core import generate_learnings, UserProfile
        learnings = generate_learnings(UserProfile())
        assert "Session Learnings" in learnings


class TestRunLearn:
    def test_generates_files(self, tmp_path, capsys):
        from cc_retrospect.core import run_learn, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        proj = claude_dir / "projects" / "testproj"
        proj.mkdir(parents=True)
        entries = [
            {"type": "user", "message": {"content": "fix this"}, "timestamp": "2026-04-05T10:00:00Z", "sessionId": "s1"},
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [], "usage": {"input_tokens": 100, "output_tokens": 50}}, "timestamp": "2026-04-05T10:00:05Z", "sessionId": "s1"},
        ]
        (proj / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in entries))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        rc = run_learn(config=cfg)
        assert rc == 0
        assert (data_dir / "STYLE.md").exists()
        assert (data_dir / "LEARNINGS.md").exists()
        out = capsys.readouterr().out
        assert "User Profile" in out
        assert "STYLE.md" in out


# ---------------------------------------------------------------------------
# Waste flags on stop hook
# ---------------------------------------------------------------------------

class TestWasteFlagsOnStop:
    def _make_claude_dir(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-Users-test-Projects-myapp"
        proj_dir.mkdir(parents=True)
        dest = proj_dir / "sess-001.jsonl"
        dest.write_bytes((FIXTURES / "sample_session.jsonl").read_bytes())
        return claude_dir

    def test_waste_flags_saved_in_state(self, tmp_path):
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = self._make_claude_dir(tmp_path)
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        cfg.hints.waste_on_stop = True
        run_stop_hook({"session_id": "sess-001", "cwd": "/test"}, config=cfg)
        state = json.loads((data_dir / "state.json").read_text())
        # sample_session.jsonl has github.com webfetch — should produce waste flags
        if "last_waste_flags" in state:
            assert any("GitHub" in f or "WebFetch" in f for f in state["last_waste_flags"])


# ---------------------------------------------------------------------------
# Daily health check in session_start
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# run_reset
# ---------------------------------------------------------------------------

class TestRunReset:
    def test_clears_all_files(self, config, capsys):
        from cc_retrospect.core import run_reset
        for name in ("sessions.jsonl", "state.json", "live_session.json", "compactions.jsonl", "trends.jsonl"):
            (config.data_dir / name).write_text("{}\n")
        run_reset(config=config)
        out = capsys.readouterr().out
        assert "Cleared" in out
        for name in ("sessions.jsonl", "state.json", "live_session.json", "compactions.jsonl", "trends.jsonl"):
            assert not (config.data_dir / name).exists()

    def test_nothing_to_clear(self, config, capsys):
        from cc_retrospect.core import run_reset
        run_reset(config=config)
        assert "Nothing to clear" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_config
# ---------------------------------------------------------------------------

class TestRunConfig:
    def test_shows_pricing(self, config, capsys):
        from cc_retrospect.core import run_config
        run_config(config=config)
        out = capsys.readouterr().out
        assert "opus" in out
        assert "sonnet" in out
        assert "15.0" in out  # default opus input price

    def test_json_output(self, config, capsys):
        from cc_retrospect.core import run_config
        run_config({"json": True}, config=config)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "pricing" in data
        assert "thresholds" in data

    def test_shows_hints(self, config, capsys):
        from cc_retrospect.core import run_config
        run_config(config=config)
        out = capsys.readouterr().out
        assert "pre_tool" in out
        assert "session_start" in out


# ---------------------------------------------------------------------------
# --json, --project, --days flags
# ---------------------------------------------------------------------------

class TestCommandFlags:
    def test_json_flag(self, config, capsys):
        from cc_retrospect.core import run_cost
        s = _make_summary()
        (config.data_dir / "sessions.jsonl").write_text(s.model_dump_json() + "\n")
        (config.claude_dir / "projects").mkdir(parents=True, exist_ok=True)
        run_cost({"json": True}, config=config)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["title"] == "Cost Analysis"

    def test_project_filter(self, tmp_path, capsys):
        from cc_retrospect.core import run_cost, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        # Create two project dirs with JSONL files
        for proj, sid, cost in [("proj-alpha", "alpha-1", 100.0), ("proj-beta", "beta-1", 50.0)]:
            pdir = claude_dir / "projects" / proj
            pdir.mkdir(parents=True)
            entry = {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
                     "usage": {"input_tokens": int(cost * 1000 / 15), "output_tokens": 100}},
                     "timestamp": "2026-04-05T10:00:00Z", "sessionId": sid}
            (pdir / f"{sid}.jsonl").write_text(json.dumps(entry))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        run_cost({"project": "alpha"}, config=cfg)
        out = capsys.readouterr().out
        assert "alpha" in out.lower()
        # beta should not appear
        assert "beta" not in out.lower()

    def test_days_filter(self, config, capsys):
        from cc_retrospect.core import run_cost
        old = _make_summary(session_id="old", start_ts="2020-01-01T10:00:00Z", total_cost=999.0)
        recent = _make_summary(session_id="new", start_ts=datetime.now(timezone.utc).isoformat(), total_cost=5.0)
        (config.data_dir / "sessions.jsonl").write_text(
            old.model_dump_json() + "\n" + recent.model_dump_json() + "\n")
        (config.claude_dir / "projects").mkdir(parents=True, exist_ok=True)
        run_cost({"days": 7}, config=config)
        out = capsys.readouterr().out
        # Should only show the recent session's cost, not $999
        assert "$999" not in out


# ---------------------------------------------------------------------------
# Trends backfill
# ---------------------------------------------------------------------------

class TestTrendsBackfill:
    def test_backfill_creates_weeks(self, tmp_path, capsys):
        from cc_retrospect.core import _backfill_trends, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        proj = claude_dir / "projects" / "testproj"
        proj.mkdir(parents=True)
        # Sessions across 2 different weeks
        entries1 = [{"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
                     "usage": {"input_tokens": 1000, "output_tokens": 500}},
                     "timestamp": "2026-03-20T10:00:00Z", "sessionId": "week1"}]
        entries2 = [{"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
                     "usage": {"input_tokens": 1000, "output_tokens": 500}},
                     "timestamp": "2026-03-27T10:00:00Z", "sessionId": "week2"}]
        (proj / "week1.jsonl").write_text(json.dumps(entries1[0]))
        (proj / "week2.jsonl").write_text(json.dumps(entries2[0]))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        _backfill_trends(cfg)
        out = capsys.readouterr().out
        assert "Backfilled" in out
        trends = [json.loads(l) for l in (data_dir / "trends.jsonl").read_text().strip().split("\n")]
        assert len(trends) >= 2

    def test_backfill_idempotent(self, tmp_path, capsys):
        from cc_retrospect.core import _backfill_trends, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        claude_dir = tmp_path / ".claude"
        proj = claude_dir / "projects" / "testproj"
        proj.mkdir(parents=True)
        entries = [{"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
                    "usage": {"input_tokens": 1000, "output_tokens": 500}},
                    "timestamp": "2026-03-20T10:00:00Z", "sessionId": "bf1"}]
        (proj / "bf1.jsonl").write_text(json.dumps(entries[0]))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        _backfill_trends(cfg)
        count1 = len((data_dir / "trends.jsonl").read_text().strip().split("\n"))
        _backfill_trends(cfg)
        count2 = len((data_dir / "trends.jsonl").read_text().strip().split("\n"))
        assert count1 == count2


# ---------------------------------------------------------------------------
# Daily health check in session_start
# ---------------------------------------------------------------------------

class TestDailyHealthCheck:
    def test_health_check_fires_once_per_day(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        config.hints.daily_health = True
        state = {
            "last_session_cost": 5.0,
            "last_session_duration_minutes": 30,
            "last_message_count": 20,
            "last_frustration_count": 0,
            "last_subagent_count": 0,
            "last_ts": datetime.now(timezone.utc).isoformat(),
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        (config.claude_dir / "projects").mkdir(parents=True, exist_ok=True)
        run_session_start_hook({"cwd": "/test"}, config=config)
        # Should have set last_health_date
        new_state = json.loads((config.data_dir / "state.json").read_text())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert new_state.get("last_health_date") == today

    def test_health_skips_if_already_done_today(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        config.hints.daily_health = True
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state = {
            "last_session_cost": 5.0,
            "last_session_duration_minutes": 30,
            "last_message_count": 20,
            "last_frustration_count": 0,
            "last_subagent_count": 0,
            "last_ts": datetime.now(timezone.utc).isoformat(),
            "last_health_date": today,
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        run_session_start_hook({"cwd": "/test"}, config=config)
        # Health section should not appear since already done today
        out = capsys.readouterr().out
        assert "Health:" not in out
