"""cc-retrospect parsers — JSONL reading, usage extraction, session analysis."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from cc_retrospect.config import Config, ModelPricing
from cc_retrospect.models import UsageRecord, SessionSummary

logger = logging.getLogger("cc_retrospect")


def iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    logger.debug("Skipping malformed JSONL line in %s: %s", path, e)
    except OSError as e:
        logger.debug("Cannot read %s: %s", path, e)


def iter_project_sessions(claude_dir: Path) -> Iterator[tuple[str, Path]]:
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        for item in sorted(project_dir.iterdir()):
            if item.suffix == ".jsonl" and item.is_file():
                yield project_dir.name, item
            elif item.is_dir() and item.name != "memory":
                for sub_dir in [item, item / "subagents"]:
                    if sub_dir.is_dir():
                        for sub in sorted(sub_dir.iterdir()):
                            if sub.suffix == ".jsonl" and sub.is_file():
                                yield project_dir.name, sub


def extract_usage(entry: dict, project: str) -> UsageRecord | None:
    if entry.get("type") != "assistant":
        return None
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not usage or not isinstance(usage, dict):
        return None
    return UsageRecord(
        timestamp=entry.get("timestamp", ""), session_id=entry.get("sessionId", ""),
        project=project, model=msg.get("model", "unknown"),
        input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        entrypoint=entry.get("entrypoint", ""), cwd=entry.get("cwd", ""),
        git_branch=entry.get("gitBranch", ""),
    )


def _pricing_for_model(model_str: str, pricing: ModelPricing):
    """Get pricing config for a model, with support for full model names."""
    m = model_str.lower()
    # Check full model names first
    if "claude-opus" in m or "claude-3-opus" in m or "claude-4" in m:
        return pricing.opus
    if "claude-sonnet" in m or "claude-3-sonnet" in m:
        return pricing.sonnet
    if "claude-haiku" in m or "claude-3-haiku" in m:
        return pricing.haiku
    # Fallback to substring matching
    if "sonnet" in m: return pricing.sonnet
    if "haiku" in m: return pricing.haiku
    # Log debug for test/synthetic models, default to opus (conservative)
    if m and not m.startswith("<"):  # Don't warn on test models like <synthetic>
        if m not in ("opus", "gpt-4", "gpt-3.5"):  # known non-Claude models
            logger.debug("Unknown model string: %s, defaulting to Opus pricing", model_str)
    return pricing.opus


def compute_cost(rec: UsageRecord, pricing: ModelPricing) -> float:
    p = _pricing_for_model(rec.model, pricing)
    return (rec.input_tokens / 1e6 * p.input_per_mtok + rec.output_tokens / 1e6 * p.output_per_mtok
            + rec.cache_creation_tokens / 1e6 * p.cache_create_per_mtok
            + rec.cache_read_tokens / 1e6 * p.cache_read_per_mtok)


def analyze_session(jsonl_path: Path, project: str, config: Config) -> SessionSummary:

    session_id = first_ts = last_ts = entrypoint = cwd = git_branch = ""
    msg_count = user_count = assistant_count = total_input = total_output = 0
    total_cache_create = total_cache_read = subagent_count = mega_count = frust_count = 0
    total_cost = 0.0
    model_costs: dict[str, float] = defaultdict(float)
    tool_counts: Counter = Counter()
    frust_words: Counter = Counter()
    webfetch_domains: Counter = Counter()
    prev_tool: str | None = None
    chain_length = 0
    chain_records: list[tuple[str, int]] = []
    keywords = [k.lower() for k in config.thresholds.frustration_keywords]

    for entry in iter_jsonl(jsonl_path):
        ts = entry.get("timestamp", "")
        if ts:
            if not first_ts: first_ts = ts
            last_ts = ts
        if not session_id: session_id = entry.get("sessionId", "")
        entry_type = entry.get("type", "")

        if entry_type == "user":
            user_count += 1; msg_count += 1
            content = entry.get("message", {}).get("content", "")
            if isinstance(content, list):
                content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            if isinstance(content, str):
                if len(content) > config.thresholds.mega_prompt_chars: mega_count += 1
                if len(content) < 100:
                    cl = content.lower().strip()
                    for kw in keywords:
                        if kw in cl:
                            frust_count += 1; frust_words[kw.strip()] += 1; break

        elif entry_type == "assistant":
            assistant_count += 1; msg_count += 1
            if not entrypoint: entrypoint = entry.get("entrypoint", "")
            if not cwd: cwd = entry.get("cwd", "")
            if not git_branch: git_branch = entry.get("gitBranch", "")
            rec = extract_usage(entry, project)
            if rec:
                total_input += rec.input_tokens; total_output += rec.output_tokens
                total_cache_create += rec.cache_creation_tokens; total_cache_read += rec.cache_read_tokens
                cost = compute_cost(rec, config.pricing); total_cost += cost; model_costs[rec.model] += cost
            for block in entry.get("message", {}).get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use": continue
                tool_name = block.get("name", "unknown")
                tool_counts[tool_name] += 1
                if tool_name == "Agent": subagent_count += 1
                if tool_name == "WebFetch":
                    url = block.get("input", {}).get("url", "") if isinstance(block.get("input"), dict) else ""
                    if url:
                        try:
                            domain = urlparse(url).netloc
                            if domain: webfetch_domains[domain] += 1
                        except Exception as e:
                            logger.debug("urlparse failed: %s", e)
                if tool_name == prev_tool:
                    chain_length += 1
                else:
                    if prev_tool and chain_length >= 2: chain_records.append((prev_tool, chain_length))
                    prev_tool = tool_name; chain_length = 1

    if prev_tool and chain_length >= 2: chain_records.append((prev_tool, chain_length))
    duration = 0.0
    if first_ts and last_ts:
        try:
            t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            duration = max(0, (t2 - t1).total_seconds() / 60)
        except (ValueError, TypeError) as e:
            logger.debug("Could not parse timestamps in %s: %s", jsonl_path, e)

    return SessionSummary(
        session_id=session_id or jsonl_path.stem, project=project,
        start_ts=first_ts, end_ts=last_ts, duration_minutes=duration,
        message_count=msg_count, user_message_count=user_count, assistant_message_count=assistant_count,
        total_input_tokens=total_input, total_output_tokens=total_output,
        total_cache_creation_tokens=total_cache_create, total_cache_read_tokens=total_cache_read,
        total_cost=total_cost, model_breakdown=dict(model_costs), tool_counts=dict(tool_counts),
        tool_chains=chain_records, subagent_count=subagent_count,
        mega_prompt_count=mega_count, frustration_count=frust_count,
        frustration_words=dict(frust_words), webfetch_domains=dict(webfetch_domains),
        entrypoint=entrypoint, cwd=cwd, git_branch=git_branch,
    )
