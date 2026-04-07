"""Tests targeting 100% coverage of cc_retrospect/core.py.

Each class targets a specific uncovered region identified by coverage report.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(**overrides):
    from cc_retrospect.core import SessionSummary
    defaults = dict(
        session_id="test-sess",
        project="testproj",
        start_ts="2026-04-05T10:00:00Z",
        end_ts="2026-04-05T11:00:00Z",
        duration_minutes=60.0,
        message_count=50,
        user_message_count=20,
        assistant_message_count=30,
        total_input_tokens=100_000,
        total_output_tokens=50_000,
        total_cache_creation_tokens=500_000,
        total_cache_read_tokens=5_000_000,
        total_cost=10.0,
        model_breakdown={"claude-opus-4-6": 10.0},
        tool_counts={"Bash": 5},
        tool_chains=[],
        subagent_count=0,
        mega_prompt_count=0,
        frustration_count=0,
        frustration_words={},
        webfetch_domains={},
        entrypoint="claude-desktop",
        cwd="/test",
        git_branch="main",
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
# load_config — file parsing and env var overrides
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_reads_from_file(self, tmp_path):
        from cc_retrospect.core import load_config
        cfg_file = tmp_path / "config.env"
        cfg_file.write_text("CC_ANALYZE_PRICING__OPUS__INPUT_PER_MTOK=99.0\n# comment\n\nNO_EQUALS\n")
        cfg = load_config(cfg_file)
        assert cfg.pricing.opus.input_per_mtok == 99.0

    def test_env_var_override(self, tmp_path):
        from cc_retrospect.core import load_config
        env = {k: v for k, v in os.environ.items()}
        env["CC_ANALYZE_PRICING__OPUS__INPUT_PER_MTOK"] = "42.0"
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(tmp_path / "nonexistent.env")
        assert cfg.pricing.opus.input_per_mtok == 42.0

    def test_no_file_uses_defaults(self, tmp_path):
        from cc_retrospect.core import load_config, default_config
        cfg = load_config(tmp_path / "nonexistent.env")
        assert cfg.pricing.opus.input_per_mtok == default_config().pricing.opus.input_per_mtok


# ---------------------------------------------------------------------------
# _apply_config — all keys + bad value path
# ---------------------------------------------------------------------------

class TestApplyConfig:
    def _cfg(self):
        from cc_retrospect.core import Config
        return Config()

    def test_all_pricing_keys(self):
        from cc_retrospect.core import _apply_config
        cfg = self._cfg()
        _apply_config(cfg, "PRICING_OPUS_OUTPUT_PER_MTOK", "55.0")
        assert cfg.pricing.opus.output_per_mtok == 55.0
        _apply_config(cfg, "PRICING_OPUS_CACHE_CREATE_PER_MTOK", "10.0")
        assert cfg.pricing.opus.cache_create_per_mtok == 10.0
        _apply_config(cfg, "PRICING_OPUS_CACHE_READ_PER_MTOK", "2.0")
        assert cfg.pricing.opus.cache_read_per_mtok == 2.0
        _apply_config(cfg, "PRICING_SONNET_INPUT_PER_MTOK", "2.0")
        assert cfg.pricing.sonnet.input_per_mtok == 2.0
        _apply_config(cfg, "PRICING_SONNET_OUTPUT_PER_MTOK", "8.0")
        assert cfg.pricing.sonnet.output_per_mtok == 8.0
        _apply_config(cfg, "PRICING_HAIKU_INPUT_PER_MTOK", "0.5")
        assert cfg.pricing.haiku.input_per_mtok == 0.5
        _apply_config(cfg, "PRICING_HAIKU_OUTPUT_PER_MTOK", "2.0")
        assert cfg.pricing.haiku.output_per_mtok == 2.0

    def test_threshold_keys(self):
        from cc_retrospect.core import _apply_config
        cfg = self._cfg()
        _apply_config(cfg, "THRESHOLD_LONG_SESSION_MINUTES", "60")
        assert cfg.thresholds.long_session_minutes == 60
        _apply_config(cfg, "THRESHOLD_LONG_SESSION_MESSAGES", "100")
        assert cfg.thresholds.long_session_messages == 100
        _apply_config(cfg, "THRESHOLD_MEGA_PROMPT_CHARS", "500")
        assert cfg.thresholds.mega_prompt_chars == 500
        _apply_config(cfg, "THRESHOLD_MAX_SUBAGENTS", "5")
        assert cfg.thresholds.max_subagents_per_session == 5
        _apply_config(cfg, "THRESHOLD_DAILY_COST_WARNING", "200.0")
        assert cfg.thresholds.daily_cost_warning == 200.0

    def test_waste_domains(self):
        from cc_retrospect.core import _apply_config
        cfg = self._cfg()
        _apply_config(cfg, "WASTE_WEBFETCH_DOMAINS", "github.com,stackoverflow.com")
        assert "stackoverflow.com" in cfg.thresholds.waste_webfetch_domains

    def test_hints_keys(self):
        from cc_retrospect.core import _apply_config
        cfg = self._cfg()
        _apply_config(cfg, "HINTS_SESSION_START", "true")
        assert cfg.hints.session_start is True
        _apply_config(cfg, "HINTS_SESSION_START", "1")
        assert cfg.hints.session_start is True
        _apply_config(cfg, "HINTS_SESSION_START", "false")
        assert cfg.hints.session_start is False
        _apply_config(cfg, "HINTS_PRE_TOOL", "false")
        assert cfg.hints.pre_tool is False
        _apply_config(cfg, "HINTS_PRE_TOOL", "true")
        assert cfg.hints.pre_tool is True
        _apply_config(cfg, "HINTS_POST_TOOL", "0")
        assert cfg.hints.post_tool is False
        _apply_config(cfg, "HINTS_POST_TOOL", "yes")
        assert cfg.hints.post_tool is True

    def test_bad_value_ignored(self):
        from cc_retrospect.core import _apply_config
        cfg = self._cfg()
        before = cfg.pricing.opus.input_per_mtok
        _apply_config(cfg, "PRICING_OPUS_INPUT_PER_MTOK", "not_a_number")
        assert cfg.pricing.opus.input_per_mtok == before


# ---------------------------------------------------------------------------
# iter_project_sessions — nested subdirectory paths
# ---------------------------------------------------------------------------

class TestIterProjectSessions:
    def test_empty_projects_dir(self, tmp_path):
        from cc_retrospect.core import iter_project_sessions
        (tmp_path / "projects").mkdir()
        assert list(iter_project_sessions(tmp_path)) == []

    def test_no_projects_dir(self, tmp_path):
        from cc_retrospect.core import iter_project_sessions
        assert list(iter_project_sessions(tmp_path)) == []

    def test_yields_top_level_jsonl(self, tmp_path):
        from cc_retrospect.core import iter_project_sessions
        proj = tmp_path / "projects" / "myproj"
        proj.mkdir(parents=True)
        (proj / "sess1.jsonl").write_text("{}\n")
        results = list(iter_project_sessions(tmp_path))
        assert len(results) == 1
        assert results[0][0] == "myproj"

    def test_yields_subdirectory_jsonl(self, tmp_path):
        from cc_retrospect.core import iter_project_sessions
        proj = tmp_path / "projects" / "myproj"
        subdir = proj / "subdir"
        subdir.mkdir(parents=True)
        (subdir / "sess2.jsonl").write_text("{}\n")
        results = list(iter_project_sessions(tmp_path))
        assert len(results) == 1

    def test_skips_memory_subdir(self, tmp_path):
        from cc_retrospect.core import iter_project_sessions
        proj = tmp_path / "projects" / "myproj"
        mem = proj / "memory"
        mem.mkdir(parents=True)
        (mem / "notes.jsonl").write_text("{}\n")
        results = list(iter_project_sessions(tmp_path))
        assert results == []

    def test_skips_non_jsonl_files(self, tmp_path):
        from cc_retrospect.core import iter_project_sessions
        proj = tmp_path / "projects" / "myproj"
        proj.mkdir(parents=True)
        (proj / "notes.txt").write_text("hello")
        results = list(iter_project_sessions(tmp_path))
        assert results == []


# ---------------------------------------------------------------------------
# extract_usage — non-dict message branch
# ---------------------------------------------------------------------------

class TestExtractUsageEdgeCases:
    def test_non_dict_message(self):
        from cc_retrospect.core import extract_usage
        entry = {"type": "assistant", "message": "not a dict"}
        assert extract_usage(entry, "proj") is None


# ---------------------------------------------------------------------------
# Format helpers — all branches
# ---------------------------------------------------------------------------

class TestFmtHelpers:
    def test_fmt_tokens_billions(self):
        from cc_retrospect.core import _fmt_tokens
        assert "B" in _fmt_tokens(2_000_000_000)

    def test_fmt_tokens_millions(self):
        from cc_retrospect.core import _fmt_tokens
        assert "M" in _fmt_tokens(1_500_000)

    def test_fmt_tokens_thousands(self):
        from cc_retrospect.core import _fmt_tokens
        assert "K" in _fmt_tokens(5_000)

    def test_fmt_tokens_plain(self):
        from cc_retrospect.core import _fmt_tokens
        assert _fmt_tokens(999) == "999"

    def test_fmt_cost_large(self):
        from cc_retrospect.core import _fmt_cost
        result = _fmt_cost(1500.0)
        assert "$" in result and "," in result

    def test_fmt_cost_medium(self):
        from cc_retrospect.core import _fmt_cost
        result = _fmt_cost(5.50)
        assert result == "$5.50"

    def test_fmt_cost_small(self):
        from cc_retrospect.core import _fmt_cost
        result = _fmt_cost(0.0012)
        assert result.startswith("$0.00")

    def test_fmt_duration_hours(self):
        from cc_retrospect.core import _fmt_duration
        result = _fmt_duration(90.0)
        assert "h" in result and "m" in result

    def test_fmt_duration_minutes(self):
        from cc_retrospect.core import _fmt_duration
        result = _fmt_duration(45.0)
        assert result == "45m"


# ---------------------------------------------------------------------------
# analyze_session — edge cases not covered by fixture tests
# ---------------------------------------------------------------------------

class TestAnalyzeSessionEdgeCases:
    def test_content_as_list_in_user_message(self, tmp_path):
        """User message content as list of blocks (not plain string)."""
        from cc_retrospect.core import analyze_session, default_config
        data = [
            {"type": "user", "message": {"content": [
                {"type": "text", "text": "ugh this is wrong"},
                {"type": "text", "text": " please fix it"},
            ]}, "timestamp": "2026-01-01T10:00:00Z", "sessionId": "s1"},
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
                "usage": {"input_tokens": 10, "output_tokens": 5}},
                "timestamp": "2026-01-01T10:00:05Z", "sessionId": "s1"},
        ]
        p = tmp_path / "s1.jsonl"
        p.write_text("\n".join(json.dumps(d) for d in data))
        summary = analyze_session(p, "proj", default_config())
        assert summary.frustration_count >= 1

    def test_final_chain_appended(self, tmp_path):
        """Tool chain at end of session (not followed by different tool) is recorded."""
        from cc_retrospect.core import analyze_session, default_config
        data = [
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {}},
                {"type": "tool_use", "name": "Bash", "id": "t2", "input": {}},
                {"type": "tool_use", "name": "Bash", "id": "t3", "input": {}},
            ], "usage": {"input_tokens": 10, "output_tokens": 5}},
                "timestamp": "2026-01-01T10:00:00Z", "sessionId": "s2"},
        ]
        p = tmp_path / "s2.jsonl"
        p.write_text("\n".join(json.dumps(d) for d in data))
        summary = analyze_session(p, "proj", default_config())
        chain_names = [name for name, _ in summary.tool_chains]
        assert "Bash" in chain_names

    def test_bad_duration_timestamps(self, tmp_path):
        """Malformed timestamps don't crash — duration stays 0."""
        from cc_retrospect.core import analyze_session, default_config
        data = [
            {"type": "user", "message": {"content": "hi"}, "timestamp": "not-a-date", "sessionId": "s3"},
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "content": [],
                "usage": {"input_tokens": 10, "output_tokens": 5}},
                "timestamp": "also-not-a-date", "sessionId": "s3"},
        ]
        p = tmp_path / "s3.jsonl"
        p.write_text("\n".join(json.dumps(d) for d in data))
        summary = analyze_session(p, "proj", default_config())
        assert summary.duration_minutes == 0.0


