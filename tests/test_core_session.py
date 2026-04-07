"""Tests for SessionSummary extraction from JSONL files."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestAnalyzeSession:
    """Full session analysis from a JSONL file."""

    def test_basic_session_summary(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        assert summary.session_id == "sess-001"
        assert summary.project == "myapp"
        assert summary.assistant_message_count == 8
        assert summary.user_message_count == 4

    def test_token_totals(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        # Sum of all input_tokens across 8 assistant messages
        expected_input = 500 + 100 + 100 + 200 + 300 + 400 + 500 + 500
        assert summary.total_input_tokens == expected_input
        # Sum of all output_tokens
        expected_output = 25 + 50 + 30 + 100 + 150 + 200 + 75 + 100
        assert summary.total_output_tokens == expected_output

    def test_tool_counts(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        assert summary.tool_counts.get("Read", 0) == 2
        assert summary.tool_counts.get("Bash", 0) == 4
        assert summary.tool_counts.get("WebFetch", 0) == 1
        assert summary.tool_counts.get("Agent", 0) == 1
        assert summary.tool_counts.get("Edit", 0) == 1

    def test_frustration_detection(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        # "ugh" and "again" are in the fixture
        assert summary.frustration_count >= 2
        assert "ugh" in summary.frustration_words
        assert "again" in summary.frustration_words

    def test_mega_prompt_detection(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        # The long pasted message is >1000 chars
        assert summary.mega_prompt_count >= 1

    def test_webfetch_domain_tracking(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        assert "github.com" in summary.webfetch_domains
        assert summary.webfetch_domains["github.com"] >= 1

    def test_subagent_counting(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        assert summary.subagent_count >= 1

    def test_tool_chain_detection(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        # Read->Read chain of 2, Bash->Bash chains
        chain_names = [name for name, length in summary.tool_chains]
        assert "Read" in chain_names or "Bash" in chain_names

    def test_duration_calculation(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        assert summary.duration_minutes > 0
        # Session spans from 10:00:00 to 10:06:00 = 6 minutes
        assert abs(summary.duration_minutes - 6.0) < 1.0

    def test_cost_is_positive(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        assert summary.total_cost > 0

    def test_sonnet_session(self):
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "sonnet_session.jsonl", "simple", default_config()
        )
        assert summary.session_id == "sess-002"
        assert "claude-sonnet-4-6" in summary.model_breakdown
        assert summary.entrypoint == "cli"

    def test_malformed_session(self):
        """Parser should not crash on malformed JSONL."""
        from cc_sentinel.core import analyze_session, default_config
        summary = analyze_session(
            FIXTURES / "malformed.jsonl", "broken", default_config()
        )
        # Should still produce a summary from whatever valid data exists
        assert summary is not None
        assert summary.project == "broken"


class TestSessionSummarySerialize:
    """SessionSummary should be serializable to/from JSON for sessions.jsonl caching."""

    def test_roundtrip(self):
        from cc_sentinel.core import analyze_session, default_config, session_summary_to_dict, session_summary_from_dict
        summary = analyze_session(
            FIXTURES / "sample_session.jsonl", "myapp", default_config()
        )
        d = session_summary_to_dict(summary)
        restored = session_summary_from_dict(d)
        assert restored.session_id == summary.session_id
        assert restored.total_cost == summary.total_cost
        assert restored.tool_counts == summary.tool_counts
        assert restored.frustration_count == summary.frustration_count
