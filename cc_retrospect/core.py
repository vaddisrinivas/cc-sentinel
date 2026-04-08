"""cc-retrospect core — Claude Code session analysis. pydantic + pydantic-settings."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Logger ---

logger = logging.getLogger("cc_retrospect")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[cc-retrospect] %(levelname)s %(message)s"))
    logger.addHandler(_h)
logger.setLevel(getattr(logging, os.environ.get("CC_RETROSPECT_LOG_LEVEL", "WARNING").upper(), logging.WARNING))



# --- Config models ---

class PricingConfig(BaseModel):
    input_per_mtok: float = 15.0
    output_per_mtok: float = 75.0
    cache_create_per_mtok: float = 18.75
    cache_read_per_mtok: float = 1.50


class ModelPricing(BaseModel):
    opus: PricingConfig = PricingConfig()
    sonnet: PricingConfig = PricingConfig(input_per_mtok=3.0, output_per_mtok=15.0, cache_create_per_mtok=3.75, cache_read_per_mtok=0.30)
    haiku: PricingConfig = PricingConfig(input_per_mtok=0.80, output_per_mtok=4.0, cache_create_per_mtok=1.0, cache_read_per_mtok=0.08)


class ThresholdsConfig(BaseModel):
    long_session_minutes: int = 120
    long_session_messages: int = 200
    mega_prompt_chars: int = 1000
    mega_prompt_very_long_chars: int = 3000
    mega_prompt_newline_density: float = 0.02
    max_subagents_per_session: int = 10
    max_claudemd_bytes: int = 50_000
    tool_chain_threshold: int = 5
    daily_cost_warning: float = 500.0
    cost_tip_threshold: float = 100.0
    frustration_tip_threshold: int = 3
    compact_nudge_first: int = 150
    compact_nudge_second: int = 300
    learn_refresh_interval: int = 50
    frustration_keywords: list[str] = ["again", "ugh", "still broken", "not working", "wrong", "try again", "that's wrong", "no ", "still not", "wtf", "come on", "seriously", "sigh", "nope"]
    waste_webfetch_domains: list[str] = ["github.com", "api.github.com"]


class HintsConfig(BaseModel):
    session_start: bool = True
    pre_tool: bool = True
    post_tool: bool = True
    user_prompt: bool = True
    daily_health: bool = True
    daily_digest: bool = True
    waste_on_stop: bool = True
    auto_learn: bool = True


class MessagesConfig(BaseModel):
    """All user-facing strings. Override any in config.env via MESSAGES__<KEY>."""
    prefix: str = "[cc-retrospect]"

    # SessionStart tips
    tip_long_session: str = "Tip: Start fresh more often — your last ran {duration}."
    tip_model_sonnet: str = "Tip: Consider /model sonnet (last session: {cost})."
    tip_frustration: str = "Tip: When stuck, /clear and restate — iterating grows context and cost."
    tip_subagent_overuse: str = "Tip: Use Grep/Read instead of spawning Agent for simple lookups."

    # Daily health
    health_long_sessions: str = "Health: {count} long sessions in last 3 days (avg {avg_duration})."
    health_cost_velocity: str = "Health: Averaging {daily_cost}/day. Projected monthly: {monthly_cost}."
    health_no_data: str = "Health: No session data found — Stop hook may not be firing."

    # Daily digest
    digest_summary: str = "Yesterday: {count} sessions, {cost}, {frustrations} frustrations, {subagents} subagents, {compactions} compactions."
    digest_model_tip: str = "Model tip: {cost} spent on Opus for simple tasks — try /model sonnet."

    # Budget
    budget_alert: str = "Budget alert: {cost} spent today (threshold: {threshold})."

    # PreToolUse
    hint_webfetch_github: str = "Consider using `gh` CLI instead of WebFetch for {domain} — structured output, fewer tokens."
    hint_agent_simple: str = "This looks like a simple search — try Grep or Glob directly to save a subagent spawn."
    hint_bash_chain: str = "Multiple consecutive Bash calls — consider combining with && or writing a script."

    # PostToolUse
    hint_compact_first: str = "Session at {count}+ tool calls. Context is growing expensive — consider /compact or starting fresh."
    hint_compact_second: str = "Session at {count}+ tool calls. Strongly recommend /compact — each message re-reads the full history."
    hint_subagent_limit: str = "You've spawned {count} subagents this session. Each loads the full system context. Try Grep/Read for simple lookups."

    # UserPromptSubmit
    hint_mega_paste: str = "Large paste detected ({chars} chars). Consider writing to a temp file and referencing it — saves tokens on every future turn."
    hint_mega_long: str = "Very long prompt ({chars} chars). This inflates conversation history. Consider using a file reference."

    # Stop hook waste flags
    waste_webfetch: str = "{count} WebFetch→GitHub (use gh CLI)"
    waste_tool_chains: str = "{count} repetitive tool chains"
    waste_mega_prompts: str = "{count} oversized prompts"
    waste_dup_reads: str = "{count} duplicate read chains"

    # Onboarding
    welcome_with_data: str = "Welcome! Found {count} sessions ({cost}). Run /cc-retrospect:analyze for a full report."
    welcome_no_data: str = "Welcome! No session data yet. Hooks will start tracking automatically."


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path.home() / ".cc-retrospect" / "config.env"),
        env_prefix="",
        env_nested_delimiter="__",
        env_ignore_empty=True,
        extra="ignore",
    )
    pricing: ModelPricing = ModelPricing()
    thresholds: ThresholdsConfig = ThresholdsConfig()
    hints: HintsConfig = HintsConfig()
    messages: MessagesConfig = MessagesConfig()
    data_dir: Path = Path.home() / ".cc-retrospect"
    claude_dir: Path = Path.home() / ".claude"


def load_config(config_path: Path | None = None) -> Config:
    """Compat shim: load config from optional path or defaults."""
    if config_path and Path(config_path).exists():
        return Config(_env_file=str(config_path))
    return Config(_env_file=None)


def default_config() -> Config:
    return Config(_env_file=None)


# --- JSONL streaming ---

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


# --- Usage extraction ---

class UsageRecord(BaseModel):
    timestamp: str = ""; session_id: str = ""; project: str = ""; model: str = "unknown"
    input_tokens: int = 0; output_tokens: int = 0
    cache_creation_tokens: int = 0; cache_read_tokens: int = 0
    entrypoint: str = ""; cwd: str = ""; git_branch: str = ""


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


def _pricing_for_model(model_str: str, pricing: ModelPricing) -> PricingConfig:
    m = model_str.lower()
    if "sonnet" in m: return pricing.sonnet
    if "haiku" in m: return pricing.haiku
    return pricing.opus


def compute_cost(rec: UsageRecord, pricing: ModelPricing) -> float:
    p = _pricing_for_model(rec.model, pricing)
    return (rec.input_tokens / 1e6 * p.input_per_mtok + rec.output_tokens / 1e6 * p.output_per_mtok
            + rec.cache_creation_tokens / 1e6 * p.cache_create_per_mtok
            + rec.cache_read_tokens / 1e6 * p.cache_read_per_mtok)


# --- Display helpers ---

_PROJECT_PREFIX_RE = re.compile(r"^-Users-[^-]+-(?:Projects-)?")


def display_project(raw_name: str) -> str:
    cleaned = _PROJECT_PREFIX_RE.sub("", raw_name)
    return cleaned if cleaned else raw_name


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)


def _fmt_cost(c: float) -> str:
    if c >= 1000: return f"${c:,.0f}"
    if c >= 1: return f"${c:.2f}"
    return f"${c:.4f}"


def _fmt_duration(minutes: float) -> str:
    if minutes >= 60: return f"{int(minutes//60)}h {int(minutes%60)}m"
    return f"{minutes:.0f}m"


# --- Session model + analysis ---

class SessionSummary(BaseModel):
    session_id: str = ""; project: str = ""; start_ts: str = ""; end_ts: str = ""
    duration_minutes: float = 0.0; message_count: int = 0
    user_message_count: int = 0; assistant_message_count: int = 0
    total_input_tokens: int = 0; total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0; total_cache_read_tokens: int = 0
    total_cost: float = 0.0; model_breakdown: dict[str, float] = {}
    tool_counts: dict[str, int] = {}; tool_chains: list[tuple[str, int]] = []
    subagent_count: int = 0; mega_prompt_count: int = 0
    frustration_count: int = 0; frustration_words: dict[str, int] = {}
    webfetch_domains: dict[str, int] = {}
    entrypoint: str = ""; cwd: str = ""; git_branch: str = ""


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


# --- Result models ---

class Section(BaseModel):
    header: str
    rows: list[tuple[str, str]] = []


class Recommendation(BaseModel):
    severity: str = "info"
    description: str
    estimated_savings: str = ""


class AnalysisResult(BaseModel):
    title: str
    sections: list[Section] = []
    recommendations: list[Recommendation] = []

    def render_markdown(self) -> str:
        lines = [f"## {self.title}", ""]
        for s in self.sections:
            lines += [f"### {s.header}", "", f"| {'Metric':<35} | {'Value':<20} |", f"|{'-'*37}|{'-'*22}|"]
            lines += [f"| {label:<35} | {value:<20} |" for label, value in s.rows]
            lines.append("")
        if self.recommendations:
            lines += ["### Recommendations", ""]
            icons = {"error": "**[!]**", "warning": "[~]", "info": "[i]"}
            for r in self.recommendations:
                sav = f" _(save {r.estimated_savings})_" if r.estimated_savings else ""
                lines.append(f"- {icons.get(r.severity, '[-]')} {r.description}{sav}")
            lines.append("")
        return "\n".join(lines)

    def render_text(self) -> str:
        return self.render_markdown()

    def render_json(self) -> str:
        return self.model_dump_json(indent=2)


# --- Analyzer helpers + built-in analyzers ---

def _group(sessions: list[SessionSummary], key_fn, val_fn=lambda s: s.total_cost) -> dict:
    out: dict = defaultdict(float)
    for s in sessions: out[key_fn(s)] += val_fn(s)
    return out


def _top(d: dict, n: int = 10) -> list:
    return sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]


def _union(sessions: list[SessionSummary], fn) -> Counter:
    c: Counter = Counter()
    for s in sessions: c.update(fn(s))
    return c


class CostAnalyzer:
    name = "cost"
    description = "Cost breakdown by project, model, and time period with what-if scenarios"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Cost Analysis", sections=[Section(header="No data", rows=[("Sessions", "0")])])
        total = sum(s.total_cost for s in sessions)
        proj_costs = _group(sessions, lambda s: display_project(s.project))
        model_costs: Counter = Counter()
        for s in sessions:
            for m, c in s.model_breakdown.items(): model_costs[m] += c
        day_costs = _group(sessions, lambda s: s.start_ts[:10] if s.start_ts else "")
        sections = [
            Section(header="Totals", rows=[
                ("Total cost", _fmt_cost(total)), ("Sessions", str(len(sessions))),
                ("Input tokens (fresh)", _fmt_tokens(sum(s.total_input_tokens for s in sessions))),
                ("Output tokens", _fmt_tokens(sum(s.total_output_tokens for s in sessions))),
                ("Cache creation tokens", _fmt_tokens(sum(s.total_cache_creation_tokens for s in sessions))),
                ("Cache read tokens", _fmt_tokens(sum(s.total_cache_read_tokens for s in sessions))),
            ]),
            Section(header="By Project (top 10)", rows=[(p, _fmt_cost(c)) for p, c in _top(proj_costs, 10)]),
            Section(header="By Model", rows=[(m, _fmt_cost(c)) for m, c in _top(model_costs)]),
        ]
        if day_costs:
            sections.append(Section(header="Daily (last 7)", rows=[(d, _fmt_cost(c)) for d, c in _top(day_costs, 7)]))
        recs = []
        opus_cost = model_costs.get("claude-opus-4-6", 0)
        if opus_cost > 0:
            savings = opus_cost * (1 - 3.0 / 15.0)
            if savings > 10:
                recs.append(Recommendation(severity="warning", description="If all Opus usage switched to Sonnet, estimated savings", estimated_savings=_fmt_cost(savings)))
        return AnalysisResult(title="Cost Analysis", sections=sections, recommendations=recs)


class WasteAnalyzer:
    name = "waste"
    description = "Detect token waste: GitHub fetches via WebFetch, repetitive tool calls, oversized prompts, wrong model choice"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Token Waste")
        recs, rows = [], []
        domain_totals: Counter = Counter()
        domain_sessions: Counter = Counter()
        for s in sessions:
            for domain, count in s.webfetch_domains.items():
                if any(wd in domain for wd in config.thresholds.waste_webfetch_domains):
                    domain_totals[domain] += count; domain_sessions[domain] += 1
        for domain, count in domain_totals.items():
            recs.append(Recommendation(severity="warning", description=f"{count} WebFetch calls to {domain} across {domain_sessions[domain]} sessions. Use `gh` CLI instead.", estimated_savings=f"~{_fmt_tokens(count * 5000)} tokens"))
        rows.append(("WebFetch to GitHub (use gh CLI)", str(sum(domain_totals.values()))))
        all_chains: dict[str, list[int]] = defaultdict(list)
        for s in sessions:
            for tool, length in s.tool_chains:
                if length >= config.thresholds.tool_chain_threshold: all_chains[tool].append(length)
        for tool, lengths in sorted(all_chains.items(), key=lambda x: sum(x[1]), reverse=True):
            recs.append(Recommendation(severity="info", description=f"{len(lengths)} consecutive {tool} chains (longest: {max(lengths)}). Combine calls or use scripts."))
        rows.append(("Repetitive tool chains", str(sum(len(v) for v in all_chains.values()))))
        total_mega = sum(s.mega_prompt_count for s in sessions)
        if total_mega > 5:
            recs.append(Recommendation(severity="warning", description=f"{total_mega} oversized prompts (>{config.thresholds.mega_prompt_chars} chars). Use file references instead of pasting content."))
        rows.append(("Oversized prompts", str(total_mega)))
        complex_tools = {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}
        for s in sessions:
            opus_cost = s.model_breakdown.get("claude-opus-4-6", 0)
            if opus_cost > 50 and not any(t in s.tool_counts for t in complex_tools):
                recs.append(Recommendation(severity="warning", description=f"Session {s.session_id[:8]}... used Opus ({_fmt_cost(opus_cost)}) for simple tasks. Sonnet would be ~5x cheaper.", estimated_savings=_fmt_cost(opus_cost * 0.8)))
                break
        rows.append(("Opus on simple tasks", str(sum(1 for s in sessions if s.model_breakdown.get("claude-opus-4-6", 0) > 50 and not any(t in s.tool_counts for t in complex_tools)))))
        return AnalysisResult(title="Token Waste", sections=[Section(header="Token Waste Overview", rows=rows)], recommendations=recs)


class HabitsAnalyzer:
    name = "habits"
    description = "Usage patterns: time of day, session lengths, prompt style, tool usage"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Usage Habits", sections=[Section(header="No data", rows=[("Sessions", "0")])])
        durations = [s.duration_minutes for s in sessions if s.duration_minutes > 0]
        avg_dur = sum(durations) / len(durations) if durations else 0
        hour_counts: Counter = Counter()
        dow_counts: Counter = Counter()
        for s in sessions:
            if s.start_ts:
                try:
                    dt = datetime.fromisoformat(s.start_ts.replace("Z", "+00:00"))
                    hour_counts[dt.hour] += 1; dow_counts[dt.strftime("%A")] += 1
                except (ValueError, TypeError): pass
        all_tools = _union(sessions, lambda s: s.tool_counts)
        total_frust = sum(s.frustration_count for s in sessions)
        frust_words = _union(sessions, lambda s: s.frustration_words)
        ep_counts: Counter = Counter(s.entrypoint for s in sessions if s.entrypoint)
        sections = [
            Section(header="Session Patterns", rows=[
                ("Average duration", _fmt_duration(avg_dur)),
                ("Average messages/session", f"{sum(s.message_count for s in sessions)/len(sessions):.0f}"),
                ("Longest session", _fmt_duration(max(durations) if durations else 0)),
                ("Total sessions", str(len(sessions))),
            ]),
            Section(header="Peak Hours (UTC)", rows=[(f"{h:02d}:00", f"{c} sessions") for h, c in _top(hour_counts, 3)]),
            Section(header="Peak Days", rows=[(d, f"{c} sessions") for d, c in _top(dow_counts, 3)]),
            Section(header="Tool Usage (top 10)", rows=[(t, str(c)) for t, c in _top(all_tools, 10)]),
        ]
        if total_frust > 0:
            sections.append(Section(header="Frustration Signals", rows=[("Total", str(total_frust))] + [(w, str(c)) for w, c in _top(frust_words, 5)]))
        if ep_counts:
            sections.append(Section(header="Entrypoints", rows=[(e, str(c)) for e, c in ep_counts.most_common()]))
        recs = []
        if avg_dur > config.thresholds.long_session_minutes:
            recs.append(Recommendation(severity="warning", description=f"Average session duration is {_fmt_duration(avg_dur)} — aim for under {config.thresholds.long_session_minutes}m"))
        return AnalysisResult(title="Usage Habits", sections=sections, recommendations=recs)


class HealthAnalyzer:
    name = "health"
    description = "Health checks: session length, subagents, config issues, cost velocity"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Health Check")
        th = config.thresholds
        recs, rows = [], []
        long_sessions = [s for s in sessions if s.duration_minutes > th.long_session_minutes or s.message_count > th.long_session_messages]
        if long_sessions:
            avg_long = sum(s.duration_minutes for s in long_sessions) / len(long_sessions)
            recs.append(Recommendation(severity="warning", description=f"{len(long_sessions)} sessions exceed thresholds. Average: {_fmt_duration(avg_long)}. Use /clear more often."))
        rows.append((f"Long sessions (>{th.long_session_minutes}m)", str(len(long_sessions))))
        heavy_agent = [s for s in sessions if s.subagent_count > th.max_subagents_per_session]
        if heavy_agent:
            recs.append(Recommendation(severity="warning", description=f"{len(heavy_agent)} sessions spawned >{th.max_subagents_per_session} subagents. Use Grep/Read directly."))
        rows.append(("Total subagent spawns", str(sum(s.subagent_count for s in sessions))))
        total_frust = sum(s.frustration_count for s in sessions)
        if total_frust > 5:
            recs.append(Recommendation(severity="info", description=f"{total_frust} frustration signals. Consider rephrasing or starting fresh sessions."))
        rows.append(("Frustration signals", str(total_frust)))
        day_costs = _group(sessions, lambda s: s.start_ts[:10] if s.start_ts else "")
        if day_costs:
            recent = sorted(day_costs.items(), reverse=True)[:3]
            avg_daily = sum(c for _, c in recent) / len(recent)
            if avg_daily > th.daily_cost_warning:
                recs.append(Recommendation(severity="error", description=f"Spending {_fmt_cost(avg_daily)}/day (3-day avg). Projected monthly: {_fmt_cost(avg_daily * 30)}."))
            rows.append(("Avg daily cost (3-day)", _fmt_cost(avg_daily)))
        all_input = sum(s.total_input_tokens + s.total_cache_creation_tokens + s.total_cache_read_tokens for s in sessions)
        cache_read = sum(s.total_cache_read_tokens for s in sessions)
        cache_rate = (cache_read / all_input * 100) if all_input > 0 else 0
        rows.append(("Cache hit rate", f"{cache_rate:.1f}%"))
        if cache_rate < 80 and all_input > 100_000:
            recs.append(Recommendation(severity="info", description=f"Cache hit rate is {cache_rate:.1f}%. Sessions may be too short or context changing too rapidly."))
        return AnalysisResult(title="Health Check", sections=[Section(header="Overview", rows=rows)], recommendations=recs)


class TipsAnalyzer:
    name = "tips"
    description = "Context-aware tips based on recent session patterns"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Tips", recommendations=[Recommendation(severity="info", description="No session data yet.")])
        th = config.thresholds
        latest = max(sessions, key=lambda s: s.end_ts or s.start_ts or "")
        recs = []
        if latest.duration_minutes > th.long_session_minutes:
            recs.append(Recommendation(severity="warning", description=f"Last session ran {_fmt_duration(latest.duration_minutes)} with {latest.message_count} messages. Start fresh to avoid context growth costs."))
        if latest.subagent_count > th.max_subagents_per_session:
            recs.append(Recommendation(severity="info", description=f"Last session spawned {latest.subagent_count} subagents. Try Grep/Read directly for simple lookups."))
        if latest.frustration_count > 3:
            recs.append(Recommendation(severity="info", description=f"Detected {latest.frustration_count} frustration signals. Consider rephrasing with more specificity."))
        gh_calls = sum(c for d, c in latest.webfetch_domains.items() if "github.com" in d)
        if gh_calls > 0:
            recs.append(Recommendation(severity="info", description=f"Last session used WebFetch for GitHub {gh_calls} times. `gh` CLI is faster and cheaper."))
        if latest.total_cost > 100:
            recs.append(Recommendation(severity="warning", description=f"Last session cost {_fmt_cost(latest.total_cost)}. Shorter sessions dramatically reduce costs."))
        if not recs:
            recs.append(Recommendation(severity="info", description="Your recent sessions look healthy. Keep it up!"))
        return AnalysisResult(title="Tips", recommendations=recs[:5])


class CompareAnalyzer:
    name = "compare"
    description = "Compare usage between two time periods"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Compare")
        now = datetime.now(timezone.utc)
        this_week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        last_week_start = this_week_start - timedelta(days=7)
        tw = [s for s in sessions if s.start_ts and s.start_ts >= this_week_start.isoformat()]
        lw = [s for s in sessions if s.start_ts and last_week_start.isoformat() <= s.start_ts < this_week_start.isoformat()]
        def _stats(ss):
            if not ss: return dict(cost=0.0, sessions=0, avg_duration=0.0, frustrations=0, subagents=0)
            return dict(cost=sum(s.total_cost for s in ss), sessions=len(ss),
                        avg_duration=sum(s.duration_minutes for s in ss) / len(ss),
                        frustrations=sum(s.frustration_count for s in ss), subagents=sum(s.subagent_count for s in ss))
        def _delta(cur, prev): return f"{(cur-prev)/prev*100:+.0f}%" if prev else "N/A"
        a, b = _stats(tw), _stats(lw)
        rows = [
            ("Total cost", f"{_fmt_cost(a['cost'])} vs {_fmt_cost(b['cost'])} ({_delta(a['cost'], b['cost'])})"),
            ("Sessions", f"{a['sessions']} vs {b['sessions']} ({_delta(a['sessions'], b['sessions'])})"),
            ("Avg duration", f"{_fmt_duration(a['avg_duration'])} vs {_fmt_duration(b['avg_duration'])}"),
            ("Frustrations", f"{a['frustrations']} vs {b['frustrations']}"),
            ("Subagent spawns", f"{a['subagents']} vs {b['subagents']}"),
        ]
        recs = []
        if a["cost"] > b["cost"] * 1.5 and b["cost"] > 0:
            recs.append(Recommendation(severity="warning", description="Spending increased significantly this week."))
        elif a["cost"] < b["cost"] * 0.7 and b["cost"] > 0:
            recs.append(Recommendation(severity="info", description="Good progress — spending decreased this week."))
        return AnalysisResult(title="This Week vs Last Week", sections=[Section(header="Comparison", rows=rows)], recommendations=recs)


@runtime_checkable
class Analyzer(Protocol):
    name: str
    description: str
    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult: ...


# --- Analyzer registry ---

class SavingsAnalyzer:
    name = "savings"
    description = "Per-habit savings projections based on actual usage data"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Savings Projections")
        th = config.thresholds
        total_cost = sum(s.total_cost for s in sessions)
        # figure out time span for monthly projection
        dates = sorted(s.start_ts[:10] for s in sessions if s.start_ts)
        if len(dates) >= 2:
            try:
                d0 = datetime.fromisoformat(dates[0]); d1 = datetime.fromisoformat(dates[-1])
                span_days = max(1, (d1 - d0).days)
            except (ValueError, TypeError): span_days = 30
        else:
            span_days = 30
        monthly_mult = 30.0 / span_days
        monthly_cost = total_cost * monthly_mult

        rows = [("Current monthly projection", _fmt_cost(monthly_cost)),
                ("Based on", f"{len(sessions)} sessions over {span_days} days")]
        recs = []

        # 1. Model switch savings
        opus_cost = sum(s.model_breakdown.get("claude-opus-4-6", 0) for s in sessions)
        if opus_cost > 0:
            simple_opus = sum(s.model_breakdown.get("claude-opus-4-6", 0)
                             for s in sessions
                             if not any(t in s.tool_counts for t in {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}))
            if simple_opus > 10:
                monthly_save = simple_opus * 0.8 * monthly_mult
                recs.append(Recommendation(severity="warning",
                    description=f"Use /model sonnet for simple tasks ({_fmt_cost(simple_opus)} Opus on Read/Edit/Bash-only sessions)",
                    estimated_savings=f"{_fmt_cost(monthly_save)}/mo"))

        # 2. Shorter sessions savings
        long_sessions = [s for s in sessions if s.duration_minutes > th.long_session_minutes]
        if long_sessions:
            long_cost = sum(s.total_cost for s in long_sessions)
            # estimate: shorter sessions use ~40% less due to reduced cache reads
            monthly_save = long_cost * 0.4 * monthly_mult
            recs.append(Recommendation(severity="warning",
                description=f"Break {len(long_sessions)} long sessions (avg {_fmt_duration(sum(s.duration_minutes for s in long_sessions)/len(long_sessions))}) at ~40 messages",
                estimated_savings=f"{_fmt_cost(monthly_save)}/mo"))

        # 3. Fewer subagents savings
        total_subs = sum(s.subagent_count for s in sessions)
        if total_subs > 20:
            # each subagent costs ~5K cache-read tokens to bootstrap
            sub_token_cost = total_subs * 5000 * config.pricing.opus.cache_read_per_mtok / 1e6
            monthly_save = sub_token_cost * monthly_mult
            recs.append(Recommendation(severity="info",
                description=f"Replace {total_subs} Agent spawns with direct Grep/Read",
                estimated_savings=f"{_fmt_cost(monthly_save)}/mo"))

        # 4. WebFetch→gh savings
        total_wf = sum(sum(c for d, c in s.webfetch_domains.items() if any(wd in d for wd in th.waste_webfetch_domains)) for s in sessions)
        if total_wf > 10:
            wf_token_cost = total_wf * 5000 * config.pricing.opus.input_per_mtok / 1e6
            monthly_save = wf_token_cost * monthly_mult
            recs.append(Recommendation(severity="info",
                description=f"Use `gh` CLI instead of {total_wf} WebFetch calls to GitHub",
                estimated_savings=f"{_fmt_cost(monthly_save)}/mo"))

        # 5. Oversized prompt savings
        total_mega = sum(s.mega_prompt_count for s in sessions)
        if total_mega > 10:
            # oversized prompts add ~2K extra tokens each to history
            mega_token_cost = total_mega * 2000 * config.pricing.opus.cache_read_per_mtok / 1e6
            monthly_save = mega_token_cost * monthly_mult
            recs.append(Recommendation(severity="info",
                description=f"Use file references instead of pasting ({total_mega} oversized prompts)",
                estimated_savings=f"{_fmt_cost(monthly_save)}/mo"))

        total_monthly_savings = 0
        for r in recs:
            try:
                s_str = r.estimated_savings.replace("/mo", "").replace("$", "").replace(",", "")
                total_monthly_savings += float(s_str)
            except (ValueError, AttributeError): pass
        if total_monthly_savings > 0:
            rows.append(("Total potential monthly savings", _fmt_cost(total_monthly_savings)))
            rows.append(("Projected monthly after savings", _fmt_cost(max(0, monthly_cost - total_monthly_savings))))

        return AnalysisResult(title="Savings Projections", sections=[Section(header="Overview", rows=rows)], recommendations=recs)


class ModelAnalyzer:
    name = "model-efficiency"
    description = "Analyze model usage efficiency — which sessions could have used cheaper models"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Model Efficiency")
        complex_tools = {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}
        rows, recs = [], []

        # Score each session: could it have used a cheaper model?
        opus_simple, opus_complex, sonnet_total, haiku_total = 0.0, 0.0, 0.0, 0.0
        mismatch_sessions: list[tuple[str, float, int]] = []  # (project, cost, msg_count)
        for s in sessions:
            opus_cost = s.model_breakdown.get("claude-opus-4-6", 0)
            sonnet_cost = sum(c for m, c in s.model_breakdown.items() if "sonnet" in m.lower())
            haiku_cost = sum(c for m, c in s.model_breakdown.items() if "haiku" in m.lower())
            sonnet_total += sonnet_cost; haiku_total += haiku_cost
            has_complex = any(t in s.tool_counts for t in complex_tools)
            if opus_cost > 1:
                if has_complex:
                    opus_complex += opus_cost
                else:
                    opus_simple += opus_cost
                    mismatch_sessions.append((display_project(s.project), opus_cost, s.message_count))

        total_model_cost = opus_simple + opus_complex + sonnet_total + haiku_total
        rows.append(("Opus on complex tasks", f"{_fmt_cost(opus_complex)} (justified)"))
        rows.append(("Opus on simple tasks", f"{_fmt_cost(opus_simple)} (could be Sonnet)"))
        rows.append(("Sonnet usage", _fmt_cost(sonnet_total)))
        rows.append(("Haiku usage", _fmt_cost(haiku_total)))
        if total_model_cost > 0:
            efficiency = (1 - opus_simple / total_model_cost) * 100
            rows.append(("Model efficiency score", f"{efficiency:.0f}%"))

        # Top mismatched sessions
        mismatch_sessions.sort(key=lambda x: x[1], reverse=True)
        if mismatch_sessions[:5]:
            recs.append(Recommendation(severity="warning",
                description="Top Opus-on-simple: " + ", ".join(f"{p} ({_fmt_cost(c)})" for p, c, _ in mismatch_sessions[:5])))
        if opus_simple > 10:
            recs.append(Recommendation(severity="warning",
                description="Consider: /model sonnet for Read/Edit/Bash work, /model opus for Agent/WebSearch/planning",
                estimated_savings=_fmt_cost(opus_simple * 0.8)))

        return AnalysisResult(title="Model Efficiency", sections=[Section(header="Model Usage", rows=rows)], recommendations=recs)


_BUILTIN_ANALYZERS = [CostAnalyzer, HabitsAnalyzer, HealthAnalyzer, WasteAnalyzer, TipsAnalyzer, CompareAnalyzer, SavingsAnalyzer, ModelAnalyzer]


def get_analyzers(config: Config) -> list:
    analyzers = [cls() for cls in _BUILTIN_ANALYZERS]
    custom_dir = config.data_dir / "analyzers"
    if not custom_dir.is_dir():
        return analyzers
    import importlib.util
    for py_file in custom_dir.glob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for name in dir(mod):
                    attr = getattr(mod, name)
                    if isinstance(attr, type) and all(hasattr(attr, x) for x in ("name", "description", "analyze")):
                        analyzers.append(attr())
        except Exception as e:
            logger.warning("Failed to load custom analyzer from %s: %s", py_file, e)
    return analyzers


# --- Session cache loader ---

def load_all_sessions(config: Config, project_filter: str | None = None) -> list[SessionSummary]:
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

class CompactionEvent(BaseModel):
    timestamp: str = ""
    session_id: str = ""
    reason: str = ""  # "manual" or "window_full"
    tokens_before: int = 0
    tokens_freed: int = 0
    message_count_at_compact: int = 0


class LiveSessionState(BaseModel):
    message_count: int = 0; tool_count: int = 0; cost_estimate: float = 0.0
    prev_tool: str = ""; chain_length: int = 0; webfetch_github_count: int = 0
    subagent_count: int = 0; bash_chain_warned: bool = False
    compact_nudged: bool = False; compact_nudged_2: bool = False; subagent_warned: bool = False
    compaction_count: int = 0; mega_prompt_count: int = 0

    def __getitem__(self, key: str):
        return getattr(self, key)

    def __setitem__(self, key: str, val) -> None:
        setattr(self, key, val)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


def _live_state_path(config: Config) -> Path:
    return config.data_dir / "live_session.json"


def _init_live_state(config: Config) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    _live_state_path(config).write_text(LiveSessionState().model_dump_json())


def _load_live_state(config: Config) -> LiveSessionState:
    path = _live_state_path(config)
    if path.exists():
        try: return LiveSessionState.model_validate_json(path.read_text())
        except Exception: pass
    return LiveSessionState()


def _save_live_state(config: Config, state) -> None:
    if isinstance(state, dict): state = LiveSessionState(**{k: v for k, v in state.items() if k in LiveSessionState.model_fields})
    try: _live_state_path(config).write_text(state.model_dump_json())
    except OSError as e: logger.debug("Could not write live state: %s", e)


# --- Command entry points ---

def _filter_sessions(sessions: list[SessionSummary], project: str | None = None, days: int | None = None) -> list[SessionSummary]:
    """Filter sessions by project name and/or recent N days."""
    if project:
        sessions = [s for s in sessions if project.lower() in display_project(s.project).lower()]
    if days and days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        sessions = [s for s in sessions if s.start_ts and s.start_ts >= cutoff]
    return sessions


def _render(analyzer_cls, payload: dict = {}, *, config: Config | None = None, sessions=None) -> int:
    cfg = config or load_config()
    ss = sessions if sessions is not None else load_all_sessions(cfg)
    ss = _filter_sessions(ss, project=payload.get("project"), days=payload.get("days"))
    result = analyzer_cls().analyze(ss, cfg)
    if payload.get("json"):
        print(result.render_json())
    else:
        print(result.render_markdown())
    return 0


def run_cost(payload: dict = {}, *, config: Config | None = None) -> int:       return _render(CostAnalyzer, payload, config=config)
def run_habits(payload: dict = {}, *, config: Config | None = None) -> int:     return _render(HabitsAnalyzer, payload, config=config)
def run_health(payload: dict = {}, *, config: Config | None = None) -> int:     return _render(HealthAnalyzer, payload, config=config)
def run_tips(payload: dict = {}, *, config: Config | None = None) -> int:       return _render(TipsAnalyzer, payload, config=config)
def run_waste(payload: dict = {}, *, config: Config | None = None) -> int:      return _render(WasteAnalyzer, payload, config=config)
def run_compare(payload: dict = {}, *, config: Config | None = None) -> int:    return _render(CompareAnalyzer, payload, config=config)


def run_report(payload: dict = {}, *, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    sessions = _filter_sessions(sessions, project=payload.get("project"), days=payload.get("days"))
    now = datetime.now()
    parts = [f"# cc-retrospect Report\n\nGenerated: {now.isoformat()}\n"]
    for a in get_analyzers(config):
        parts.append(a.analyze(sessions, config).render_markdown())
    report = "\n---\n\n".join(parts)
    reports_dir = config.data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"report-{now.strftime('%Y-%m-%dT%H-%M-%S')}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report saved to {report_path}")
    print(report)
    return 0


def run_savings(payload: dict = {}, *, config: Config | None = None) -> int:   return _render(SavingsAnalyzer, payload, config=config)
def run_model_efficiency(payload: dict = {}, *, config: Config | None = None) -> int: return _render(ModelAnalyzer, payload, config=config)


def run_digest(payload: dict = {}, *, config: Config | None = None) -> int:
    """Daily digest: yesterday's sessions analyzed with savings + model efficiency."""
    config = config or load_config()
    sessions = load_all_sessions(config)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_sessions = [s for s in sessions if s.start_ts and yesterday <= s.start_ts[:10] <= today]
    if not day_sessions:
        print(f"{config.messages.prefix} No sessions found for {yesterday}.")
        return 0
    parts = [f"## {config.messages.prefix} Daily Digest ({yesterday})", ""]
    day_cost = sum(s.total_cost for s in day_sessions)
    day_msgs = sum(s.message_count for s in day_sessions)
    day_frust = sum(s.frustration_count for s in day_sessions)
    day_subs = sum(s.subagent_count for s in day_sessions)
    compactions = _load_compactions(config, since=yesterday)
    parts.append(f"**{len(day_sessions)} sessions** | {_fmt_cost(day_cost)} | {day_msgs} msgs | {day_frust} frustrations | {day_subs} subagents | {len(compactions)} compactions")
    parts.append("")
    # Model efficiency for the day
    model_result = ModelAnalyzer().analyze(day_sessions, config)
    parts.append(model_result.render_markdown())
    # Savings for the day
    savings_result = SavingsAnalyzer().analyze(day_sessions, config)
    parts.append(savings_result.render_markdown())
    # Top 3 most expensive sessions
    expensive = sorted(day_sessions, key=lambda s: s.total_cost, reverse=True)[:3]
    if expensive:
        parts.append("### Most Expensive Sessions")
        parts.append("")
        for s in expensive:
            models = ", ".join(f"{m}: {_fmt_cost(c)}" for m, c in sorted(s.model_breakdown.items(), key=lambda x: x[1], reverse=True))
            parts.append(f"- **{display_project(s.project)}**: {_fmt_cost(s.total_cost)}, {_fmt_duration(s.duration_minutes)}, {s.message_count} msgs ({models})")
        parts.append("")
    # Compaction summary
    if compactions:
        total_freed = sum(c.get("tokens_freed", 0) for c in compactions)
        parts.append(f"### Compactions: {len(compactions)} events, {_fmt_tokens(total_freed)} tokens freed")
        parts.append("")
    print("\n".join(parts))
    return 0