# ---------------------------------------------------------------------------
# HabitsAnalyzer — uncovered branches
# ---------------------------------------------------------------------------

class TestHabitsAnalyzerFull:
    def test_bad_timestamp_skipped(self):
        from cc_retrospect.core import HabitsAnalyzer, default_config
        sessions = [_make_summary(start_ts="not-a-date")]
        result = HabitsAnalyzer().analyze(sessions, default_config())
        assert result is not None  # doesn't crash

    def test_frustration_section_shown(self):
        from cc_retrospect.core import HabitsAnalyzer, default_config
        sessions = [_make_summary(
            frustration_count=5,
            frustration_words={"ugh": 3, "again": 2},
        )]
        result = HabitsAnalyzer().analyze(sessions, default_config())
        headers = [s.header for s in result.sections]
        assert any("frustration" in h.lower() for h in headers)

    def test_entrypoints_section_shown(self):
        from cc_retrospect.core import HabitsAnalyzer, default_config
        sessions = [_make_summary(entrypoint="cli")]
        result = HabitsAnalyzer().analyze(sessions, default_config())
        headers = [s.header for s in result.sections]
        assert any("entrypoint" in h.lower() for h in headers)

    def test_no_entrypoint_section_when_empty(self):
        from cc_retrospect.core import HabitsAnalyzer, default_config
        sessions = [_make_summary(entrypoint="")]
        result = HabitsAnalyzer().analyze(sessions, default_config())
        headers = [s.header for s in result.sections]
        assert not any("entrypoint" in h.lower() for h in headers)

    def test_long_avg_duration_recommendation(self):
        from cc_retrospect.core import HabitsAnalyzer, default_config
        sessions = [_make_summary(duration_minutes=300)]
        result = HabitsAnalyzer().analyze(sessions, default_config())
        descs = [r.description for r in result.recommendations]
        assert any("duration" in d.lower() or "session" in d.lower() for d in descs)


