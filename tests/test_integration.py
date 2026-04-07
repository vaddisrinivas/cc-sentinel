"""End-to-end integration tests for cc-sentinel.

These tests exercise full pipelines: JSONL parsing → analysis → caching →
hooks → report generation. Each test spins up an isolated temp directory so
nothing touches the real ~/.claude or ~/.cc-sentinel directories.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_claude_dir(base: Path) -> Path:
    """Return a simulated ~/.claude directory under *base*."""
    d = base / ".claude"
    (d / "projects").mkdir(parents=True)
    return d


def _write_session(projects_dir: Path, proj_name: str, session_id: str, lines: list[str]) -> Path:
    """Write a JSONL session file and return its path."""
    proj_dir = projects_dir / proj_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    path = proj_dir / f"{session_id}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _minimal_assistant(session_id: str, ts: str, model: str = "claude-opus-4-6",
                        input_tokens: int = 1000, output_tokens: int = 100,
                        tool_name: str | None = None) -> str:
    content = [{"type": "text", "text": "ok"}]
    if tool_name:
        content = [{"type": "tool_use", "id": "tu1", "name": tool_name, "input": {}}]
    return json.dumps({
        "type": "assistant",
        "sessionId": session_id,
        "timestamp": ts,
        "entrypoint": "claude-desktop",
        "cwd": "/test",
        "gitBranch": "main",
        "message": {
            "model": model,
            "id": "msg_x",
            "role": "assistant",
            "content": content,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    })


def _user_msg(session_id: str, ts: str, text: str) -> str:
    return json.dumps({
        "type": "user",
        "sessionId": session_id,
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    })


@pytest.fixture
def tmp_env(tmp_path):
    """Return (claude_dir, data_dir, Config) all wired to tmp_path."""
    from cc_sentinel.core import Config
    claude_dir = _build_claude_dir(tmp_path)
    data_dir = tmp_path / ".cc-sentinel"
    data_dir.mkdir()
    config = Config(data_dir=data_dir, claude_dir=claude_dir)
    return claude_dir, data_dir, config


# ===========================================================================
# 1. Stop hook — full write pipeline
# ===========================================================================

class TestStopHookPipeline:
    """run_stop_hook should analyze the session JSONL, write sessions.jsonl, and update state.json."""

    def _setup_session(self, claude_dir: Path, session_id: str = "integ-stop-001") -> None:
        lines = [
            _user_msg(session_id, "2026-04-06T10:00:00Z", "do something"),
            _minimal_assistant(session_id, "2026-04-06T10:00:05Z", input_tokens=2000, output_tokens=200),
            _user_msg(session_id, "2026-04-06T10:05:00Z", "ugh"),
            _minimal_assistant(session_id, "2026-04-06T10:05:10Z", input_tokens=2500, output_tokens=300),
        ]
        _write_session(claude_dir / "projects", "-test-myapp", session_id, lines)

    def test_stop_hook_writes_sessions_cache(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        session_id = "integ-stop-001"
        self._setup_session(claude_dir, session_id)

        from cc_sentinel.core import run_stop_hook
        rc = run_stop_hook({"session_id": session_id, "cwd": "/test/myapp"}, config=config)

        assert rc == 0
        cache_path = data_dir / "sessions.jsonl"
        assert cache_path.exists(), "sessions.jsonl should be created"
        lines = [l for l in cache_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        cached = json.loads(lines[0])
        assert cached["session_id"] == session_id

    def test_stop_hook_writes_state_json(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        session_id = "integ-stop-002"
        self._setup_session(claude_dir, session_id)

        from cc_sentinel.core import run_stop_hook
        run_stop_hook({"session_id": session_id, "cwd": "/test/myapp"}, config=config)

        state_path = data_dir / "state.json"
        assert state_path.exists(), "state.json should be created"
        state = json.loads(state_path.read_text())
        assert state["last_session_id"] == session_id
        assert state["last_session_cost"] > 0
        assert "last_ts" in state

    def test_stop_hook_ignores_missing_session_id(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        from cc_sentinel.core import run_stop_hook
        rc = run_stop_hook({"cwd": "/test/myapp"}, config=config)  # no session_id
        assert rc == 0
        assert not (data_dir / "sessions.jsonl").exists()

    def test_stop_hook_ignores_nonexistent_session_file(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        from cc_sentinel.core import run_stop_hook
        rc = run_stop_hook({"session_id": "ghost-session-999", "cwd": "/test/myapp"}, config=config)
        assert rc == 0
        assert not (data_dir / "sessions.jsonl").exists()

    def test_stop_hook_preserves_existing_state_keys(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        session_id = "integ-stop-003"
        self._setup_session(claude_dir, session_id)

        # Pre-populate state with a custom key
        existing_state = {"custom_key": "should_survive", "old_cost": 5.0}
        (data_dir / "state.json").write_text(json.dumps(existing_state))

        from cc_sentinel.core import run_stop_hook
        run_stop_hook({"session_id": session_id, "cwd": "/test/myapp"}, config=config)

        state = json.loads((data_dir / "state.json").read_text())
        assert state.get("custom_key") == "should_survive"
        assert "last_session_id" in state  # new key also present


# ===========================================================================
# 2. load_all_sessions — caching & incremental updates
# ===========================================================================

class TestLoadAllSessionsCache:
    """load_all_sessions should build a cache and re-use it on subsequent calls."""

    def _populate_project(self, claude_dir: Path, proj: str, session_id: str, ts_start: str, ts_end: str) -> None:
        lines = [
            _user_msg(session_id, ts_start, "hello"),
            _minimal_assistant(session_id, ts_end, input_tokens=500, output_tokens=50),
        ]
        _write_session(claude_dir / "projects", proj, session_id, lines)

    def test_first_load_builds_cache(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._populate_project(claude_dir, "proj-a", "s-001", "2026-04-01T10:00:00Z", "2026-04-01T10:01:00Z")

        from cc_sentinel.core import load_all_sessions
        sessions = load_all_sessions(config)

        assert len(sessions) == 1
        assert sessions[0].session_id == "s-001"
        assert (data_dir / "sessions.jsonl").exists()

    def test_second_load_uses_cache(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._populate_project(claude_dir, "proj-a", "s-002", "2026-04-01T10:00:00Z", "2026-04-01T10:02:00Z")

        from cc_sentinel.core import load_all_sessions, analyze_session
        load_all_sessions(config)  # builds cache

        # Patch analyze_session so we can tell if it's called again
        call_count = []
        original = analyze_session
        def counting_analyze(*args, **kwargs):
            call_count.append(1)
            return original(*args, **kwargs)

        with patch("cc_sentinel.core.analyze_session", side_effect=counting_analyze):
            sessions = load_all_sessions(config)

        assert len(sessions) == 1
        assert len(call_count) == 0, "analyze_session should NOT be called again for cached session"

    def test_incremental_cache_update(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._populate_project(claude_dir, "proj-a", "s-003", "2026-04-01T10:00:00Z", "2026-04-01T10:01:00Z")

        from cc_sentinel.core import load_all_sessions
        sessions1 = load_all_sessions(config)
        assert len(sessions1) == 1

        # Add a second session
        self._populate_project(claude_dir, "proj-a", "s-004", "2026-04-02T10:00:00Z", "2026-04-02T10:02:00Z")
        sessions2 = load_all_sessions(config)

        assert len(sessions2) == 2
        ids = {s.session_id for s in sessions2}
        assert "s-003" in ids
        assert "s-004" in ids

    def test_project_filter_excludes_non_matching(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._populate_project(claude_dir, "-Users-dev-Projects-frontend", "s-front", "2026-04-01T10:00:00Z", "2026-04-01T10:01:00Z")
        self._populate_project(claude_dir, "-Users-dev-Projects-backend", "s-back", "2026-04-01T11:00:00Z", "2026-04-01T11:01:00Z")

        from cc_sentinel.core import load_all_sessions
        sessions = load_all_sessions(config, project_filter="frontend")

        assert all("frontend" in s.project for s in sessions)
        ids = {s.session_id for s in sessions}
        assert "s-front" in ids
        assert "s-back" not in ids


# ===========================================================================
# 3. Multi-project analysis
# ===========================================================================

class TestMultiProjectAnalysis:
    """Cost and health analyzers should handle multiple projects correctly."""

    def _populate(self, claude_dir: Path) -> None:
        for proj, sid, cost_tokens in [
            ("-proj-alpha", "alpha-001", 500_000),
            ("-proj-beta", "beta-001", 200_000),
            ("-proj-gamma", "gamma-001", 50_000),
        ]:
            lines = [
                _user_msg(sid, "2026-04-05T10:00:00Z", "work"),
                _minimal_assistant(sid, "2026-04-05T10:01:00Z", input_tokens=cost_tokens, output_tokens=10_000),
            ]
            _write_session(claude_dir / "projects", proj, sid, lines)

    def test_all_projects_loaded(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._populate(claude_dir)
        from cc_sentinel.core import load_all_sessions
        sessions = load_all_sessions(config)
        assert len(sessions) == 3

    def test_cost_analyzer_covers_all_projects(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._populate(claude_dir)
        from cc_sentinel.core import load_all_sessions, CostAnalyzer
        sessions = load_all_sessions(config)
        result = CostAnalyzer().analyze(sessions, config)
        text = result.render_text()
        assert "alpha" in text.lower()
        assert "beta" in text.lower()
        assert "gamma" in text.lower()

    def test_total_cost_is_sum_of_sessions(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._populate(claude_dir)
        from cc_sentinel.core import load_all_sessions
        sessions = load_all_sessions(config)
        total = sum(s.total_cost for s in sessions)
        assert total > 0
        # alpha (500K input tokens) should dominate
        alpha_session = next(s for s in sessions if "alpha" in s.project)
        assert alpha_session.total_cost > sum(
            s.total_cost for s in sessions if "alpha" not in s.project
        )


# ===========================================================================
# 4. Report generation — writes a file and includes all analyzer sections
# ===========================================================================

class TestReportGeneration:
    """run_report should write a markdown file and include all analyzer sections."""

    def _populate(self, claude_dir: Path) -> None:
        lines = [
            _user_msg("rep-001", "2026-04-05T10:00:00Z", "task"),
            _minimal_assistant("rep-001", "2026-04-05T10:01:00Z"),
        ]
        _write_session(claude_dir / "projects", "-test-project", "rep-001", lines)

    def test_report_file_is_created(self, tmp_env, capsys):
        claude_dir, data_dir, config = tmp_env
        self._populate(claude_dir)
        from cc_sentinel.core import run_report
        rc = run_report({}, config=config)
        assert rc == 0
        reports = list((data_dir / "reports").glob("report-*.md"))
        assert len(reports) == 1

    def test_report_contains_all_sections(self, tmp_env, capsys):
        claude_dir, data_dir, config = tmp_env
        self._populate(claude_dir)
        from cc_sentinel.core import run_report
        run_report({}, config=config)
        report_path = sorted((data_dir / "reports").glob("report-*.md"))[0]
        content = report_path.read_text()
        for section in ["Cost", "Habits", "Health", "Waste", "Tips", "Week"]:
            assert section in content, f"Report missing '{section}' section"

    def test_report_is_valid_markdown(self, tmp_env, capsys):
        claude_dir, data_dir, config = tmp_env
        self._populate(claude_dir)
        from cc_sentinel.core import run_report
        run_report({}, config=config)
        report_path = sorted((data_dir / "reports").glob("report-*.md"))[0]
        content = report_path.read_text()
        assert content.startswith("# cc-sentinel Report")
        assert "---" in content  # section separators


# ===========================================================================
# 5. Custom analyzer discovery
# ===========================================================================

class TestCustomAnalyzerDiscovery:
    """Analyzers dropped in data_dir/analyzers/*.py should be auto-discovered."""

    def _write_custom_analyzer(self, data_dir: Path) -> None:
        analyzers_dir = data_dir / "analyzers"
        analyzers_dir.mkdir()
        code = textwrap.dedent("""\
            from cc_sentinel.core import AnalysisResult, Section, Recommendation

            class MyCustomAnalyzer:
                name = "custom-test"
                description = "Integration test custom analyzer"

                def analyze(self, sessions, config):
                    return AnalysisResult(
                        title="Custom Test",
                        sections=[Section(header="Summary", rows=[("Sessions", str(len(sessions)))])],
                        recommendations=[],
                    )
        """)
        (analyzers_dir / "my_custom.py").write_text(code)

    def test_custom_analyzer_is_discovered(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._write_custom_analyzer(data_dir)
        from cc_sentinel.core import get_analyzers
        analyzers = get_analyzers(config)
        names = [a.name for a in analyzers]
        assert "custom-test" in names

    def test_custom_analyzer_produces_result(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._write_custom_analyzer(data_dir)
        from cc_sentinel.core import get_analyzers, SessionSummary
        analyzers = get_analyzers(config)
        custom = next(a for a in analyzers if a.name == "custom-test")
        result = custom.analyze([], config)
        assert result.title == "Custom Test"

    def test_broken_custom_analyzer_does_not_crash(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        analyzers_dir = data_dir / "analyzers"
        analyzers_dir.mkdir()
        (analyzers_dir / "broken.py").write_text("this is not valid python !!!")
        from cc_sentinel.core import get_analyzers
        # Should not raise — broken file is skipped with a warning
        analyzers = get_analyzers(config)
        names = [a.name for a in analyzers]
        assert "broken" not in names

    def test_builtin_analyzers_still_present_with_custom(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        self._write_custom_analyzer(data_dir)
        from cc_sentinel.core import get_analyzers
        analyzers = get_analyzers(config)
        names = [a.name for a in analyzers]
        for builtin in ["cost", "habits", "health", "waste", "tips", "compare"]:
            assert builtin in names, f"Built-in analyzer '{builtin}' missing after custom discovery"


# ===========================================================================
# 6. Full session lifecycle — hooks in sequence
# ===========================================================================

class TestFullSessionLifecycle:
    """Simulate a complete session: start → tool calls → stop → start again."""

    def test_lifecycle_updates_live_state(self, tmp_env):
        claude_dir, data_dir, config = tmp_env

        from cc_sentinel.core import (
            _init_live_state, _load_live_state,
            run_pre_tool_use, run_post_tool_use,
        )
        _init_live_state(config)
        run_post_tool_use({"tool_name": "Read"}, config=config)
        run_post_tool_use({"tool_name": "Edit"}, config=config)
        run_post_tool_use({"tool_name": "Bash"}, config=config)

        live = _load_live_state(config)
        assert live["tool_count"] == 3
        assert live["message_count"] == 3

    def test_lifecycle_subagent_tracking(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        from cc_sentinel.core import _init_live_state, _load_live_state, run_post_tool_use
        _init_live_state(config)
        for _ in range(5):
            run_post_tool_use({"tool_name": "Agent"}, config=config)

        live = _load_live_state(config)
        assert live["subagent_count"] == 5

    def test_lifecycle_stop_hook_after_tools(self, tmp_env):
        """After tool calls, stop hook should persist the session summary."""
        claude_dir, data_dir, config = tmp_env
        session_id = "lifecycle-001"
        lines = [
            _user_msg(session_id, "2026-04-06T12:00:00Z", "start"),
            _minimal_assistant(session_id, "2026-04-06T12:00:10Z", input_tokens=3000, output_tokens=300),
            _minimal_assistant(session_id, "2026-04-06T12:05:00Z", input_tokens=3000, output_tokens=300),
        ]
        _write_session(claude_dir / "projects", "-lifecycle-proj", session_id, lines)

        from cc_sentinel.core import _init_live_state, run_post_tool_use, run_stop_hook
        _init_live_state(config)
        run_post_tool_use({"tool_name": "Read"}, config=config)
        run_post_tool_use({"tool_name": "Bash"}, config=config)
        run_stop_hook({"session_id": session_id, "cwd": "/lifecycle/proj"}, config=config)

        assert (data_dir / "sessions.jsonl").exists()
        assert (data_dir / "state.json").exists()

    def test_session_start_injects_last_session_summary(self, tmp_env, capsys):
        """After stop hook writes state, session start should show summary when hints enabled."""
        claude_dir, data_dir, config = tmp_env
        config.hints.session_start = True

        state = {
            "last_session_cost": 42.0,
            "last_session_duration_minutes": 65,
            "last_message_count": 80,
            "last_frustration_count": 2,
            "last_subagent_count": 0,
            "last_project": "test-myapp",
        }
        (data_dir / "state.json").write_text(json.dumps(state))

        from cc_sentinel.core import run_session_start_hook
        run_session_start_hook({"cwd": "/test/myapp"}, config=config)

        out = capsys.readouterr().out
        assert "cc-sentinel" in out
        assert "42" in out  # cost
        assert "65" in out or "1h" in out  # duration

    def test_session_start_silent_when_hints_disabled(self, tmp_env, capsys):
        claude_dir, data_dir, config = tmp_env
        config.hints.session_start = False  # default

        state = {"last_session_cost": 100.0, "last_session_duration_minutes": 90, "last_project": ""}
        (data_dir / "state.json").write_text(json.dumps(state))

        from cc_sentinel.core import run_session_start_hook
        run_session_start_hook({"cwd": "/any/path"}, config=config)

        out = capsys.readouterr().out
        assert out == ""


# ===========================================================================
# 7. Config file + env var override chain
# ===========================================================================

class TestConfigOverrideChain:
    """Pricing in config.env should flow through to cost calculations."""

    def test_config_file_overrides_default_pricing(self, tmp_path):
        from cc_sentinel.core import load_config
        cfg_file = tmp_path / "config.env"
        cfg_file.write_text("PRICING_SONNET_INPUT_PER_MTOK=99.0\n")
        cfg = load_config(cfg_file)
        assert cfg.pricing.sonnet.input_per_mtok == 99.0

    def test_env_var_overrides_file(self, tmp_path):
        from cc_sentinel.core import load_config
        cfg_file = tmp_path / "config.env"
        cfg_file.write_text("PRICING_SONNET_INPUT_PER_MTOK=50.0\n")
        with patch.dict(os.environ, {"CC_ANALYZE_PRICING_SONNET_INPUT_PER_MTOK": "77.0"}):
            cfg = load_config(cfg_file)
        assert cfg.pricing.sonnet.input_per_mtok == 77.0

    def test_custom_pricing_affects_cost_computation(self, tmp_path):
        from cc_sentinel.core import load_config, compute_cost, UsageRecord
        cfg_file = tmp_path / "config.env"
        # Use a very distinctive rate so we can verify
        cfg_file.write_text("PRICING_OPUS_INPUT_PER_MTOK=100.0\n")
        cfg = load_config(cfg_file)
        rec = UsageRecord(
            timestamp="", session_id="", project="", model="claude-opus-4-6",
            input_tokens=1_000_000, output_tokens=0,
            cache_creation_tokens=0, cache_read_tokens=0,
            entrypoint="", cwd="", git_branch="",
        )
        cost = compute_cost(rec, cfg.pricing)
        assert abs(cost - 100.0) < 0.01, f"Expected $100.00, got {cost}"

    def test_threshold_override_affects_health_check(self, tmp_path):
        from cc_sentinel.core import load_config, HealthAnalyzer
        cfg_file = tmp_path / "config.env"
        # Set very low threshold so a 10-minute session triggers warning
        cfg_file.write_text("THRESHOLD_LONG_SESSION_MINUTES=5\n")
        cfg = load_config(cfg_file)

        from tests.test_core_detectors import _make_summary
        sessions = [_make_summary(duration_minutes=10, message_count=20)]
        result = HealthAnalyzer().analyze(sessions, cfg)
        descriptions = [r.description for r in result.recommendations]
        assert any("session" in d.lower() for d in descriptions)


# ===========================================================================
# 8. Fixture-based analysis — high cost and bash chain sessions
# ===========================================================================

class TestFixtureBasedAnalysis:
    """Verify that the new fixture files are analyzed correctly."""

    def test_high_cost_session_has_frustration(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(FIXTURES / "high_cost_session.jsonl", "bigapp", default_config())
        assert summary.session_id == "sess-high"
        assert summary.frustration_count >= 3  # ugh, still not working, wtf, nope
        assert summary.subagent_count >= 2
        assert "github.com" in summary.webfetch_domains or "api.github.com" in summary.webfetch_domains

    def test_high_cost_session_total_tokens(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(FIXTURES / "high_cost_session.jsonl", "bigapp", default_config())
        # Sum of input_tokens: 50000+80000+120000+90000+100000 = 440000
        assert summary.total_input_tokens == 440_000
        assert summary.total_cost > 0

    def test_bash_chain_session_detects_chain(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(FIXTURES / "bash_chain_session.jsonl", "pipeline", default_config())
        assert summary.session_id == "sess-chain"
        chain_names = [name for name, length in summary.tool_chains]
        assert "Bash" in chain_names

    def test_bash_chain_session_model_is_sonnet(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(FIXTURES / "bash_chain_session.jsonl", "pipeline", default_config())
        assert "claude-sonnet-4-6" in summary.model_breakdown

    def test_bash_chain_waste_analyzer_flags_chain(self):
        from cc_sentinel.core import analyze_session, WasteAnalyzer, default_config
        summary = analyze_session(FIXTURES / "bash_chain_session.jsonl", "pipeline", default_config())
        result = WasteAnalyzer().analyze([summary], default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("chain" in d.lower() or "consecutive" in d.lower() for d in descriptions)

    def test_high_cost_waste_analyzer_flags_github_webfetch(self):
        from cc_sentinel.core import analyze_session, WasteAnalyzer, default_config
        summary = analyze_session(FIXTURES / "high_cost_session.jsonl", "bigapp", default_config())
        result = WasteAnalyzer().analyze([summary], default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("github" in d.lower() or "gh" in d.lower() for d in descriptions)


# ===========================================================================
# 9. Render formats — text, markdown, JSON consistency
# ===========================================================================

class TestRenderFormats:
    """All three render formats should produce consistent, valid output."""

    def _get_result(self):
        from cc_sentinel.core import CostAnalyzer, default_config
        from tests.test_core_detectors import _make_summary
        sessions = [_make_summary(total_cost=50.0), _make_summary(total_cost=30.0, session_id="s2")]
        return CostAnalyzer().analyze(sessions, default_config())

    def test_render_text_is_non_empty(self):
        result = self._get_result()
        text = result.render_text()
        assert len(text) > 50

    def test_render_markdown_has_headers(self):
        result = self._get_result()
        md = result.render_markdown()
        assert md.count("#") >= 1

    def test_render_json_is_valid(self):
        result = self._get_result()
        parsed = json.loads(result.render_json())
        assert "title" in parsed
        assert "sections" in parsed
        assert "recommendations" in parsed

    def test_all_analyzers_render_all_formats(self):
        from cc_sentinel.core import (
            CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
            WasteAnalyzer, TipsAnalyzer, CompareAnalyzer, default_config,
        )
        from tests.test_core_detectors import _make_summary
        sessions = [_make_summary()]
        for cls in [CostAnalyzer, HabitsAnalyzer, HealthAnalyzer, WasteAnalyzer, TipsAnalyzer, CompareAnalyzer]:
            result = cls().analyze(sessions, default_config())
            assert result.render_text(), f"{cls.__name__}.render_text() returned empty"
            assert result.render_markdown(), f"{cls.__name__}.render_markdown() returned empty"
            parsed = json.loads(result.render_json())
            assert parsed["title"], f"{cls.__name__}.render_json() has no title"


# ===========================================================================
# 10. Session summary serialization roundtrip
# ===========================================================================

class TestSessionSummaryRoundtrip:
    """SessionSummary should survive a serialize → write → read → deserialize cycle."""

    def test_full_roundtrip_via_file(self, tmp_path):
        from cc_sentinel.core import (
            analyze_session, default_config,
            session_summary_to_dict, session_summary_from_dict,
        )
        summary = analyze_session(FIXTURES / "sample_session.jsonl", "myapp", default_config())

        cache = tmp_path / "sessions.jsonl"
        with open(cache, "w") as f:
            f.write(json.dumps(session_summary_to_dict(summary)) + "\n")

        from cc_sentinel.core import iter_jsonl
        entries = list(iter_jsonl(cache))
        assert len(entries) == 1
        restored = session_summary_from_dict(entries[0])

        assert restored.session_id == summary.session_id
        assert restored.total_cost == summary.total_cost
        assert restored.frustration_count == summary.frustration_count
        assert restored.tool_counts == summary.tool_counts
        assert restored.webfetch_domains == summary.webfetch_domains

    def test_high_cost_session_roundtrip(self, tmp_path):
        from cc_sentinel.core import (
            analyze_session, default_config,
            session_summary_to_dict, session_summary_from_dict,
        )
        summary = analyze_session(FIXTURES / "high_cost_session.jsonl", "bigapp", default_config())
        d = session_summary_to_dict(summary)
        restored = session_summary_from_dict(d)
        assert restored.subagent_count == summary.subagent_count
        assert restored.frustration_count == summary.frustration_count
        assert abs(restored.total_cost - summary.total_cost) < 0.001


# ===========================================================================
# 11. Dispatch routing
# ===========================================================================

class TestDispatchRouting:
    """dispatch.py should map all expected commands."""

    def test_dispatch_map_has_all_commands(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        dispatch = importlib.import_module("dispatch")
        expected = {
            "stop_hook", "session_start_hook", "pre_tool_use", "post_tool_use",
            "cost", "habits", "health", "tips", "report", "compare", "waste", "hints",
        }
        assert expected == set(dispatch._DISPATCH.keys())

    def test_dispatch_hints_subprocess(self):
        """hints command should run successfully as a subprocess."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "dispatch.py"), "hints"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "cc-sentinel" in result.stdout.lower() or "hint" in result.stdout.lower()

    def test_dispatch_unknown_command_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "dispatch.py"), "nonexistent_command"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


# ===========================================================================
# 12. iter_project_sessions — directory traversal
# ===========================================================================

class TestIterProjectSessions:
    """iter_project_sessions should discover JSONL files across nested structures."""

    def test_discovers_top_level_jsonl(self, tmp_path):
        claude_dir = _build_claude_dir(tmp_path)
        path = _write_session(claude_dir / "projects", "proj-one", "sess-a", [
            _user_msg("sess-a", "2026-04-01T10:00:00Z", "hi"),
        ])
        from cc_sentinel.core import iter_project_sessions
        results = list(iter_project_sessions(claude_dir))
        assert len(results) == 1
        assert results[0][0] == "proj-one"
        assert results[0][1] == path

    def test_discovers_multiple_projects(self, tmp_path):
        claude_dir = _build_claude_dir(tmp_path)
        for proj in ["proj-a", "proj-b", "proj-c"]:
            _write_session(claude_dir / "projects", proj, f"s-{proj}", [
                _user_msg(f"s-{proj}", "2026-04-01T10:00:00Z", "hi"),
            ])
        from cc_sentinel.core import iter_project_sessions
        results = list(iter_project_sessions(claude_dir))
        assert len(results) == 3
        project_names = {r[0] for r in results}
        assert project_names == {"proj-a", "proj-b", "proj-c"}

    def test_returns_nothing_for_missing_projects_dir(self, tmp_path):
        from cc_sentinel.core import iter_project_sessions
        results = list(iter_project_sessions(tmp_path / "nonexistent"))
        assert results == []

    def test_skips_non_jsonl_files(self, tmp_path):
        claude_dir = _build_claude_dir(tmp_path)
        proj_dir = claude_dir / "projects" / "proj-x"
        proj_dir.mkdir(parents=True)
        (proj_dir / "notes.txt").write_text("not a session")
        (proj_dir / "sess-x.jsonl").write_text(_user_msg("sess-x", "2026-04-01T10:00:00Z", "hi") + "\n")
        from cc_sentinel.core import iter_project_sessions
        results = list(iter_project_sessions(claude_dir))
        assert len(results) == 1
        assert results[0][1].suffix == ".jsonl"


# ===========================================================================
# 13. Pre-tool hints — integration with live state on disk
# ===========================================================================

class TestPreToolHintsIntegration:
    """Pre-tool hints should read/write live_session.json correctly."""

    def test_webfetch_api_github_also_triggers_hint(self, tmp_env, capsys):
        claude_dir, data_dir, config = tmp_env
        from cc_sentinel.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        run_pre_tool_use({
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://api.github.com/repos/org/repo"},
        }, config=config)
        out = capsys.readouterr().out
        assert "gh" in out.lower() or "github" in out.lower()

    def test_hints_disabled_suppresses_output(self, tmp_env, capsys):
        claude_dir, data_dir, config = tmp_env
        config.hints.pre_tool = False
        from cc_sentinel.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        run_pre_tool_use({
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://github.com/org/repo"},
        }, config=config)
        out = capsys.readouterr().out
        assert out == ""

    def test_bash_chain_resets_after_different_tool(self, tmp_env, capsys):
        claude_dir, data_dir, config = tmp_env
        from cc_sentinel.core import run_pre_tool_use, _init_live_state, _load_live_state
        _init_live_state(config)
        for _ in range(5):
            run_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "ls"}}, config=config)
        # Now a different tool — chain should reset
        run_pre_tool_use({"tool_name": "Read", "tool_input": {}}, config=config)

        live = _load_live_state(config)
        assert live["chain_length"] == 1
        assert not live["bash_chain_warned"]

    def test_post_tool_tracks_webfetch_github(self, tmp_env):
        claude_dir, data_dir, config = tmp_env
        from cc_sentinel.core import run_post_tool_use, _init_live_state, _load_live_state
        _init_live_state(config)
        run_post_tool_use({
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://github.com/org/repo/issues/1"},
        }, config=config)
        live = _load_live_state(config)
        assert live["webfetch_github_count"] == 1