def run_hints(payload: dict = {}, *, config: Config | None = None) -> int:
    config = config or load_config()
    lines = [
        "## cc-retrospect Hint Settings", "",
        f"  session_start   {'on ' if config.hints.session_start else 'off'}  — summary at session start  (HINTS__SESSION_START)",
        f"  pre_tool        {'on ' if config.hints.pre_tool else 'off'}  — hints before tool calls     (HINTS__PRE_TOOL)",
        f"  post_tool       {'on ' if config.hints.post_tool else 'off'}  — compaction + subagent nudge (HINTS__POST_TOOL)",
        "", "To change, add to ~/.cc-retrospect/config.env:",
        "  HINTS__SESSION_START=true",
        "  HINTS__PRE_TOOL=true",
        "  HINTS__POST_TOOL=true",
    ]
    print("\n".join(lines))
    return 0


# --- Status, export, trends ---

def run_status(payload: dict = {}, *, config: Config | None = None) -> int:
    """Plugin health check — verify install, hooks, data, deps."""
    config = config or load_config()
    lines = ["## cc-retrospect Status", ""]
    # Data dir
    data_exists = config.data_dir.exists()
    lines.append(f"Data directory: {config.data_dir} ({'exists' if data_exists else 'MISSING'})")
    # Session count
    cache_path = config.data_dir / "sessions.jsonl"
    session_count = sum(1 for _ in iter_jsonl(cache_path)) if cache_path.exists() else 0
    lines.append(f"Cached sessions: {session_count}")
    # Config file
    config_path = config.data_dir / "config.env"
    lines.append(f"Config file: {config_path} ({'found' if config_path.exists() else 'not found (using defaults)'})")
    # Compactions
    comp_path = config.data_dir / "compactions.jsonl"
    comp_count = sum(1 for _ in iter_jsonl(comp_path)) if comp_path.exists() else 0
    lines.append(f"Compaction events logged: {comp_count}")
    # Trends
    trends_path = config.data_dir / "trends.jsonl"
    trend_count = sum(1 for _ in iter_jsonl(trends_path)) if trends_path.exists() else 0
    lines.append(f"Weekly trend snapshots: {trend_count}")
    # Last session
    state_path = config.data_dir / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            lines.append(f"Last session: {state.get('last_ts', 'unknown')[:16]} ({display_project(state.get('last_project', '?'))})")
        except (json.JSONDecodeError, OSError): pass
    # Deps
    try:
        import pydantic; lines.append(f"pydantic: {pydantic.__version__}")
    except ImportError: lines.append("pydantic: NOT INSTALLED")
    try:
        import pydantic_settings; lines.append(f"pydantic-settings: {pydantic_settings.__version__}")
    except ImportError: lines.append("pydantic-settings: NOT INSTALLED")
    lines.append("")
    print("\n".join(lines))
    return 0


