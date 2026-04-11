# Graph Report - .  (2026-04-10)

## Corpus Check
- 24 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 722 nodes · 1177 edges · 25 communities detected
- Extraction: 61% EXTRACTED · 39% INFERRED · 0% AMBIGUOUS · INFERRED: 460 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `Config` - 51 edges
2. `cc-retrospect core — backward compatibility shim.  All functionality has been mo` - 31 edges
3. `SessionSummary` - 28 edges
4. `_make_summary()` - 21 edges
5. `CostAnalyzer` - 19 edges
6. `WasteAnalyzer` - 19 edges
7. `HabitsAnalyzer` - 19 edges
8. `HealthAnalyzer` - 19 edges
9. `TipsAnalyzer` - 19 edges
10. `CompareAnalyzer` - 19 edges

## Surprising Connections (you probably didn't know these)
- `Generate and serve a dashboard from cc-retrospect data.` --uses--> `Config`  [INFERRED]
  cc_retrospect/dashboard.py → cc_retrospect/config.py
- `Generate dashboard JSON string with embedded data.` --uses--> `Config`  [INFERRED]
  cc_retrospect/dashboard.py → cc_retrospect/config.py
- `Build dashboard data JSON string.` --uses--> `Config`  [INFERRED]
  cc_retrospect/dashboard.py → cc_retrospect/config.py
- `Refresh data.js, ensure server is running, open browser.` --uses--> `Config`  [INFERRED]
  cc_retrospect/dashboard.py → cc_retrospect/config.py
- `cc-retrospect core — backward compatibility shim.  All functionality has been mo` --uses--> `CostAnalyzer`  [INFERRED]
  cc_retrospect/core.py → cc_retrospect/analyzers.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.03
