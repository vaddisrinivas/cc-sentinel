---
name: cc-retrospect
description: Analyze Claude Code session costs, waste, habits, health, model efficiency, and savings. Accepts subcommands like /cc-retrospect waste, /cc-retrospect health, /cc-retrospect learn, etc.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# cc-retrospect

Route based on the first argument. If no argument, run full analysis.

## Subcommand routing

Check the user's argument (the text after `/cc-retrospect`). Match the first word:

| Arg | Action |
|-----|--------|
| (none) | Full analysis — run Step A then Step B |
| `waste` | Run `waste` analyzer then interpret |
| `health` | Run `health` analyzer then interpret |
| `savings` | Run `savings` analyzer then interpret |
| `model` | Run `model` analyzer then interpret |
| `digest` | Run `digest` analyzer then interpret |
| `habits` | Run `habits` analyzer, present results |
| `compare` | Run `compare` analyzer, present results |
| `trends` | Run `trends` analyzer, present results |
| `tips` | Run `tips` analyzer, present results |
| `report` | Run `report` analyzer, present results |
| `export` | Run `export`, present results |
| `hints` | Run `hints`, present results |
| `learn` | Run Step C |
| `profile` | Run Step D |
| `cleanup` | Run Step E |

## Step A — Run all analyzers (for full analysis)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py cost
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py waste
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py health
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py habits
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py savings
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py model
```

## Step B — Interpret (for full analysis + deep subcommands)

After running the data commands, synthesize findings into:

1. **Executive summary** — 2-3 sentences: total spend, biggest waste, top opportunity
2. **Top 3 actions** — ranked by $/month impact, with specific instructions
3. **Model routing** — which projects should use Sonnet vs Opus
4. **Session discipline** — are sessions too long? too many subagents?
5. **Trend** — getting better or worse vs last week?

Be specific. Name projects, dollar amounts, and exact actions. No generic advice.

## Running a single analyzer

For any subcommand that maps to a dispatcher command:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py <subcommand>
```

For deep subcommands (waste, health, savings, model, digest), also interpret the output:
- Name specific projects and dollar amounts
- Explain *why* each pattern costs money
- Prioritize by impact
- Give one concrete next action

For data subcommands (habits, compare, trends, tips, report, export, hints), just present the output cleanly.

## Step C — Learn (generate STYLE.md + LEARNINGS.md)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py learn
```

Read the generated files and offer to save them:
- `~/.claude/STYLE.md` — communication style directive
- `~/.cc-retrospect/LEARNINGS.md` — transferable patterns

Ask before overwriting existing files.

## Step D — Profile (behavioral analysis)

Run these analyzers first:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py cost
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py habits
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py waste
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py model
```

Then analyze behavioral patterns:
- Communication style (prompt lengths, frustration triggers, command vs instruction ratio)
- Session discipline (marathon sessions, compaction frequency)
- Model usage efficiency per project
- Plan mode opportunities (sessions with many corrections)
- Top 5 money-saving actions with $/month from actual data

Output a structured profile and offer to save as `~/.cc-retrospect/profiles/profile-{date}.md`.

## Step E — Cleanup (disk waste)

```bash
du -sh ~/.claude/ 2>/dev/null || echo "~/.claude not found"
```

```bash
du -sh ~/.claude/telemetry/ 2>/dev/null || echo "No telemetry dir"
```

```bash
find ~/.claude/projects/ -path "*/subagents/*" -name "*.jsonl" | wc -l
```

```bash
du -sh ~/.cc-retrospect/ 2>/dev/null || echo "No data dir"
```

Present findings in a table. Show cleanup commands but NEVER run them without asking first.

## Rules

- Always run the data commands first, then interpret
- Be specific — name projects, dollar amounts, dates
- No generic advice — every recommendation must cite the user's actual data
- For cleanup: NEVER delete without explicit confirmation