def run_export(payload: dict = {}, *, config: Config | None = None) -> int:
    """Export all session data as JSON to stdout."""
    config = config or load_config()
    sessions = load_all_sessions(config)
    print(json.dumps([s.model_dump() for s in sessions], default=str))
    return 0


class TrendAnalyzer:
    name = "trends"
    description = "Weekly trend tracking — are you improving over time?"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        trends_path = config.data_dir / "trends.jsonl"
        weeks: list[dict] = list(iter_jsonl(trends_path)) if trends_path.exists() else []
        if not weeks:
            return AnalysisResult(title="Trends", recommendations=[
                Recommendation(severity="info", description="No trend data yet. Trends are recorded weekly via the stop hook.")])
        rows = []
        prev: dict | None = None
        for w in sorted(weeks, key=lambda x: x.get("week", ""))[-8:]:
            wk = w.get("week", "?")
            cost = w.get("cost", 0)
            sess = w.get("sessions", 0)
            eff = w.get("model_efficiency", 0)
            delta = ""
            if prev:
                pc = prev.get("cost", 0)
                if pc > 0: delta = f" ({'↓' if cost < pc else '↑'}{abs(cost - pc) / pc * 100:.0f}%)"
            rows.append((wk, f"{_fmt_cost(cost)}, {sess} sessions, {eff}% efficiency{delta}"))
            prev = w
        recs = []
        if len(weeks) >= 2:
            latest, prior = weeks[-1], weeks[-2]
            if latest.get("cost", 0) < prior.get("cost", 0) * 0.8:
                recs.append(Recommendation(severity="info", description="Spending trending down — good progress."))
            elif latest.get("cost", 0) > prior.get("cost", 0) * 1.3:
                recs.append(Recommendation(severity="warning", description="Spending trending up. Check /savings for actionable cuts."))
        return AnalysisResult(title="Weekly Trends", sections=[Section(header="Last 8 Weeks", rows=rows)], recommendations=recs)


