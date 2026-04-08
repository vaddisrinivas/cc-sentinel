# /cc-retrospect:diff

Compare two sessions side-by-side.

## Description

Lists all cached sessions and lets you pick two to compare. Shows cost, duration, tool usage, and model breakdown side-by-side, highlighting cost differences and efficiency gaps.

## Usage

```
/cc-retrospect:diff
```

## What it does

1. Loads all cached sessions and presents a numbered list:
   ```
   [1] 2026-04-08 09:15 (React feature) $12.50, 45m, 23 msgs, Opus
   [2] 2026-04-08 14:20 (Bug fix) $3.20, 12m, 8 msgs, Sonnet
   [3] 2026-04-07 16:00 (Analysis) $8.75, 38m, 19 msgs, Opus
   ```

2. Prompts for two session numbers

3. Compares:
   - Cost delta (absolute and %)
   - Duration and message count
   - Model breakdown
   - Tool chains (which tools used, how many)
   - Waste flags (WebFetch, mega-prompts, etc.)

4. Explains differences:
   - "Session 1 cost 3.9x more due to Opus + longer chains"
   - "Session 2 hit compaction threshold at message 150"

## Example output

```
Session 1: React feature ($12.50) vs Session 2: Bug fix ($3.20)

Cost delta: +$9.30 (3.9x more)
  - Model: Opus vs Sonnet (5.0x factor)
  - Duration: 45m vs 12m (3.75x longer)

Tools used:
  Session 1: Read(15), Bash(8), Grep(3), Agent(2)
  Session 2: Read(4), Grep(3), Bash(1)

Efficiency: Session 2 is 2.4x more efficient
```

## Notes

- Useful for identifying cost outliers
- Helps calibrate model selection
- Safe to run repeatedly