# ---------------------------------------------------------------------------
# HealthAnalyzer — low cache rate warning
# ---------------------------------------------------------------------------

class TestHealthAnalyzerFull:
    def test_low_cache_rate_recommendation(self):
        from cc_retrospect.core import HealthAnalyzer, default_config
        # Large input tokens but almost no cache reads → low cache rate
        sessions = [_make_summary(
            total_input_tokens=500_000,
            total_cache_creation_tokens=500_000,
            total_cache_read_tokens=0,
        )]
        result = HealthAnalyzer().analyze(sessions, default_config())
        descs = [r.description for r in result.recommendations]
        assert any("cache" in d.lower() for d in descs)

    def test_no_cost_data_row_omitted(self):
        """Sessions with no start_ts don't produce a daily cost row."""
        from cc_retrospect.core import HealthAnalyzer, default_config
        sessions = [_make_summary(start_ts="", total_cost=0.0)]
        result = HealthAnalyzer().analyze(sessions, default_config())
        assert result is not None


# ---------------------------------------------------------------------------
# WasteAnalyzer — model mismatch branches
# ---------------------------------------------------------------------------

class TestWasteAnalyzerFull:
    def test_model_mismatch_not_flagged_when_complex_tools_used(self):
        """Opus session with Agent/WebSearch should NOT get mismatch warning."""
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(
            model_breakdown={"claude-opus-4-6": 500.0},
            tool_counts={"Agent": 5, "Read": 3},
            total_cost=500.0,
        )]
        result = WasteAnalyzer().analyze(sessions, default_config())
        descs = [r.description for r in result.recommendations]
        mismatch = [d for d in descs if "simple tasks" in d.lower()]
        assert len(mismatch) == 0

    def test_model_mismatch_not_flagged_when_cost_below_threshold(self):
        """Opus session under $50 cost doesn't trigger mismatch."""
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(
            model_breakdown={"claude-opus-4-6": 10.0},
            tool_counts={"Read": 5},
            total_cost=10.0,
        )]
        result = WasteAnalyzer().analyze(sessions, default_config())
        descs = [r.description for r in result.recommendations]
        assert not any("simple tasks" in d.lower() for d in descs)

    def test_mega_prompt_threshold_not_crossed(self):
        """<= 5 mega prompts produces no recommendation."""
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(mega_prompt_count=3)]
        result = WasteAnalyzer().analyze(sessions, default_config())
        descs = [r.description for r in result.recommendations]
        assert not any("mega" in d.lower() or "file reference" in d.lower() for d in descs)


# ---------------------------------------------------------------------------
# TipsAnalyzer — all tip branches
# ---------------------------------------------------------------------------