def run_trends(payload: dict = {}, *, config: Config | None = None) -> int:
    if payload.get("backfill"):
        config = config or load_config()
        _backfill_trends(config)
        return 0
    return _render(TrendAnalyzer, payload, config=config)


def run_reset(payload: dict = {}, *, config: Config | None = None) -> int:
    """Clear all cached data files. Sessions are re-scanned on next command."""
    config = config or load_config()
    cleared = []
    for name in ("sessions.jsonl", "state.json", "live_session.json", "compactions.jsonl", "trends.jsonl"):
        path = config.data_dir / name
        if path.exists():
            path.unlink()
            cleared.append(name)
    if cleared:
        print(f"[cc-retrospect] Cleared: {', '.join(cleared)}")
    else:
        print("[cc-retrospect] Nothing to clear.")
    return 0


def run_config(payload: dict = {}, *, config: Config | None = None) -> int:
    """Show current config values (defaults + overrides from config.env)."""
    config = config or load_config()
    lines = ["## cc-retrospect Configuration", ""]
    config_path = config.data_dir / "config.env"
    lines.append(f"Config file: {config_path} ({'found' if config_path.exists() else 'not found — using defaults'})")
    lines.append("")
    lines.append("### Pricing ($/MTok)")
    for model_name in ("opus", "sonnet", "haiku"):
        p = getattr(config.pricing, model_name)
        lines.append(f"  {model_name}: input={p.input_per_mtok} output={p.output_per_mtok} cache_create={p.cache_create_per_mtok} cache_read={p.cache_read_per_mtok}")
    lines.append("")
    lines.append("### Thresholds")
    for field, val in config.thresholds.model_dump().items():
        if field not in ("frustration_keywords", "waste_webfetch_domains"):
            lines.append(f"  {field}: {val}")
    lines.append(f"  waste_webfetch_domains: {', '.join(config.thresholds.waste_webfetch_domains)}")
    lines.append("")
    lines.append("### Hints (which hooks produce output)")
    for field, val in config.hints.model_dump().items():
        lines.append(f"  {field}: {'on' if val else 'off'}")
    lines.append("")
    lines.append("### Data")
    lines.append(f"  data_dir: {config.data_dir}")
    lines.append(f"  claude_dir: {config.claude_dir}")
    lines.append("")
    if payload.get("json"):
        print(config.model_dump_json(indent=2))
    else:
        print("\n".join(lines))
    return 0


