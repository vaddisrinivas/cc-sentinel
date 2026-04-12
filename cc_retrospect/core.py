"""cc-retrospect core — backward compatibility shim.

All functionality has been moved to submodules for better organization.
This file re-exports everything to maintain compatibility with existing code.
"""
from __future__ import annotations

import logging
import os
import sys

# Logger setup (same as original)
logger = logging.getLogger("cc_retrospect")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[cc-retrospect] %(levelname)s %(message)s"))
    logger.addHandler(_h)
logger.setLevel(getattr(logging, os.environ.get("CC_RETROSPECT_LOG_LEVEL", "WARNING").upper(), logging.WARNING))

# Re-export all public APIs from submodules
from cc_retrospect.config import (
    Config, PricingConfig, ModelPricing, ThresholdsConfig,
    HintsConfig, MessagesConfig, FilterConfig,
    ProjectOverride, BudgetTier, BudgetConfig, ScriptsConfig, StyleConfig,  # noqa: F401
    load_config, default_config,
)

from cc_retrospect.models import (
    UsageRecord, SessionSummary, ToolCall, Section, Recommendation, AnalysisResult,
    CompactionEvent, LiveSessionState, UserProfile, Analyzer,
)

from cc_retrospect.parsers import (
    iter_jsonl, iter_project_sessions, extract_usage,
    compute_cost, analyze_session,
)

from cc_retrospect.utils import (
    display_project, _fmt_tokens, _fmt_cost, _fmt_duration,
    _group, _top, _union, _filter_sessions, _render,
)

from cc_retrospect.cache import (
    load_all_sessions, _atomic_write_json, _is_valid_session_id,
    _init_live_state, _load_live_state, _save_live_state, _live_state_path,
)

from cc_retrospect.analyzers import (
    CostAnalyzer, WasteAnalyzer, HealthAnalyzer, HabitsAnalyzer,
    TipsAnalyzer, CompareAnalyzer, SavingsAnalyzer, ModelAnalyzer,
    TrendAnalyzer, get_analyzers,
)

from cc_retrospect.commands import (
    run_cost, run_habits, run_health, run_tips, run_waste, run_compare,
    run_report, run_savings, run_model_efficiency, run_digest, run_hints,
    run_status, run_export, run_trends, run_reset, run_config, run_uninstall, run_all, run_dashboard,
    run_chains, run_toolcalls,
)

from cc_retrospect.hooks import (
    run_stop_hook, run_session_start_hook,
    run_pre_tool_use, run_post_tool_use,
    run_user_prompt, run_pre_compact, run_post_compact,
    _update_trends, _should_show_daily_digest, _backfill_trends,
)

from cc_retrospect.learn import (
    analyze_user_messages, generate_style, generate_learnings, run_learn,
)

__all__ = [
    # Config
    'Config', 'load_config', 'default_config',
    'PricingConfig', 'ModelPricing', 'ThresholdsConfig',
    'HintsConfig', 'MessagesConfig', 'FilterConfig',
    # Models
    'UsageRecord', 'SessionSummary', 'ToolCall', 'Section', 'Recommendation', 'AnalysisResult',
    'CompactionEvent', 'LiveSessionState', 'UserProfile', 'Analyzer',
    # Parsers
    'iter_jsonl', 'iter_project_sessions', 'extract_usage',
    'analyze_session', 'compute_cost',
    # Utils
    'display_project', '_fmt_cost', '_fmt_tokens', '_fmt_duration',
    '_filter_sessions', '_render', '_group', '_top', '_union',
    # Cache
    'load_all_sessions', '_atomic_write_json', '_is_valid_session_id',
    '_init_live_state', '_load_live_state', '_save_live_state', '_live_state_path',
    # Analyzers
    'CostAnalyzer', 'WasteAnalyzer', 'HealthAnalyzer', 'HabitsAnalyzer',
    'TipsAnalyzer', 'CompareAnalyzer', 'SavingsAnalyzer', 'ModelAnalyzer',
    'TrendAnalyzer', 'get_analyzers',
    # Commands
    'run_cost', 'run_habits', 'run_health', 'run_tips', 'run_waste', 'run_compare',
    'run_report', 'run_savings', 'run_model_efficiency', 'run_digest', 'run_hints',
    'run_status', 'run_export', 'run_trends', 'run_reset', 'run_config', 'run_uninstall', 'run_all', 'run_dashboard',
    'run_chains', 'run_toolcalls',
    # Hooks
    'run_stop_hook', 'run_session_start_hook',
    'run_pre_tool_use', 'run_post_tool_use',
    'run_user_prompt', 'run_pre_compact', 'run_post_compact',
    '_update_trends', '_should_show_daily_digest', '_backfill_trends',
    # Learn
    'analyze_user_messages', 'generate_style', 'generate_learnings', 'run_learn',
    # Logger
    'logger',
]
