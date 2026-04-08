"""cc-retrospect commands — CLI entry points for all /commands."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cc_retrospect.config import Config, load_config
from cc_retrospect.models import SessionSummary
from cc_retrospect.cache import load_all_sessions, _load_live_state, _save_live_state
from cc_retrospect.analyzers import get_analyzers, CostAnalyzer, HabitsAnalyzer, HealthAnalyzer, TipsAnalyzer, WasteAnalyzer, CompareAnalyzer, SavingsAnalyzer, ModelAnalyzer, TrendAnalyzer
from cc_retrospect.utils import _render, _fmt_cost, _fmt_tokens, _fmt_duration, display_project, _filter_sessions


def _get_confirmation(prompt: str) -> bool:
    """Request 'y' confirmation from TTY. Return True if TTY and user confirms, else True (non-TTY)."""
    if not sys.stdin.isatty():
        return True
    try:
        response = input(f"{prompt} [y/N]: ").strip().lower()
        return response == 'y'
    except (EOFError, KeyboardInterrupt):
        return False


def _print_progress(count: int, label: str = "items", threshold: int = 50) -> None:
    """Print progress message every `threshold` items."""
    if count % threshold == 0 and count > 0:
        print(f"Scanning... {count} {label}", file=sys.stderr)


def run_cost(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(CostAnalyzer, payload, config=config)


def run_habits(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(HabitsAnalyzer, payload, config=config)


def run_health(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(HealthAnalyzer, payload, config=config)


def run_tips(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(TipsAnalyzer, payload, config=config)


def run_waste(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(WasteAnalyzer, payload, config=config)


def run_compare(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(CompareAnalyzer, payload, config=config)


def run_report(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    config = config or load_config()
    sessions = load_all_sessions(config)
    sessions = _filter_sessions(sessions, project=payload.get("project"), days=payload.get("days"), config=config)
    now = datetime.now(timezone.utc)
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


def run_savings(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(SavingsAnalyzer, payload, config=config)


def run_model_efficiency(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
    return _render(ModelAnalyzer, payload, config=config)


def run_digest(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Daily digest: yesterday's sessions analyzed with savings + model efficiency."""
    from cc_retrospect.hooks import _load_compactions

    payload = payload or {}
    config = config or load_config()
    sessions = load_all_sessions(config)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    day_sessions = [s for s in sessions if s.start_ts and s.start_ts[:10] == yesterday]
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


def run_hints(payload: dict | None = None, *, config: Config | None = None) -> int:
    payload = payload or {}
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


def run_status(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Plugin health check — verify install, hooks, data, deps."""
    from cc_retrospect.parsers import iter_jsonl

    payload = payload or {}
    config = config or load_config()
    lines = ["## cc-retrospect Status", ""]
    # Data dir
    data_exists = config.data_dir.exists()
    lines.append(f"Data directory: {config.data_dir} ({'exists' if data_exists else 'MISSING'})")
    # Session count
    cache_path = config.data_dir / "sessions.jsonl"
    session_count = 0
    if cache_path.exists():
        for _ in iter_jsonl(cache_path):
            session_count += 1
            _print_progress(session_count, "sessions")
    if session_count == 0:
        lines.append(f"Cached sessions: No sessions yet")
    else:
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
            last_ts = state.get('last_ts', 'unknown')
            if last_ts != 'unknown':
                last_ts = last_ts[:16]
            lines.append(f"Last session: {last_ts} ({display_project(state.get('last_project', '?'))})")
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


def run_export(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Export all session data as JSON to stdout."""
    payload = payload or {}
    config = config or load_config()
    sessions = load_all_sessions(config)
    print(json.dumps([s.model_dump() for s in sessions], default=str))
    return 0


def run_trends(payload: dict | None = None, *, config: Config | None = None) -> int:
    from cc_retrospect.hooks import _backfill_trends

    payload = payload or {}
    if payload.get("backfill"):
        config = config or load_config()
        _backfill_trends(config)
        return 0
    return _render(TrendAnalyzer, payload, config=config)


def run_reset(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Clear all cached data files. Sessions are re-scanned on next command."""
    payload = payload or {}
    config = config or load_config()
    cleared = []
    files_to_clear = ("sessions.jsonl", "state.json", "live_session.json", "compactions.jsonl", "trends.jsonl")

    # Print what will be deleted
    existing = [name for name in files_to_clear if (config.data_dir / name).exists()]
    if existing:
        print(f"[cc-retrospect] Will delete: {', '.join(existing)}")
        if not _get_confirmation("Confirm deletion"):
            print("[cc-retrospect] Reset cancelled.")
            return 0

    for name in files_to_clear:
        path = config.data_dir / name
        if path.exists():
            path.unlink()
            cleared.append(name)
    if cleared:
        print(f"[cc-retrospect] Cleared: {', '.join(cleared)}")
    else:
        print("[cc-retrospect] Nothing to clear.")
    return 0


def run_config(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Show current config values (defaults + overrides from config.env)."""
    payload = payload or {}
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


def run_uninstall(payload: dict | None = None, *, config: Config | None = None) -> int:
    """Remove cc-retrospect hooks and plugin registration from settings.json."""
    payload = payload or {}
    config = config or load_config()
    settings_path = config.claude_dir / "settings.json"
    if not settings_path.exists():
        print("[cc-retrospect] No settings.json found.")
        return 0
    try:
        settings = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[cc-retrospect] Could not read settings.json: {e}")
        return 1
    changed = False
    # Remove hooks referencing cc-retrospect
    hooks = settings.get("hooks", {})
    for event in list(hooks.keys()):
        handlers = hooks[event]
        filtered = []
        for handler in handlers:
            hook_list = handler.get("hooks", [])
            clean = [h for h in hook_list if "cc-retrospect" not in h.get("command", "") and "dispatch.py" not in h.get("command", "")]
            if clean:
                handler["hooks"] = clean
                filtered.append(handler)
            elif clean != hook_list:
                changed = True
        if filtered != handlers:
            changed = True
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]
            changed = True
    # Remove plugin registration
    plugins = settings.get("enabledPlugins", {})
    for key in list(plugins.keys()):
        if "cc-retrospect" in key or "cc-sentinel" in key:
            del plugins[key]
            changed = True
    marketplaces = settings.get("extraKnownMarketplaces", [])
    filtered_mp = [m for m in marketplaces if "cc-retrospect" not in str(m) and "cc-sentinel" not in str(m)]
    if len(filtered_mp) != len(marketplaces):
        settings["extraKnownMarketplaces"] = filtered_mp
        changed = True
    if changed:
        settings_path.write_text(json.dumps(settings, indent=2))
        print("[cc-retrospect] Removed hooks and plugin from settings.json.")
    else:
        print("[cc-retrospect] No cc-retrospect entries found in settings.json.")
    return 0
