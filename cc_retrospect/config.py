"""cc-retrospect configuration models."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class PricingConfig(BaseModel):
    input_per_mtok: float = 5.0
    output_per_mtok: float = 25.0
    cache_create_per_mtok: float = 6.25
    cache_read_per_mtok: float = 0.50


class ModelPricing(BaseModel):
    opus: PricingConfig = PricingConfig()
    sonnet: PricingConfig = PricingConfig(input_per_mtok=3.0, output_per_mtok=15.0, cache_create_per_mtok=3.75, cache_read_per_mtok=0.30)
    haiku: PricingConfig = PricingConfig(input_per_mtok=1.0, output_per_mtok=5.0, cache_create_per_mtok=1.25, cache_read_per_mtok=0.10)


class ThresholdsConfig(BaseModel):
    long_session_minutes: int = 90
    long_session_messages: int = 150
    mega_prompt_chars: int = 1000
    mega_prompt_very_long_chars: int = 3000
    mega_prompt_newline_density: float = 0.02
    max_subagents_per_session: int = 8
    max_claudemd_bytes: int = 50_000
    tool_chain_threshold: int = 5
    daily_cost_warning: float = 400.0
    cost_tip_threshold: float = 50.0
    frustration_tip_threshold: int = 3
    compact_nudge_first: int = 30
    compact_nudge_second: int = 60
    learn_refresh_interval: int = 30
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
    waste_to_later: bool = False


class MessagesConfig(BaseModel):
    """All user-facing strings. Override any in config.env via MESSAGES__<KEY>."""
    prefix: str = "[cc-retrospect]"
    tip_long_session: str = "Tip: Start fresh more often — your last ran {duration}."
    tip_model_sonnet: str = "Tip: Consider /model sonnet (last session: {cost})."
    tip_frustration: str = "Tip: When stuck, /clear and restate — iterating grows context and cost."
    tip_subagent_overuse: str = "Tip: Use Grep/Read instead of spawning Agent for simple lookups."
    health_long_sessions: str = "Health: {count} long sessions in last 3 days (avg {avg_duration})."
    health_cost_velocity: str = "Health: Averaging {daily_cost}/day. Projected monthly: {monthly_cost}."
    health_no_data: str = "Health: No session data found — Stop hook may not be firing."
    digest_summary: str = "Yesterday: {count} sessions, {cost}, {frustrations} frustrations, {subagents} subagents, {compactions} compactions."
    digest_model_tip: str = "Model tip: {cost} spent on Opus for simple tasks — try /model sonnet."
    budget_alert: str = "Budget alert: {cost} spent today (threshold: {threshold})."
    budget_warning: str = "Budget warning: {cost} spent today (threshold: {threshold})."
    budget_critical: str = "BUDGET CRITICAL: {cost} spent today (threshold: {threshold}). Consider pausing."
    budget_severe: str = "BUDGET SEVERE: {cost} spent today (threshold: {threshold}). Strongly recommend stopping."
    hint_webfetch_github: str = "Consider using `gh` CLI instead of WebFetch for {domain} — structured output, fewer tokens."
    hint_agent_simple: str = "This looks like a simple search — try Grep or Glob directly to save a subagent spawn."
    hint_bash_chain: str = "Multiple consecutive Bash calls — consider combining with && or writing a script."
    hint_compact_first: str = "Session at {count}+ tool calls. Context is growing expensive — consider /compact or starting fresh."
    hint_compact_second: str = "⚠️ Session at {count}+ tool calls. You MUST run /compact now before continuing. Context bloat is wasting tokens on every message."
    hint_subagent_limit: str = "You've spawned {count} subagents this session. Each loads the full system context. Try Grep/Read for simple lookups."
    hint_mega_paste: str = "Large paste detected ({chars} chars). Consider writing to a temp file and referencing it — saves tokens on every future turn."
    hint_mega_long: str = "Very long prompt ({chars} chars). This inflates conversation history. Consider using a file reference."
    waste_webfetch: str = "{count} WebFetch→GitHub (use gh CLI)"
    waste_tool_chains: str = "{count} repetitive tool chains"
    waste_mega_prompts: str = "{count} oversized prompts"
    waste_dup_reads: str = "{count} duplicate read chains"
    welcome_with_data: str = "Welcome! Found {count} sessions ({cost}). Run /cc-retrospect:analyze for a full report."
    welcome_no_data: str = "Welcome! No session data yet. Hooks will start tracking automatically."


class FilterConfig(BaseModel):
    """Session filtering configuration."""
    exclude_projects: list[str] = []
    exclude_entrypoints: list[str] = ["cc-retrospect", "cc-later"]
    exclude_sessions_shorter_than: int = 0


class ProjectOverride(BaseModel):
    """Per-project threshold overrides. Fields set to None fall back to global."""
    daily_cost_warning: float | None = None
    long_session_minutes: int | None = None
    max_subagents_per_session: int | None = None


class BudgetTier(BaseModel):
    threshold: float
    message: str | None = None


class BudgetConfig(BaseModel):
    warning: BudgetTier = BudgetTier(threshold=100.0)
    critical: BudgetTier = BudgetTier(threshold=300.0)
    severe: BudgetTier = BudgetTier(threshold=500.0)


class ScriptsConfig(BaseModel):
    on_session_end: list[str] = []
    on_session_start: list[str] = []
    on_budget_alert: list[str] = []
    on_waste_detected: list[str] = []
    on_compaction: list[str] = []
    timeout_seconds: int = 5


class StyleConfig(BaseModel):
    enabled_rules: list[str] = ["core_style", "corrections", "approvals", "mega_paste", "frustration", "compression"]
    custom_rules: list[str] = []
    correction_threshold: int = 10
    frustration_threshold: float = 3.0
    mega_pct_threshold: float = 10.0
    template_path: str | None = None


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
    filter: FilterConfig = FilterConfig()
    budget: BudgetConfig = BudgetConfig()
    scripts: ScriptsConfig = ScriptsConfig()
    style: StyleConfig = StyleConfig()
    project_overrides: dict[str, ProjectOverride] = {}
    data_dir: Path = Path.home() / ".cc-retrospect"
    claude_dir: Path = Path.home() / ".claude"

    def get_threshold(self, project: str, field: str):
        """Return project-specific override if set, else global threshold."""
        normalized = project.lower().replace("-", "_")
        for key, override in self.project_overrides.items():
            if key.lower().replace("-", "_") in normalized:
                val = getattr(override, field, None)
                if val is not None:
                    return val
        return getattr(self.thresholds, field)


def load_config(config_path: Path | None = None) -> Config:
    """Load config from optional path, or from default ~/.cc-retrospect/config.env."""
    if config_path and Path(config_path).exists():
        return Config(_env_file=str(config_path))
    # Let pydantic use the default env_file from model_config
    return Config()


def default_config() -> Config:
    return Config(_env_file=None)
