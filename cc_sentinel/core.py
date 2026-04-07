"""cc-sentinel core — all business logic for Claude Code session analysis.

Pure Python 3.10+, stdlib only. Extensible analyzer protocol.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Logger — writes to stderr, level controlled by CC_SENTINEL_LOG_LEVEL
# ---------------------------------------------------------------------------

def _make_logger() -> logging.Logger:
    log = logging.getLogger("cc_sentinel")
    if not log.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("[cc-sentinel] %(levelname)s %(message)s"))
        log.addHandler(handler)
    level_name = os.environ.get("CC_SENTINEL_LOG_LEVEL", "WARNING").upper()
    log.setLevel(getattr(logging, level_name, logging.WARNING))
    return log

logger = _make_logger()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PricingConfig:
    input_per_mtok: float = 15.0
    output_per_mtok: float = 75.0
    cache_create_per_mtok: float = 18.75
    cache_read_per_mtok: float = 1.50


@dataclass
class ModelPricing:
    opus: PricingConfig = field(default_factory=PricingConfig)
    sonnet: PricingConfig = field(default_factory=lambda: PricingConfig(
        input_per_mtok=3.0, output_per_mtok=15.0,
        cache_create_per_mtok=3.75, cache_read_per_mtok=0.30,
    ))
    haiku: PricingConfig = field(default_factory=lambda: PricingConfig(
        input_per_mtok=0.80, output_per_mtok=4.0,
        cache_create_per_mtok=1.0, cache_read_per_mtok=0.08,
    ))


@dataclass
class ThresholdsConfig:
    long_session_minutes: int = 120
    long_session_messages: int = 200
    mega_prompt_chars: int = 1000
    max_subagents_per_session: int = 10
    max_claudemd_bytes: int = 50_000
    frustration_keywords: list[str] = field(default_factory=lambda: [
        "again", "ugh", "still broken", "not working", "wrong",
        "try again", "that's wrong", "no ", "still not", "wtf",
        "come on", "seriously", "sigh", "nope",
    ])
    waste_webfetch_domains: list[str] = field(default_factory=lambda: [
        "github.com", "api.github.com",
    ])
    tool_chain_threshold: int = 5
    daily_cost_warning: float = 500.0


@dataclass
class HintsConfig:
    session_start: bool = False   # Show last-session summary on new session (default: off)
    pre_tool: bool = True         # Inline hints before tool calls (WebFetch/Bash chains)
    post_tool: bool = True        # Post-tool hints: compact nudge, subagent warnings


@dataclass
class Config:
    pricing: ModelPricing = field(default_factory=ModelPricing)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    hints: HintsConfig = field(default_factory=HintsConfig)
    data_dir: Path = field(default_factory=lambda: Path.home() / ".cc-sentinel")
    claude_dir: Path = field(default_factory=lambda: Path.home() / ".claude")


def default_config() -> Config:
    return Config()


def load_config(config_path: Path | None = None) -> Config:
    cfg = Config()
    path = config_path or cfg.data_dir / "config.env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            _apply_config(cfg, key, val)
    # Env var overrides
    for k, v in os.environ.items():
        if k.startswith("CC_ANALYZE_"):
            _apply_config(cfg, k[len("CC_ANALYZE_"):], v)
    return cfg


def _apply_config(cfg: Config, key: str, val: str) -> None:
    key = key.upper()
    try:
        if key == "PRICING_OPUS_INPUT_PER_MTOK":
            cfg.pricing.opus.input_per_mtok = float(val)
        elif key == "PRICING_OPUS_OUTPUT_PER_MTOK":
            cfg.pricing.opus.output_per_mtok = float(val)
        elif key == "PRICING_OPUS_CACHE_CREATE_PER_MTOK":
            cfg.pricing.opus.cache_create_per_mtok = float(val)
        elif key == "PRICING_OPUS_CACHE_READ_PER_MTOK":
            cfg.pricing.opus.cache_read_per_mtok = float(val)
        elif key == "PRICING_SONNET_INPUT_PER_MTOK":
            cfg.pricing.sonnet.input_per_mtok = float(val)
        elif key == "PRICING_SONNET_OUTPUT_PER_MTOK":
            cfg.pricing.sonnet.output_per_mtok = float(val)
        elif key == "PRICING_HAIKU_INPUT_PER_MTOK":
            cfg.pricing.haiku.input_per_mtok = float(val)
        elif key == "PRICING_HAIKU_OUTPUT_PER_MTOK":
            cfg.pricing.haiku.output_per_mtok = float(val)
        elif key == "THRESHOLD_LONG_SESSION_MINUTES":
            cfg.thresholds.long_session_minutes = int(val)
        elif key == "THRESHOLD_LONG_SESSION_MESSAGES":
            cfg.thresholds.long_session_messages = int(val)
        elif key == "THRESHOLD_MEGA_PROMPT_CHARS":
            cfg.thresholds.mega_prompt_chars = int(val)
        elif key == "THRESHOLD_MAX_SUBAGENTS":
            cfg.thresholds.max_subagents_per_session = int(val)
        elif key == "THRESHOLD_DAILY_COST_WARNING":
            cfg.thresholds.daily_cost_warning = float(val)
        elif key == "WASTE_WEBFETCH_DOMAINS":
            cfg.thresholds.waste_webfetch_domains = [d.strip() for d in val.split(",") if d.strip()]
        elif key == "HINTS_SESSION_START":
            cfg.hints.session_start = val.lower() in ("1", "true", "yes")
        elif key == "HINTS_PRE_TOOL":
            cfg.hints.pre_tool = val.lower() not in ("0", "false", "no")
        elif key == "HINTS_POST_TOOL":
            cfg.hints.post_tool = val.lower() not in ("0", "false", "no")
    except (ValueError, TypeError) as e:
        logger.debug("Ignoring bad config value %s=%r: %s", key, val, e)


# ---------------------------------------------------------------------------
# JSONL streaming parser
# ---------------------------------------------------------------------------

def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield parsed JSON objects from a JSONL file, line by line."""
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
                    continue
    except OSError as e:
        logger.debug("Cannot read %s: %s", path, e)
        return