def _update_trends(config: Config) -> None:
    """Append a weekly snapshot if the current week hasn't been recorded yet."""
    now = datetime.now(timezone.utc)
    current_week = now.strftime("%G-W%V")
    trends_path = config.data_dir / "trends.jsonl"
    existing_weeks = set()
    if trends_path.exists():
        for entry in iter_jsonl(trends_path):
            existing_weeks.add(entry.get("week", ""))
    if current_week in existing_weeks:
        return
    # Build snapshot from this week's sessions
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = load_all_sessions(config)
    week_sessions = [s for s in sessions if s.start_ts and s.start_ts >= week_start.isoformat()]
    if not week_sessions:
        return
    total_cost = sum(s.total_cost for s in week_sessions)
    complex_tools = {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}
    opus_simple = sum(s.model_breakdown.get("claude-opus-4-6", 0) for s in week_sessions
                      if not any(t in s.tool_counts for t in complex_tools))
    all_model_cost = sum(s.total_cost for s in week_sessions)
    efficiency = int((1 - opus_simple / all_model_cost) * 100) if all_model_cost > 0 else 100
    compactions = _load_compactions(config, since=week_start.isoformat()[:10])
    snapshot = {
        "week": current_week,
        "cost": round(total_cost, 2),
        "sessions": len(week_sessions),
        "avg_duration": round(sum(s.duration_minutes for s in week_sessions) / len(week_sessions), 1),
        "frustrations": sum(s.frustration_count for s in week_sessions),
        "subagents": sum(s.subagent_count for s in week_sessions),
        "model_efficiency": efficiency,
        "compactions": len(compactions),
    }
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(trends_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot) + "\n")


def _backfill_trends(config: Config) -> None:
    """Backfill weekly trends from historical session data."""
    sessions = load_all_sessions(config)
    if not sessions:
        print("[cc-retrospect] No sessions to backfill from.")
        return
    trends_path = config.data_dir / "trends.jsonl"
    existing_weeks = set()
    if trends_path.exists():
        for entry in iter_jsonl(trends_path):
            existing_weeks.add(entry.get("week", ""))
    # Group sessions by ISO week
    weeks: dict[str, list[SessionSummary]] = defaultdict(list)
    for s in sessions:
        if s.start_ts:
            try:
                dt = datetime.fromisoformat(s.start_ts.replace("Z", "+00:00"))
                weeks[dt.strftime("%G-W%V")].append(s)
            except (ValueError, TypeError): pass
    complex_tools = {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}
    added = 0
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(trends_path, "a", encoding="utf-8") as f:
        for wk in sorted(weeks.keys()):
            if wk in existing_weeks:
                continue
            ws = weeks[wk]
            total_cost = sum(s.total_cost for s in ws)
            opus_simple = sum(s.model_breakdown.get("claude-opus-4-6", 0) for s in ws
                              if not any(t in s.tool_counts for t in complex_tools))
            all_model_cost = sum(s.total_cost for s in ws)
            efficiency = int((1 - opus_simple / all_model_cost) * 100) if all_model_cost > 0 else 100
            snapshot = {
                "week": wk, "cost": round(total_cost, 2), "sessions": len(ws),
                "avg_duration": round(sum(s.duration_minutes for s in ws) / len(ws), 1),
                "frustrations": sum(s.frustration_count for s in ws),
                "subagents": sum(s.subagent_count for s in ws),
                "model_efficiency": efficiency, "compactions": 0,
            }
            f.write(json.dumps(snapshot) + "\n")
            added += 1
    print(f"[cc-retrospect] Backfilled {added} weeks of trend data.")


# --- Hook entry points ---

