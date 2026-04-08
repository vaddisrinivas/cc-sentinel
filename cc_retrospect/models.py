"""cc-retrospect models — Pydantic data structures for sessions and analysis results."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


# --- Usage extraction ---

class UsageRecord(BaseModel):
    timestamp: str = ""; session_id: str = ""; project: str = ""; model: str = "unknown"
    input_tokens: int = 0; output_tokens: int = 0
    cache_creation_tokens: int = 0; cache_read_tokens: int = 0
    entrypoint: str = ""; cwd: str = ""; git_branch: str = ""


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


# --- Analyzer protocol ---

@runtime_checkable
class Analyzer(Protocol):
    name: str
    description: str
    def analyze(self, sessions: list[SessionSummary], config) -> AnalysisResult: ...


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


# --- User profile ---

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