def iter_project_sessions(claude_dir: Path) -> Iterator[tuple[str, Path]]:
    """Yield (project_name, jsonl_path) for all project session files."""
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        for item in sorted(project_dir.iterdir()):
            if item.suffix == ".jsonl" and item.is_file():
                yield project_name, item
            elif item.is_dir() and item.name != "memory":
                for sub_dir in [item, item / "subagents"]:
                    if sub_dir.is_dir():
                        for sub in sorted(sub_dir.iterdir()):
                            if sub.suffix == ".jsonl" and sub.is_file():
                                yield project_name, sub


# ---------------------------------------------------------------------------
# Usage extraction
# ---------------------------------------------------------------------------

@dataclass
class UsageRecord:
    timestamp: str
    session_id: str
    project: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    entrypoint: str
    cwd: str
    git_branch: str


def extract_usage(entry: dict, project: str) -> UsageRecord | None:
    """Extract usage from an assistant-type entry. Returns None for non-assistant."""
    if entry.get("type") != "assistant":
        return None
    msg = entry.get("message", {})
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not usage or not isinstance(usage, dict):
        return None
    return UsageRecord(
        timestamp=entry.get("timestamp", ""),
        session_id=entry.get("sessionId", ""),
        project=project,
        model=msg.get("model", "unknown"),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        entrypoint=entry.get("entrypoint", ""),
        cwd=entry.get("cwd", ""),
        git_branch=entry.get("gitBranch", ""),
    )


def _pricing_for_model(model_str: str, pricing: ModelPricing) -> PricingConfig:
    m = model_str.lower()
    if "sonnet" in m:
        return pricing.sonnet
    elif "haiku" in m:
        return pricing.haiku
    return pricing.opus  # default to most expensive