def run_stop_hook(payload: dict, *, config: Config | None = None) -> int:
    config = config or load_config()
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd", "")
    if not session_id or not cwd: return 0
    projects_dir = config.claude_dir / "projects"
    jsonl_path = next(
        (pdir / f"{session_id}.jsonl" for pdir in projects_dir.iterdir()
         if pdir.is_dir() and (pdir / f"{session_id}.jsonl").exists()), None
    )
    if not jsonl_path: return 0
    summary = analyze_session(jsonl_path, jsonl_path.parent.name, config)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(config.data_dir / "sessions.jsonl", "a", encoding="utf-8") as f:
        f.write(summary.model_dump_json() + "\n")
    state_path = config.data_dir / "state.json"
    state = {}
    if state_path.exists():
        try: state = json.loads(state_path.read_text())
        except json.JSONDecodeError: pass
    state.update({
        "last_session_id": summary.session_id, "last_project": summary.project,
        "last_session_cost": summary.total_cost, "last_session_duration_minutes": summary.duration_minutes,
        "last_message_count": summary.message_count, "last_frustration_count": summary.frustration_count,
        "last_subagent_count": summary.subagent_count, "last_ts": datetime.now(timezone.utc).isoformat(),
    })
    # Budget tracking: accumulate today's cost
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("today_date") == today:
        state["today_cost"] = state.get("today_cost", 0) + summary.total_cost
    else:
        state["today_date"] = today
        state["today_cost"] = summary.total_cost
    state_path.write_text(json.dumps(state, indent=2))
    # Waste flags on session end (configurable)
    waste_flags = []
    gh_calls = sum(c for d, c in summary.webfetch_domains.items() if "github.com" in d)
    m = config.messages
    if gh_calls > 0:
        waste_flags.append(m.waste_webfetch.format(count=gh_calls))
    long_chains = [(t, l) for t, l in summary.tool_chains if l >= config.thresholds.tool_chain_threshold]
    if long_chains:
        waste_flags.append(m.waste_tool_chains.format(count=len(long_chains)))
    if summary.mega_prompt_count > 3:
        waste_flags.append(m.waste_mega_prompts.format(count=summary.mega_prompt_count))
    read_chains = sum(1 for t, l in summary.tool_chains if t == "Read" and l >= 2)
    if read_chains > 3:
        waste_flags.append(m.waste_dup_reads.format(count=read_chains))
    if config.hints.waste_on_stop and waste_flags:
        state["last_waste_flags"] = waste_flags
        logger.info("Session waste: %s", ", ".join(waste_flags))

    # Auto-refresh LEARNINGS.md periodically
    session_count = state.get("session_count_since_learn", 0) + 1
    state["session_count_since_learn"] = session_count
    if config.hints.auto_learn and session_count >= config.thresholds.learn_refresh_interval:
        try:
            profile = analyze_user_messages(config)
            style_path = config.data_dir / "STYLE.md"
            learnings_path = config.data_dir / "LEARNINGS.md"
            style_path.write_text(generate_style(profile), encoding="utf-8")
            learnings_path.write_text(generate_learnings(profile), encoding="utf-8")
            state["session_count_since_learn"] = 0
            state["last_learn_refresh"] = datetime.now(timezone.utc).isoformat()
            logger.info("Auto-refreshed STYLE.md and LEARNINGS.md after %d sessions", session_count)
        except Exception as e:
            logger.debug("Auto-refresh learn failed: %s", e)

    # Budget alert
    if state["today_cost"] > config.thresholds.daily_cost_warning:
        print(f"{config.messages.prefix} {config.messages.budget_alert.format(cost=_fmt_cost(state['today_cost']), threshold=_fmt_cost(config.thresholds.daily_cost_warning))}", file=sys.stderr)
    # Update weekly trends
    try: _update_trends(config)
    except Exception as e: logger.debug("Trend update failed: %s", e)
    return 0


