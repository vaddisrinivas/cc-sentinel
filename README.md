# cc-retrospect

**Stop burning tokens you can't see.**

Claude Code doesn't show you what you're spending. No cost dashboard, no warning when a session hits 300 messages, no signal that you used Opus for a task Sonnet could handle. cc-retrospect fixes that — real-time interception, automatic tracking, and on-demand analysis.

## Install

```bash
git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect
cd ~/.claude/plugins/cc-retrospect && uv pip install -e .
```

No `pip`? Use `pip install -e .` instead. Hooks are auto-discovered by Claude Code from the plugin.

---

## What happens automatically

These hooks fire silently on every session — no commands needed.

| Hook | When | What it does |
|---|---|---|
| **Stop** | Session ends | Caches session summary (cost, tokens, tools, frustration) |
| **SessionStart** | Session begins | Shows last-session recap + daily digest on first session of new day |
| **PreToolUse** | Before WebFetch/Agent/Bash | Warns: GitHub URL → use `gh`, simple search → use Grep, Bash chain → combine |
| **PostToolUse** | After every tool | Nudges `/compact` at 150+ calls, warns on subagent overuse |
| **PreCompact** | Before compaction | Logs compaction event |
| **PostCompact** | After compaction | Logs tokens freed |

First session ever? You'll see: `[cc-retrospect] Welcome! Found N sessions ($X). Run /cc-retrospect:analyze for full report.`

Daily budget exceeded? You'll see: `[cc-retrospect] Budget alert: $X spent today.`

---

## Commands

| Command | What it does |
|---|---|
| `/cc-retrospect:cost` | Cost by project, model, and time period. What-if Sonnet savings. |
| `/cc-retrospect:habits` | Session lengths, peak hours, tool usage, frustration signals |
| `/cc-retrospect:health` | Long sessions, subagent overuse, cost velocity, cache hit rate |
| `/cc-retrospect:waste` | WebFetch to GitHub, tool chains, mega prompts, model mismatch |
| `/cc-retrospect:tips` | 1-3 actionable tips from your most recent session |
| `/cc-retrospect:compare` | This week vs last week |
| `/cc-retrospect:savings` | Per-habit savings projections with actual $/month from your data |
| `/cc-retrospect:model` | Model efficiency — which sessions wasted Opus on simple tasks |
| `/cc-retrospect:digest` | Yesterday's full digest with model + savings analysis |
| `/cc-retrospect:trends` | Weekly trend tracking — are you improving over time? |
| `/cc-retrospect:report` | Full markdown report saved to `~/.cc-retrospect/reports/` |
| `/cc-retrospect:export` | Dump all session data as JSON (pipeable) |
| `/cc-retrospect:status` | Plugin health check — verify install, data, dependencies |
| `/cc-retrospect:hints` | Show which inline hints are enabled and how to toggle them |

---

## Skills

Skills use Claude's reasoning to analyze patterns that numbers alone can't capture.

| Skill | What it does |
|---|---|
| `/cc-retrospect:analyze` | Full retrospective: cost + habits + health + waste + model efficiency + plan mode opportunities + volatile hotspots |
| `/cc-retrospect:profile` | Behavioral analysis of your communication style. Generates a STYLE.md you can drop into `~/.claude/`. |
| `/cc-retrospect:cleanup` | Scans `~/.claude/` for disk waste (stale subagent logs, failed telemetry, old sessions). Asks before deleting. |

---

## Configuration

Create `~/.cc-retrospect/config.env` to override defaults:

```env
# Pricing ($/MTok) — update when Anthropic changes rates
PRICING__OPUS__INPUT_PER_MTOK=15.0
PRICING__OPUS__OUTPUT_PER_MTOK=75.0
PRICING__SONNET__INPUT_PER_MTOK=3.0
PRICING__SONNET__OUTPUT_PER_MTOK=15.0

# Thresholds
THRESHOLDS__LONG_SESSION_MINUTES=120
THRESHOLDS__DAILY_COST_WARNING=500

# Inline hints (true/false)
HINTS__SESSION_START=false
HINTS__PRE_TOOL=true
HINTS__POST_TOOL=true
```

See `scripts/default_config.env` for all available settings.

---

## Custom analyzers

Drop a `.py` file in `~/.cc-retrospect/analyzers/`:

```python
class MyAnalyzer:
    name = "my-check"
    description = "Flag sessions over budget"

    def analyze(self, sessions, config):
        from cc_retrospect.core import AnalysisResult, Recommendation
        over = [s for s in sessions if s.total_cost > 200]
        recs = [Recommendation(severity="warning", description=f"{len(over)} sessions over $200")]
        return AnalysisResult(title="Budget", recommendations=recs)
```

Auto-discovered and included in `/cc-retrospect:report`.

---

## Architecture

```
cc_retrospect/core.py    — config, parsing, analyzers, hooks (~1200 LOC)
scripts/dispatch.py      — lean stdin/argv router
commands/*.md            — 14 slash commands (single bash block each)
skills/*/SKILL.md        — 3 skills (Claude reasoning)
hooks/hooks.json         — 6 hook definitions
```

**Precision layer** (Python): cost, waste, savings, model efficiency, trends, export. Exact numbers.

**Behavioral layer** (Skills/Claude): habits analysis, plan mode detection, volatile hotspots, communication profiling, STYLE.md generation. Pattern recognition.

**Action layer** (Hooks): real-time interception, compact nudges, budget alerts, daily digest, compaction tracking. Automatic.

---

## Data

Reads from `~/.claude/projects/` — the same JSONL files Claude Code writes. No network calls, no telemetry.

Cache at `~/.cc-retrospect/sessions.jsonl` (auto-built on first run). Delete to force re-scan.

---

## Development

```bash
uv pip install -e ".[test]"
pytest
```
