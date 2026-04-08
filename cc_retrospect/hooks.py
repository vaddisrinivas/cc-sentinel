"""cc-retrospect hooks — All hook entry points and helper functions."""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from cc_retrospect.cache import _atomic_write_json, _init_live_state, _load_live_state, _save_live_state, load_all_sessions
from cc_retrospect.config import Config, load_config
from cc_retrospect.models import SessionSummary
from cc_retrospect.parsers import iter_jsonl, analyze_session, iter_project_sessions
from cc_retrospect.utils import _fmt_cost, _fmt_duration, _fmt_tokens, display_project
from cc_retrospect.learn import analyze_user_messages, generate_style, generate_learnings

logger = logging.getLogger("cc_retrospect")


def _is_valid_session_id(session_id: str) -> bool:
    """Validate session ID format."""
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', session_id))


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


def _should_show_daily_digest(config: Config) -> bool:
    """True if this is the first session of a new day."""
    state_path = config.data_dir / "state.json"
    if not state_path.exists(): return False
    try: state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError): return False
    last_ts = state.get("last_ts", "")
    if not last_ts: return False
    try:
        last_date = datetime.fromisoformat(last_ts.replace("Z", "+00:00")).date()
        return last_date < datetime.now(timezone.utc).date()
    except (ValueError, TypeError): return False


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
    if not _is_valid_session_id(session_id):
        logger.warning("Invalid session ID format: %s", session_id)
        return 0
    projects_dir = config.claude_dir / "projects"
    jsonl_path = next(
        (pdir / f"{session_id}.jsonl" for pdir in projects_dir.iterdir()
         if pdir.is_dir() and (pdir / f"{session_id}.jsonl").exists()), None
    )
    if not jsonl_path: return 0
    summary = analyze_session(jsonl_path, jsonl_path.parent.name, config)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    # Check if session already in cache before appending
    cache_path = config.data_dir / "sessions.jsonl"
    existing_ids = set()
    if cache_path.exists():
        try:
            for entry in iter_jsonl(cache_path):
                s = SessionSummary.model_validate(entry)
                existing_ids.add(s.session_id)
        except Exception as e:
            logger.debug("Failed to read existing cache entries: %s", e)
    if summary.session_id not in existing_ids:
        with open(cache_path, "a", encoding="utf-8") as f:
            f.write(summary.model_dump_json() + "\n")
    state_path = config.data_dir / "state.json"
    state = {}
    if state_path.exists():
        try: state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e: logger.debug("Failed to parse state.json: %s", e)
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
    try:
        _atomic_write_json(state_path, state)
    except Exception as e:
        logger.debug("Failed to write state.json: %s", e)
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

    # Write model recommendation JSON
    try:
        recommendation = {
            "recommended_model": "sonnet" if summary.total_cost > 5 else "haiku",
            "reason": "Based on session cost and complexity",
            "confidence": 0.75,
            "session_id": summary.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        rec_path = config.data_dir / "model_recommendation.json"
        _atomic_write_json(rec_path, recommendation)
    except Exception as e:
        logger.debug("Failed to write model recommendation: %s", e)

    # Write waste entries to LATER.md if enabled
    if config.hints.waste_to_later and waste_flags:
        try:
            later_path = config.claude_dir / "LATER.md"
            later_content = ""
            if later_path.exists():
                later_content = later_path.read_text(encoding="utf-8")
            timestamp = datetime.now(timezone.utc).isoformat()[:16]
            waste_entry = f"- [{timestamp}] cc-retrospect: {', '.join(waste_flags)} [cc-retrospect auto]\n"
            later_content += waste_entry
            later_path.write_text(later_content, encoding="utf-8")
        except Exception as e:
            logger.debug("Failed to write to LATER.md: %s", e)

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
    if state.get("today_cost", 0) > config.thresholds.daily_cost_warning:
        print(f"{config.messages.prefix} {config.messages.budget_alert.format(cost=_fmt_cost(state.get('today_cost', 0)), threshold=_fmt_cost(config.thresholds.daily_cost_warning))}", file=sys.stderr)
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
            state = {"first_run": datetime.now(timezone.utc).isoformat()}
            try:
                _atomic_write_json(state_path, state)
            except Exception as e:
                logger.debug("Failed to write initial state: %s", e)
        except Exception as e:
            logger.debug("First-run onboarding failed: %s", e)
        _init_live_state(config)
        return 0
    if not state_path.exists(): return 0
    try: state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e: logger.debug("Failed to read state.json: %s", e); return 0
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
                for line in reports[0].read_text(encoding="utf-8").splitlines():
                    if "Waste" in line and line.startswith("#"): in_waste = True
                    elif in_waste and line.startswith("#"): break
                    elif in_waste and line.strip().startswith(("- **[!]**", "- [~]", "- [i]")):
                        waste_tips.append(line.strip().lstrip("- ").lstrip("*[]!~i* "))
                        if len(waste_tips) >= 2: break
                if waste_tips: lines.append("Top waste: " + "; ".join(waste_tips))
            except OSError as e: logger.debug("Failed to read waste tips: %s", e)
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
            try:
                _atomic_write_json(state_path, state)
            except Exception as e:
                logger.debug("Failed to write state after health check: %s", e)
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
