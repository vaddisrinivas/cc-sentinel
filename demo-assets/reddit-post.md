# r/ClaudeAI Post

**Title:** I spent $5,202 on Claude Code last month and had no idea where it went. So I built a dashboard that tracks everything.

**Body:**

I use Claude Code a lot. Like, a concerning amount — 1,204 sessions in 30 days, 948 hours of coding time, 47,000 tool calls.

The problem: Claude Code gives you no visibility into what you're spending. No breakdown by project, no alerts when a session gets expensive, no signal that you used Opus for a task Haiku could handle at 1/100th the cost.

I found out I'd spent $5,202 in a month by checking my credit card. That's when I decided to build something.

**cc-retrospect** is a Claude Code plugin that passively tracks every session. It hooks into Claude Code's session lifecycle — when a session ends, it analyzes the JSONL, grades the session A through D, and caches the data. Zero config, completely silent.

Then you open the dashboard and see everything:

- **Budget tracking** — real-time spend with 3 alert tiers + macOS notifications
- **AI savings tips** — "switch to Sonnet for simple tasks, save $553/mo" with actual projected savings
- **Session grading** — every session gets A/B/C/D based on efficiency, cost velocity, cache rate
- **Grade streak** — I have 10 A's in a row right now and I'm not breaking it
- **Week-over-week comparison** — my cost went from $901 to $4,133 in one week. Frustrations up 453%. Now I can't unsee it.
- **Profile card** — it calls me "The Opus Maximalist" which... tracks. Exports as animated GIF.
- **5 themes** including Cyberpunk, Nord, Solarized. Command palette with ⌘K.
- **7 passive hooks** — waste detection, model nudging, compact alerts, all invisible

The dashboard runs locally, no telemetry, reads the JSONL files Claude Code already writes.

**Install (2 commands):**

```
/marketplace add vaddisrinivas/cc-retrospect
/install cc-retrospect@cc-retrospect
```

Then just use Claude Code normally. It watches everything in the background. Open the dashboard whenever you want to check in.

GitHub: https://github.com/vaddisrinivas/cc-retrospect

The demo video in the README was made with another plugin I built called [framecraft](https://github.com/vaddisrinivas/framecraft) — generates polished demo videos from screenshots + scene descriptions. Install that too if you want:

```
/marketplace add vaddisrinivas/framecraft
/install framecraft@framecraft
```

Happy to answer questions. The profile card GIF is genuinely fun to share.

---

# r/LocalLLaMA Cross-post

**Title:** Built a usage analytics dashboard for Claude Code — tracks every session, grades efficiency, projects savings

**Body:**

Same body as above, but add at the top:

> Not strictly local LLM, but a lot of people here use Claude Code alongside local models. This plugin gives you the cost visibility that's missing.

And remove the framecraft mention at the bottom (less relevant for that sub).
