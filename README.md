# cc-retrospect

[![CI](https://github.com/vaddisrinivas/cc-retrospect/workflows/CI/badge.svg)](https://github.com/vaddisrinivas/cc-retrospect/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

**Stop burning tokens you can't see.**

Claude Code doesn't show what you're spending. No cost dashboard, no warning at 300 tool calls, no signal you used Opus for a task Sonnet could handle. cc-retrospect fixes that.

## Install

### Plugin marketplace (recommended)

```
/install-plugin vaddisrinivas/cc-retrospect
```

### One-liner

```bash
git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect && ~/.claude/plugins/cc-retrospect/install.sh
```

### Manual

```bash
git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect
cd ~/.claude/plugins/cc-retrospect
pip install -e .
```

Hooks are auto-discovered by Claude Code from the plugin directory.

---

## How it works

### Hooks (automatic, silent)

Hooks fire on every session with zero setup:

| Hook | Trigger | What it does |
|------|---------|-------------|
| **Session end** | Session closes | Cache cost/tokens/tools, track daily spend, log waste flags, update trends |
| **Session start** | Session opens | Show last-session recap, daily digest, tips if thresholds exceeded |
| **Pre-tool** | Before WebFetch/Agent/Bash | Warn on GitHub WebFetch (use `gh`), Agent for simple searches (use Grep), long Bash chains |
| **Post-tool** | After any tool | Nudge `/compact` at 150+ and 300+ tool calls, warn on subagent overuse |
| **User prompt** | Before prompt submit | Detect mega-pastes (>1000 chars) and very long prompts |
| **Compaction** | Before/after compact | Log compaction events with token counts |

### Commands (quick data, no AI reasoning)

```
/cc-retrospect:cost        Cost breakdown by project, model, time period
/cc-retrospect:status      Plugin health check — verify install, hooks, data
/cc-retrospect:config      Show current config values and overrides
/cc-retrospect:reset       Clear cached data, force full re-scan
/cc-retrospect:uninstall   Remove hooks from settings.json
```

All commands support `--json`, `--project NAME`, and `--days N` flags.

### Analysis skill (AI-powered insights)

One skill for everything. Claude runs the analyzers, then interprets your data:

```
/cc-retrospect              Full retrospective — cost + waste + health + habits + savings + model
/cc-retrospect waste        Deep waste analysis with project-specific explanations
/cc-retrospect health       Health deep-dive — session discipline, frustration patterns
/cc-retrospect savings      Prioritized savings recommendations with dollar amounts
/cc-retrospect model        Model efficiency — which projects should use Sonnet vs Opus
/cc-retrospect digest       Morning briefing — yesterday's numbers vs baseline
/cc-retrospect habits       Usage patterns — session lengths, peak hours, tools
/cc-retrospect compare      This week vs last week
/cc-retrospect trends       Weekly trend tracking over time
/cc-retrospect tips         1-3 actionable tips from recent patterns
/cc-retrospect report       Full markdown report saved to disk
/cc-retrospect learn        Generate STYLE.md + LEARNINGS.md from your history
/cc-retrospect profile      Behavioral profile with communication style analysis
/cc-retrospect cleanup      Find and clean disk waste from Claude Code sessions
/cc-retrospect export       JSON export of all session data
/cc-retrospect hints        Show/configure which inline hints are active
```

---

## Configuration

Override defaults in `~/.cc-retrospect/config.env`:

```env
# Pricing ($/MTok) — auto-detected for claude-opus-4-6, sonnet-4-6, haiku-4-5
PRICING__OPUS__INPUT_PER_MTOK=15.0
PRICING__SONNET__INPUT_PER_MTOK=3.0

# Thresholds
THRESHOLDS__DAILY_COST_WARNING=500.0
THRESHOLDS__COMPACT_NUDGE_FIRST=150
THRESHOLDS__LONG_SESSION_MINUTES=120

# Toggle hooks on/off
HINTS__SESSION_START=true
HINTS__PRE_TOOL=true
HINTS__POST_TOOL=true

# Exclude projects/entrypoints from analysis
FILTER__EXCLUDE_ENTRYPOINTS=["cc-retrospect","cc-later"]
```

Full config reference: [docs/configuration.md](docs/configuration.md)

---

## Architecture

```
cc_retrospect/
  config.py      Config models (Pydantic + pydantic-settings)
  models.py      Data models (SessionSummary, AnalysisResult, etc.)
  parsers.py     JSONL parsing, session analysis, cost computation
  cache.py       Session cache, atomic writes, live state
  analyzers.py   9 analyzers (Cost, Waste, Health, Habits, Tips, Compare, Savings, Model, Trend)
  hooks.py       7 hooks (stop, start, pre/post tool, prompt, pre/post compact)
  commands.py    17 command entry points
  utils.py       Formatting, filtering, rendering
  learn.py       STYLE.md / LEARNINGS.md generation
  core.py        Backward-compat re-export shim
```

## Data & Privacy

Reads `~/.claude/projects/` — the JSONL files Claude Code already writes. No network calls, no telemetry, no external services. Cache stored at `~/.cc-retrospect/`.

## Documentation

- [Commands & Analysis](docs/commands.md)
- [Configuration](docs/configuration.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing](CONTRIBUTING.md)