def compute_cost(rec: UsageRecord, pricing: ModelPricing) -> float:
    p = _pricing_for_model(rec.model, pricing)
    return (
        rec.input_tokens / 1e6 * p.input_per_mtok
        + rec.output_tokens / 1e6 * p.output_per_mtok
        + rec.cache_creation_tokens / 1e6 * p.cache_create_per_mtok
        + rec.cache_read_tokens / 1e6 * p.cache_read_per_mtok
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_PROJECT_PREFIX_RE = re.compile(r"^-Users-[^-]+-(?:Projects-)?")


def display_project(raw_name: str) -> str:
    """Clean project directory name for display."""
    cleaned = _PROJECT_PREFIX_RE.sub("", raw_name)
    return cleaned if cleaned else raw_name


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(c: float) -> str:
    if c >= 1000:
        return f"${c:,.0f}"
    elif c >= 1:
        return f"${c:.2f}"
    return f"${c:.4f}"


def _fmt_duration(minutes: float) -> str:
    if minutes >= 60:
        h = int(minutes // 60)
        m = int(minutes % 60)
        return f"{h}h {m}m"
    return f"{minutes:.0f}m"


# ---------------------------------------------------------------------------
# Session analysis
# ---------------------------------------------------------------------------

@dataclass
class SessionSummary:
    session_id: str
    project: str
    start_ts: str
    end_ts: str
    duration_minutes: float
    message_count: int
    user_message_count: int
    assistant_message_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_cost: float
    model_breakdown: dict[str, float]
    tool_counts: dict[str, int]
    tool_chains: list[tuple[str, int]]
    subagent_count: int
    mega_prompt_count: int
    frustration_count: int
    frustration_words: dict[str, int]
    webfetch_domains: dict[str, int]
    entrypoint: str
    cwd: str
    git_branch: str


def analyze_session(jsonl_path: Path, project: str, config: Config) -> SessionSummary:
    """Stream through a JSONL file and produce a SessionSummary in a single pass."""
    session_id = ""
    first_ts = ""
    last_ts = ""
    msg_count = 0
    user_count = 0
    assistant_count = 0
    total_input = 0
    total_output = 0
    total_cache_create = 0
    total_cache_read = 0
    total_cost = 0.0
    model_costs: dict[str, float] = defaultdict(float)
    tool_counts: dict[str, int] = Counter()
    subagent_count = 0
    mega_prompt_count = 0
    frustration_count = 0
    frustration_words: dict[str, int] = Counter()
    webfetch_domains: dict[str, int] = Counter()
    entrypoint = ""
    cwd = ""
    git_branch = ""

    # Tool chain tracking
    prev_tool: str | None = None
    chain_length = 0
    chain_records: list[tuple[str, int]] = []
    threshold = config.thresholds.tool_chain_threshold

    keywords = [k.lower() for k in config.thresholds.frustration_keywords]

    for entry in iter_jsonl(jsonl_path):
        entry_type = entry.get("type", "")
        ts = entry.get("timestamp", "")

        if ts:
            if not first_ts:
                first_ts = ts
            last_ts = ts

        if not session_id:
            session_id = entry.get("sessionId", "")

        if entry_type == "user":
            user_count += 1
            msg_count += 1
            content = entry.get("message", {}).get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            if isinstance(content, str):
                clen = len(content)
                if clen > config.thresholds.mega_prompt_chars:
                    mega_prompt_count += 1
                # Frustration detection: short messages with keywords
                if clen < 100:
                    content_lower = content.lower().strip()
                    for kw in keywords:
                        if kw in content_lower:
                            frustration_count += 1
                            frustration_words[kw.strip()] += 1
                            break  # count once per message

        elif entry_type == "assistant":
            assistant_count += 1
            msg_count += 1
            rec = extract_usage(entry, project)

            if not entrypoint:
                entrypoint = entry.get("entrypoint", "")
            if not cwd:
                cwd = entry.get("cwd", "")
            if not git_branch:
                git_branch = entry.get("gitBranch", "")

            if rec:
                total_input += rec.input_tokens
                total_output += rec.output_tokens
                total_cache_create += rec.cache_creation_tokens
                total_cache_read += rec.cache_read_tokens
                cost = compute_cost(rec, config.pricing)
                total_cost += cost
                model_costs[rec.model] += cost

            # Extract tools from content blocks
            msg = entry.get("message", {})
            content_blocks = msg.get("content", [])
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tool_name = block.get("name", "unknown")
                        tool_counts[tool_name] += 1

                        # Subagent detection
                        if tool_name == "Agent":
                            subagent_count += 1

                        # WebFetch domain tracking
                        if tool_name == "WebFetch":
                            tool_input = block.get("input", {})
                            if isinstance(tool_input, dict):
                                url = tool_input.get("url", "")
                                if url:
                                    try:
                                        domain = urlparse(url).netloc
                                        if domain:
                                            webfetch_domains[domain] += 1
                                    except Exception as e:
                                        logger.debug("urlparse failed for WebFetch URL: %s", e)

                        # Tool chain tracking
                        if tool_name == prev_tool:
                            chain_length += 1
                        else:
                            if prev_tool and chain_length >= 2:
                                chain_records.append((prev_tool, chain_length))
                            prev_tool = tool_name
                            chain_length = 1

    # Final chain
    if prev_tool and chain_length >= 2:
        chain_records.append((prev_tool, chain_length))

    # Duration
    duration = 0.0
    if first_ts and last_ts:
        try:
            t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            duration = max(0, (t2 - t1).total_seconds() / 60)
        except (ValueError, TypeError) as e:
            logger.debug("Could not parse duration timestamps in %s: %s", jsonl_path, e)

    return SessionSummary(
        session_id=session_id or jsonl_path.stem,
        project=project,
        start_ts=first_ts,
        end_ts=last_ts,
        duration_minutes=duration,
        message_count=msg_count,
        user_message_count=user_count,
        assistant_message_count=assistant_count,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cache_creation_tokens=total_cache_create,
        total_cache_read_tokens=total_cache_read,
        total_cost=total_cost,
        model_breakdown=dict(model_costs),
        tool_counts=dict(tool_counts),
        tool_chains=chain_records,
        subagent_count=subagent_count,
        mega_prompt_count=mega_prompt_count,
        frustration_count=frustration_count,
        frustration_words=dict(frustration_words),
        webfetch_domains=dict(webfetch_domains),
        entrypoint=entrypoint,
        cwd=cwd,
        git_branch=git_branch,
    )


def session_summary_to_dict(s: SessionSummary) -> dict:
    return asdict(s)


def session_summary_from_dict(d: dict) -> SessionSummary:
    d = dict(d)
    d["tool_chains"] = [tuple(x) for x in d.get("tool_chains", [])]
    return SessionSummary(**d)


# ---------------------------------------------------------------------------
# Analyzer protocol and result types
# ---------------------------------------------------------------------------

@dataclass
class Section:
    header: str
    rows: list[tuple[str, str]]  # (label, value) pairs


@dataclass
class Recommendation:
    severity: str  # "info", "warning", "error"
    description: str
    estimated_savings: str = ""


@dataclass
class AnalysisResult:
    title: str
    sections: list[Section]
    recommendations: list[Recommendation]

    def render_text(self) -> str:
        lines: list[str] = []
        lines.append(f"## {self.title}")
        lines.append("")
        for section in self.sections:
            lines.append(f"### {section.header}")
            for label, value in section.rows:
                lines.append(f"  {label:<35} {value}")
            lines.append("")
        if self.recommendations:
            lines.append("### Recommendations")
            for r in self.recommendations:
                icon = {"error": "[!]", "warning": "[~]", "info": "[i]"}.get(r.severity, "[-]")
                sav = f" (save {r.estimated_savings})" if r.estimated_savings else ""
                lines.append(f"  {icon} {r.description}{sav}")
            lines.append("")
        return "\n".join(lines)

    def render_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"## {self.title}")
        lines.append("")
        for section in self.sections:
            lines.append(f"### {section.header}")
            lines.append("")
            lines.append(f"| {'Metric':<35} | {'Value':<20} |")
            lines.append(f"|{'-'*37}|{'-'*22}|")
            for label, value in section.rows:
                lines.append(f"| {label:<35} | {value:<20} |")
            lines.append("")
        if self.recommendations:
            lines.append("### Recommendations")
            lines.append("")
            for r in self.recommendations:
                icon = {"error": "**[!]**", "warning": "[~]", "info": "[i]"}.get(r.severity, "[-]")
                sav = f" _(save {r.estimated_savings})_" if r.estimated_savings else ""
                lines.append(f"- {icon} {r.description}{sav}")
            lines.append("")
        return "\n".join(lines)

    def render_json(self) -> str:
        return json.dumps({
            "title": self.title,
            "sections": [
                {"header": s.header, "rows": [{"label": l, "value": v} for l, v in s.rows]}
                for s in self.sections
            ],
            "recommendations": [
                {"severity": r.severity, "description": r.description, "estimated_savings": r.estimated_savings}
                for r in self.recommendations
            ],
        }, indent=2)


@runtime_checkable
class Analyzer(Protocol):
    name: str
    description: str

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult: ...


# ---------------------------------------------------------------------------
# Built-in analyzers
# ---------------------------------------------------------------------------

class CostAnalyzer:
    name = "cost"
    description = "Cost breakdown by project, model, and time period with what-if scenarios"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions:
            return AnalysisResult(title="Cost Analysis", sections=[Section(header="No data", rows=[("Sessions", "0")])], recommendations=[])

        total_cost = sum(s.total_cost for s in sessions)
        total_input = sum(s.total_input_tokens for s in sessions)
        total_output = sum(s.total_output_tokens for s in sessions)
        total_cache_create = sum(s.total_cache_creation_tokens for s in sessions)
        total_cache_read = sum(s.total_cache_read_tokens for s in sessions)

        # By project
        proj_costs: dict[str, float] = defaultdict(float)
        for s in sessions:
            proj_costs[display_project(s.project)] += s.total_cost

        # By model
        model_costs: dict[str, float] = defaultdict(float)
        for s in sessions:
            for m, c in s.model_breakdown.items():
                model_costs[m] += c

        # By day
        day_costs: dict[str, float] = defaultdict(float)
        for s in sessions:
            if s.start_ts:
                day = s.start_ts[:10]
                day_costs[day] += s.total_cost

        sections = [
            Section(header="Totals", rows=[
                ("Total cost", _fmt_cost(total_cost)),
                ("Sessions", str(len(sessions))),
                ("Input tokens (fresh)", _fmt_tokens(total_input)),
                ("Output tokens", _fmt_tokens(total_output)),
                ("Cache creation tokens", _fmt_tokens(total_cache_create)),
                ("Cache read tokens", _fmt_tokens(total_cache_read)),
            ]),
            Section(header="By Project (top 10)", rows=[
                (proj, _fmt_cost(cost))
                for proj, cost in sorted(proj_costs.items(), key=lambda x: x[1], reverse=True)[:10]
            ]),
            Section(header="By Model", rows=[
                (model, _fmt_cost(cost))
                for model, cost in sorted(model_costs.items(), key=lambda x: x[1], reverse=True)
            ]),
        ]

        if day_costs:
            recent_days = sorted(day_costs.items(), reverse=True)[:7]
            sections.append(Section(header="Daily (last 7)", rows=[
                (day, _fmt_cost(cost)) for day, cost in recent_days
            ]))

        # What-if: all Opus at Sonnet rates
        recs: list[Recommendation] = []
        opus_cost = model_costs.get("claude-opus-4-6", 0)
        if opus_cost > 0:
            # Rough estimate: Sonnet is ~5x cheaper
            sonnet_equiv = opus_cost * (3.0 / 15.0)  # input ratio approximation
            savings = opus_cost - sonnet_equiv
            if savings > 10:
                recs.append(Recommendation(
                    severity="warning",
                    description=f"If all Opus usage switched to Sonnet, estimated savings",
                    estimated_savings=_fmt_cost(savings),
                ))

        return AnalysisResult(title="Cost Analysis", sections=sections, recommendations=recs)


class HabitsAnalyzer:
    name = "habits"
    description = "Usage patterns: time of day, session lengths, prompt style, tool usage"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions:
            return AnalysisResult(title="Usage Habits", sections=[Section(header="No data", rows=[("Sessions", "0")])], recommendations=[])

        # Session patterns
        durations = [s.duration_minutes for s in sessions if s.duration_minutes > 0]
        msg_counts = [s.message_count for s in sessions]
        avg_dur = sum(durations) / len(durations) if durations else 0
        avg_msgs = sum(msg_counts) / len(msg_counts) if msg_counts else 0
        max_dur = max(durations) if durations else 0

        # Time of day
        hour_counts: dict[int, int] = Counter()
        dow_counts: dict[str, int] = Counter()
        for s in sessions:
            if s.start_ts:
                try:
                    dt = datetime.fromisoformat(s.start_ts.replace("Z", "+00:00"))
                    hour_counts[dt.hour] += 1
                    dow_counts[dt.strftime("%A")] += 1
                except (ValueError, TypeError) as e:
                    logger.debug("Could not parse session timestamp %r: %s", s.start_ts, e)

        peak_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        peak_days = sorted(dow_counts.items(), key=lambda x: x[1], reverse=True)[:3]

        # Tool usage
        all_tools: dict[str, int] = Counter()
        for s in sessions:
            for t, c in s.tool_counts.items():
                all_tools[t] += c
        top_tools = sorted(all_tools.items(), key=lambda x: x[1], reverse=True)[:10]

        # Frustration
        total_frust = sum(s.frustration_count for s in sessions)
        all_frust_words: dict[str, int] = Counter()
        for s in sessions:
            for w, c in s.frustration_words.items():
                all_frust_words[w] += c

        # Entrypoints
        ep_counts: dict[str, int] = Counter()
        for s in sessions:
            if s.entrypoint:
                ep_counts[s.entrypoint] += 1

        sections = [
            Section(header="Session Patterns", rows=[
                ("Average duration", _fmt_duration(avg_dur)),
                ("Average messages/session", f"{avg_msgs:.0f}"),
                ("Longest session", _fmt_duration(max_dur)),
                ("Total sessions", str(len(sessions))),
            ]),
            Section(header="Peak Hours (UTC)", rows=[
                (f"{h:02d}:00", f"{c} sessions") for h, c in peak_hours
            ]),
            Section(header="Peak Days", rows=[
                (day, f"{c} sessions") for day, c in peak_days
            ]),
            Section(header="Tool Usage (top 10)", rows=[
                (tool, str(count)) for tool, count in top_tools
            ]),
        ]

        if total_frust > 0:
            frust_rows = [(w, str(c)) for w, c in sorted(all_frust_words.items(), key=lambda x: x[1], reverse=True)[:5]]
            sections.append(Section(header="Frustration Signals", rows=[
                ("Total frustration messages", str(total_frust)),
            ] + frust_rows))

        if ep_counts:
            sections.append(Section(header="Entrypoints", rows=[
                (ep, str(c)) for ep, c in ep_counts.most_common()
            ]))

        recs: list[Recommendation] = []
        if avg_dur > config.thresholds.long_session_minutes:
            recs.append(Recommendation(
                severity="warning",
                description=f"Average session duration is {_fmt_duration(avg_dur)} — aim for under {config.thresholds.long_session_minutes}m",
            ))

        return AnalysisResult(title="Usage Habits", sections=sections, recommendations=recs)


class HealthAnalyzer:
    name = "health"
    description = "Health checks: session length, subagents, config issues, cost velocity"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions:
            return AnalysisResult(title="Health Check", sections=[], recommendations=[])

        recs: list[Recommendation] = []
        rows: list[tuple[str, str]] = []
        th = config.thresholds

        # Long sessions
        long_sessions = [s for s in sessions if s.duration_minutes > th.long_session_minutes or s.message_count > th.long_session_messages]
        if long_sessions:
            avg_long = sum(s.duration_minutes for s in long_sessions) / len(long_sessions)
            recs.append(Recommendation(
                severity="warning",
                description=f"{len(long_sessions)} sessions exceed duration/message thresholds. Average long session: {_fmt_duration(avg_long)}. Use /clear more often.",
            ))
        rows.append((f"Long sessions (>{th.long_session_minutes}m)", str(len(long_sessions))))

        # Subagent overuse
        heavy_agent_sessions = [s for s in sessions if s.subagent_count > th.max_subagents_per_session]
        total_subagents = sum(s.subagent_count for s in sessions)
        if heavy_agent_sessions:
            recs.append(Recommendation(
                severity="warning",
                description=f"{len(heavy_agent_sessions)} sessions spawned >{th.max_subagents_per_session} subagents. Use Grep/Read directly for simple lookups.",
            ))
        rows.append(("Total subagent spawns", str(total_subagents)))

        # Frustration loops
        total_frust = sum(s.frustration_count for s in sessions)
        if total_frust > 5:
            recs.append(Recommendation(
                severity="info",
                description=f"{total_frust} frustration signals detected. Consider rephrasing or starting fresh sessions when stuck.",
            ))
        rows.append(("Frustration signals", str(total_frust)))

        # Cost velocity
        day_costs: dict[str, float] = defaultdict(float)
        for s in sessions:
            if s.start_ts:
                day_costs[s.start_ts[:10]] += s.total_cost
        if day_costs:
            recent = sorted(day_costs.items(), reverse=True)[:3]
            avg_daily = sum(c for _, c in recent) / len(recent) if recent else 0
            if avg_daily > th.daily_cost_warning:
                recs.append(Recommendation(
                    severity="error",
                    description=f"Spending {_fmt_cost(avg_daily)}/day (3-day avg). Projected monthly: {_fmt_cost(avg_daily * 30)}.",
                ))
            rows.append(("Avg daily cost (3-day)", _fmt_cost(avg_daily)))

        # Cache hit rate
        total_all_input = sum(s.total_input_tokens + s.total_cache_creation_tokens + s.total_cache_read_tokens for s in sessions)
        total_cache_read = sum(s.total_cache_read_tokens for s in sessions)
        cache_rate = (total_cache_read / total_all_input * 100) if total_all_input > 0 else 0
        rows.append(("Cache hit rate", f"{cache_rate:.1f}%"))
        if cache_rate < 80 and total_all_input > 100_000:
            recs.append(Recommendation(
                severity="info",
                description=f"Cache hit rate is {cache_rate:.1f}%. Sessions may be too short or context changing too rapidly.",
            ))

        sections = [Section(header="Overview", rows=rows)]
        return AnalysisResult(title="Health Check", sections=sections, recommendations=recs)


class WasteAnalyzer:
    name = "waste"
    description = "Detect wasted tokens: WebFetch to GitHub, duplicate reads, tool chains, model mismatch"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions:
            return AnalysisResult(title="Waste Analysis", sections=[], recommendations=[])

        recs: list[Recommendation] = []
        rows: list[tuple[str, str]] = []

        # WebFetch to waste domains
        domain_totals: dict[str, int] = Counter()
        domain_sessions: dict[str, int] = Counter()
        for s in sessions:
            for domain, count in s.webfetch_domains.items():
                for waste_domain in config.thresholds.waste_webfetch_domains:
                    if waste_domain in domain:
                        domain_totals[domain] += count
                        domain_sessions[domain] += 1

        for domain, count in domain_totals.items():
            recs.append(Recommendation(
                severity="warning",
                description=f"{count} WebFetch calls to {domain} across {domain_sessions[domain]} sessions. Use `gh` CLI instead — fewer tokens, structured output.",
                estimated_savings=f"~{_fmt_tokens(count * 5000)} tokens",
            ))
        rows.append(("WebFetch to waste domains", str(sum(domain_totals.values()))))

        # Tool chains
        all_chains: dict[str, list[int]] = defaultdict(list)
        for s in sessions:
            for tool, length in s.tool_chains:
                if length >= config.thresholds.tool_chain_threshold:
                    all_chains[tool].append(length)

        for tool, lengths in sorted(all_chains.items(), key=lambda x: sum(x[1]), reverse=True):
            total_in_chains = sum(lengths)
            recs.append(Recommendation(
                severity="info",
                description=f"{len(lengths)} consecutive {tool} chains (longest: {max(lengths)}). Combine related calls or use scripts.",
            ))
        rows.append(("Long tool chains", str(sum(len(v) for v in all_chains.values()))))

        # Mega prompts
        total_mega = sum(s.mega_prompt_count for s in sessions)
        if total_mega > 5:
            recs.append(Recommendation(
                severity="warning",
                description=f"{total_mega} mega prompts (>{config.thresholds.mega_prompt_chars} chars). Use file references instead of pasting content inline.",
            ))
        rows.append(("Mega prompts", str(total_mega)))

        # Model mismatch: Opus for simple tasks
        for s in sessions:
            opus_cost = s.model_breakdown.get("claude-opus-4-6", 0)
            if opus_cost <= 0:
                continue
            complex_tools = {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}
            uses_complex = any(t in s.tool_counts for t in complex_tools)
            if not uses_complex and opus_cost > 50:
                recs.append(Recommendation(
                    severity="warning",
                    description=f"Session {s.session_id[:8]}... used Opus ({_fmt_cost(opus_cost)}) for simple tasks. Sonnet would be ~5x cheaper.",
                    estimated_savings=_fmt_cost(opus_cost * 0.8),
                ))
                break  # Only report once to avoid noise

        rows.append(("Model mismatch candidates", str(
            sum(1 for s in sessions
                if s.model_breakdown.get("claude-opus-4-6", 0) > 50
                and not any(t in s.tool_counts for t in {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}))
        )))

        sections = [Section(header="Waste Summary", rows=rows)]
        return AnalysisResult(title="Waste Analysis", sections=sections, recommendations=recs)


class TipsAnalyzer:
    name = "tips"
    description = "Context-aware tips based on recent session patterns"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions:
            return AnalysisResult(title="Tips", sections=[], recommendations=[
                Recommendation(severity="info", description="No session data yet. Tips improve as more sessions are recorded."),
            ])

        recs: list[Recommendation] = []
        th = config.thresholds

        # Last session analysis
        latest = max(sessions, key=lambda s: s.end_ts or s.start_ts or "")

        if latest.duration_minutes > th.long_session_minutes:
            recs.append(Recommendation(
                severity="warning",
                description=f"Your last session ran {_fmt_duration(latest.duration_minutes)} with {latest.message_count} messages. Start fresh to avoid context growth costs.",
            ))

        if latest.subagent_count > th.max_subagents_per_session:
            recs.append(Recommendation(
                severity="info",
                description=f"Last session spawned {latest.subagent_count} subagents. Try Grep/Read directly for simple lookups.",
            ))

        if latest.frustration_count > 3:
            recs.append(Recommendation(
                severity="info",
                description=f"Detected {latest.frustration_count} frustration signals in last session. Consider rephrasing with more specificity.",
            ))

        gh_calls = sum(c for d, c in latest.webfetch_domains.items() if "github.com" in d)
        if gh_calls > 0:
            recs.append(Recommendation(
                severity="info",
                description=f"Last session used WebFetch for GitHub {gh_calls} times. `gh` CLI is faster and cheaper.",
            ))

        if latest.total_cost > 100:
            recs.append(Recommendation(
                severity="warning",
                description=f"Last session cost {_fmt_cost(latest.total_cost)}. Shorter sessions dramatically reduce costs.",
            ))

        if not recs:
            recs.append(Recommendation(severity="info", description="Your recent sessions look healthy. Keep it up!"))

        return AnalysisResult(title="Tips", sections=[], recommendations=recs[:5])


class CompareAnalyzer:
    name = "compare"
    description = "Compare usage between two time periods"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        """Compare this week vs last week by default."""
        if not sessions:
            return AnalysisResult(title="Compare", sections=[], recommendations=[])

        now = datetime.now(timezone.utc)
        # This week: Monday to now
        days_since_monday = now.weekday()
        this_week_start = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        last_week_start = this_week_start - timedelta(days=7)

        this_week = [s for s in sessions if s.start_ts and s.start_ts >= this_week_start.isoformat()]
        last_week = [s for s in sessions if s.start_ts and last_week_start.isoformat() <= s.start_ts < this_week_start.isoformat()]

        def _stats(ss: list[SessionSummary]) -> dict:
            if not ss:
                return {"cost": 0, "sessions": 0, "avg_duration": 0, "frustrations": 0, "subagents": 0}
            return {
                "cost": sum(s.total_cost for s in ss),
                "sessions": len(ss),
                "avg_duration": sum(s.duration_minutes for s in ss) / len(ss),
                "frustrations": sum(s.frustration_count for s in ss),
                "subagents": sum(s.subagent_count for s in ss),
            }

        tw = _stats(this_week)
        lw = _stats(last_week)

        def _delta(cur: float, prev: float) -> str:
            if prev == 0:
                return "N/A"
            pct = (cur - prev) / prev * 100
            return f"{pct:+.0f}%"

        rows = [
            ("Total cost", f"{_fmt_cost(tw['cost'])} vs {_fmt_cost(lw['cost'])} ({_delta(tw['cost'], lw['cost'])})"),
            ("Sessions", f"{tw['sessions']} vs {lw['sessions']} ({_delta(tw['sessions'], lw['sessions'])})"),
            ("Avg duration", f"{_fmt_duration(tw['avg_duration'])} vs {_fmt_duration(lw['avg_duration'])}"),
            ("Frustrations", f"{tw['frustrations']} vs {lw['frustrations']}"),
            ("Subagent spawns", f"{tw['subagents']} vs {lw['subagents']}"),
        ]

        recs: list[Recommendation] = []
        if tw["cost"] > lw["cost"] * 1.5 and lw["cost"] > 0:
            recs.append(Recommendation(severity="warning", description="Spending increased significantly this week."))
        elif tw["cost"] < lw["cost"] * 0.7 and lw["cost"] > 0:
            recs.append(Recommendation(severity="info", description="Good progress — spending decreased this week."))

        return AnalysisResult(
            title="This Week vs Last Week",
            sections=[Section(header="Comparison", rows=rows)],
            recommendations=recs,
        )


# ---------------------------------------------------------------------------
# Analyzer registry (extensible)
# ---------------------------------------------------------------------------

_BUILTIN_ANALYZERS: list[type] = [
    CostAnalyzer, HabitsAnalyzer, HealthAnalyzer,
    WasteAnalyzer, TipsAnalyzer, CompareAnalyzer,
]


def get_analyzers(config: Config) -> list[Analyzer]:
    """Return all registered analyzers, including user-defined ones."""
    analyzers: list[Analyzer] = [cls() for cls in _BUILTIN_ANALYZERS]

    # Auto-discover custom analyzers
    custom_dir = config.data_dir / "analyzers"
    if custom_dir.is_dir():
        for py_file in custom_dir.glob("*.py"):
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (isinstance(attr, type)
                            and attr is not Analyzer
                            and hasattr(attr, "name")
                            and hasattr(attr, "description")
                            and hasattr(attr, "analyze")):
                            analyzers.append(attr())
            except Exception as e:
                logger.warning("Failed to load custom analyzer from %s: %s", py_file, e)
                continue

    return analyzers


# ---------------------------------------------------------------------------
# Aggregate loader (reads all sessions, uses cache)
# ---------------------------------------------------------------------------

def load_all_sessions(config: Config, project_filter: str | None = None) -> list[SessionSummary]:
    """Load all session summaries. Uses sessions.jsonl cache where possible."""
    cache_path = config.data_dir / "sessions.jsonl"
    cached: dict[str, SessionSummary] = {}

    # Load cache
    if cache_path.exists():
        for entry in iter_jsonl(cache_path):
            try:
                s = session_summary_from_dict(entry)
                cached[s.session_id] = s
            except (TypeError, KeyError) as e:
                logger.debug("Skipping malformed cache entry: %s", e)
                continue

    sessions: list[SessionSummary] = []
    new_summaries: list[SessionSummary] = []

    for proj_name, jsonl_path in iter_project_sessions(config.claude_dir):
        if project_filter:
            if project_filter.lower() not in display_project(proj_name).lower():
                continue

        session_key = jsonl_path.stem
        if session_key in cached:
            sessions.append(cached[session_key])
            continue

        summary = analyze_session(jsonl_path, proj_name, config)
        sessions.append(summary)
        new_summaries.append(summary)

    # Append new summaries to cache
    if new_summaries:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "a", encoding="utf-8") as f:
            for s in new_summaries:
                f.write(json.dumps(session_summary_to_dict(s)) + "\n")

    return sessions


