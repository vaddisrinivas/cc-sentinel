"""Generate and serve a dashboard from cc-retrospect data."""
from __future__ import annotations

import json
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from cc_retrospect.config import Config, load_config
from cc_retrospect.cache import load_all_sessions
from cc_retrospect.dashboard_server import PORT, ensure_running

DASHBOARD_HTML = (Path(__file__).parent / "dashboard_template.html").read_text(encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def generate_dashboard(config: Config | None = None, days: int = 30) -> str:
    """Generate dashboard JSON string with embedded data."""
    try:
        return _build_dashboard_data(config, days)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return json.dumps({
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "error": str(e),
            "state": {}, "sessions": [], "trends": [], "compactions": [],
            "budget_tiers": [], "days": days, "reports": [],
            "tool_usage": {}, "hourly_activity": [0]*24, "cost_by_day": {},
            "model_recommendation": {},
        }, default=str)


def _build_dashboard_data(config: Config | None = None, days: int = 30) -> str:
    """Build dashboard data JSON string."""
    config = config or load_config()

    from cc_retrospect.utils import _filter_sessions
    all_sessions_unfiltered = load_all_sessions(config)
    all_sessions = _filter_sessions(all_sessions_unfiltered, days=days, config=config)
    # Sort by date descending and exclude noise
    sessions = sorted(
        [s for s in all_sessions if s.start_ts],
        key=lambda s: s.start_ts, reverse=True,
    )

    state = _load_json(config.data_dir / "state.json")
    trends = _load_jsonl(config.data_dir / "trends.jsonl")
    compactions = _load_jsonl(config.data_dir / "compactions.jsonl")

    # Calculate today's cost from full session data (not state.json which only covers hook-fired sessions)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_cost = sum(
        s.total_cost for s in all_sessions_unfiltered
        if (s.start_ts or "")[:10] == today_str
    )
    today_by_project: dict[str, float] = {}
    for s in all_sessions_unfiltered:
        if (s.start_ts or "")[:10] == today_str:
            today_by_project[s.project] = today_by_project.get(s.project, 0) + s.total_cost
    state["today_cost"] = today_cost
    state["today_date"] = today_str
    # Replace entirely — stale entries from state.json cause overflow bars
    state["projects"] = {
        proj: {"today_date": today_str, "today_cost": cost}
        for proj, cost in today_by_project.items()
    }

    budget_tiers = [
        {"label": "Warning", "threshold": config.budget.warning.threshold, "color": "#d29922"},
        {"label": "Critical", "threshold": config.budget.critical.threshold, "color": "#d18616"},
        {"label": "Severe", "threshold": config.budget.severe.threshold, "color": "#f85149"},
    ]

    # Build reports list for Reports tab
    reports: list[dict] = []
    reports_dir = config.data_dir / "reports"
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("dashboard-*.html"), reverse=True):
            stamp = f.stem.replace("dashboard-", "")
            data_name = f"data-{stamp}.js"
            reports.append({
                "name": f.stem,
                "date": stamp.replace("_", " ").replace("-", "/", 2),
                "html_url": f"/reports/{f.name}",
                "data_url": f"/reports/{data_name}" if (reports_dir / data_name).exists() else None,
            })

    # Aggregate: tool usage
    tool_usage: dict[str, int] = {}
    for s in sessions:
        for tool, count in (s.tool_counts or {}).items():
            tool_usage[tool] = tool_usage.get(tool, 0) + count

    # Aggregate: hourly activity (24 buckets)
    hourly_activity = [0] * 24
    for s in sessions:
        if s.start_ts:
            try:
                hour = int(s.start_ts[11:13])
                hourly_activity[hour] += 1
            except (ValueError, IndexError):
                pass

    # Aggregate: cost by day
    cost_by_day: dict[str, float] = defaultdict(float)
    for s in sessions:
        day = (s.start_ts or "")[:10]
        if day:
            cost_by_day[day] += s.total_cost

    model_rec = _load_json(config.data_dir / "model_recommendation.json")

    # ── Profile stats ────────────────────────────────────────────────────────
    from datetime import timedelta

    total_cost = sum(s.total_cost for s in sessions)
    total_sessions = len(sessions)
    total_messages = sum(s.message_count for s in sessions)
    total_input = sum(s.total_input_tokens for s in sessions)
    total_output = sum(s.total_output_tokens for s in sessions)
    total_cache_read = sum(s.total_cache_read_tokens for s in sessions)
    total_cache_create = sum(s.total_cache_creation_tokens for s in sessions)
    # Cache rate: reads / (reads + creation + fresh input) — matches health analyzer
    cache_denom = total_cache_read + total_cache_create + total_input
    cache_rate = total_cache_read / cache_denom * 100 if cache_denom > 0 else 0
    avg_session_min = sum(s.duration_minutes for s in sessions) / total_sessions if total_sessions else 0
    total_tools = sum(sum(s.tool_counts.values()) for s in sessions)
    total_frustrations = sum(s.frustration_count for s in sessions)
    frustration_rate = total_frustrations / total_sessions * 100 if total_sessions else 0
    total_subagents = sum(s.subagent_count for s in sessions)

    model_costs: dict[str, float] = {}
    for s in sessions:
        for m, c in (s.model_breakdown or {}).items():
            model_costs[m] = model_costs.get(m, 0) + c

    # Project name cleanup: '-Users-user-Projects-my-app' -> 'my-app'
    def _clean_proj(name: str) -> str:
        if "-Users-" in name:
            name = name.split("-Users-")[-1]
            # Drop username segment (first part before -)
            parts = name.split("-", 1)
            if len(parts) > 1:
                name = parts[1]
            # Drop 'Projects-' prefix if present
            if name.startswith("Projects-"):
                name = name[9:]
        return name or "unknown"

    proj_costs: dict[str, float] = {}
    proj_raw: dict[str, str] = {}  # cleaned -> raw
    for s in sessions:
        cleaned = _clean_proj(s.project)
        proj_costs[cleaned] = proj_costs.get(cleaned, 0) + s.total_cost
        proj_raw[cleaned] = s.project
    top_projects = sorted(proj_costs.items(), key=lambda x: -x[1])[:5]

    long_sessions = sum(1 for s in sessions if s.duration_minutes > 90)
    short_sessions = sum(1 for s in sessions if s.duration_minutes <= 45)
    style = "Deep Diver" if long_sessions > total_sessions * 0.3 else "Sprinter" if short_sessions > total_sessions * 0.6 else "Balanced"

    # Model efficiency: % of Opus spend on sessions that used complex tools (Agent, WebSearch, Plan)
    opus_total = sum(c for m, c in model_costs.items() if "opus" in m.lower())
    opus_justified = 0.0
    complex_tool_names = {"Agent", "WebSearch", "WebFetch", "EnterPlanMode", "TodoWrite"}
    for s in sessions:
        opus_cost = sum(c for m, c in (s.model_breakdown or {}).items() if "opus" in m.lower())
        if opus_cost > 0:
            has_complex = any(s.tool_counts.get(t, 0) > 0 for t in complex_tool_names)
            if has_complex or s.subagent_count > 0 or s.duration_minutes > 60:
                opus_justified += opus_cost
    model_efficiency = round(opus_justified / opus_total * 100) if opus_total > 0 else 100

    peak_hour = max(range(24), key=lambda h: sum(1 for s in sessions if s.start_ts and s.start_ts[11:13] == f"{h:02d}")) if sessions else 0

    session_dates = sorted(set((s.start_ts or "")[:10] for s in sessions if s.start_ts))
    streak = 0
    if session_dates:
        current_streak = 1
        for i in range(len(session_dates) - 1, 0, -1):
            try:
                d1 = datetime.strptime(session_dates[i], "%Y-%m-%d")
                d2 = datetime.strptime(session_dates[i - 1], "%Y-%m-%d")
                if (d1 - d2).days == 1:
                    current_streak += 1
                else:
                    break
            except ValueError:
                break
        streak = current_streak

    now = datetime.now()
    this_week = [s for s in sessions if s.start_ts and s.start_ts[:10] >= (now - timedelta(days=7)).strftime("%Y-%m-%d")]
    last_week = [s for s in sessions if s.start_ts and (now - timedelta(days=14)).strftime("%Y-%m-%d") <= s.start_ts[:10] < (now - timedelta(days=7)).strftime("%Y-%m-%d")]
    this_week_cost = sum(s.total_cost for s in this_week)
    last_week_cost = sum(s.total_cost for s in last_week)
    wow_change = ((this_week_cost - last_week_cost) / last_week_cost * 100) if last_week_cost > 0 else 0
    this_week_sessions = len(this_week)
    last_week_sessions = len(last_week)
    this_week_frust = sum(s.frustration_count for s in this_week)
    last_week_frust = sum(s.frustration_count for s in last_week)
    this_week_avg_dur = sum(s.duration_minutes for s in this_week) / this_week_sessions if this_week_sessions else 0
    last_week_avg_dur = sum(s.duration_minutes for s in last_week) / last_week_sessions if last_week_sessions else 0

    # Frustration word aggregation (top 8)
    frust_words: dict[str, int] = {}
    for s in sessions:
        for w, c in (s.frustration_words or {}).items():
            frust_words[w] = frust_words.get(w, 0) + c
    top_frustrations = sorted(frust_words.items(), key=lambda x: -x[1])[:8]

    # WebFetch domain waste
    wf_domains: dict[str, int] = {}
    for s in sessions:
        for d, c in (s.webfetch_domains or {}).items():
            wf_domains[d] = wf_domains.get(d, 0) + c
    github_fetches = sum(c for d, c in wf_domains.items() if "github" in d.lower())

    # Unique finds
    avg_cost_per_session = total_cost / total_sessions if total_sessions else 0
    most_expensive_session = max(sessions, key=lambda s: s.total_cost) if sessions else None
    max_session_cost = most_expensive_session.total_cost if most_expensive_session else 0

    # ── Personality archetype ──
    opus_pct = opus_total / total_cost * 100 if total_cost > 0 else 0
    avg_dur = avg_session_min
    sess_per_day = total_sessions / max(len(session_dates), 1)
    bash_pct = tool_usage.get("Bash", 0) / total_tools * 100 if total_tools else 0
    edit_pct = tool_usage.get("Edit", 0) / total_tools * 100 if total_tools else 0
    web_pct = (tool_usage.get("WebSearch", 0) + tool_usage.get("WebFetch", 0)) / total_tools * 100 if total_tools else 0

    # Determine archetype — ordered most-specific first
    if opus_pct > 75 and sess_per_day > 20:
        archetype = "The Opus Maximalist"
        archetype_desc = f"Runs premium AI at {round(opus_pct)}% — {round(sess_per_day)} sessions/day, no compromises"
        archetype_emoji = "💜"
    elif opus_pct > 70 and avg_dur > 60 and total_subagents > total_sessions * 0.3:
        archetype = "The Architect"
        archetype_desc = "Designs complex systems with deep sessions and heavy orchestration"
        archetype_emoji = "🏛️"
    elif sess_per_day > 25 and streak > 20:
        archetype = "The Daily Grinder"
        archetype_desc = f"{round(sess_per_day)} sessions/day, {streak}-day streak — Claude is your oxygen"
        archetype_emoji = "🔥"
    elif sess_per_day > 8 and avg_dur < 40:
        archetype = "The Speedrunner"
        archetype_desc = "Burns through tasks in rapid-fire sessions with surgical precision"
        archetype_emoji = "⚡"
    elif web_pct > 15:
        archetype = "The Explorer"
        archetype_desc = "Always researching, fetching docs, and expanding the knowledge frontier"
        archetype_emoji = "🔭"
    elif edit_pct > 15 and frustration_rate < 5:
        archetype = "The Craftsman"
        archetype_desc = "Methodical editor who shapes code with patience and low friction"
        archetype_emoji = "🔨"
    elif bash_pct > 40:
        archetype = "The Operator"
        archetype_desc = "Lives in the terminal — scripts, deploys, and automates everything"
        archetype_emoji = "🖥️"
    elif long_sessions > total_sessions * 0.2:
        archetype = "The Deep Diver"
        archetype_desc = "Goes deep on hard problems with marathon sessions and relentless focus"
        archetype_emoji = "🌊"
    elif total_subagents > total_sessions * 0.5:
        archetype = "The Commander"
        archetype_desc = "Delegates aggressively — spawns agents like a fleet admiral"
        archetype_emoji = "🎖️"
    elif opus_pct > 60 and total_cost > 1000:
        archetype = "The Relentless Builder"
        archetype_desc = f"${round(total_cost):,} spent, {total_sessions} sessions — shipping non-stop"
        archetype_emoji = "🚀"
    else:
        archetype = "The Pragmatist"
        archetype_desc = "Adapts model and tool choices precisely to the task at hand"
        archetype_emoji = "🎯"

    # Trait scores (0-100)
    trait_efficiency = min(100, round(cache_rate * 0.5 + model_efficiency * 0.5))
    trait_intensity = min(100, round(min(avg_cost_per_session / 10 * 100, 100)))
    trait_persistence = min(100, round(streak / 30 * 100))
    trait_patience = min(100, max(0, round(100 - frustration_rate * 3)))
    trait_velocity = min(100, round(sess_per_day / 15 * 100))
    trait_depth = min(100, round(avg_dur / 120 * 100))

    # Fun facts
    fun_facts = []
    total_hours = sum(s.duration_minutes for s in sessions) / 60
    fun_facts.append(f"{round(total_hours)}h total coding time with Claude")
    if total_tools > 10000:
        fun_facts.append(f"{total_tools:,} tool calls — that's {round(total_tools / total_sessions)} per session")
    if streak > 14:
        fun_facts.append(f"{streak}-day streak — consistency is your superpower")
    if github_fetches > 100:
        fun_facts.append(f"{github_fetches} WebFetch calls to GitHub (try gh CLI!)")
    if max_session_cost > 100:
        fun_facts.append(f"Most expensive session: ${max_session_cost:.0f}")
    top_tool = max(tool_usage.items(), key=lambda x: x[1])[0] if tool_usage else "Bash"
    fun_facts.append(f"Favorite tool: {top_tool}")

    profile = {
        "total_cost": round(total_cost, 2),
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_tokens": total_input + total_output + total_cache_read + total_cache_create,
        "cache_rate": round(cache_rate, 1),
        "avg_session_min": round(avg_session_min),
        "total_tools_used": total_tools,
        "frustration_rate": round(frustration_rate, 1),
        "total_frustrations": total_frustrations,
        "total_subagents": total_subagents,
        "model_costs": {k: round(v, 2) for k, v in sorted(model_costs.items(), key=lambda x: -x[1])},
        "top_projects": [[p, round(c, 2)] for p, c in top_projects],
        "work_style": style,
        "model_efficiency": model_efficiency,
        "peak_hour": peak_hour,
        "streak_days": streak,
        "days_tracked": days,
        "this_week_cost": round(this_week_cost, 2),
        "last_week_cost": round(last_week_cost, 2),
        "wow_change": round(wow_change, 1),
        "this_week_sessions": this_week_sessions,
        "last_week_sessions": last_week_sessions,
        "this_week_frust": this_week_frust,
        "last_week_frust": last_week_frust,
        "this_week_avg_dur": round(this_week_avg_dur),
        "last_week_avg_dur": round(last_week_avg_dur),
        "long_sessions": long_sessions,
        "top_frustrations": top_frustrations,
        "github_fetches": github_fetches,
        "avg_cost_per_session": round(avg_cost_per_session, 2),
        "max_session_cost": round(max_session_cost, 2),
        "archetype": archetype,
        "archetype_desc": archetype_desc,
        "archetype_emoji": archetype_emoji,
        "traits": {
            "Efficiency": trait_efficiency,
            "Intensity": trait_intensity,
            "Persistence": trait_persistence,
            "Patience": trait_patience,
            "Velocity": trait_velocity,
            "Depth": trait_depth,
        },
        "fun_facts": fun_facts[:4],
    }
    # ── /Profile stats ───────────────────────────────────────────────────────

    # ── Action chips: top 3 actionable recommendations with $/impact ────────
    action_chips = []
    try:
        from cc_retrospect.analyzers import SavingsAnalyzer
        savings_result = SavingsAnalyzer().analyze(list(sessions), config)
        for rec in savings_result.recommendations[:3]:
            action_chips.append({
                "text": rec.description,
                "savings": rec.estimated_savings,
                "severity": rec.severity,
            })
    except (ImportError, ValueError, TypeError):
        pass

    # ── Session grades: A-D per session based on cost/duration/frustration ──
    def _grade_session(s):
        score = 100
        if s.total_cost > 20: score -= 30
        elif s.total_cost > 10: score -= 15
        elif s.total_cost > 5: score -= 5
        if s.duration_minutes > 120: score -= 20
        elif s.duration_minutes > 90: score -= 10
        if s.frustration_count > 3: score -= 20
        elif s.frustration_count > 1: score -= 10
        if s.subagent_count > 8: score -= 10
        if score >= 80: return "A"
        if score >= 60: return "B"
        if score >= 40: return "C"
        return "D"

    session_grades = [{"session_id": s.session_id, "grade": _grade_session(s)} for s in sessions[:50]]
    grade_streak = "".join(sg["grade"] for sg in session_grades[:10])

    # ── WoW deltas for inline badges ────────────────────────────────────────
    def _wow_delta(this_val, last_val, fmt="num"):
        delta = this_val - last_val
        pct = ((delta / last_val) * 100) if last_val else 0
        return {"value": round(this_val, 2), "delta": round(delta, 2), "delta_pct": round(pct, 1), "direction": "up" if delta > 0 else "down" if delta < 0 else "flat"}

    wow_deltas = {
        "cost": _wow_delta(this_week_cost, last_week_cost),
        "sessions": _wow_delta(this_week_sessions, last_week_sessions),
        "frustrations": _wow_delta(this_week_frust, last_week_frust),
        "avg_duration": _wow_delta(this_week_avg_dur, last_week_avg_dur),
    }

    # ── Daily model cost breakdown (for stacked chart) ──────────────────────
    daily_model_cost: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for s in sessions:
        day = (s.start_ts or "")[:10]
        if day:
            for m, c in (s.model_breakdown or {}).items():
                daily_model_cost[day][m] += c
    daily_model_cost_serializable = {day: dict(models) for day, models in sorted(daily_model_cost.items())}

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "state": state,
        "sessions": [s.model_dump() for s in sessions],
        "trends": trends,
        "compactions": compactions,
        "budget_tiers": budget_tiers,
        "days": days,
        "reports": reports,
        "tool_usage": dict(sorted(tool_usage.items(), key=lambda x: -x[1])[:20]),
        "hourly_activity": hourly_activity,
        "cost_by_day": dict(sorted(cost_by_day.items())),
        "model_recommendation": model_rec,
        "profile": profile,
        "action_chips": action_chips,
        "session_grades": session_grades,
        "grade_streak": grade_streak,
        "wow_deltas": wow_deltas,
        "daily_model_cost": daily_model_cost_serializable,
    }

    data_json = json.dumps(data, default=str)
    return data_json


def run_dashboard(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Refresh data.js, ensure server is running, open browser."""
    payload = payload or {}
    config = config or load_config()
    days = payload.get("days", 30)

    data_json = generate_dashboard(config, days=days)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    data_dir = config.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    # Write latest data.js (server serves this at /data.js)
    (data_dir / "data.js").write_text(f"const D = {data_json};\n", encoding="utf-8")

    # Write latest dashboard.html template
    (data_dir / "dashboard.html").write_text(DASHBOARD_HTML, encoding="utf-8")

    # Save timestamped snapshot
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / f"data-{stamp}.js").write_text(f"const D = {data_json};\n", encoding="utf-8")
    snap_html = reports_dir / f"dashboard-{stamp}.html"
    snap_html.write_text(
        DASHBOARD_HTML.replace('src="data.js"', f'src="data-{stamp}.js"'),
        encoding="utf-8",
    )

    # Ensure server is running (starts once, persists)
    ensure_running()

    url = f"http://127.0.0.1:{PORT}/"
    print(f"Dashboard: {url}", file=sys.stderr)
    webbrowser.open(url)
    return 0
