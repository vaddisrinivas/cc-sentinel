# Architecture

How cc-retrospect works internally.

## Module diagram

```
scripts/dispatch.py
    │
    ├─→ _read_payload() ─→ Hooks (passive, JSON from Claude Code)
    │      │
    │      └─→ cc_retrospect/hooks.py
    │           ├─ run_stop_hook (analyze on session end)
    │           ├─ run_session_start_hook (recap + health)
    │           ├─ run_pre_tool_use (warn before waste)
    │           └─ run_post_tool_use (nudge compaction)
    │
    └─→ _parse_cli_flags() ─→ Commands (active, user invokes)
           │
           └─→ cc_retrospect/commands.py
                ├─ run_cost()
                ├─ run_waste()
                ├─ run_health()
                ├─ run_reset()
                └─ ... (18 total)
                    │
                    └─→ _render() ─→ Analyzers
                         │
                         └─→ cc_retrospect/analyzers.py
                              ├─ CostAnalyzer
                              ├─ WasteAnalyzer
                              ├─ HealthAnalyzer
                              ├─ TipsAnalyzer
                              ├─ CompareAnalyzer
                              ├─ SavingsAnalyzer
                              ├─ ModelAnalyzer
                              └─ TrendAnalyzer
```

## Data flow: Session end

```
1. Claude Code stops session
   ↓
2. run_stop_hook() receives {session_id, cwd}
   ↓
3. Locate session JSONL: ~/.claude/projects/PROJECT/SESSION_ID.jsonl
   ↓
4. analyze_session() parses JSONL → SessionSummary
   - Extracts: cost, duration, model, tools, waste flags
   - Calls: CostAnalyzer, WasteAnalyzer, etc. for flags
   ↓
5. Append to ~/.cc-retrospect/sessions.jsonl
   ↓
6. Update state.json (last session, daily cost, trends)
   ↓
7. If hints.waste_on_stop: print waste flags to stderr
```

## Data flow: User command

```
1. User runs: /cc-retrospect:cost --days 7 --json
   ↓
2. dispatch.py parses flags → {days: 7, json: True}
   ↓
3. run_cost() called with payload
   ↓
4. _render() loads all sessions from cache
   ↓
5. _filter_sessions() applies filters (project, days, exclude)
   ↓
6. CostAnalyzer.analyze() processes filtered sessions
   ↓
7. AnalysisResult.render_markdown() or render_json()
   ↓
8. Output to stdout
```

## Config layering

```
Defaults (code)
  ↓
  + Overrides (config.env)
  ↓
  = Config object (loaded by commands)

~/.cc-retrospect/config.env
PRICING__SONNET__INPUT_PER_MTOK=3.0
THRESHOLDS__LONG_SESSION_MINUTES=120
HINTS__SESSION_START=true
```

## SessionSummary structure

```json
{
  "session_id": "abc123",
  "project": "myproject",
  "start_ts": "2026-04-08T14:30:00Z",
  "duration_minutes": 45,
  "message_count": 23,
  "total_cost": 12.50,
  "model_breakdown": {
    "claude-opus-4-6": 10.00,
    "claude-sonnet-4-20250514": 2.50
  },
  "tool_counts": {
    "Read": 15,
    "Bash": 8,
    "Grep": 3
  },
  "tool_chains": [
    ["Read", 5],
    ["Bash", 3]
  ],
  "frustration_count": 2,
  "subagent_count": 1,
  "webfetch_domains": {"github.com": 3},
  "mega_prompt_count": 1
}
```

## AnalysisResult structure

```python
class AnalysisResult(BaseModel):
    title: str
    lines: list[str]
    warnings: list[str] = []
    tips: list[str] = []
    
    def render_markdown(self) -> str:
        # Returns formatted markdown
    
    def render_json(self) -> dict:
        # Returns JSON-serializable dict
```

## Caching strategy

- **sessions.jsonl** — append-only log of SessionSummary (JSONL)
- **state.json** — live state (last session, daily cost, etc.)
- **compactions.jsonl** — log of compaction events
- **trends.jsonl** — weekly snapshots for trends
- **model_recommendation.json** — latest model suggestion
- **LATER.md** — waste entries tagged for later review

## Performance notes

1. **First load is slow**: `load_all_sessions()` scans `~/.claude/projects/`
   - Subsequent calls use `sessions.jsonl` cache
   - Clear with: `/cc-retrospect:reset`

2. **Large cache scans**: Print progress every 50 items
   ```python
   for i, session in enumerate(sessions):
       if i % 50 == 0:
           print(f"Scanning... {i} sessions", file=sys.stderr)
   ```

3. **JSONL append is atomic**: Safe for concurrent hooks
   - Uses `_atomic_write_json()` for state.json

4. **Filters applied early**: project, days, exclude filters reduce processing

## Extending cc-retrospect

### Add a new analyzer

1. Create class in `analyzers.py`:
   ```python
   class MyAnalyzer(BaseAnalyzer):
       def analyze(self, sessions, config):
           # Process sessions
           return AnalysisResult(...)
   ```

2. Add command in `commands.py`:
   ```python
   def run_my_command(payload, config=None):
       return _render(MyAnalyzer, payload, config=config)
   ```

3. Register in `dispatch.py`:
   ```python
   _DISPATCH["my_command"] = run_my_command
   ```

### Add a new config field

1. Add to model in `config.py`:
   ```python
   class MyConfig(BaseModel):
       new_field: str = "default"
   ```

2. Add to `Config`:
   ```python
   my_config: MyConfig = MyConfig()
   ```

3. Env var: `MY_CONFIG__NEW_FIELD=value`

### Add a new hook

1. Implement in `hooks.py`:
   ```python
   def run_my_hook(payload, config=None):
       # Your logic
       return 0
   ```

2. Register in `dispatch.py`:
   ```python
   _DISPATCH["my_hook"] = run_my_hook
   _HOOKS = {..., "my_hook"}
   ```

3. Configure in Claude Code settings.json (hooks fire on events)

## Testing

All tests in `tests/`. Use patterns:
- `default_config()` for test config
- `SessionSummary(...)` to create test data
- `load_all_sessions(config)` to read cache

Run: `make test`
