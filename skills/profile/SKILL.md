---
name: profile
description: Analyze your Claude Code usage patterns and generate a behavioral profile with actionable recommendations. Use when asked about usage style, habits, or to generate a STYLE.md.
user-invocable: true
allowed-tools: Bash Read Grep Glob
---

# cc-retrospect Profile Analysis

You are building a behavioral profile of the user's Claude Code usage. This goes beyond numbers — you're finding patterns, quirks, inefficiencies, and strengths.

## Step 1 — Gather data

Run the precision analyzers first:

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
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py savings
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py model
```

Then read the raw session data for behavioral analysis:

```bash
# Recent user messages — scan for communication style
find ~/.claude/projects/ -name "*.jsonl" -newer ~/.claude/projects/ -mtime -7 | head -5 | while read f; do
  grep '"type":"user"' "$f" | head -20
done
```

## Step 2 — Behavioral analysis (Claude reasons about these)

From the session data, analyze:

### Communication style
- Average prompt length, median prompt length
- Ratio of short commands ("do it", "yes", "continue") vs detailed instructions
- Frustration patterns — what triggers "ugh", "again", "no"?
- Gratitude-to-correction ratio
- Does the user explain intent or just give commands?

### Session discipline
- How long do sessions run before the user starts a new one?
- Does the user /compact or let context overflow?
- Are there "marathon" sessions (100+ messages) that should have been split?
- How many context continuations (compaction events)?

### Model usage efficiency
- Is Opus used for tasks where Sonnet/Haiku would suffice?
- Which projects genuinely need Opus (complex reasoning, architecture)?
- Which projects could default to Sonnet (routine Read/Edit/Bash)?

### Plan mode opportunities
- Look for sessions with many back-and-forth corrections ("no", "wrong", "not what I meant")
- These suggest the user should have used /plan or EnterPlanMode to align upfront
- Count: corrections that could have been avoided with a plan

### Volatile patterns
- Files edited most frequently (churn)
- Projects with highest frustration-to-session ratio
- Tasks that consistently take many iterations (CI debugging, config tweaking)
- Repeated searches for the same thing

### Weird/non-obvious findings
- Any patterns that stand out as unusual
- Ghost files (edited more than read)
- Repeated searches for the same topic
- Agent inception (agents spawning agents)
- Time-of-day patterns that correlate with quality

## Step 3 — Generate the profile

Output a structured markdown report with:

1. **User Profile Summary** — 3-4 sentences describing who this user is as a Claude Code user
2. **Communication Style** — how they talk to Claude, what works, what doesn't
3. **Top 5 Money-Saving Actions** — with actual $/month from their data, ranked by impact
4. **Model Routing Recommendations** — which projects should default to which model
5. **Plan Mode Opportunities** — specific patterns where /plan would help
6. **Volatile Hotspots** — files/projects that churn most, suggesting architectural issues
7. **Weird Findings** — non-obvious patterns (the stuff that makes analysis interesting)
8. **Suggested STYLE.md** — a ready-to-use behavioral directive based on their communication patterns

## Step 4 — Offer to save

Ask the user if they want to:
1. Save the STYLE.md to `~/.claude/STYLE.md` (or update existing)
2. Save the full profile to `~/.cc-retrospect/profiles/profile-{date}.md`
