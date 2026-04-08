"""Tests for waste detectors, health checks, and analyzers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _make_summary(**overrides):
    """Create a minimal SessionSummary with overrides."""
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
        total_cost=100.0,
        model_breakdown={"claude-opus-4-6": 100.0},
        tool_counts={"Bash": 10, "Read": 8, "Edit": 3},
        tool_chains=[("Bash", 5)],
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


class TestWasteAnalyzer:
    """Waste detection from session summaries."""

    def test_detects_webfetch_github(self):
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(webfetch_domains={"github.com": 50})]
        analyzer = WasteAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("github" in d.lower() or "gh" in d.lower() for d in descriptions)

    def test_detects_repetitive_chains(self):
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(tool_chains=[("Bash", 12), ("Read", 8)])]
        analyzer = WasteAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("chain" in d.lower() or "consecutive" in d.lower() for d in descriptions)

    def test_detects_oversized_prompts(self):
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(mega_prompt_count=15)]
        analyzer = WasteAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("prompt" in d.lower() or "paste" in d.lower() for d in descriptions)

    def test_no_waste_clean_session(self):
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary()]
        analyzer = WasteAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        # Might still have some recommendations but shouldn't have critical waste
        assert result is not None

    def test_detects_opus_on_simple(self):
        """Simple sessions using Opus should suggest Sonnet."""
        from cc_retrospect.core import WasteAnalyzer, default_config
        sessions = [_make_summary(
            model_breakdown={"claude-opus-4-6": 500.0},
            tool_counts={"Read": 5, "Bash": 3},  # simple tools only
            total_cost=500.0,
            subagent_count=0,
        )]
        analyzer = WasteAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("sonnet" in d.lower() or "model" in d.lower() for d in descriptions)


class TestHealthAnalyzer:
    """Health checks from session data and config."""

    def test_flags_long_sessions(self):
        from cc_retrospect.core import HealthAnalyzer, default_config
        sessions = [_make_summary(duration_minutes=300, message_count=500)]
        analyzer = HealthAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("session" in d.lower() and ("long" in d.lower() or "duration" in d.lower() or "clear" in d.lower()) for d in descriptions)

    def test_flags_subagent_overuse(self):
        from cc_retrospect.core import HealthAnalyzer, default_config
        sessions = [_make_summary(subagent_count=25)]
        analyzer = HealthAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("subagent" in d.lower() or "agent" in d.lower() for d in descriptions)

    def test_flags_high_cost_velocity(self):
        from cc_retrospect.core import HealthAnalyzer, default_config
        sessions = [
            _make_summary(
                total_cost=600.0,
                start_ts="2026-04-05T10:00:00Z",
                end_ts="2026-04-05T11:00:00Z",
            )
        ]
        analyzer = HealthAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("cost" in d.lower() or "spending" in d.lower() or "velocity" in d.lower() for d in descriptions)

    def test_flags_frustration_loops(self):
        from cc_retrospect.core import HealthAnalyzer, default_config
        sessions = [_make_summary(frustration_count=10, frustration_words={"ugh": 5, "again": 5})]
        analyzer = HealthAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        descriptions = [r.description for r in result.recommendations]
        assert any("frustration" in d.lower() or "loop" in d.lower() for d in descriptions)

    def test_healthy_session_no_critical(self):
        from cc_retrospect.core import HealthAnalyzer, default_config
        sessions = [_make_summary(
            duration_minutes=30,
            message_count=20,
            subagent_count=1,
            total_cost=5.0,
            frustration_count=0,
        )]
        analyzer = HealthAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        severities = [r.severity for r in result.recommendations]
        assert "error" not in severities


class TestHabitsAnalyzer:
    """Behavioral pattern analysis."""

    def test_produces_output(self):
        from cc_retrospect.core import HabitsAnalyzer, default_config
        sessions = [
            _make_summary(start_ts="2026-04-05T10:00:00Z"),
            _make_summary(start_ts="2026-04-05T22:00:00Z", session_id="s2"),
        ]
        analyzer = HabitsAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        assert result.title
        assert len(result.sections) > 0

    def test_detects_peak_hours(self):
        from cc_retrospect.core import HabitsAnalyzer, default_config
        sessions = [
            _make_summary(start_ts=f"2026-04-05T22:{i:02d}:00Z", session_id=f"s{i}")
            for i in range(10)
        ]
        analyzer = HabitsAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        # Should mention evening/night as peak
        flat = " ".join(str(s) for s in result.sections)
        assert "22" in flat or "10 PM" in flat or "peak" in flat.lower()


class TestCostAnalyzer:
    """Cost analysis and what-if scenarios."""

    def test_produces_output(self):
        from cc_retrospect.core import CostAnalyzer, default_config
        sessions = [_make_summary()]
        analyzer = CostAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        assert result.title
        assert len(result.sections) > 0

    def test_whatif_sonnet(self):
        """What-if should show savings if using Sonnet."""
        from cc_retrospect.core import CostAnalyzer, default_config
        sessions = [_make_summary(
            model_breakdown={"claude-opus-4-6": 1000.0},
            total_cost=1000.0,
        )]
        analyzer = CostAnalyzer()
        result = analyzer.analyze(sessions, default_config())
        recs = [r.description for r in result.recommendations]
        assert any("sonnet" in r.lower() or "save" in r.lower() for r in recs)


class TestAnalyzerProtocol:
    """All analyzers must follow the protocol."""

    def test_all_analyzers_have_name_and_description(self):
        from cc_retrospect.core import (
            CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
            WasteAnalyzer, TipsAnalyzer, CompareAnalyzer,
        )
        for cls in [CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
                     WasteAnalyzer, TipsAnalyzer, CompareAnalyzer]:
            a = cls()
            assert hasattr(a, "name")
            assert hasattr(a, "description")
            assert len(a.name) > 0
            assert len(a.description) > 0

    def test_all_analyzers_return_analysis_result(self):
        from cc_retrospect.core import (
            CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
            WasteAnalyzer, TipsAnalyzer,
            AnalysisResult, default_config,
        )
        sessions = [_make_summary()]
        for cls in [CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
                     WasteAnalyzer, TipsAnalyzer]:
            a = cls()
            result = a.analyze(sessions, default_config())
            assert isinstance(result, AnalysisResult), f"{cls.__name__} didn't return AnalysisResult"

    def test_analyzers_handle_empty_sessions(self):
        from cc_retrospect.core import (
            CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
            WasteAnalyzer, TipsAnalyzer,
            default_config,
        )
        for cls in [CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
                     WasteAnalyzer, TipsAnalyzer]:
            a = cls()
            result = a.analyze([], default_config())
            assert result is not None


class TestAnalysisResultRendering:
    """AnalysisResult should render as text, markdown, and JSON."""

    def test_render_text(self):
        from cc_retrospect.core import AnalysisResult, Section, Recommendation
        result = AnalysisResult(
            title="Test",
            sections=[Section(header="Stats", rows=[("Cost", "$100")])],
            recommendations=[Recommendation(severity="warning", description="Too expensive", estimated_savings="$50")],
        )
        text = result.render_text()
        assert "Test" in text
        assert "$100" in text
        assert "Too expensive" in text

    def test_render_markdown(self):
        from cc_retrospect.core import AnalysisResult, Section, Recommendation
        result = AnalysisResult(
            title="Test",
            sections=[Section(header="Stats", rows=[("Cost", "$100")])],
            recommendations=[Recommendation(severity="warning", description="Fix it", estimated_savings="$50")],
        )
        md = result.render_markdown()
        assert "## Test" in md or "# Test" in md
        assert "$100" in md

    def test_render_json(self):
        from cc_retrospect.core import AnalysisResult, Section, Recommendation
        result = AnalysisResult(
            title="Test",
            sections=[Section(header="Stats", rows=[("Cost", "$100")])],
            recommendations=[Recommendation(severity="info", description="Note", estimated_savings="")],
        )
        j = result.render_json()
        parsed = json.loads(j)
        assert parsed["title"] == "Test"
        assert len(parsed["sections"]) == 1
        assert len(parsed["recommendations"]) == 1
