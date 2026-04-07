"""Tests for JSONL parsing, token extraction, and cost calculation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestIterJsonl:
    """Streaming JSONL parser must handle real-world edge cases."""

    def test_parses_valid_lines(self):
        from cc_sentinel.core import iter_jsonl
        results = list(iter_jsonl(FIXTURES / "sample_session.jsonl"))
        assert len(results) == 12  # 4 user + 8 assistant entries

    def test_skips_malformed_lines(self):
        from cc_sentinel.core import iter_jsonl
        results = list(iter_jsonl(FIXTURES / "malformed.jsonl"))
        # "not valid json at all" and empty line should be skipped
        assert all(isinstance(r, dict) for r in results)
        # Should parse 4 valid JSON objects (skip bad line and empty line)
        assert len(results) == 4

    def test_empty_file(self):
        from cc_sentinel.core import iter_jsonl
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            f.flush()
            results = list(iter_jsonl(Path(f.name)))
        assert results == []

    def test_nonexistent_file(self):
        from cc_sentinel.core import iter_jsonl
        results = list(iter_jsonl(Path("/nonexistent/file.jsonl")))
        assert results == []


class TestExtractUsage:
    """Usage extraction from assistant messages."""

    def test_extracts_opus_usage(self):
        from cc_sentinel.core import extract_usage
        entry = {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 25,
                    "cache_creation_input_tokens": 10000,
                    "cache_read_input_tokens": 0,
                },
            },
            "timestamp": "2026-04-05T10:00:05Z",
            "sessionId": "sess-001",
            "entrypoint": "claude-desktop",
            "cwd": "/test",
            "gitBranch": "main",
        }
        rec = extract_usage(entry, "myproject")
        assert rec is not None
        assert rec.model == "claude-opus-4-6"
        assert rec.input_tokens == 500
        assert rec.output_tokens == 25
        assert rec.cache_creation_tokens == 10000
        assert rec.cache_read_tokens == 0
        assert rec.project == "myproject"

    def test_returns_none_for_user_messages(self):
        from cc_sentinel.core import extract_usage
        entry = {"type": "user", "message": {"content": "hello"}}
        assert extract_usage(entry, "proj") is None

    def test_returns_none_for_missing_usage(self):
        from cc_sentinel.core import extract_usage
        entry = {"type": "assistant", "message": {"model": "claude-opus-4-6"}}
        assert extract_usage(entry, "proj") is None

    def test_handles_missing_optional_fields(self):
        from cc_sentinel.core import extract_usage
        entry = {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
            "timestamp": "2026-04-05T10:00:00Z",
            "sessionId": "s1",
        }
        rec = extract_usage(entry, "proj")
        assert rec is not None
        assert rec.cache_creation_tokens == 0
        assert rec.cache_read_tokens == 0
        assert rec.entrypoint == ""
        assert rec.cwd == ""


class TestComputeCost:
    """Cost calculation at known API rates, verified to the penny."""

    def test_opus_cost(self):
        from cc_sentinel.core import compute_cost, UsageRecord, default_config
        rec = UsageRecord(
            timestamp="", session_id="", project="", model="claude-opus-4-6",
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000,
            entrypoint="", cwd="", git_branch="",
        )
        cost = compute_cost(rec, default_config().pricing)
        # 1M input * $15/M + 1M output * $75/M + 1M cache_create * $18.75/M + 1M cache_read * $1.50/M
        expected = 15.0 + 75.0 + 18.75 + 1.50
        assert abs(cost - expected) < 0.01, f"Expected {expected}, got {cost}"

    def test_sonnet_cost(self):
        from cc_sentinel.core import compute_cost, UsageRecord, default_config
        rec = UsageRecord(
            timestamp="", session_id="", project="", model="claude-sonnet-4-6",
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000,
            entrypoint="", cwd="", git_branch="",
        )
        cost = compute_cost(rec, default_config().pricing)
        expected = 3.0 + 15.0 + 3.75 + 0.30
        assert abs(cost - expected) < 0.01, f"Expected {expected}, got {cost}"

    def test_haiku_cost(self):
        from cc_sentinel.core import compute_cost, UsageRecord, default_config
        rec = UsageRecord(
            timestamp="", session_id="", project="", model="claude-haiku-4-5-20251001",
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000,
            entrypoint="", cwd="", git_branch="",
        )
        cost = compute_cost(rec, default_config().pricing)
        expected = 0.80 + 4.0 + 1.0 + 0.08
        assert abs(cost - expected) < 0.01, f"Expected {expected}, got {cost}"

    def test_zero_tokens_zero_cost(self):
        from cc_sentinel.core import compute_cost, UsageRecord, default_config
        rec = UsageRecord(
            timestamp="", session_id="", project="", model="claude-opus-4-6",
            input_tokens=0, output_tokens=0,
            cache_creation_tokens=0, cache_read_tokens=0,
            entrypoint="", cwd="", git_branch="",
        )
        assert compute_cost(rec, default_config().pricing) == 0.0

    def test_unknown_model_defaults_to_opus(self):
        from cc_sentinel.core import compute_cost, UsageRecord, default_config
        rec = UsageRecord(
            timestamp="", session_id="", project="", model="some-future-model",
            input_tokens=1_000_000, output_tokens=0,
            cache_creation_tokens=0, cache_read_tokens=0,
            entrypoint="", cwd="", git_branch="",
        )
        cost = compute_cost(rec, default_config().pricing)
        assert abs(cost - 15.0) < 0.01  # Opus input rate


class TestDisplayProject:
    """Project name cleaning for display."""

    def test_strips_full_prefix(self):
        from cc_sentinel.core import display_project
        assert display_project("-Users-testuser-Projects-later") == "later"

    def test_strips_partial_prefix(self):
        from cc_sentinel.core import display_project
        assert display_project("-Users-testuser-moltsnip") == "moltsnip"

    def test_handles_worktrees(self):
        from cc_sentinel.core import display_project
        result = display_project("-Users-testuser-moltsnip--claude-worktrees-nifty-mendeleev")
        assert "moltsnip" in result

    def test_passthrough_for_simple_names(self):
        from cc_sentinel.core import display_project
        assert display_project("myproject") == "myproject"
