# cc-retrospect

**Stop burning tokens you can't see.**

Claude Code doesn't show you what you're spending. No cost dashboard, no warning when a session hits 300 messages, no signal that you used Opus for a task Sonnet could handle. cc-retrospect fixes that — real-time interception, automatic tracking, and on-demand analysis.

## Install

### From GitHub (recommended)

```bash
git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect
~/.claude/plugins/cc-retrospect/install.sh
```

The installer detects `uv`/`pip`, installs dependencies, verifies the plugin, and optionally backfills trend data from your existing sessions.

### Manual

```bash
git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect
cd ~/.claude/plugins/cc-retrospect && uv pip install -e .  # or pip install -e .
```

Hooks are auto-discovered by Claude Code from the plugin.

## What it does

**Automatic** — hooks fire silently on every session:
- Warns before wasteful tool calls (WebFetch→GitHub, Agent for simple searches, Bash chains)
- Nudges `/compact` at 150+ tool calls
- Tracks session cost, compaction events, daily spend
- Shows last-session recap + daily digest on session start

**On demand** — 17 slash commands for cost breakdowns, waste detection, model efficiency, savings projections, trends, and more.

**Behavioral** — 3 skills where Claude reasons about your patterns: full retrospective, communication profiling (generates STYLE.md), and disk cleanup.

## Quick start

After install, just use Claude Code normally. Hooks work silently. When you want data:

```
/cc-retrospect:cost          — where's my money going?
/cc-retrospect:savings       — how much can I save and how?
/cc-retrospect:model         — am I using the right model?
/cc-retrospect:analyze       — full retrospective (Claude reasons about everything)
```

## Documentation

- [Commands & Skills](docs/commands.md) — all 17 commands and 3 skills
- [Configuration](docs/configuration.md) — pricing, thresholds, hints, custom analyzers
- [Architecture](docs/architecture.md) — how it works, hook flow, data sources
- [Development](docs/development.md) — running tests, contributing

## Data

Reads `~/.claude/projects/` — the same JSONL files Claude Code writes. No network calls, no telemetry. Cache at `~/.cc-retrospect/sessions.jsonl`.