# ---------------------------------------------------------------------------
# Command entry points (called from scripts/)
# ---------------------------------------------------------------------------

def run_cost(payload: dict, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    result = CostAnalyzer().analyze(sessions, config)
    print(result.render_text())
    return 0


def run_habits(payload: dict, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    result = HabitsAnalyzer().analyze(sessions, config)
    print(result.render_text())
    return 0


def run_health(payload: dict, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    result = HealthAnalyzer().analyze(sessions, config)
    print(result.render_text())
    return 0


def run_tips(payload: dict, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    result = TipsAnalyzer().analyze(sessions, config)
    print(result.render_text())
    return 0


def run_waste(payload: dict, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    result = WasteAnalyzer().analyze(sessions, config)
    print(result.render_text())
    return 0


def run_compare(payload: dict, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    result = CompareAnalyzer().analyze(sessions, config)
    print(result.render_text())
    return 0


def run_report(payload: dict, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    analyzers = [CostAnalyzer(), HabitsAnalyzer(), HealthAnalyzer(), WasteAnalyzer(), TipsAnalyzer(), CompareAnalyzer()]

    now = datetime.now()
    parts: list[str] = [f"# cc-sentinel Report\n\nGenerated: {now.isoformat()}\n"]
    for a in analyzers:
        result = a.analyze(sessions, config)
        parts.append(result.render_markdown())

    report = "\n---\n\n".join(parts)

    reports_dir = config.data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"report-{now.strftime('%Y-%m-%dT%H-%M-%S')}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report saved to {report_path}")
    print()
    print(report)
    return 0


def run_hints(payload: dict, config: Config | None = None) -> int:
    """Show and configure which inline hints are enabled."""
    config = config or load_config()
    config_path = config.data_dir / "config.env"

    lines = [
        "## cc-sentinel Hint Settings",
        "",
        f"  session_start   {'on ' if config.hints.session_start else 'off'}  — last-session summary shown at session start  (HINTS_SESSION_START)",
        f"  pre_tool        {'on ' if config.hints.pre_tool else 'off'}  — inline hints before tool calls                (HINTS_PRE_TOOL)",
        f"  post_tool       {'on ' if config.hints.post_tool else 'off'}  — compaction nudge + subagent warnings          (HINTS_POST_TOOL)",
        "",
        "To change, add to ~/.cc-sentinel/config.env:",
        "  HINTS_SESSION_START=true",
        "  HINTS_PRE_TOOL=true",
        "  HINTS_POST_TOOL=true",
    ]
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# Hook entry points
# ---------------------------------------------------------------------------

def run_stop_hook(payload: dict, config: Config | None = None) -> int:
    """Stop hook: analyze current session and append summary to sessions.jsonl."""
    config = config or load_config()
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd", "")

    if not session_id or not cwd:
        return 0

    # Derive project directory name
    home = str(Path.home())
    proj_dir_name = cwd.replace("/", "-")
    if proj_dir_name.startswith("-"):
        pass  # already in the right format
    projects_dir = config.claude_dir / "projects"

    # Find matching project dir
    jsonl_path: Path | None = None
    for pdir in projects_dir.iterdir():
        if not pdir.is_dir():
            continue
        candidate = pdir / f"{session_id}.jsonl"
        if candidate.exists():
            jsonl_path = candidate
            break

    if not jsonl_path:
        return 0

    summary = analyze_session(jsonl_path, jsonl_path.parent.name, config)

    config.data_dir.mkdir(parents=True, exist_ok=True)
    cache_path = config.data_dir / "sessions.jsonl"
    with open(cache_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(session_summary_to_dict(summary)) + "\n")

    # Update state
    state_path = config.data_dir / "state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError as e:
            logger.warning("Could not parse state.json: %s", e)

    state["last_session_id"] = summary.session_id
    state["last_project"] = summary.project
    state["last_session_cost"] = summary.total_cost
    state["last_session_duration_minutes"] = summary.duration_minutes
    state["last_message_count"] = summary.message_count
    state["last_frustration_count"] = summary.frustration_count
    state["last_subagent_count"] = summary.subagent_count
    state["last_ts"] = datetime.now(timezone.utc).isoformat()
    state_path.write_text(json.dumps(state, indent=2))

    return 0


def run_session_start_hook(payload: dict, config: Config | None = None) -> int:
    """SessionStart hook: inject last-session summary + report highlights + tips."""
    config = config or load_config()
    cwd = payload.get("cwd", "")
    if not cwd:
        return 0

    state_path = config.data_dir / "state.json"
    if not state_path.exists():
        return 0

    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Could not read state for session start hook: %s", e)
        return 0

    # Only show last-session summary if it's from the same project.
    # last_project is stored as the raw project dir name (e.g. "-Users-x-Projects-foo"),
    # cwd is a filesystem path (e.g. "/Users/x/Projects/foo") — normalize both to compare.
    last_project = state.get("last_project", "")
    if last_project:
        cwd_normalized = cwd.replace("/", "-").lstrip("-")
        last_normalized = last_project.lstrip("-")
        if cwd_normalized != last_normalized:
            _init_live_state(config)
            return 0

    lines: list[str] = []

    # Last session summary
    last_cost = state.get("last_session_cost", 0)
    last_dur = state.get("last_session_duration_minutes", 0)
    last_frust = state.get("last_frustration_count", 0)
    last_subagents = state.get("last_subagent_count", 0)
    msg_count = state.get("last_message_count", 0)

    if last_dur > 0:
        parts = [f"Last session: {_fmt_duration(last_dur)}, {_fmt_cost(last_cost)}"]
        if msg_count:
            parts.append(f"{msg_count} msgs")
        if last_frust > 0:
            parts.append(f"{last_frust} frustrations")
        if last_subagents > 0:
            parts.append(f"{last_subagents} subagents")
        lines.append(", ".join(parts) + ".")

    # Actionable tips from last session
    if last_dur > config.thresholds.long_session_minutes:
        lines.append(f"Tip: Start fresh sessions more often — your last ran {_fmt_duration(last_dur)}.")

    if last_cost > 100:
        lines.append(f"Tip: Consider /model sonnet for routine work (last session: {_fmt_cost(last_cost)}).")

    if last_frust > 3:
        lines.append("Tip: When stuck, /clear and restate the problem fresh — iterating grows context and cost.")

    if last_subagents > config.thresholds.max_subagents_per_session:
        lines.append("Tip: Use Grep/Read directly instead of spawning Agent for simple lookups.")

    # Inject top waste from last report (if exists)
    report_dir = config.data_dir / "reports"
    if report_dir.is_dir():
        reports = sorted(report_dir.glob("report-*.md"), reverse=True)
        if reports:
            try:
                report_text = reports[0].read_text(encoding="utf-8")
                # Extract first 2 recommendations from waste section
                in_waste = False
                waste_tips = []
                for line in report_text.splitlines():
                    if "Waste" in line and "#" in line:
                        in_waste = True
                    elif in_waste and line.strip().startswith(("- **[!]**", "- [~]", "- [i]")):
                        waste_tips.append(line.strip().lstrip("- ").lstrip("*[]!~i* "))
                        if len(waste_tips) >= 2:
                            break
                    elif in_waste and line.startswith("#"):
                        break
                if waste_tips:
                    lines.append("Top waste: " + "; ".join(waste_tips))
            except OSError as e:
                logger.debug("Could not read last report for session start hints: %s", e)

    if lines and config.hints.session_start:
        print("[cc-sentinel] " + " ".join(lines))

    # Initialize live session state for PostToolUse tracking
    _init_live_state(config)

    return 0


# ---------------------------------------------------------------------------
# Live session state (for PreToolUse / PostToolUse tracking)
# ---------------------------------------------------------------------------

def _live_state_path(config: Config) -> Path:
    return config.data_dir / "live_session.json"


def _init_live_state(config: Config) -> None:
    """Reset live session tracking on session start."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "message_count": 0,
        "tool_count": 0,
        "cost_estimate": 0.0,
        "prev_tool": "",
        "chain_length": 0,
        "webfetch_github_count": 0,
        "subagent_count": 0,
        "bash_chain_warned": False,
        "compact_nudged": False,
    }
    _live_state_path(config).write_text(json.dumps(state))


def _load_live_state(config: Config) -> dict:
    path = _live_state_path(config)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Could not read live session state: %s", e)
    return {"message_count": 0, "tool_count": 0, "cost_estimate": 0.0,
            "prev_tool": "", "chain_length": 0, "webfetch_github_count": 0,
            "subagent_count": 0, "bash_chain_warned": False, "compact_nudged": False}


def _save_live_state(config: Config, state: dict) -> None:
    try:
        _live_state_path(config).write_text(json.dumps(state))
    except OSError as e:
        logger.debug("Could not write live session state: %s", e)


# ---------------------------------------------------------------------------
# PreToolUse hook — real-time waste interception
# ---------------------------------------------------------------------------

def run_pre_tool_use(payload: dict, config: Config | None = None) -> int:
    """Intercept tool calls BEFORE they execute. Print hints to stderr (non-blocking)."""
    config = config or load_config()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if not isinstance(tool_input, dict):
        tool_input = {}

    hints: list[str] = []

    # WebFetch to GitHub → suggest gh CLI
    if tool_name == "WebFetch":
        url = tool_input.get("url", "")
        if url:
            try:
                domain = urlparse(url).netloc
                if any(wd in domain for wd in config.thresholds.waste_webfetch_domains):
                    hints.append(f"Consider using `gh` CLI instead of WebFetch for {domain} — structured output, fewer tokens.")
            except Exception as e:
                logger.debug("urlparse failed for WebFetch URL in pre_tool_use: %s", e)

    # Agent spawn → check if simple lookup
    if tool_name == "Agent":
        prompt = tool_input.get("prompt", "")
        subagent_type = tool_input.get("subagent_type", "")
        # Simple lookups that could use Grep/Read
        simple_patterns = ["find", "search for", "look for", "where is", "which file", "grep"]
        if any(p in prompt.lower() for p in simple_patterns) and subagent_type in ("Explore", ""):
            hints.append("This looks like a simple search — try Grep or Glob directly to save a subagent spawn.")

    # Bash chain detection
    live = _load_live_state(config)
    if tool_name == "Bash":
        if live.get("prev_tool") == "Bash":
            live["chain_length"] = live.get("chain_length", 0) + 1
            if live["chain_length"] >= 4 and not live.get("bash_chain_warned"):
                hints.append("Multiple consecutive Bash calls — consider combining with && or writing a script.")
                live["bash_chain_warned"] = True
        else:
            live["chain_length"] = 1
            live["bash_chain_warned"] = False
    else:
        if tool_name != live.get("prev_tool"):
            live["chain_length"] = 1
            live["bash_chain_warned"] = False

    live["prev_tool"] = tool_name
    _save_live_state(config, live)

    if hints and config.hints.pre_tool:
        for hint in hints:
            print(f"[cc-sentinel] {hint}")

    return 0


# ---------------------------------------------------------------------------
# PostToolUse hook — live session health tracking + auto-compact nudge
# ---------------------------------------------------------------------------

def run_post_tool_use(payload: dict, config: Config | None = None) -> int:
    """Track session health after each tool call. Nudge compact when needed."""
    config = config or load_config()
    live = _load_live_state(config)

    live["tool_count"] = live.get("tool_count", 0) + 1
    live["message_count"] = live.get("message_count", 0) + 1

    tool_name = payload.get("tool_name", "")

    # Track subagent spawns
    if tool_name == "Agent":
        live["subagent_count"] = live.get("subagent_count", 0) + 1

    # Track WebFetch to GitHub
    if tool_name == "WebFetch":
        tool_input = payload.get("tool_input", {})
        if isinstance(tool_input, dict):
            url = tool_input.get("url", "")
            if "github.com" in url:
                live["webfetch_github_count"] = live.get("webfetch_github_count", 0) + 1

    hints: list[str] = []

    # Auto-compact nudge: at 150+ messages, suggest compacting
    msg = live.get("message_count", 0)
    if msg >= 150 and not live.get("compact_nudged"):
        hints.append(f"Session at {msg}+ tool calls. Context is growing expensive — consider /compact or starting fresh.")
        live["compact_nudged"] = True
    elif msg >= 300 and live.get("compact_nudged") and not live.get("compact_nudged_2"):
        hints.append(f"Session at {msg}+ tool calls. Strongly recommend /compact — each message re-reads the full history.")
        live["compact_nudged_2"] = True

    # Subagent overuse nudge
    subs = live.get("subagent_count", 0)
    if subs == config.thresholds.max_subagents_per_session and not live.get("subagent_warned"):
        hints.append(f"You've spawned {subs} subagents this session. Each loads the full system context. Try Grep/Read for simple lookups.")
        live["subagent_warned"] = True

    _save_live_state(config, live)

    if hints and config.hints.post_tool:
        for hint in hints:
            print(f"[cc-sentinel] {hint}")

    return 0
