"""cc-retrospect analyzers — Built-in analysis implementations."""
from __future__ import annotations

import importlib.util
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from cc_retrospect.config import Config
from cc_retrospect.models import SessionSummary, AnalysisResult, Section, Recommendation
from cc_retrospect.utils import _group, _top, _union, display_project, _fmt_tokens, _fmt_cost, _fmt_duration

logger = logging.getLogger("cc_retrospect")


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
            savings = opus_cost * (1 - config.pricing.sonnet.input_per_mtok / config.pricing.opus.input_per_mtok)
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
        a = _stats(tw); b = _stats(lw)
        rows = [
            ("This week: cost", _fmt_cost(a["cost"])), ("This week: sessions", str(a["sessions"])),
            ("This week: avg duration", _fmt_duration(a["avg_duration"])), ("This week: frustrations", str(a["frustrations"])),
            ("Last week: cost", _fmt_cost(b["cost"])), ("Last week: sessions", str(b["sessions"])),
            ("Last week: avg duration", _fmt_duration(b["avg_duration"])), ("Last week: frustrations", str(b["frustrations"])),
        ]
        recs = []
        if a["cost"] > b["cost"] * 1.5 and b["cost"] > 0:
            recs.append(Recommendation(severity="warning", description="Spending increased significantly this week."))
        elif a["cost"] < b["cost"] * 0.7 and b["cost"] > 0:
            recs.append(Recommendation(severity="info", description="Good progress — spending decreased this week."))
        return AnalysisResult(title="This Week vs Last Week", sections=[Section(header="Comparison", rows=rows)], recommendations=recs)


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


class TrendAnalyzer:
    name = "trends"
    description = "Weekly trend tracking — are you improving over time?"

    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        from cc_retrospect.parsers import iter_jsonl

        trends_path = config.data_dir / "trends.jsonl"
        weeks: list[dict] = list(iter_jsonl(trends_path)) if trends_path.exists() else []
        if not weeks:
            return AnalysisResult(title="Trends", recommendations=[
                Recommendation(severity="info", description="No trend data yet. Trends are recorded weekly via the stop hook.")])
        sorted_weeks = sorted(weeks, key=lambda x: x.get("week", ""))[-8:]
        rows = []
        prev: dict | None = None
        for w in sorted_weeks:
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
        if len(sorted_weeks) >= 2:
            latest, prior = sorted_weeks[-1], sorted_weeks[-2]
            if latest.get("cost", 0) < prior.get("cost", 0) * 0.8:
                recs.append(Recommendation(severity="info", description="Spending trending down — good progress."))
            elif latest.get("cost", 0) > prior.get("cost", 0) * 1.3:
                recs.append(Recommendation(severity="warning", description="Spending trending up. Check /savings for actionable cuts."))
        return AnalysisResult(title="Weekly Trends", sections=[Section(header="Last 8 Weeks", rows=rows)], recommendations=recs)


_BUILTIN_ANALYZERS = [CostAnalyzer, HabitsAnalyzer, HealthAnalyzer, WasteAnalyzer, TipsAnalyzer, CompareAnalyzer, SavingsAnalyzer, ModelAnalyzer, TrendAnalyzer]


def get_analyzers(config: Config) -> list:
    """Return all registered analyzers (builtin + custom from data_dir/analyzers/)."""
    analyzers = [cls() for cls in _BUILTIN_ANALYZERS]
    custom_dir = config.data_dir / "analyzers"
    if not custom_dir.is_dir():
        return analyzers
    for py_file in custom_dir.glob("*.py"):
        try:
            logger.warning("Loading custom analyzer from %s — ensure this is trusted code", py_file)
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for name in dir(mod):
                    attr = getattr(mod, name)
                    if isinstance(attr, type) and all(hasattr(attr, x) for x in ("name", "description", "analyze")):
                        analyzers.append(attr())
        except (OSError, ImportError, AttributeError, SyntaxError) as e:
            logger.warning("Failed to load custom analyzer from %s: %s", py_file, e)
    return analyzers
