# Troubleshooting

Common issues and how to fix them.

## Hooks not firing

**Symptom**: Run a session, but `/status` shows 0 sessions.

**Fix**:
1. Verify hooks are registered:
   ```bash
   cat ~/.claude/settings.json | grep -i retrospect
   ```
   Should see references to `dispatch.py`

2. Check Claude Code version:
   ```bash
   which claude
   claude --version
   ```
   cc-retrospect requires Claude Code 0.7.0+

3. Reinstall hooks:
   ```bash
   ~/.claude/plugins/cc-retrospect/install.sh
   ```

4. Check data directory:
   ```bash
   ls -la ~/.cc-retrospect/
   ```
   Should exist and be writable

## Cache bloat

**Symptom**: Sessions accumulate, commands slow down.

**Fix**:
1. Clear cache safely:
   ```bash
   /cc-retrospect:reset
   ```
   Asks for confirmation, shows what will be deleted.

2. Or manually clean:
   ```bash
   rm ~/.cc-retrospect/sessions.jsonl
   rm ~/.cc-retrospect/state.json
   ```
   Sessions will be re-scanned on next command.

## Hook debug

**Symptom**: Hook failed or produced unexpected output.

**Fix**:
1. Enable debug logging:
   ```bash
   CC_RETROSPECT_LOG_LEVEL=DEBUG /cc-retrospect:status
   ```

2. Check stderr:
   ```bash
   python3 ~/.claude/plugins/cc-retrospect/scripts/dispatch.py status 2>&1
   ```

3. Manual hook test:
   ```bash
   echo '{"session_id":"test","cwd":"/tmp"}' | \
   python3 ~/.claude/plugins/cc-retrospect/scripts/dispatch.py stop_hook
   ```

## State recovery

**Symptom**: "No sessions yet" even after running sessions.

**Fix**:
1. Check if sessions exist:
   ```bash
   ls ~/.cc-retrospect/sessions.jsonl
   wc -l ~/.cc-retrospect/sessions.jsonl
   ```

2. Verify JSONL format:
   ```bash
   head -1 ~/.cc-retrospect/sessions.jsonl | python3 -m json.tool
   ```
   Should be valid JSON.

3. Rebuild cache:
   ```bash
   /cc-retrospect:reset
   /cc-retrospect:status
   ```

## Permission errors

**Symptom**: `Permission denied: ~/.cc-retrospect/`

**Fix**:
```bash
chmod 755 ~/.cc-retrospect/
rm ~/.cc-retrospect/*.json
rm ~/.cc-retrospect/*.jsonl
```

## Config not loading

**Symptom**: Settings in `~/.cc-retrospect/config.env` not applied.

**Fix**:
1. Check syntax:
   ```bash
   cat ~/.cc-retrospect/config.env
   ```
   Should be `KEY=VALUE` format (not YAML).

2. Verify keys:
   ```bash
   /cc-retrospect:config
   ```
   Shows current values.

3. Reload:
   ```bash
   python3 -c "from cc_retrospect.config import load_config; c = load_config(); print(c.hints)"
   ```

## Deps not found

**Symptom**: `ModuleNotFoundError: pydantic`

**Fix**:
```bash
cd ~/.claude/plugins/cc-retrospect
pip install -e .
```

Or with uv:
```bash
uv pip install -e ~/.claude/plugins/cc-retrospect
```

## Large JSONL corruption

**Symptom**: `sessions.jsonl` partially corrupted (broken lines).

**Fix** (safely):
```bash
# Backup
cp ~/.cc-retrospect/sessions.jsonl ~/.cc-retrospect/sessions.jsonl.bak

# Validate and rebuild
python3 << 'EOF'
from pathlib import Path
from cc_retrospect.parsers import iter_jsonl

old_path = Path.home() / ".cc-retrospect" / "sessions.jsonl"
backup_path = old_path.with_suffix(".jsonl.backup")

valid_lines = []
for line in old_path.read_text().splitlines():
    try:
        import json
        json.loads(line)
        valid_lines.append(line)
    except:
        pass

old_path.rename(backup_path)
old_path.write_text("\n".join(valid_lines) + "\n")
print(f"Recovered {len(valid_lines)} valid lines. Backup: {backup_path}")
EOF
```

## Still stuck?

- Check logs: `CC_RETROSPECT_LOG_LEVEL=DEBUG /cc-retrospect:status 2>&1 | head -20`
- Run smoke test: `make smoke`
- Open an issue with error message and Python version
