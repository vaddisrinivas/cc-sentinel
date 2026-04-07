# cc-retrospect

**Stop burning tokens you didn't mean to spend.**

Claude Code sessions are invisible by default — no cost dashboard, no warnings when context bloats, no signal that you've been in the same session for six hours. Most users only notice after the bill lands.

cc-retrospect runs alongside Claude Code as a plugin. It watches every tool call, flags waste before it happens, nudges you to compact before context costs spiral, and gives you a clear picture of where your tokens actually went.

A single long session can cost more than a week of normal work. cc-retrospect makes that visible — and catches the patterns (WebFetch to GitHub, mega-pasted prompts, Opus on simple tasks) that silently inflate every session.

---

## What it does

Hooks fire on every tool call. No polling, no background processes.

**Before a tool runs** — if you're WebFetching a GitHub URL, spawning an Agent for something Grep can handle, or Bashing five times in a row, you get a one-line hint in the chat.

**During the session** — at 150 tool calls you're nudged to `/compact`. At 300 it strongly recommends it. Subagent overuse is flagged at threshold.

**After a session** — cost, duration, frustration signals, and subagent count are cached and surfaced at the start of your next session (opt-in).

**On demand** — eight commands give you cost breakdowns, habit patterns, health checks, week-over-week comparisons, and a full markdown report.

---

## Install

```bash
git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect
cd ~/.claude/plugins/cc-retrospect
pip install -e .
```

Merge the hooks into `~/.claude/settings.json`:

```bash
cat hooks/hooks.json
```

Copy the `Stop`, `SessionStart`, `PreToolUse`, and `PostToolUse` entries into your settings under `"hooks"`.

---

## Commands

| Command | What it does |
|---|---|
| `/cc-retrospect:cost` | Cost by project, model, and time period. What-if: what would Sonnet have cost? |
| `/cc-retrospect:habits` | Session lengths, peak hours, tool usage, frustration signals |
| `/cc-retrospect:health` | Long sessions, subagent overuse, cost velocity, cache hit rate |
| `/cc-retrospect:tips` | 1–3 actionable tips from your recent patterns |
| `/cc-retrospect:waste` | WebFetch to GitHub, tool chains, mega prompts, model mismatch |
| `/cc-retrospect:compare` | This week vs last week |
| `/cc-retrospect:report` | Full markdown report saved to `~/.cc-retrospect/reports/` |
| `/cc-retrospect:hints` | Show which inline hints are enabled and how to toggle them |

---

## Configuration

```env
# ~/.cc-retrospect/config.env

# Pricing ($/MTok) — update when Anthropic changes rates
PRICING_OPUS_INPUT_PER_MTOK=15.0
PRICING_SONNET_INPUT_PER_MTOK=3.0

# Thresholds
THRESHOLD_LONG_SESSION_MINUTES=120
THRESHOLD_MEGA_PROMPT_CHARS=1000
THRESHOLD_DAILY_COST_WARNING=500

# Inline hints (true/false)
HINTS_SESSION_START=false   # suppress "Ran a hook" noise at session start
HINTS_PRE_TOOL=true         # hints before WebFetch/Agent/Bash calls
HINTS_POST_TOOL=true        # compact nudge + subagent warnings

# Extra domains to flag on WebFetch
WASTE_WEBFETCH_DOMAINS=github.com,api.github.com,stackoverflow.com

# Log level for internal diagnostics (stderr)
# CC_RETROSPECT_LOG_LEVEL=WARNING
```

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
        recs = [Recommendation("warning", f"{len(over)} sessions over $200")]
        return AnalysisResult(title="Budget", sections=[], recommendations=recs)
```

Auto-discovered and included in `/cc-retrospect:report`.

---

## Data

Reads from `~/.claude/projects/` — the same JSONL files Claude Code writes. No network calls, no telemetry. Cache at `~/.cc-retrospect/sessions.jsonl`; delete to force a full re-scan.