def run_session_start_hook(payload: dict, *, config: Config | None = None) -> int:
    config = config or load_config()
    cwd = payload.get("cwd", "")
    if not cwd: return 0
    state_path = config.data_dir / "state.json"
    # First-run onboarding
    if not state_path.exists():
        try:
            sessions = load_all_sessions(config)
            m = config.messages
            if sessions:
                total_cost = sum(s.total_cost for s in sessions)
                print(f"{m.prefix} {m.welcome_with_data.format(count=len(sessions), cost=_fmt_cost(total_cost))}")
            else:
                print(f"{m.prefix} {m.welcome_no_data}")
            config.data_dir.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"first_run": datetime.now(timezone.utc).isoformat()}))
        except Exception as e:
            logger.debug("First-run onboarding failed: %s", e)
        _init_live_state(config)
        return 0
    if not state_path.exists(): return 0
    try: state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError): return 0
    last_project = state.get("last_project", "")
    if last_project:
        if cwd.replace("/", "-").lstrip("-") != last_project.lstrip("-"):
            _init_live_state(config); return 0
    last_dur = state.get("last_session_duration_minutes", 0)
    last_cost = state.get("last_session_cost", 0)
    last_frust = state.get("last_frustration_count", 0)
    last_subs = state.get("last_subagent_count", 0)
    msg_count = state.get("last_message_count", 0)
    lines = []
    if last_dur > 0:
        parts = [f"Last session: {_fmt_duration(last_dur)}, {_fmt_cost(last_cost)}"]
        if msg_count: parts.append(f"{msg_count} msgs")
        if last_frust: parts.append(f"{last_frust} frustrations")
        if last_subs: parts.append(f"{last_subs} subagents")
        lines.append(", ".join(parts) + ".")
    th = config.thresholds
    m = config.messages
    if last_dur > th.long_session_minutes: lines.append(m.tip_long_session.format(duration=_fmt_duration(last_dur)))
    if last_cost > th.cost_tip_threshold: lines.append(m.tip_model_sonnet.format(cost=_fmt_cost(last_cost)))
    if last_frust > th.frustration_tip_threshold: lines.append(m.tip_frustration)
    if last_subs > th.max_subagents_per_session: lines.append(m.tip_subagent_overuse)
    report_dir = config.data_dir / "reports"
    if report_dir.is_dir():
        reports = sorted(report_dir.glob("report-*.md"), reverse=True)
        if reports:
            try:
                waste_tips, in_waste = [], False
                for line in reports[0].read_text().splitlines():
                    if "Waste" in line and line.startswith("#"): in_waste = True
                    elif in_waste and line.startswith("#"): break
                    elif in_waste and line.strip().startswith(("- **[!]**", "- [~]", "- [i]")):
                        waste_tips.append(line.strip().lstrip("- ").lstrip("*[]!~i* "))
                        if len(waste_tips) >= 2: break
                if waste_tips: lines.append("Top waste: " + "; ".join(waste_tips))
            except OSError: pass
    # Daily health check (once per day, configurable)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if config.hints.daily_health and state.get("last_health_date") != today:
        try:
            sessions = load_all_sessions(config)
            recent = [s for s in sessions if s.start_ts and s.start_ts[:10] >= (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")]
            if recent:
                # Long sessions
                long = [s for s in recent if s.duration_minutes > th.long_session_minutes]
                if long:
                    lines.append(m.health_long_sessions.format(count=len(long), avg_duration=_fmt_duration(sum(s.duration_minutes for s in long)/len(long))))
                # High cost velocity
                day_costs = defaultdict(float)
                for s in recent:
                    if s.start_ts: day_costs[s.start_ts[:10]] += s.total_cost
                if day_costs:
                    avg_daily = sum(day_costs.values()) / len(day_costs)
                    if avg_daily > th.daily_cost_warning:
                        lines.append(m.health_cost_velocity.format(daily_cost=_fmt_cost(avg_daily), monthly_cost=_fmt_cost(avg_daily * 30)))
            # Plugin status check
            hooks_ok = (config.data_dir / "sessions.jsonl").exists()
            if not hooks_ok:
                lines.append(m.health_no_data)
            state["last_health_date"] = today
            state_path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug("Daily health check failed: %s", e)

    # Daily digest: first session of a new day gets yesterday's summary
    if config.hints.daily_digest and _should_show_daily_digest(config):
        try:
            sessions = load_all_sessions(config)
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            day_sessions = [s for s in sessions if s.start_ts and s.start_ts[:10] == yesterday]
            if day_sessions:
                day_cost = sum(s.total_cost for s in day_sessions)
                day_frust = sum(s.frustration_count for s in day_sessions)
                day_subs = sum(s.subagent_count for s in day_sessions)
                compactions = _load_compactions(config, since=yesterday)
                lines.append(m.digest_summary.format(count=len(day_sessions), cost=_fmt_cost(day_cost), frustrations=day_frust, subagents=day_subs, compactions=len(compactions)))
                # Quick model efficiency note
                opus_simple = sum(s.model_breakdown.get("claude-opus-4-6", 0) for s in day_sessions
                                  if not any(t in s.tool_counts for t in {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}))
                if opus_simple > 10:
                    lines.append(m.digest_model_tip.format(cost=_fmt_cost(opus_simple)))
        except Exception as e:
            logger.debug("Daily digest failed: %s", e)
    if lines and config.hints.session_start:
        print(f"{m.prefix} " + " ".join(lines))
    _init_live_state(config)
    return 0


def run_pre_tool_use(payload: dict, *, config: Config | None = None) -> int:
    config = config or load_config()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict): tool_input = {}
    hints = []
    if tool_name == "WebFetch":
        url = tool_input.get("url", "")
        if url:
            try:
                domain = urlparse(url).netloc
                if any(wd in domain for wd in config.thresholds.waste_webfetch_domains):
                    hints.append(config.messages.hint_webfetch_github.format(domain=domain))
            except Exception as e:
                logger.debug("urlparse failed for WebFetch URL in pre_tool_use: %s", e)
    if tool_name == "Agent":
        prompt = tool_input.get("prompt", "")
        if any(p in prompt.lower() for p in ["find", "search for", "look for", "where is", "which file", "grep"]) and tool_input.get("subagent_type", "") in ("Explore", ""):
            hints.append(config.messages.hint_agent_simple)
    live = _load_live_state(config)
    if tool_name == "Bash":
        if live.prev_tool == "Bash":
            live.chain_length += 1
            if live.chain_length >= 4 and not live.bash_chain_warned:
                hints.append(config.messages.hint_bash_chain)
                live.bash_chain_warned = True
        else:
            live.chain_length = 1; live.bash_chain_warned = False
    elif tool_name != live.prev_tool:
        live.chain_length = 1; live.bash_chain_warned = False
    live.prev_tool = tool_name
    _save_live_state(config, live)
    if hints and config.hints.pre_tool:
        for hint in hints: print(f"{config.messages.prefix} {hint}")
    return 0


def run_post_tool_use(payload: dict, *, config: Config | None = None) -> int:
    config = config or load_config()
    live = _load_live_state(config)
    live.tool_count += 1; live.message_count += 1
    tool_name = payload.get("tool_name", "")
    if tool_name == "Agent": live.subagent_count += 1
    if tool_name == "WebFetch":
        url = (payload.get("tool_input") or {}).get("url", "") if isinstance(payload.get("tool_input"), dict) else ""
        if "github.com" in url: live.webfetch_github_count += 1
    hints = []
    msg = live.message_count
    th = config.thresholds
    if msg >= th.compact_nudge_first and not live.compact_nudged:
        hints.append(config.messages.hint_compact_first.format(count=msg))
        live.compact_nudged = True
    elif msg >= th.compact_nudge_second and live.compact_nudged and not live.compact_nudged_2:
        hints.append(config.messages.hint_compact_second.format(count=msg))
        live.compact_nudged_2 = True
    if live.subagent_count == config.thresholds.max_subagents_per_session and not live.subagent_warned:
        hints.append(config.messages.hint_subagent_limit.format(count=live.subagent_count))
        live.subagent_warned = True
    _save_live_state(config, live)
    if hints and config.hints.post_tool:
        for hint in hints: print(f"{config.messages.prefix} {hint}")
    return 0


# --- UserPromptSubmit hook — oversized prompt interception ---

def run_user_prompt(payload: dict, *, config: Config | None = None) -> int:
    """Intercept user prompts before submission. Warn on oversized prompts."""
    config = config or load_config()
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        return 0

    hints = []
    plen = len(prompt)

    # Oversized prompt detection
    if plen > config.thresholds.mega_prompt_chars:
        newline_density = prompt.count("\n") / max(plen, 1)
        # High newline density = likely a paste (logs, stack traces, code)
        if newline_density > config.thresholds.mega_prompt_newline_density:
            hints.append(config.messages.hint_mega_paste.format(chars=plen))
        elif plen > config.thresholds.mega_prompt_very_long_chars:
            hints.append(config.messages.hint_mega_long.format(chars=plen))

    # Track in live state
    live = _load_live_state(config)
    live.message_count += 1
    if plen > config.thresholds.mega_prompt_chars:
        live.mega_prompt_count = getattr(live, "mega_prompt_count", 0) + 1
    _save_live_state(config, live)

    if hints and config.hints.user_prompt:
        for hint in hints:
            print(f"{config.messages.prefix} {hint}")

    return 0


# --- Compaction hooks ---

def _compactions_path(config: Config) -> Path:
    return config.data_dir / "compactions.jsonl"


def _load_compactions(config: Config, since: str = "") -> list[dict]:
    path = _compactions_path(config)
    events = []
    for entry in iter_jsonl(path):
        if since and entry.get("timestamp", "") < since:
            continue
        events.append(entry)
    return events


def run_pre_compact(payload: dict, *, config: Config | None = None) -> int:
    """Log compaction start — fires when context window fills or user runs /compact."""
    config = config or load_config()
    live = _load_live_state(config)
    live.compaction_count += 1
    _save_live_state(config, live)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": payload.get("session_id", ""),
        "phase": "pre",
        "reason": payload.get("compact_reason", "unknown"),
        "message_count_at_compact": live.message_count,
    }
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(_compactions_path(config), "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return 0


def run_post_compact(payload: dict, *, config: Config | None = None) -> int:
    """Log compaction result — tokens freed, summary produced."""
    config = config or load_config()
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": payload.get("session_id", ""),
        "phase": "post",
        "reason": payload.get("compact_reason", "unknown"),
        "tokens_freed": payload.get("tokens_freed", 0),
    }
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with open(_compactions_path(config), "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return 0


# ---------------------------------------------------------------------------
# /learn — behavioral profile + transferable learnings
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    total_messages: int = 0
    median_length: int = 0
    avg_length: float = 0
    single_word_pct: float = 0
    mega_prompt_pct: float = 0
    top_openers: list[tuple[str, int]] = []
    approval_signals: dict[str, int] = {}
    correction_count: int = 0
    frustration_rate: float = 0
    frustration_words: dict[str, int] = {}
    gratitude_rate: float = 0
    rapid_fire_pct: float = 0
    consecutive_user_msgs: int = 0
    read_edit_read_count: int = 0
    peak_hours: list[int] = []
    projects_per_day_avg: float = 0
    avg_session_duration: float = 0
    avg_session_messages: float = 0
    top_cost_driver: str = ""
    cache_hit_rate: float = 0
    total_sessions: int = 0
    model_breakdown: dict[str, float] = {}
    tool_after_frustration: dict[str, int] = {}


def analyze_user_messages(config: Config) -> UserProfile:
    """Scan all JSONL files and build a behavioral profile."""
    from urllib.parse import urlparse as _urlparse

    lengths = []
    openers = Counter()
    approvals = Counter()
    corrections = 0
    frustrations = 0
    frust_words = Counter()
    gratitude = 0
    rapid_fire = 0
    consec_user = 0
    total_user = 0
    total_gaps = 0
    mega = 0

    # Efficiency tracking
    read_edit_read = 0
    tool_after_frust = Counter()

    # Work patterns
    hour_counts = Counter()
    daily_projects = defaultdict(set)

    # Session-level
    session_durations = []
    session_msg_counts = []

    # Cost
    total_input = 0
    total_output = 0
    total_cache_create = 0
    total_cache_read = 0
    model_costs = Counter()

    mega_threshold = config.thresholds.mega_prompt_chars
    frust_keywords = [k.lower() for k in config.thresholds.frustration_keywords]
    approval_words = {"yes", "y", "ok", "do it", "go", "proceed", "continue", "yep",
                      "yeah", "sure", "go ahead", "lets go", "let's go", "ship it", "lgtm"}

    for proj_name, jsonl_path in iter_project_sessions(config.claude_dir):
        if "subagents" in str(jsonl_path):
            continue

        prev_type = None
        prev_user_ts = None
        prev_tool = None
        prev_file_read = None
        was_frustrated = False
        sess_first_ts = None
        sess_last_ts = None
        sess_msgs = 0
        local_consec = 0

        for entry in iter_jsonl(jsonl_path):
            etype = entry.get("type", "")
            ts_str = entry.get("timestamp", "")
            ts = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if not sess_first_ts:
                        sess_first_ts = ts
                    sess_last_ts = ts
                except (ValueError, TypeError):
                    pass

            if etype == "user":
                total_user += 1
                sess_msgs += 1
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, list):
                    content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                if not isinstance(content, str) or len(content) < 2:
                    prev_type = "user"
                    continue
                if content.startswith("This session is being continued"):
                    prev_type = "user"
                    continue

                clen = len(content)
                lengths.append(clen)
                words = content.split()

                # Openers
                if words:
                    opener = words[0].lower().strip(".,!?:;\"'()[]{}< >")
                    if (opener
                        and not opener.startswith("<")
                        and not opener.startswith("/")
                        and ">" not in opener
                        and opener not in ("task-notification", "local-command-caveat", "local-command-stdout",
                                           "command-name", "status", "system-reminder")):
                        openers[opener] += 1

                # Mega
                if clen > mega_threshold:
                    mega += 1

                # Approvals
                cl = content.lower().strip()
                if cl in approval_words:
                    approvals[cl] += 1

                # Corrections
                if cl.startswith(("no ", "not ", "i mean", "wrong", "that's not", "no,")):
                    corrections += 1

                # Frustration
                if clen < 100:
                    for kw in frust_keywords:
                        if kw in cl:
                            frustrations += 1
                            frust_words[kw.strip()] += 1
                            was_frustrated = True
                            break
                    else:
                        was_frustrated = False
                else:
                    was_frustrated = False

                # Gratitude
                if any(w in cl for w in ["thanks", "thank you", "thx", "great", "perfect", "nice", "awesome"]):
                    gratitude += 1

                # Rapid fire
                if ts and prev_user_ts:
                    gap = (ts - prev_user_ts).total_seconds()
                    total_gaps += 1
                    if gap < 5:
                        rapid_fire += 1

                # Consecutive user
                if prev_type == "user":
                    local_consec += 1
                    if local_consec >= 2:
                        consec_user += 1
                else:
                    local_consec = 0

                # Hour
                if ts:
                    hour_counts[ts.hour] += 1
                    if ts_str:
                        daily_projects[ts_str[:10]].add(proj_name)

                prev_user_ts = ts
                prev_type = "user"

            elif etype == "assistant":
                sess_msgs += 1
                msg = entry.get("message", {})
                usage = msg.get("usage", {})
                model = msg.get("model", "")

                if usage:
                    total_input += usage.get("input_tokens", 0)
                    total_output += usage.get("output_tokens", 0)
                    total_cache_create += usage.get("cache_creation_input_tokens", 0)
                    total_cache_read += usage.get("cache_read_input_tokens", 0)
                    if model:
                        c = usage.get("input_tokens", 0) / 1e6 * 15 + usage.get("output_tokens", 0) / 1e6 * 75
                        model_costs[model] += c

                # Tool extraction
                content_blocks = msg.get("content", [])
                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool = block.get("name", "")

                            if was_frustrated and tool:
                                tool_after_frust[tool] += 1

                            # Read-edit-read
                            tool_input = block.get("input", {})
                            if isinstance(tool_input, dict):
                                if tool == "Read":
                                    fp = tool_input.get("file_path", "")
                                    if prev_tool == "Edit" and prev_file_read and fp == prev_file_read:
                                        read_edit_read += 1
                                    prev_file_read = fp

                            prev_tool = tool

                prev_type = "assistant"
                was_frustrated = False

        # Session summary
        if sess_first_ts and sess_last_ts:
            dur = (sess_last_ts - sess_first_ts).total_seconds() / 60
            session_durations.append(dur)
            session_msg_counts.append(sess_msgs)

    # Build profile
    lengths.sort()
    total_all_input = total_input + total_cache_create + total_cache_read
    cache_rate = (total_cache_read / total_all_input * 100) if total_all_input > 0 else 0

    # Top cost driver
    if session_durations and sum(session_durations) / len(session_durations) > 120:
        top_driver = "session_length"
    elif model_costs and model_costs.get("claude-opus-4-6", 0) > sum(model_costs.values()) * 0.8:
        top_driver = "model_choice"
    else:
        top_driver = "subagents"

    peak = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    ppd = sum(len(v) for v in daily_projects.values()) / max(len(daily_projects), 1)

    return UserProfile(
        total_messages=total_user,
        median_length=lengths[len(lengths) // 2] if lengths else 0,
        avg_length=sum(lengths) / len(lengths) if lengths else 0,
        single_word_pct=len([l for l in lengths if l < 15]) / max(total_user, 1) * 100,
        mega_prompt_pct=mega / max(total_user, 1) * 100,
        top_openers=sorted(openers.items(), key=lambda x: x[1], reverse=True)[:10],
        approval_signals=dict(approvals.most_common(10)),
        correction_count=corrections,
        frustration_rate=frustrations / max(total_user, 1) * 100,
        frustration_words=dict(frust_words.most_common(10)),
        gratitude_rate=gratitude / max(total_user, 1) * 100,
        rapid_fire_pct=rapid_fire / max(total_gaps, 1) * 100,
        consecutive_user_msgs=consec_user,
        read_edit_read_count=read_edit_read,
        peak_hours=[h for h, _ in peak],
        projects_per_day_avg=ppd,
        avg_session_duration=sum(session_durations) / len(session_durations) if session_durations else 0,
        avg_session_messages=sum(session_msg_counts) / len(session_msg_counts) if session_msg_counts else 0,
        top_cost_driver=top_driver,
        cache_hit_rate=cache_rate,
        total_sessions=len(session_durations),
        model_breakdown=dict(model_costs.most_common()),
        tool_after_frustration=dict(tool_after_frust.most_common(5)),
    )


def generate_style(profile: UserProfile) -> str:
    """Generate a STYLE.md based on detected patterns."""
    lines = ["# Response Style", ""]

    # Core style
    if profile.median_length < 100:
        lines.append("Be extremely concise. Lead with answer or action, not reasoning. No preamble, no trailing summaries. First sentence = the answer.")
    elif profile.median_length < 300:
        lines.append("Be concise but thorough. Lead with the answer, add brief context only when needed.")
    else:
        lines.append("Match the user's detail level. They write detailed prompts — provide proportionally detailed responses.")

    # Correction style
    if profile.correction_count > 10:
        lines.append('When user says "no X" — change only X, keep everything else unchanged.')

    # Approval signals
    top_approvals = list(profile.approval_signals.keys())[:3]
    if top_approvals:
        quoted = ", ".join(f'"{a}"' for a in top_approvals)
        lines.append(f"When user says {quoted} — execute immediately, zero recap.")

    # Paste handling
    if profile.mega_prompt_pct > 10:
        lines.append("When user pastes large content — scan it, identify the actionable item, and act. Don't ask what they want.")

    # Frustration
    if profile.frustration_rate > 3:
        lines.append("On frustration signals — pause, re-read context, don't blindly execute. Suggest a different approach.")

    lines.append("")
    lines.append("## Output Compression")
    lines.append("")
    lines.append("Drop articles (a/an/the), filler words, pleasantries, hedging. Use short synonyms. Fragments OK. Keep technical terms exact, code blocks unchanged, error quotes verbatim. Revert to normal for security warnings and irreversible actions.")

    return "\n".join(lines) + "\n"


def generate_learnings(profile: UserProfile) -> str:
    """Generate transferable LEARNINGS.md from behavioral patterns."""
    sections = ["# Session Learnings", "",
                 "Auto-generated behavioral rules. Drop into ~/.claude/ or share as a template.", ""]

    # Message style
    sections.append("## Communication Style")
    if profile.median_length < 100:
        sections.append(f"- User is terse (median {profile.median_length} chars). Match their brevity.")
    if profile.single_word_pct > 5:
        sections.append(f"- {profile.single_word_pct:.0f}% of messages are single-word commands. Treat as directives.")
    if profile.top_openers:
        top3 = ", ".join(f'"{w}"' for w, _ in profile.top_openers[:5])
        sections.append(f"- Most common openers: {top3}")

    # Corrections
    if profile.correction_count > 5:
        sections.append("")
        sections.append("## Correction Pattern")
        sections.append(f'- User corrects via "no X" ({profile.correction_count} occurrences). Means "change only X."')
        sections.append("- Don't revert unrelated work when correcting.")

    # Approvals
    if profile.approval_signals:
        sections.append("")
        sections.append("## Approval Signals")
        for sig, count in profile.approval_signals.items():
            sections.append(f'- "{sig}" x{count} — means execute now, no confirmation needed.')

    # Frustration
    if profile.frustration_rate > 2:
        sections.append("")
        sections.append("## Frustration Response")
        sections.append(f"- Frustration rate: {profile.frustration_rate:.1f}% of messages.")
        if profile.tool_after_frustration:
            top_tool = list(profile.tool_after_frustration.keys())[0]
            sections.append(f"- After frustration, Claude defaults to {top_tool}. Should Read context first instead.")
        sections.append("- When stuck, suggest /clear and fresh restatement rather than iterating.")

    # Efficiency
    sections.append("")
    sections.append("## Efficiency Rules")
    if profile.rapid_fire_pct > 30:
        sections.append(f"- User sends rapid-fire messages ({profile.rapid_fire_pct:.0f}% within 5s). Don't act on partial sequences.")
    if profile.consecutive_user_msgs > 20:
        sections.append(f"- {profile.consecutive_user_msgs} consecutive messages without response. Wait for completion.")
    if profile.read_edit_read_count > 10:
        sections.append(f"- {profile.read_edit_read_count} read-edit-read cycles detected. Don't re-read after Edit — it confirms success.")

    # Work patterns
    sections.append("")
    sections.append("## Work Patterns")
    if profile.peak_hours:
        hours_str = ", ".join(f"{h}:00" for h in profile.peak_hours)
        sections.append(f"- Peak hours (UTC): {hours_str}")
    if profile.projects_per_day_avg > 2:
        sections.append(f"- Avg {profile.projects_per_day_avg:.1f} projects/day. Expect frequent context switches.")
    sections.append(f"- Avg session: {_fmt_duration(profile.avg_session_duration)}, {profile.avg_session_messages:.0f} messages")

    # Cost
    sections.append("")
    sections.append("## Cost Awareness")
    sections.append(f"- Top cost driver: {profile.top_cost_driver.replace('_', ' ')}")
    sections.append(f"- Cache hit rate: {profile.cache_hit_rate:.1f}%")
    if profile.avg_session_messages > 200:
        sections.append(f"- Sessions average {profile.avg_session_messages:.0f} messages. Nudge /compact at 150.")
    if profile.top_cost_driver == "model_choice":
        sections.append("- Suggest /model sonnet for routine Read/Edit/Bash work.")

    return "\n".join(sections) + "\n"


def run_learn(payload: dict = {}, *, config: Config | None = None) -> int:
    """Analyze user messages and generate STYLE.md + LEARNINGS.md."""
    config = config or load_config()
    print("Scanning session data...", file=sys.stderr)

    profile = analyze_user_messages(config)

    style_content = generate_style(profile)
    learnings_content = generate_learnings(profile)

    # Write to data dir
    config.data_dir.mkdir(parents=True, exist_ok=True)
    style_path = config.data_dir / "STYLE.md"
    learnings_path = config.data_dir / "LEARNINGS.md"
    style_path.write_text(style_content, encoding="utf-8")
    learnings_path.write_text(learnings_content, encoding="utf-8")

    # Print profile summary
    print(f"## User Profile ({profile.total_messages} messages, {profile.total_sessions} sessions)")
    print(f"  Median message: {profile.median_length} chars")
    print(f"  Rapid-fire rate: {profile.rapid_fire_pct:.0f}%")
    print(f"  Frustration rate: {profile.frustration_rate:.1f}%")
    print(f"  Correction count: {profile.correction_count}")
    print(f"  Read-edit-read waste: {profile.read_edit_read_count}")
    print(f"  Avg session: {_fmt_duration(profile.avg_session_duration)}, {profile.avg_session_messages:.0f} msgs")
    print(f"  Top cost driver: {profile.top_cost_driver}")
    print()
    print("--- Generated STYLE.md ---")
    print(style_content)
    print("--- Generated LEARNINGS.md ---")
    print(learnings_content)
    print(f"Files written to:")
    print(f"  {style_path}")
    print(f"  {learnings_path}")
    print()
    print(f"To apply: copy STYLE.md to ~/.claude/STYLE.md and add @STYLE.md to ~/.claude/CLAUDE.md")
    print(f"To share: LEARNINGS.md contains no PII — safe to share as a template.")
    return 0


# --- Daily digest injection on SessionStart ---

def _should_show_daily_digest(config: Config) -> bool:
    """True if this is the first session of a new day."""
    state_path = config.data_dir / "state.json"
    if not state_path.exists(): return False
    try: state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError): return False
    last_ts = state.get("last_ts", "")
    if not last_ts: return False
    try:
        last_date = datetime.fromisoformat(last_ts).date()
        return last_date < datetime.now(timezone.utc).date()
    except (ValueError, TypeError): return False