class TestTipsAnalyzerFull:
    def test_no_sessions_returns_placeholder(self):
        from cc_retrospect.core import TipsAnalyzer, default_config
        result = TipsAnalyzer().analyze([], default_config())
        assert any("no session" in r.description.lower() for r in result.recommendations)

    def test_long_session_tip(self):
        from cc_retrospect.core import TipsAnalyzer, default_config
        sessions = [_make_summary(duration_minutes=300, message_count=400)]
        result = TipsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("fresh" in d or "session" in d for d in descs)

    def test_subagent_overuse_tip(self):
        from cc_retrospect.core import TipsAnalyzer, default_config
        sessions = [_make_summary(subagent_count=20)]
        result = TipsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("subagent" in d for d in descs)

    def test_frustration_tip(self):
        from cc_retrospect.core import TipsAnalyzer, default_config
        sessions = [_make_summary(frustration_count=5)]
        result = TipsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("frustration" in d for d in descs)

    def test_github_webfetch_tip(self):
        from cc_retrospect.core import TipsAnalyzer, default_config
        sessions = [_make_summary(webfetch_domains={"github.com": 3})]
        result = TipsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("github" in d or "gh" in d for d in descs)

    def test_high_cost_tip(self):
        from cc_retrospect.core import TipsAnalyzer, default_config
        sessions = [_make_summary(total_cost=200.0)]
        result = TipsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("cost" in d or "expensive" in d for d in descs)

    def test_healthy_session_keep_it_up(self):
        from cc_retrospect.core import TipsAnalyzer, default_config
        sessions = [_make_summary(
            duration_minutes=20,
            message_count=10,
            subagent_count=0,
            frustration_count=0,
            webfetch_domains={},
            total_cost=1.0,
        )]
        result = TipsAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("healthy" in d or "keep" in d for d in descs)


# ---------------------------------------------------------------------------
# CompareAnalyzer — full logic
# ---------------------------------------------------------------------------

