# /cc-retrospect:budget

Cost analysis with budget planning.

## Description

Analyzes your spending over the past N days and helps you plan a sustainable budget. Calculates current velocity, projects monthly costs, and determines the gap between actual and target spending.

## Usage

```
/cc-retrospect:budget [--days 7]
```

## What it does

1. Runs `/cc-retrospect:cost --days N --json` (default: 7 days)

2. Extracts:
   - Total cost for period
   - Daily average
   - Peak day spending
   - Cost by model (Opus vs Sonnet vs Haiku)

3. Prompts you for target monthly budget

4. Generates report:
   - Current monthly projection
   - Gap to target (positive = over budget)
   - Savings breakdown by model switching
   - Concrete actions to reach target

## Example output

```
Last 7 days: $42.50 (avg $6.07/day)
Projected monthly: $182.10

Your target: $100/month
Gap: +$82.10 over budget

Recommendations:
  1. Switch 50% of Opus → Sonnet: save $35/month
  2. Avoid WebFetch→GitHub (use gh): save $12/month
  3. Compact more frequently: save $15/month
```

## Notes

- Updates daily as you work
- Non-binding (no enforcement)
- Safe to re-run to adjust target
