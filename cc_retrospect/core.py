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
    max_subagents_per_session: int = 10
    max_claudemd_bytes: int = 50_000
    tool_chain_threshold: int = 5
    daily_cost_warning: float = 500.0
    frustration_keywords: list[str] = ["again", "ugh", "still broken", "not working", "wrong", "try again", "that's wrong", "no ", "still not", "wtf", "come on", "seriously", "sigh", "nope"]
    waste_webfetch_domains: list[str] = ["github.com", "api.github.com"]


class HintsConfig(BaseModel):
    session_start: bool = False
    pre_tool: bool = True
    post_tool: bool = True


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
    description = "Detect wasted tokens: WebFetch to GitHub, duplicate reads, tool chains, model mismatch"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        if not sessions: return AnalysisResult(title="Waste Analysis")
        recs, rows = [], []
        domain_totals: Counter = Counter()
        domain_sessions: Counter = Counter()
        for s in sessions:
            for domain, count in s.webfetch_domains.items():
                if any(wd in domain for wd in config.thresholds.waste_webfetch_domains):
                    domain_totals[domain] += count; domain_sessions[domain] += 1
        for domain, count in domain_totals.items():
            recs.append(Recommendation(severity="warning", description=f"{count} WebFetch calls to {domain} across {domain_sessions[domain]} sessions. Use `gh` CLI instead.", estimated_savings=f"~{_fmt_tokens(count * 5000)} tokens"))
        rows.append(("WebFetch to waste domains", str(sum(domain_totals.values()))))
        all_chains: dict[str, list[int]] = defaultdict(list)
        for s in sessions:
            for tool, length in s.tool_chains:
                if length >= config.thresholds.tool_chain_threshold: all_chains[tool].append(length)
        for tool, lengths in sorted(all_chains.items(), key=lambda x: sum(x[1]), reverse=True):
            recs.append(Recommendation(severity="info", description=f"{len(lengths)} consecutive {tool} chains (longest: {max(lengths)}). Combine calls or use scripts."))
        rows.append(("Long tool chains", str(sum(len(v) for v in all_chains.values()))))
        total_mega = sum(s.mega_prompt_count for s in sessions)
        if total_mega > 5:
            recs.append(Recommendation(severity="warning", description=f"{total_mega} mega prompts (>{config.thresholds.mega_prompt_chars} chars). Use file references instead of pasting content."))
        rows.append(("Mega prompts", str(total_mega)))
        complex_tools = {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}
        for s in sessions:
            opus_cost = s.model_breakdown.get("claude-opus-4-6", 0)
            if opus_cost > 50 and not any(t in s.tool_counts for t in complex_tools):
                recs.append(Recommendation(severity="warning", description=f"Session {s.session_id[:8]}... used Opus ({_fmt_cost(opus_cost)}) for simple tasks. Sonnet would be ~5x cheaper.", estimated_savings=_fmt_cost(opus_cost * 0.8)))
                break
        rows.append(("Model mismatch candidates", str(sum(1 for s in sessions if s.model_breakdown.get("claude-opus-4-6", 0) > 50 and not any(t in s.tool_counts for t in complex_tools)))))
        return AnalysisResult(title="Waste Analysis", sections=[Section(header="Waste Summary", rows=rows)], recommendations=recs)


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

        # 5. Mega prompt savings
        total_mega = sum(s.mega_prompt_count for s in sessions)
        if total_mega > 10:
            # mega prompts add ~2K extra tokens each to history
            mega_token_cost = total_mega * 2000 * config.pricing.opus.cache_read_per_mtok / 1e6
            monthly_save = mega_token_cost * monthly_mult
            recs.append(Recommendation(severity="info",
                description=f"Use file references instead of pasting ({total_mega} mega prompts)",
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
    compaction_count: int = 0

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

def _render(analyzer_cls, config: Config | None = None, sessions=None) -> int:
    cfg = config or load_config()
    ss = sessions if sessions is not None else load_all_sessions(cfg)
    print(analyzer_cls().analyze(ss, cfg).render_markdown())
    return 0


def run_cost(payload: dict = {}, *, config: Config | None = None) -> int:       return _render(CostAnalyzer, config=config)
def run_habits(payload: dict = {}, *, config: Config | None = None) -> int:     return _render(HabitsAnalyzer, config=config)
def run_health(payload: dict = {}, *, config: Config | None = None) -> int:     return _render(HealthAnalyzer, config=config)
def run_tips(payload: dict = {}, *, config: Config | None = None) -> int:       return _render(TipsAnalyzer, config=config)
def run_waste(payload: dict = {}, *, config: Config | None = None) -> int:      return _render(WasteAnalyzer, config=config)
def run_compare(payload: dict = {}, *, config: Config | None = None) -> int:    return _render(CompareAnalyzer, config=config)


def run_report(payload: dict = {}, *, config: Config | None = None) -> int:
    config = config or load_config()
    sessions = load_all_sessions(config)
    parts = [f"# cc-retrospect Report\n\nGenerated: {datetime.now().isoformat()}\n"]
    for a in get_analyzers(config):
        parts.append(a.analyze(sessions, config).render_markdown())
    report = "\n---\n\n".join(parts)
    reports_dir = config.data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"report-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report saved to {report_path}")
    print(report)
    return 0


def run_savings(payload: dict = {}, *, config: Config | None = None) -> int:   return _render(SavingsAnalyzer, config=config)
def run_model_efficiency(payload: dict = {}, *, config: Config | None = None) -> int: return _render(ModelAnalyzer, config=config)


def run_digest(payload: dict = {}, *, config: Config | None = None) -> int:
    """Daily digest: yesterday's sessions analyzed with savings + model efficiency."""
    config = config or load_config()
    sessions = load_all_sessions(config)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_sessions = [s for s in sessions if s.start_ts and yesterday <= s.start_ts[:10] <= today]
    if not day_sessions:
        print(f"[cc-retrospect] No sessions found for {yesterday}.")
        return 0
    parts = [f"## cc-retrospect Daily Digest ({yesterday})", ""]
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
    return _render(TrendAnalyzer, config=config)


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
    opus_total = sum(s.model_breakdown.get("claude-opus-4-6", 0) for s in week_sessions)
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
    # Budget alert
    if state["today_cost"] > config.thresholds.daily_cost_warning:
        print(f"[cc-retrospect] Budget alert: {_fmt_cost(state['today_cost'])} spent today (threshold: {_fmt_cost(config.thresholds.daily_cost_warning)}).", file=sys.stderr)
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
            if sessions:
                total_cost = sum(s.total_cost for s in sessions)
                print(f"[cc-retrospect] Welcome! Found {len(sessions)} sessions ({_fmt_cost(total_cost)}). Run /cc-retrospect:analyze for a full report.")
            else:
                print("[cc-retrospect] Welcome! No session data yet. Hooks will start tracking automatically.")
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
    if last_dur > th.long_session_minutes: lines.append(f"Tip: Start fresh more often — your last ran {_fmt_duration(last_dur)}.")
    if last_cost > 100: lines.append(f"Tip: Consider /model sonnet (last session: {_fmt_cost(last_cost)}).")
    if last_frust > 3: lines.append("Tip: When stuck, /clear and restate — iterating grows context and cost.")
    if last_subs > th.max_subagents_per_session: lines.append("Tip: Use Grep/Read instead of spawning Agent for simple lookups.")
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
    # Daily digest: first session of a new day gets yesterday's summary
    if _should_show_daily_digest(config):
        try:
            sessions = load_all_sessions(config)
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            day_sessions = [s for s in sessions if s.start_ts and s.start_ts[:10] == yesterday]
            if day_sessions:
                day_cost = sum(s.total_cost for s in day_sessions)
                day_frust = sum(s.frustration_count for s in day_sessions)
                day_subs = sum(s.subagent_count for s in day_sessions)
                compactions = _load_compactions(config, since=yesterday)
                lines.append(f"Yesterday: {len(day_sessions)} sessions, {_fmt_cost(day_cost)}, {day_frust} frustrations, {day_subs} subagents, {len(compactions)} compactions.")
                # Quick model efficiency note
                opus_simple = sum(s.model_breakdown.get("claude-opus-4-6", 0) for s in day_sessions
                                  if not any(t in s.tool_counts for t in {"Agent", "EnterPlanMode", "WebSearch", "WebFetch"}))
                if opus_simple > 10:
                    lines.append(f"Model tip: {_fmt_cost(opus_simple)} spent on Opus for simple tasks — try /model sonnet.")
        except Exception as e:
            logger.debug("Daily digest failed: %s", e)
    if lines and config.hints.session_start:
        print("[cc-retrospect] " + " ".join(lines))
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
                    hints.append(f"Consider using `gh` CLI instead of WebFetch for {domain} — structured output, fewer tokens.")
            except Exception as e:
                logger.debug("urlparse failed for WebFetch URL in pre_tool_use: %s", e)
    if tool_name == "Agent":
        prompt = tool_input.get("prompt", "")
        if any(p in prompt.lower() for p in ["find", "search for", "look for", "where is", "which file", "grep"]) and tool_input.get("subagent_type", "") in ("Explore", ""):
            hints.append("This looks like a simple search — try Grep or Glob directly to save a subagent spawn.")
    live = _load_live_state(config)
    if tool_name == "Bash":
        if live.prev_tool == "Bash":
            live.chain_length += 1
            if live.chain_length >= 4 and not live.bash_chain_warned:
                hints.append("Multiple consecutive Bash calls — consider combining with && or writing a script.")
                live.bash_chain_warned = True
        else:
            live.chain_length = 1; live.bash_chain_warned = False
    elif tool_name != live.prev_tool:
        live.chain_length = 1; live.bash_chain_warned = False
    live.prev_tool = tool_name
    _save_live_state(config, live)
    if hints and config.hints.pre_tool:
        for hint in hints: print(f"[cc-retrospect] {hint}")
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
    if msg >= 150 and not live.compact_nudged:
        hints.append(f"Session at {msg}+ tool calls. Context is growing expensive — consider /compact or starting fresh.")
        live.compact_nudged = True
    elif msg >= 300 and live.compact_nudged and not live.compact_nudged_2:
        hints.append(f"Session at {msg}+ tool calls. Strongly recommend /compact — each message re-reads the full history.")
        live.compact_nudged_2 = True
    if live.subagent_count == config.thresholds.max_subagents_per_session and not live.subagent_warned:
        hints.append(f"You've spawned {live.subagent_count} subagents this session. Each loads the full system context. Try Grep/Read for simple lookups.")
        live.subagent_warned = True
    _save_live_state(config, live)
    if hints and config.hints.post_tool:
        for hint in hints: print(f"[cc-retrospect] {hint}")
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