class TestCompareAnalyzerFull:
    def _make_week_sessions(self):
        """Sessions in this week and last week."""
        now = datetime.now(timezone.utc)
        days_since_monday = now.weekday()
        this_week_start = (now - timedelta(days=days_since_monday)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        last_week_ts = (this_week_start - timedelta(days=3)).isoformat()
        this_week_ts = (this_week_start + timedelta(hours=1)).isoformat()
        return last_week_ts, this_week_ts

    def test_spending_increased(self):
        from cc_retrospect.core import CompareAnalyzer, default_config
        lw_ts, tw_ts = self._make_week_sessions()
        sessions = [
            _make_summary(session_id="lw", start_ts=lw_ts, total_cost=100.0),
            _make_summary(session_id="tw", start_ts=tw_ts, total_cost=200.0),
        ]
        result = CompareAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("increased" in d or "spending" in d for d in descs)

    def test_spending_decreased(self):
        from cc_retrospect.core import CompareAnalyzer, default_config
        lw_ts, tw_ts = self._make_week_sessions()
        sessions = [
            _make_summary(session_id="lw", start_ts=lw_ts, total_cost=200.0),
            _make_summary(session_id="tw", start_ts=tw_ts, total_cost=50.0),
        ]
        result = CompareAnalyzer().analyze(sessions, default_config())
        descs = [r.description.lower() for r in result.recommendations]
        assert any("decreased" in d or "good" in d or "progress" in d for d in descs)

    def test_delta_na_when_no_previous(self):
        from cc_retrospect.core import CompareAnalyzer, default_config
        now = datetime.now(timezone.utc)
        days_since_monday = now.weekday()
        this_week_start = (now - timedelta(days=days_since_monday)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        tw_ts = (this_week_start + timedelta(hours=1)).isoformat()
        sessions = [_make_summary(session_id="tw", start_ts=tw_ts, total_cost=50.0)]
        result = CompareAnalyzer().analyze(sessions, default_config())
        # Should produce a comparison row with N/A for delta
        all_values = [v for s in result.sections for _, v in s.rows]
        assert any("N/A" in v for v in all_values)

    def test_empty_sessions(self):
        from cc_retrospect.core import CompareAnalyzer, default_config
        result = CompareAnalyzer().analyze([], default_config())
        assert result.title == "Compare"
        assert result.sections == []


# ---------------------------------------------------------------------------
# get_analyzers — custom analyzer loading
# ---------------------------------------------------------------------------

class TestGetAnalyzers:
    def test_builtin_analyzers_returned(self, config):
        from cc_retrospect.core import get_analyzers
        analyzers = get_analyzers(config)
        names = [a.name for a in analyzers]
        assert "cost" in names
        assert "health" in names

    def test_custom_analyzer_discovered(self, config):
        from cc_retrospect.core import get_analyzers
        custom_dir = config.data_dir / "analyzers"
        custom_dir.mkdir()
        (custom_dir / "my_analyzer.py").write_text("""
class MyCustomAnalyzer:
    name = "my-custom"
    description = "Test custom analyzer"

    def analyze(self, sessions, config):
        from cc_retrospect.core import AnalysisResult
        return AnalysisResult(title="Custom", sections=[], recommendations=[])
""")
        analyzers = get_analyzers(config)
        names = [a.name for a in analyzers]
        assert "my-custom" in names

    def test_broken_custom_analyzer_skipped(self, config):
        from cc_retrospect.core import get_analyzers
        custom_dir = config.data_dir / "analyzers"
        custom_dir.mkdir()
        (custom_dir / "broken.py").write_text("this is not valid python !!!")
        # Should not raise — broken analyzer is skipped with a warning
        analyzers = get_analyzers(config)
        names = [a.name for a in analyzers]
        assert "cost" in names  # builtins still present


# ---------------------------------------------------------------------------
# load_all_sessions — cache, project filter, new entries
# ---------------------------------------------------------------------------

class TestLoadAllSessions:
    def _make_claude_dir_with_session(self, tmp_path, session_fixture: Path) -> Path:
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-Users-test-Projects-myapp"
        proj_dir.mkdir(parents=True)
        dest = proj_dir / session_fixture.name
        dest.write_bytes(session_fixture.read_bytes())
        return claude_dir

    def test_loads_sessions_from_disk(self, tmp_path):
        from cc_retrospect.core import load_all_sessions, Config
        claude_dir = self._make_claude_dir_with_session(tmp_path, FIXTURES / "sample_session.jsonl")
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        sessions = load_all_sessions(cfg)
        assert len(sessions) == 1
        assert sessions[0].session_id == "sess-001"

    def test_writes_cache(self, tmp_path):
        from cc_retrospect.core import load_all_sessions, Config
        claude_dir = self._make_claude_dir_with_session(tmp_path, FIXTURES / "sample_session.jsonl")
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        load_all_sessions(cfg)
        assert (data_dir / "sessions.jsonl").exists()

    def test_uses_cache_on_second_load(self, tmp_path):
        from cc_retrospect.core import load_all_sessions, Config
        claude_dir = self._make_claude_dir_with_session(tmp_path, FIXTURES / "sample_session.jsonl")
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        sessions1 = load_all_sessions(cfg)
        sessions2 = load_all_sessions(cfg)
        assert len(sessions1) == len(sessions2)
        assert sessions2[0].session_id == "sess-001"

    def test_project_filter(self, tmp_path):
        from cc_retrospect.core import load_all_sessions, Config
        claude_dir = self._make_claude_dir_with_session(tmp_path, FIXTURES / "sample_session.jsonl")
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        sessions = load_all_sessions(cfg, project_filter="myapp")
        assert len(sessions) == 1
        sessions_no_match = load_all_sessions(cfg, project_filter="zzznomatch")
        assert len(sessions_no_match) == 0

    def test_malformed_cache_entry_skipped(self, tmp_path):
        from cc_retrospect.core import load_all_sessions, Config
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        (data_dir / "sessions.jsonl").write_text('{"bad": "entry"}\n')
        claude_dir = tmp_path / ".claude"
        (claude_dir / "projects").mkdir(parents=True)
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        sessions = load_all_sessions(cfg)
        assert sessions == []


# ---------------------------------------------------------------------------
# Command entry points — run_cost, run_habits, etc.
# ---------------------------------------------------------------------------

class TestCommandEntrypoints:
    """All run_X commands call load_config + load_all_sessions and print output."""

    def _run_with_mocks(self, fn_name: str, capsys):
        from cc_retrospect import core
        sessions = []
        with patch.object(core, "load_config", return_value=core.default_config()):
            with patch.object(core, "load_all_sessions", return_value=sessions):
                fn = getattr(core, fn_name)
                rc = fn({})
        assert rc == 0
        return capsys.readouterr().out

    def test_run_cost(self, capsys):
        out = self._run_with_mocks("run_cost", capsys)
        assert len(out) > 0

    def test_run_habits(self, capsys):
        out = self._run_with_mocks("run_habits", capsys)
        assert len(out) > 0

    def test_run_health(self, capsys):
        out = self._run_with_mocks("run_health", capsys)
        assert len(out) > 0

    def test_run_tips(self, capsys):
        out = self._run_with_mocks("run_tips", capsys)
        assert len(out) > 0

    def test_run_waste(self, capsys):
        out = self._run_with_mocks("run_waste", capsys)
        assert len(out) > 0

    def test_run_compare(self, capsys):
        out = self._run_with_mocks("run_compare", capsys)
        assert len(out) > 0

    def test_run_report(self, tmp_path, capsys):
        from cc_retrospect import core
        cfg = core.Config(data_dir=tmp_path / ".cc-retrospect")
        with patch.object(core, "load_config", return_value=cfg):
            with patch.object(core, "load_all_sessions", return_value=[]):
                rc = core.run_report({})
        assert rc == 0
        out = capsys.readouterr().out
        assert "Report saved to" in out
        assert (tmp_path / ".cc-retrospect" / "reports").is_dir()

    def test_run_hints_shows_settings(self, capsys):
        from cc_retrospect.core import run_hints
        rc = run_hints({})
        assert rc == 0
        out = capsys.readouterr().out
        assert "session_start" in out
        assert "pre_tool" in out
        assert "post_tool" in out

    def test_run_hints_reflects_config(self, tmp_path, capsys):
        from cc_retrospect import core
        cfg = core.Config(data_dir=tmp_path)
        cfg.hints.session_start = True
        with patch.object(core, "load_config", return_value=cfg):
            core.run_hints({})
        out = capsys.readouterr().out
        assert "on " in out


# ---------------------------------------------------------------------------
# run_stop_hook — full flow
# ---------------------------------------------------------------------------

class TestRunStopHook:
    def _make_claude_dir(self, tmp_path) -> Path:
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-Users-test-Projects-myapp"
        proj_dir.mkdir(parents=True)
        dest = proj_dir / "sess-001.jsonl"
        dest.write_bytes((FIXTURES / "sample_session.jsonl").read_bytes())
        return claude_dir

    def test_missing_session_id_returns_early(self, config):
        from cc_retrospect.core import run_stop_hook
        with patch("cc_retrospect.core.load_config", return_value=config):
            rc = run_stop_hook({"cwd": "/test"})
        assert rc == 0

    def test_missing_cwd_returns_early(self, config):
        from cc_retrospect.core import run_stop_hook
        with patch("cc_retrospect.core.load_config", return_value=config):
            rc = run_stop_hook({"session_id": "abc"})
        assert rc == 0

    def test_no_matching_jsonl_returns_early(self, tmp_path):
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = tmp_path / ".claude"
        (claude_dir / "projects").mkdir(parents=True)
        cfg = Config(data_dir=tmp_path / ".cc-retrospect", claude_dir=claude_dir)
        cfg.data_dir.mkdir()
        with patch("cc_retrospect.core.load_config", return_value=cfg):
            rc = run_stop_hook({"session_id": "nosuchfile", "cwd": "/test/myapp"})
        assert rc == 0

    def test_full_flow_writes_cache_and_state(self, tmp_path):
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = self._make_claude_dir(tmp_path)
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        with patch("cc_retrospect.core.load_config", return_value=cfg):
            rc = run_stop_hook({
                "session_id": "sess-001",
                "cwd": "/Users/test/Projects/myapp",
            })
        assert rc == 0
        assert (data_dir / "sessions.jsonl").exists()
        assert (data_dir / "state.json").exists()
        state = json.loads((data_dir / "state.json").read_text())
        assert state["last_session_id"] == "sess-001"

    def test_existing_state_is_preserved_and_updated(self, tmp_path):
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = self._make_claude_dir(tmp_path)
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        state_path = data_dir / "state.json"
        state_path.write_text(json.dumps({"extra_key": "preserved"}))
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        with patch("cc_retrospect.core.load_config", return_value=cfg):
            run_stop_hook({"session_id": "sess-001", "cwd": "/Users/test/Projects/myapp"})
        state = json.loads(state_path.read_text())
        assert "extra_key" in state
        assert "last_session_id" in state

    def test_corrupt_state_json_overwritten(self, tmp_path):
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = self._make_claude_dir(tmp_path)
        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        (data_dir / "state.json").write_text("{ not valid json }")
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        with patch("cc_retrospect.core.load_config", return_value=cfg):
            rc = run_stop_hook({"session_id": "sess-001", "cwd": "/Users/test/Projects/myapp"})
        assert rc == 0
        state = json.loads((data_dir / "state.json").read_text())
        assert "last_session_id" in state


# ---------------------------------------------------------------------------
# run_session_start_hook — missing branches
# ---------------------------------------------------------------------------

class TestRunSessionStartHookFull:
    def test_missing_cwd_returns_early(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        with patch("cc_retrospect.core.load_config", return_value=config):
            rc = run_session_start_hook({})
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_corrupt_state_returns_early(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        (config.data_dir / "state.json").write_text("{ bad json }")
        with patch("cc_retrospect.core.load_config", return_value=config):
            rc = run_session_start_hook({"cwd": "/test"})
        assert rc == 0

    def test_different_project_returns_early_no_output(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        state = {"last_project": "-Users-x-Projects-other-project", "last_session_duration_minutes": 60}
        (config.data_dir / "state.json").write_text(json.dumps(state))
        config.hints.session_start = True
        with patch("cc_retrospect.core.load_config", return_value=config):
            rc = run_session_start_hook({"cwd": "/Users/x/Projects/myproject"})
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_same_project_shows_summary(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {
            "last_project": "-Users-x-Projects-myproject",
            "last_session_cost": 5.0,
            "last_session_duration_minutes": 30,
            "last_message_count": 50,
            "last_frustration_count": 0,
            "last_subagent_count": 0,
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_session_start_hook({"cwd": "/Users/x/Projects/myproject"})
        out = capsys.readouterr().out
        assert "cc-retrospect" in out
        assert "30m" in out

    def test_report_waste_injected(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {
            "last_session_cost": 5.0,
            "last_session_duration_minutes": 30,
            "last_message_count": 10,
            "last_frustration_count": 0,
            "last_subagent_count": 0,
        }
        (config.data_dir / "state.json").write_text(json.dumps(state))
        reports_dir = config.data_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "report-2026-04-01.md").write_text(
            "## Waste Analysis\n- [~] Use `gh` CLI instead of WebFetch\n"
        )
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        out = capsys.readouterr().out
        assert "cc-retrospect" in out

    def test_hints_suppressed_when_session_start_off(self, config, capsys):
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = False
        state = {"last_session_cost": 50.0, "last_session_duration_minutes": 200,
                 "last_message_count": 100, "last_frustration_count": 5, "last_subagent_count": 15}
        (config.data_dir / "state.json").write_text(json.dumps(state))
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# run_pre_tool_use — uncovered branches
# ---------------------------------------------------------------------------

class TestPreToolUseFull:
    def test_hints_suppressed_when_pre_tool_off(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        config.hints.pre_tool = False
        _init_live_state(config)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_pre_tool_use({
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://github.com/org/repo"},
            })
        assert capsys.readouterr().out == ""

    def test_bash_after_non_bash_resets_chain(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        live = _load_live_state(config)
        live["prev_tool"] = "Read"
        live["chain_length"] = 5
        _save_live_state(config, live)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_pre_tool_use({"tool_name": "Bash", "tool_input": {}})
        live_after = _load_live_state(config)
        assert live_after["chain_length"] == 1

    def test_non_bash_different_tool_resets_chain(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        live = _load_live_state(config)
        live["prev_tool"] = "Read"
        live["chain_length"] = 3
        _save_live_state(config, live)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_pre_tool_use({"tool_name": "Edit", "tool_input": {}})
        live_after = _load_live_state(config)
        assert live_after["chain_length"] == 1

    def test_non_bash_same_tool_does_not_reset_chain(self, config):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        live = _load_live_state(config)
        live["prev_tool"] = "Read"
        live["chain_length"] = 3
        _save_live_state(config, live)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_pre_tool_use({"tool_name": "Read", "tool_input": {}})
        live_after = _load_live_state(config)
        assert live_after["chain_length"] == 3  # not reset

    def test_bash_chain_warn_fires_once(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        # Pre-set warned state
        live = _load_live_state(config)
        live["prev_tool"] = "Bash"
        live["chain_length"] = 5
        live["bash_chain_warned"] = True
        _save_live_state(config, live)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_pre_tool_use({"tool_name": "Bash", "tool_input": {}})
        out = capsys.readouterr().out
        assert "combining" not in out.lower()  # no second warning

    def test_agent_non_explore_subagent_no_hint(self, config, capsys):
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_pre_tool_use({
                "tool_name": "Agent",
                "tool_input": {"prompt": "search for login function", "subagent_type": "general-purpose"},
            })
        out = capsys.readouterr().out
        assert out == ""


# ---------------------------------------------------------------------------
# run_post_tool_use — uncovered branches
# ---------------------------------------------------------------------------

class TestPostToolUseFull:
    def test_hints_suppressed_when_post_tool_off(self, config, capsys):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state, _save_live_state
        config.hints.post_tool = False
        _init_live_state(config)
        live = _load_live_state(config)
        live["message_count"] = 149
        _save_live_state(config, live)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_post_tool_use({"tool_name": "Read"})
        assert capsys.readouterr().out == ""

    def test_webfetch_github_tracking(self, config):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state
        _init_live_state(config)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_post_tool_use({
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://github.com/org/repo"},
            })
        live = _load_live_state(config)
        assert live["webfetch_github_count"] == 1

    def test_webfetch_non_github_not_tracked(self, config):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state
        _init_live_state(config)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_post_tool_use({
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://docs.python.org"},
            })
        live = _load_live_state(config)
        assert live.get("webfetch_github_count", 0) == 0

    def test_second_compact_nudge_at_300(self, config, capsys):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        live = _load_live_state(config)
        live["message_count"] = 299
        live["compact_nudged"] = True
        _save_live_state(config, live)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_post_tool_use({"tool_name": "Read"})
        out = capsys.readouterr().out
        assert "300" in out or "strongly" in out.lower()

    def test_no_second_nudge_if_first_not_sent(self, config, capsys):
        from cc_retrospect.core import run_post_tool_use, _init_live_state, _load_live_state, _save_live_state
        _init_live_state(config)
        live = _load_live_state(config)
        live["message_count"] = 299
        live["compact_nudged"] = False
        _save_live_state(config, live)
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_post_tool_use({"tool_name": "Read"})
        out = capsys.readouterr().out
        # Should show first nudge, not second
        assert "strongly" not in out.lower()


# ---------------------------------------------------------------------------
# Remaining edge cases — OSError paths, dead branches, fixture gaps
# ---------------------------------------------------------------------------

class TestIterJsonlOSError:
    def test_oserror_on_open_returns_empty(self, tmp_path):
        from cc_retrospect.core import iter_jsonl
        p = tmp_path / "fake.jsonl"
        p.write_text('{"ok": true}\n')
        with patch("builtins.open", side_effect=OSError("permission denied")):
            results = list(iter_jsonl(p))
        assert results == []


class TestIterProjectSessionsNonDir:
    def test_file_in_projects_dir_skipped(self, tmp_path):
        """A plain file inside projects/ (not a dir) is skipped."""
        from cc_retrospect.core import iter_project_sessions
        projects = tmp_path / "projects"
        projects.mkdir()
        (projects / "stray_file.txt").write_text("not a dir")
        results = list(iter_project_sessions(tmp_path))
        assert results == []


class TestAnalyzeSessionNonDictBlock:
    def test_non_dict_content_block_skipped(self, tmp_path):
        """Non-dict entries in content blocks don't crash the parser."""
        from cc_retrospect.core import analyze_session, default_config
        data = [{"type": "assistant", "message": {
            "model": "claude-opus-4-6",
            "content": ["not a dict", {"type": "tool_use", "name": "Read", "id": "t1", "input": {}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }, "timestamp": "2026-01-01T10:00:00Z", "sessionId": "s-nd"}]
        p = tmp_path / "s-nd.jsonl"
        p.write_text(json.dumps(data[0]))
        summary = analyze_session(p, "proj", default_config())
        assert summary.tool_counts.get("Read", 0) == 1


class TestUrlparseExceptionPaths:
    def test_urlparse_exception_in_analyze_session(self, tmp_path):
        """urlparse failure in analyze_session is swallowed."""
        from cc_retrospect.core import analyze_session, default_config
        from unittest.mock import patch
        data = [{"type": "assistant", "message": {
            "model": "claude-opus-4-6",
            "content": [{"type": "tool_use", "name": "WebFetch", "id": "t1",
                         "input": {"url": "https://github.com/x"}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }, "timestamp": "2026-01-01T10:00:00Z", "sessionId": "s-up"}]
        p = tmp_path / "s-up.jsonl"
        p.write_text(json.dumps(data[0]))
        with patch("cc_retrospect.core.urlparse", side_effect=Exception("boom")):
            summary = analyze_session(p, "proj", default_config())
        assert summary is not None  # didn't crash

    def test_urlparse_exception_in_pre_tool_use(self, config, capsys):
        """urlparse failure in pre_tool_use is swallowed."""
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.core.load_config", return_value=config):
            with patch("cc_retrospect.core.urlparse", side_effect=Exception("boom")):
                run_pre_tool_use({
                    "tool_name": "WebFetch",
                    "tool_input": {"url": "https://github.com/x"},
                })
        assert capsys.readouterr().out == ""


class TestWasteAnalyzerZeroOpusCost:
    def test_zero_opus_cost_skipped(self):
        """Session with no opus cost in model_breakdown skips mismatch check."""
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(model_breakdown={"claude-sonnet-4-6": 100.0})]
        result = WasteAnalyzer().analyze(sessions, default_config())
        descs = [r.description for r in result.recommendations]
        assert not any("simple tasks" in d.lower() for d in descs)


class TestCacheHitPath:
    def test_cache_hit_skips_disk_analysis(self, tmp_path):
        """When session_key matches cache, it uses cached summary instead of re-reading."""
        from cc_retrospect.core import load_all_sessions, Config
        # Create a JSONL session file named by session_id (as real Claude Code does)
        claude_dir = tmp_path / ".claude"
        proj_dir = claude_dir / "projects" / "-Users-test-myapp"
        proj_dir.mkdir(parents=True)
        src = FIXTURES / "sample_session.jsonl"
        # Name the file after the session_id so stem == session_id
        dest = proj_dir / "sess-001.jsonl"
        dest.write_bytes(src.read_bytes())

        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)

        # First load — writes cache
        sessions1 = load_all_sessions(cfg)
        assert len(sessions1) == 1

        # Second load — should hit cache (1094-1095)
        sessions2 = load_all_sessions(cfg)
        assert len(sessions2) == 1
        assert sessions2[0].session_id == "sess-001"


class TestRunStopHookNonDirInProjects:
    def test_non_dir_entry_in_projects_skipped(self, tmp_path):
        """A stray file inside the claude projects dir is skipped (non-dir continue)."""
        from cc_retrospect.core import Config, run_stop_hook
        claude_dir = tmp_path / ".claude"
        projects_dir = claude_dir / "projects"
        projects_dir.mkdir(parents=True)
        # Only a stray file, no valid project dir — ensures line 1230 is hit
        (projects_dir / "stray.txt").write_text("not a dir")

        data_dir = tmp_path / ".cc-retrospect"
        data_dir.mkdir()
        cfg = Config(data_dir=data_dir, claude_dir=claude_dir)
        with patch("cc_retrospect.core.load_config", return_value=cfg):
            rc = run_stop_hook({"session_id": "sess-001", "cwd": "/Users/test/myapp"})
        assert rc == 0  # no matching jsonl → returns early


class TestReportWasteParsing:
    def test_waste_tips_limited_to_two(self, config, capsys):
        """Report parsing stops after 2 waste tips (line 1344 break)."""
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {"last_session_cost": 5.0, "last_session_duration_minutes": 30,
                 "last_message_count": 10, "last_frustration_count": 0, "last_subagent_count": 0}
        (config.data_dir / "state.json").write_text(json.dumps(state))
        reports_dir = config.data_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "report-2026-04-01.md").write_text(
            "## Waste Analysis\n"
            "- [~] Tip one\n"
            "- [~] Tip two\n"
            "- [~] Tip three should be excluded\n"
        )
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        out = capsys.readouterr().out
        assert "Tip three" not in out

    def test_waste_section_ends_at_new_header(self, config, capsys):
        """Report parsing stops when a new markdown section starts (line 1346 break)."""
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {"last_session_cost": 5.0, "last_session_duration_minutes": 30,
                 "last_message_count": 10, "last_frustration_count": 0, "last_subagent_count": 0}
        (config.data_dir / "state.json").write_text(json.dumps(state))
        reports_dir = config.data_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "report-2026-04-01.md").write_text(
            "## Waste Analysis\n"
            "- [~] Only tip\n"
            "## Another Section\n"
            "- [~] Should not appear\n"
        )
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        out = capsys.readouterr().out
        assert "Should not appear" not in out

    def test_report_oserror_handled(self, config, capsys):
        """OSError reading a report file is swallowed (line 1349-1350).
        Make the report path a directory so read_text() raises IsADirectoryError."""
        from cc_retrospect.core import run_session_start_hook
        config.hints.session_start = True
        state = {"last_session_cost": 5.0, "last_session_duration_minutes": 30,
                 "last_message_count": 10, "last_frustration_count": 0, "last_subagent_count": 0}
        (config.data_dir / "state.json").write_text(json.dumps(state))
        reports_dir = config.data_dir / "reports"
        reports_dir.mkdir()
        # Create a directory with the report filename — read_text() on a dir raises OSError
        (reports_dir / "report-2026-04-01.md").mkdir()
        with patch("cc_retrospect.core.load_config", return_value=config):
            run_session_start_hook({"cwd": "/test"})
        # Should not raise
        capsys.readouterr()


class TestLiveStateFallbacks:
    def test_load_live_state_corrupt_json_returns_defaults(self, config):
        """Corrupt JSON in live_session.json returns default state."""
        from cc_retrospect.core import _load_live_state, _live_state_path
        _live_state_path(config).write_text("{ bad json }")
        state = _load_live_state(config)
        assert state["message_count"] == 0

    def test_save_live_state_oserror_silenced(self, tmp_path):
        """OSError writing live state doesn't raise."""
        from cc_retrospect.core import _save_live_state, Config
        # Use a path whose parent doesn't exist so write fails
        cfg = Config(data_dir=tmp_path / "nonexistent" / "nested")
        _save_live_state(cfg, {"message_count": 1})  # should not raise


class TestPreToolUseNonDictInput:
    def test_non_dict_tool_input_handled(self, config, capsys):
        """tool_input that's not a dict is normalized to {} without crashing."""
        from cc_retrospect.core import run_pre_tool_use, _init_live_state
        _init_live_state(config)
        with patch("cc_retrospect.core.load_config", return_value=config):
            rc = run_pre_tool_use({"tool_name": "WebFetch", "tool_input": "not a dict"})
        assert rc == 0
