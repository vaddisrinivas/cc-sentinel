"""cc-retrospect utils — Display formatting, filtering, and rendering helpers."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from cc_retrospect.config import Config
from cc_retrospect.models import SessionSummary

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


def _group(sessions: list[SessionSummary], key_fn, val_fn=lambda s: s.total_cost) -> dict:
    out: dict = {}
    for s in sessions:
        key = key_fn(s)
        if key not in out:
            out[key] = 0
        out[key] += val_fn(s)
    return out


def _top(d: dict, n: int = 10) -> list:
    return sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]


def _union(sessions: list[SessionSummary], fn) -> Counter:
    c: Counter = Counter()
    for s in sessions: c.update(fn(s))
    return c


def _filter_sessions(sessions: list[SessionSummary], project: str | None = None, days: int | None = None, config: Config | None = None) -> list[SessionSummary]:
    """Filter sessions by project name, recent N days, and config exclusion rules."""
    if project:
        sessions = [s for s in sessions if project.lower() in display_project(s.project).lower()]
    if days and days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        sessions = [s for s in sessions if s.start_ts and s.start_ts >= cutoff]
    if config and config.filter:
        # Exclude by project patterns
        for pat in config.filter.exclude_projects:
            sessions = [s for s in sessions if pat.lower() not in display_project(s.project).lower()]
        # Exclude by entrypoint
        for ep in config.filter.exclude_entrypoints:
            sessions = [s for s in sessions if ep.lower() not in (s.entrypoint or "").lower()]
        # Exclude by minimum duration
        if config.filter.exclude_sessions_shorter_than > 0:
            sessions = [s for s in sessions if s.duration_minutes >= config.filter.exclude_sessions_shorter_than]
    return sessions


def _render(analyzer_cls, payload: dict = {}, *, config: Config | None = None, sessions=None) -> int:
    from cc_retrospect.config import load_config
    from cc_retrospect.cache import load_all_sessions

    cfg = config or load_config()
    ss = sessions if sessions is not None else load_all_sessions(cfg)
    ss = _filter_sessions(ss, project=payload.get("project"), days=payload.get("days"), config=cfg)
    result = analyzer_cls().analyze(ss, cfg)
    if payload.get("json"):
        print(result.render_json())
    else:
        print(result.render_markdown())
    return 0
