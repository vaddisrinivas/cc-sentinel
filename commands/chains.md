---
name: chains
description: Extract and analyze tool chain patterns from sessions
allowed-tools: Bash
user-invocable: true
---

Run the chains analyzer to extract tool chain patterns:

```bash
python3 "$PLUGIN_ROOT/scripts/dispatch.py" chains --json
```

Analyze the JSON output and identify:
1. **Recurring patterns**: Tool sequences that repeat across sessions (e.g., Read→Edit→Read)
2. **Waste patterns**: Long chains of the same tool (Bash x10, Read x5)
3. **Effective patterns**: Chains that correlate with low-cost sessions

For each pattern found, write a brief guide to `~/.cc-retrospect/chains/`:
- When to use this pattern
- Expected output
- Common pitfalls
