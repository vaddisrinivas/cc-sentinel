# cc-retrospect Development Guide

Internal conventions and patterns for contributors.

## Architecture

cc-retrospect = 3 layers:

1. **Hooks** (passive, silent)
   - `run_stop_hook` — analyze session on exit
   - `run_session_start_hook` — show recap + health check
   - `run_pre_tool_use`, `run_post_tool_use` — nudge on waste
   - All in `cc_retrospect/hooks.py`

2. **Analyzers** (analysis engine)
   - `CostAnalyzer`, `WasteAnalyzer`, `HealthAnalyzer`, etc.
   - All in `cc_retrospect/analyzers.py`
   - Implement: `analyze(sessions: list[SessionSummary], config: Config) -> AnalysisResult`
   - Returns markdown-renderable results

3. **Commands** (dispatch)
   - Entry points in `cc_retrospect/commands.py`
   - Each is `run_X(payload: dict, config: Config) -> int`
   - Called by `scripts/dispatch.py`

## Adding a new command

### Step 1: Implement analyzer (if needed)

```python
# In cc_retrospect/analyzers.py
class MyAnalyzer(BaseAnalyzer):
    def analyze(self, sessions: list[SessionSummary], config: Config) -> AnalysisResult:
        # Your logic here
        return AnalysisResult(title="...", lines=[...])
```

### Step 2: Add command entry point

```python
# In cc_retrospect/commands.py
def run_my_command(payload: dict = {}, *, config: Config | None = None) -> int:
    return _render(MyAnalyzer, payload, config=config)
```

### Step 3: Register in dispatch

```python
# In scripts/dispatch.py
_DISPATCH = {
    # ... existing
    "my_command": run_my_command,
}
```

### Step 4: Add test

```python
# In tests/test_commands.py
def test_my_command():
    config = default_config()
    result = run_my_command({}, config=config)
    assert result == 0
```

## Config pattern

All config via Pydantic models in `cc_retrospect/config.py`:
- `PricingConfig` — model costs
- `ThresholdsConfig` — limits for warnings/nudges
- `HintsConfig` — which hooks produce output
- `MessagesConfig` — all user-facing strings

Load config:
```python
config = load_config()  # reads ~/.cc-retrospect/config.env
```

Override in `~/.cc-retrospect/config.env`:
```env
PRICING__SONNET__INPUT_PER_MTOK=3.0
HINTS__SESSION_START=true
```

## Data flow

1. Claude Code session runs
2. `run_stop_hook` fires (receives JSONL from Claude Code)
3. `analyze_session()` parses JSONL → `SessionSummary`
4. Summary appended to `~/.cc-retrospect/sessions.jsonl`
5. Commands read from cache, apply filters, run analyzers

## Testing patterns

### Test a hook

```python
def test_stop_hook_tracks_cost():
    config = default_config()
    payload = {
        "session_id": "test-123",
        "cwd": "/path",
    }
    result = run_stop_hook(payload, config=config)
    assert result == 0
    cache = config.data_dir / "sessions.jsonl"
    assert cache.exists()
```

### Test an analyzer

```python
def test_waste_analyzer():
    sessions = [
        SessionSummary(
            session_id="1",
            total_cost=10.0,
            webfetch_domains={"github.com": 5},
            tool_chains=[("Bash", 6)],
        ),
    ]
    result = WasteAnalyzer().analyze(sessions, default_config())
    assert "WebFetch" in result.render_markdown()
```

### Test a command

```python
def test_cost_command():
    config = default_config()
    # Create dummy session in cache
    sessions = load_all_sessions(config)
    result = run_cost({}, config=config)
    assert result == 0
```

## PR checklist

- [ ] New command? Added to `_DISPATCH`
- [ ] New config field? Added to config model
- [ ] New hook? Registered in `scripts/dispatch.py`
- [ ] Tests added for new logic
- [ ] Docstrings on public functions
- [ ] Type hints on all parameters
- [ ] No debugging print statements
- [ ] Passes `make lint` and `make test`

## Common patterns

### Safe JSON writes
```python
from cc_retrospect.cache import _atomic_write_json
_atomic_write_json(path, data)  # atomic, no corruption on crash
```

### Load sessions with progress
```python
sessions = load_all_sessions(config)
for i, s in enumerate(sessions):
    if i % 50 == 0:
        print(f"Processing... {i}", file=sys.stderr)
```

### Filter sessions
```python
from cc_retrospect.utils import _filter_sessions
filtered = _filter_sessions(sessions, project="myproject", days=7)
```

### Format output
```python
from cc_retrospect.utils import _fmt_cost, _fmt_tokens, _fmt_duration
print(_fmt_cost(12.50))     # "$12.50"
print(_fmt_tokens(50000))   # "50.0k"
print(_fmt_duration(125))   # "2h 5m"
```

## Debugging

Enable debug logging:
```bash
CC_RETROSPECT_LOG_LEVEL=DEBUG python scripts/dispatch.py cost
```

Logs go to stderr. Check:
```bash
python scripts/dispatch.py status  # shows what's tracked
```

## Performance notes

- `load_all_sessions()` scans `~/.claude/projects/` on first run (slow)
  - Subsequent calls use cache at `~/.cc-retrospect/sessions.jsonl`
  - Clear cache: `/cc-retrospect:reset`

- Large analyzers cache during session (in-memory)

- JSONL is line-delimited, safe for concurrent appends
