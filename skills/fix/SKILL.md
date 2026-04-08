# /cc-retrospect:fix

Run waste analysis, Claude generates concrete fixes.

## Description

Analyzes token waste patterns from your sessions and generates actionable optimization recommendations. Runs `/cc-retrospect:waste --json` to extract waste data, then uses Claude's reasoning to suggest specific, implementable fixes.

## Usage

```
/cc-retrospect:fix
```

## What it does

1. Executes `waste --json` to capture:
   - WebFetch→GitHub calls (should use `gh` CLI)
   - Repetitive tool chains (should combine with `&&`)
   - Oversized prompts (should use file references)
   - Duplicate read patterns (cache results)

2. Passes JSON output to Claude for analysis

3. Generates concrete fixes with:
   - Specific technique for each waste pattern
   - Token savings estimate
   - Example refactor for your actual code
   - When to apply (per-session vs. architectural)

## Example output

```
Waste Pattern: 5 WebFetch→GitHub calls
  Recommendation: Use gh CLI instead
  Savings: ~200 tokens per session
  Example: gh api repos/owner/repo/issues/123

Waste Pattern: 3 duplicate Read chains
  Recommendation: Cache API responses in files
  Savings: ~150 tokens
```

## Notes

- Works best after 5+ sessions (need historical data)
- Recommendations are cumulative
- Safe to run multiple times (non-destructive)