Nodes (26): config(), _make_summary(), Tests for new features: savings, model efficiency, trends, status, export, diges, TestBudgetAlert, TestCommandFlags, TestCompactionHooks, TestDailyDigest, TestDailyHealthCheck (+18 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (27): Tests targeting 100% coverage of cc_retrospect/core.py.  Each class targets a sp, urlparse failure in analyze_session is swallowed., urlparse failure in pre_tool_use is swallowed., When session_key matches cache, it uses cached summary instead of re-reading., A stray file inside the claude projects dir is skipped (non-dir continue)., Report parsing stops after 2 waste tips (line 1344 break)., Report parsing stops when a new markdown section starts (line 1346 break)., OSError reading a report file is swallowed (line 1349-1350).         Make the re (+19 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (50): CompareAnalyzer, CostAnalyzer, HabitsAnalyzer, HealthAnalyzer, ModelAnalyzer, cc-retrospect analyzers — Built-in analysis implementations., SavingsAnalyzer, TipsAnalyzer (+42 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (32): _build_claude_dir(), _minimal_assistant(), End-to-end integration tests for cc-retrospect.  These tests exercise full pipel, load_all_sessions should build a cache and re-use it on subsequent calls., Cost and health analyzers should handle multiple projects correctly., Return a simulated ~/.claude directory under *base*., run_report should write a markdown file and include all analyzer sections., Write a JSONL session file and return its path. (+24 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (41): BaseModel, BudgetConfig, BudgetTier, default_config(), FilterConfig, HintsConfig, load_config(), MessagesConfig (+33 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (17): _make_summary(), Tests for waste detectors, health checks, and analyzers., Create a minimal SessionSummary with overrides., Behavioral pattern analysis., Cost analysis and what-if scenarios., What-if should show savings if using Sonnet., All analyzers must follow the protocol., AnalysisResult should render as text, markdown, and JSON. (+9 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (13): _make_summary(), Session with no opus cost in model_breakdown skips mismatch check., Sessions with no start_ts don't produce a daily cost row., Opus session with Agent/WebSearch should NOT get mismatch warning., Opus session under $50 cost doesn't trigger mismatch., <= 5 oversized prompts produces no recommendation., Sessions in this week and last week., TestCompareAnalyzerFull (+5 more)

### Community 7 - "Community 7"
Cohesion: 0.1
Nodes (8): config(), Corrupt JSON in live_session.json returns default state., OSError writing live state doesn't raise., All run_X commands call load_config + load_all_sessions and print output., TestCommandEntrypoints, TestLiveStateFallbacks, TestLoadAllSessions, TestRunStopHook

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (12): Integration tests against REAL local session data.  These tests use ~/.claude/pr, Cross-validate analyzer outputs against each other., Total cost from CostAnalyzer should match sum of exported sessions., Model efficiency score should be between 0 and 100., Monthly savings projection shouldn't exceed monthly cost projection., WebFetch waste count should match sum using the configured waste domains., Verify session loading against actual ~/.claude/projects/., All analyzers should see the same session count. (+4 more)

### Community 9 - "Community 9"
Cohesion: 0.12
Nodes (18): BaseHTTPRequestHandler, ensure_running(), _Handler, is_running(), _list_reports(), _mime(), pid_file(), Persistent localhost dashboard server for cc-retrospect.  Runs on 127.0.0.1:7731 (+10 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (9): Tests for JSONL parsing, token extraction, and cost calculation., Cost calculation at known API rates, verified to the penny., Streaming JSONL parser must handle real-world edge cases., Project name cleaning for display., Usage extraction from assistant messages., TestComputeCost, TestDisplayProject, TestExtractUsage (+1 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (11): Tests for proactive features: PreToolUse, PostToolUse, enhanced SessionStart., SessionStart should inject last-session summary + tips., Create a temporary data dir for cc-retrospect state., The single dispatch.py should route all commands., PreToolUse hook should intercept waste in real-time., PostToolUse hook should track session health and nudge compact., TestDispatcher, TestEnhancedSessionStart (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.1
Nodes (6): Tests for SessionSummary extraction from JSONL files., Parser should not crash on malformed JSONL., SessionSummary should be serializable to/from JSON for sessions.jsonl caching., Full session analysis from a JSONL file., TestAnalyzeSession, TestSessionSummarySerialize

### Community 13 - "Community 13"
Cohesion: 0.22
Nodes (2): Run dispatch commands as subprocesses and verify they don't crash., TestRealDispatchCommands

### Community 14 - "Community 14"
Cohesion: 0.21
Nodes (9): _atomic_write_json(), _init_live_state(), _is_valid_session_id(), _live_state_path(), _load_live_state(), cc-retrospect cache — Session cache management and live state., Validate session ID format., _save_live_state() (+1 more)

### Community 15 - "Community 15"
Cohesion: 0.25
Nodes (11): _backfill_trends(), _compactions_path(), _load_compactions(), _run_custom_scripts(), run_post_compact(), run_pre_compact(), run_session_start_hook(), run_stop_hook() (+3 more)

### Community 16 - "Community 16"
Cohesion: 0.29
Nodes (9): _build_dashboard_data(), generate_dashboard(), _load_json(), _load_jsonl(), Generate and serve a dashboard from cc-retrospect data., Refresh data.js, ensure server is running, open browser., Generate dashboard JSON string with embedded data., Build dashboard data JSON string. (+1 more)

### Community 17 - "Community 17"
Cohesion: 0.24
Nodes (3): display_project(), _filter_sessions(), _render()

### Community 18 - "Community 18"
Cohesion: 0.25
Nodes (2): Verify that the new fixture files are analyzed correctly., TestFixtureBasedAnalysis

### Community 19 - "Community 19"
Cohesion: 0.29
Nodes (4): User message content as list of blocks (not plain string)., Tool chain at end of session (not followed by different tool) is recorded., Malformed timestamps don't crash — duration stays 0., TestAnalyzeSessionEdgeCases

### Community 20 - "Community 20"
Cohesion: 0.43
Nodes (2): Analyzers dropped in data_dir/analyzers/*.py should be auto-discovered., TestCustomAnalyzerDiscovery

### Community 21 - "Community 21"
Cohesion: 0.43
Nodes (2): All three render formats should produce consistent, valid output., TestRenderFormats

### Community 22 - "Community 22"
Cohesion: 0.33
Nodes (0): 

### Community 23 - "Community 23"
Cohesion: 0.6
Nodes (4): main(), _parse_cli_flags(), Parse --json, --project NAME, --days N, --backfill, --exclude, --verbose from sy, _read_payload()

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (1): cc-retrospect — Claude Code session analysis plugin.

## Knowledge Gaps
- **93 isolated node(s):** `cc-retrospect — Claude Code session analysis plugin.`, `cc-retrospect configuration models.`, `All user-facing strings. Override any in config.env via MESSAGES__<KEY>.`, `Session filtering configuration.`, `Per-project threshold overrides. Fields set to None fall back to global.` (+88 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 24`** (2 nodes): `__init__.py`, `cc-retrospect — Claude Code session analysis plugin.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Config` connect `Community 2` to `Community 16`, `Community 4`, `Community 14`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `cc-retrospect core — backward compatibility shim.  All functionality has been mo` connect `Community 4` to `Community 2`, `Community 14`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **Why does `SessionSummary` connect `Community 2` to `Community 4`, `Community 14`?**
  _High betweenness centrality (0.008) - this node is a cross-community bridge._
- **Are the 48 inferred relationships involving `Config` (e.g. with `load_config()` and `default_config()`) actually correct?**
  _`Config` has 48 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `cc-retrospect core — backward compatibility shim.  All functionality has been mo` (e.g. with `Config` and `PricingConfig`) actually correct?**
  _`cc-retrospect core — backward compatibility shim.  All functionality has been mo` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `SessionSummary` (e.g. with `CostAnalyzer` and `WasteAnalyzer`) actually correct?**
  _`SessionSummary` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `_make_summary()` (e.g. with `.test_bad_timestamp_skipped()` and `.test_frustration_section_shown()`) actually correct?**
  _`_make_summary()` has 20 INFERRED edges - model-reasoned connections that need verification._