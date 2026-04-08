# LATER

Use this format:
- [ ] (P1) concise actionable task
- [ ] (P0) urgent production/security task
- [x] completed task

## Queue

- [x] (P0) fix default_config.env: uses PRICING__OPUS__INPUT_PER_MTOK format
- [x] (P0) delete dead cc_retrospective/ dir
- [x] (P0) fix nomenclature: mega_prompt→oversized_prompt, tool_chain→repetitive_chain, model_mismatch→opus_on_simple
- [x] (P0) add tests for run_learn, run_user_prompt, generate_style, generate_learnings, daily health, waste flags
- [x] (P0) update dispatch map tests for 24 routes / 7 hooks
- [x] (P1) add cc_retrospective/ to .gitignore
- [x] (P1) pyproject.toml optional-deps: `test` key matches README
- [x] (P1) run_report: fixed timestamp (single datetime.now() call)
- [x] (P1) add /reset command — clear sessions.jsonl, state.json, live_session.json
- [x] (P1) add /config command — show current config values, verify overrides loading
- [x] (P2) add --json flag to commands for structured output
- [x] (P2) add --project filter to scope commands to one project
- [x] (P2) add --days filter to scope commands to recent N days
- [x] (P2) test_real_data.py: --ignore in CI (skips slow tests on GitHub Actions)
- [x] (P2) trend snapshots: added _backfill_trends + `trends --backfill` command
- [x] (P2) cleanup skill: documented actual paths (subagent logs, telemetry, worktrees)
- [x] (P2) SKILL.md (analyze): added Windows path note
- [x] (P2) hybrid skills: /waste, /savings, /model, /health, /digest — Python precision + Claude reasoning layer
- [x] (P3) add py.typed marker
- [ ] (P1) delete stale ~/.cc-sentinel/ data dir (hooks now write to ~/.cc-retrospect/)
- [ ] (P2) add /uninstall command — remove hooks from settings.json
- [ ] (P2) hooks.json: verify PreCompact/PostCompact event names actually fire in Claude Code
- [ ] (P3) add GitHub release workflow (tag → build → publish)
