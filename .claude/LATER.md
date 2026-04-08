# LATER

Use this format:
- [ ] (P1) concise actionable task
- [ ] (P0) urgent production/security task
- [x] completed task

## Queue

- [x] (P0) fix default_config.env: already correct — uses PRICING__OPUS__INPUT_PER_MTOK format
- [x] (P0) delete dead cc_retrospective/ dir
- [x] (P0) fix nomenclature: mega_prompt→oversized_prompt, tool_chain→repetitive_chain, model_mismatch→opus_on_simple in display strings, tests, skills
- [x] (P0) add tests for run_learn, run_user_prompt, generate_style, generate_learnings, daily health, waste flags
- [x] (P0) update dispatch map tests for 22 routes / 7 hooks
- [x] (P1) add cc_retrospective/ to .gitignore
- [ ] (P1) delete stale ~/.cc-sentinel/ data dir (hooks now write to ~/.cc-retrospect/)
- [ ] (P1) pyproject.toml optional-deps: rename `test` to match README (`uv pip install -e ".[test]"`)
- [ ] (P1) run_report: filename uses datetime.now() twice — could produce inconsistent timestamps
- [ ] (P1) add /reset command — clear sessions.jsonl, state.json, live_session.json
- [ ] (P1) add /config command — show current config values, verify overrides loading
- [ ] (P2) add --json flag to commands for structured output
- [ ] (P2) add --project filter to scope commands to one project
- [ ] (P2) add --days filter to scope commands to recent N days
- [ ] (P2) add /uninstall command — remove hooks from settings.json
- [ ] (P2) test_real_data.py: slow (2+ min) — add pytest marker `@pytest.mark.slow` and skip by default in CI
- [ ] (P2) trend snapshots: add /cc-retrospect:trends --backfill to seed from historical data
- [ ] (P2) cleanup skill: document actual paths to scan (subagent logs, telemetry, worktrees)
- [ ] (P2) SKILL.md (analyze): shell fallback won't work on Windows
- [ ] (P2) hooks.json: verify PreCompact/PostCompact event names actually fire in Claude Code
- [ ] (P3) add py.typed marker for downstream type checking
- [ ] (P3) add GitHub release workflow (tag → build → publish)
