# /cc-retrospect:optimize-later

Optimize dispatch model selection.

## Description

Analyzes both cc-retrospect (Claude Code sessions) and cc-later (Claude web app usage) logs to recommend the best model for different task types. Uses historical performance to suggest model switching strategies that balance cost and capability.

## Usage

```
/cc-retrospect:optimize-later
```

## What it does

1. Reads:
   - `~/.cc-retrospect/` (Claude Code logs)
   - `~/.cc-later/` logs if available (Claude web app usage)

2. Groups tasks by type:
   - Analysis tasks (Research, WebSearch)
   - Coding tasks (Bash, multiple file edits)
   - Simple tasks (single Read/Grep)
   - Complex reasoning (Agent, compactions)

3. For each category, calculates:
   - Success rate by model
   - Average cost per task
   - Context window efficiency
   - User satisfaction signals (frustration count)

4. Generates recommendations:
   ```json
   {
     "recommended_model": "sonnet",
     "reason": "85% success on coding, 40% cheaper than Opus",
     "confidence": 0.92,
     "strategy": "Use Sonnet for coding+analysis, Haiku for simple tasks, Opus only for complex reasoning"
   }
   ```

## Example output

```
Model recommendations by task type:

  Simple tasks (Read, Grep): haiku
    - Cost: $0.10/task vs $2.50 Opus
    - Success: 99% (same as Opus)
    - Recommendation: ALWAYS use Haiku here

  Coding tasks (Bash, edits): sonnet
    - Cost: $1.50 vs $4.20 Opus  (64% savings)
    - Success: 88% vs 91% Opus (acceptable trade-off)
    - Recommendation: DEFAULT to Sonnet, escalate on error

  Complex reasoning: opus
    - Cost: justified by success rate 95% vs 78% Sonnet
    - Only 15% of your tasks (high ROI to get right)
    - Recommendation: Use only for /analyze, /hints
```

## Notes

- Requires 20+ sessions for statistical relevance
- Runs weekly recommendation engine
- Safe to ignore recommendations (advisory only)
- Pairs with `/cc-retrospect:cost --model` for per-session comparison
