# cc-retrospect Comprehensive Audit Plan

## Context

Full audit of cc-retrospect (v2.1.0) uncovered **7 critical bugs**, **10+ hardening issues**, and opportunities for new features, cc-later integration, and a monolith split. The 69MB sessions.jsonl cache has 85,097 duplicate entries (129 unique). Stop hook state isn't persisting. User wants everything fixed plus cc-later integration, session exclusion, and improved cost analytics.

---

## Phase 1: Critical Bug Fixes

### 1.1 Cache Deduplication (CRITICAL)
**File:** `cc_retrospect/core.py` — `load_all_sessions()` ~line 795

**Bug:** After reading cache into `cached` dict (keyed by session_id), disk scan appends ALL sessions to cache file — including ones already present. 129 sessions → 85,226 entries.

**Fix:**
- In `load_all_sessions()`: after building `cached` dict, compare `raw_line_count` vs `len(cached)`. If mismatch, rewrite file atomically (write temp + `os.replace`)
- In `run_stop_hook()` line 1276: before appending, check if `summary.session_id` already in cache file (quick set scan)
- **Nuke existing cache** — delete `~/.cc-retrospect/sessions.jsonl`, let rebuild happen naturally

### 1.2 Stop Hook State Overwrite
**File:** `cc_retrospect/core.py` — `run_session_start_hook()` ~line 1346-1356

**Bug:** First-run branch writes `{"first_run": ...}` via `state_path.write_text()` — destroys any existing state fields. Subsequent session start reads/merges correctly, but this initial write is destructive.

**Fix:** Change first-run branch to read-merge-write: read existing state (if any), merge `first_run` key, write back.

### 1.3 Timezone "Z" Suffix
**File:** `cc_retrospect/core.py` — `_should_show_daily_digest()` line 2030

**Bug:** `datetime.fromisoformat(last_ts)` fails on "Z" suffix (Python <3.11). Other locations already handle this.

**Fix:** `datetime.fromisoformat(last_ts.replace("Z", "+00:00"))`

### 1.4 IndexError in TrendAnalyzer
**File:** `cc_retrospect/core.py` — line 1061

**Bug:** `weeks[-2]` accessed without length check.

**Fix:** Already guarded at line 1060 (`if len(weeks) >= 2`) — BUT `weeks` variable may reference the unfiltered list. Use same sorted reference for safety.

### 1.5 Race Condition on state.json
**File:** `cc_retrospect/core.py` — lines 1278-1296, 1356, 1424

**Fix:** Create `_atomic_write_json(path, data)` helper using temp file + `os.replace()`. Apply to all state writes.

### 1.6 Hardcoded Pricing in User Profile
**File:** `cc_retrospect/core.py` — line 1793

**Bug:** `usage.get("input_tokens", 0) / 1e6 * 15` — magic numbers instead of config.pricing.

**Fix:** Use `_pricing_for_model(model, config.pricing)` lookup.

### 1.7 Custom Analyzer Security Warning
**File:** `cc_retrospect/core.py` — lines 777-789

**Fix:** Add WARNING-level log when loading custom analyzers. Add docstring warning. Add note in docs.

---

## Phase 2: Hardening

| Fix | Location | Change |
|-----|----------|--------|
| Log silent exceptions | lines 504, 863, 1282, 1363, 1399 | Add `logger.debug(...)` with `as e` |
| Explicit UTF-8 encoding | 7 `read_text()` calls | Add `encoding="utf-8"` |
| Safe dict access | line 1332 `state["today_cost"]` | → `state.get("today_cost", 0)` |
| Session ID validation | `run_stop_hook` line 1265 | Regex check: `^[a-zA-Z0-9_-]+$` |
| Remove redundant getattr | line 1542 | `live.mega_prompt_count += 1` |
| Date string robustness | 8 `[:10]` slice locations | Add comment, consider `datetime.date()` |

---

## Phase 3: New Feature — `/exclude` and Session Filtering

### 3.1 Exclusion Config
**File:** `cc_retrospect/config.py` (post-split) or `core.py`

Add to `Config`:
```python
class FilterConfig(BaseModel):
    exclude_projects: list[str] = []  # regex patterns
    exclude_entrypoints: list[str] = ["cc-retrospect", "cc-later"]
    exclude_sessions_shorter_than: int = 0  # minutes
```

Env var: `FILTER__EXCLUDE_PROJECTS=compact,retro,worktree`
Env var: `FILTER__EXCLUDE_ENTRYPOINTS=cc-retrospect,cc-later`

### 3.2 Exclusion Logic
**File:** `cc_retrospect/core.py` — `load_all_sessions()` and `_filter_sessions()`

Add filtering step after loading:
```python
def _filter_sessions(sessions, *, project=None, days=None, config=None):
    # existing project/days filters...
    if config and config.filter:
        for pat in config.filter.exclude_projects:
            sessions = [s for s in sessions if pat.lower() not in s.project.lower()]
        for ep in config.filter.exclude_entrypoints:
            sessions = [s for s in sessions if ep.lower() not in (s.entrypoint or "").lower()]
        if config.filter.exclude_sessions_shorter_than > 0:
            sessions = [s for s in sessions if s.duration_minutes >= config.filter.exclude_sessions_shorter_than]
    return sessions
```

### 3.3 CLI Flag
Add `--exclude PATTERN` to dispatch.py CLI, passed through to `_filter_sessions()`.

### 3.4 `/cc-retrospect:exclude` Command
New command `commands/exclude.md` to manage exclusion patterns interactively.

---

## Phase 4: Improved Cost Analytics & Pricing

### 4.1 Update Pricing to Current Figures
**File:** `cc_retrospect/core.py` — `PricingConfig`, `ModelPricing`

Current pricing is outdated. Update defaults to latest Anthropic pricing:

```python
class ModelPricing(BaseModel):
    opus: PricingConfig = PricingConfig(
        input_per_mtok=15.0, output_per_mtok=75.0,
        cache_create_per_mtok=18.75, cache_read_per_mtok=1.50
    )
    sonnet: PricingConfig = PricingConfig(
        input_per_mtok=3.0, output_per_mtok=15.0,
        cache_create_per_mtok=3.75, cache_read_per_mtok=0.30
    )
    haiku: PricingConfig = PricingConfig(
        input_per_mtok=0.80, output_per_mtok=4.0,
        cache_create_per_mtok=1.0, cache_read_per_mtok=0.08
    )
```

Verify against https://docs.anthropic.com/en/docs/about-claude/models — update if stale.

### 4.2 Enhanced Cost Breakdown in CostAnalyzer
**File:** `cc_retrospect/core.py` — `CostAnalyzer.analyze()` ~line 418

Add to output:
- **Per-token-type breakdown**: input vs output vs cache_create vs cache_read cost
- **Cache efficiency**: `(cache_read_cost_saved / hypothetical_input_cost) * 100`
- **Cost per message**: total_cost / message_count
- **Cost per minute**: total_cost / duration_minutes
- **Model split**: % of cost on Opus vs Sonnet vs Haiku
- **"What-if" scenarios**: If all Opus → Sonnet, if all Sonnet → Haiku

### 4.3 Cost Trend Sparkline
In `/digest` and `/trends` output, add ASCII sparkline of daily costs:
```
Last 7 days: ▁▃▅▇▅▂▁ ($12 → $89 → $45)
```

### 4.4 Pricing Auto-Detect from Model Strings
**File:** `core.py` — `_pricing_for_model()`

Currently prefix-matches "opus", "sonnet", "haiku". Add support for:
- `claude-opus-4-6`, `claude-opus-4-5` → opus pricing
- `claude-sonnet-4-6`, `claude-sonnet-4-5` → sonnet pricing
- `claude-haiku-4-5` → haiku pricing
- Unknown → log warning, default to opus (conservative)

---

## Phase 5: Monolith Split

Split `cc_retrospect/core.py` (2032 lines) into:

| New Module | Content | ~LOC |
|------------|---------|------|
| `config.py` | PricingConfig, ModelPricing, ThresholdsConfig, HintsConfig, MessagesConfig, FilterConfig, Config, load_config() | 160 |
| `models.py` | UsageRecord, SessionSummary, Section, Recommendation, AnalysisResult, CompactionEvent, LiveSessionState, UserProfile, Analyzer protocol | 120 |
| `parsers.py` | iter_jsonl(), iter_project_sessions(), extract_usage(), _pricing_for_model(), compute_cost(), analyze_session() | 200 |
| `utils.py` | display_project(), _fmt_*(), _filter_sessions(), _render(), _group(), _top() | 60 |
| `analyzers.py` | All 9 analyzer classes + get_analyzers() | 370 |
| `cache.py` | load_all_sessions(), live state helpers, _atomic_write_json() | 80 |
| `hooks.py` | All 7 run_*_hook() functions, _should_show_daily_digest(), trend helpers | 360 |
| `commands.py` | All 18 run_*() commands | 360 |
| `learn.py` | analyze_user_messages(), generate_style(), generate_learnings() | 400 |

**Backward compat:** `core.py` becomes a re-export shim:
```python
from cc_retrospect.config import *
from cc_retrospect.models import *
# ... etc
```

All tests and dispatch.py continue importing from `cc_retrospect.core` unchanged.

**Import dependency graph:**
```
config → models → parsers → utils → cache → analyzers → learn
                                                ↓          ↓
                                             commands ← hooks
```

---

## Phase 6: UX/DevX Improvements

| Change | File | Detail |
|--------|------|--------|
| `--help` support | `scripts/dispatch.py` | Migrate commands to argparse (keep stdin for hooks) |
| `--verbose` flag | `scripts/dispatch.py` | Sets `CC_RETROSPECT_LOG_LEVEL=DEBUG` |
| Confirm on `/reset` | `commands.py` | Print what will be deleted, require "y" if TTY |
| Fix `/status` display | `commands.py` | Show "No sessions yet" instead of "unknown" |
| Progress on large scans | `cache.py` | Print counter to stderr every 50 sessions |

---

## Phase 7: New Skills

### 7.1 `/cc-retrospect:fix` (hybrid)
Run `waste --json`, Claude generates concrete fixes per project (CLAUDE.md rules, shell aliases, workflow changes).

### 7.2 `/cc-retrospect:budget` (hybrid)
Run `cost --json --days 7`, ask user target budget, calculate gap, recommend threshold changes.

### 7.3 `/cc-retrospect:diff` (hybrid)
List recent sessions, user picks two, side-by-side comparison with Claude interpretation.

### 7.4 `/cc-retrospect:optimize-later` (hybrid)
Read `~/.cc-later/run_log.jsonl` + cc-retrospect sessions, cross-reference dispatch costs, recommend DISPATCH_MODEL.

### 7.5 `/cc-retrospect:exclude` (command)
Interactive exclusion pattern management — list current exclusions, add/remove patterns, preview affected sessions.

---

## Phase 8: cc-later Integration

### 8.1 Waste → LATER.md Auto-Entries
**Config:** `HintsConfig.waste_to_later: bool = False`

In `run_stop_hook()`, after building waste_flags, if enabled:
- Map waste to LATER.md tasks: `- [ ] (P1) Fix: {description} [cc-retrospect auto]`
- Append to `.claude/LATER.md` (project cwd from payload)
- Deduplicate by checking for `[cc-retrospect auto]` tag

### 8.2 Model Routing → DISPATCH_MODEL
Write `~/.cc-retrospect/model_recommendation.json` after trend update:
```json
{"recommended_model": "sonnet", "reason": "85% simple tasks", "confidence": 0.85}
```
cc-later reads this at dispatch time as override suggestion.

### 8.3 Dispatch Cost Tagging
Detect sessions with entrypoint containing "cc-later" → tag as dispatch sessions in CostAnalyzer output. Add "Dispatch" column when detected.

### 8.4 Cross-Plugin `/optimize-later` Skill
Already covered in Phase 7.4 — reads both plugins' data.

---

## Phase 9: World-Class DevX & Install UX

### Current State Assessment

**Install paths (3 methods):**
1. Marketplace: `/plugin marketplace add` — works but undocumented error recovery
2. One-liner: `git clone && install.sh` — decent, has color output + backfill prompt
3. Manual: `git clone && pip install -e .` — bare minimum

**DevX gaps found:**

| Gap | Impact | Fix |
|-----|--------|-----|
| No `make` / task runner | Contributors must memorize test/lint/smoke commands | Add `Makefile` |
| install.sh has no `--uninstall` | Manual cleanup if something breaks | Add uninstall flag |
| install.sh doesn't verify Python version | Silent failure on Python 3.9 | Add version check |
| install.sh doesn't check if already installed | Re-runs full pip install unnecessarily | Add upgrade detection |
| No `--dry-run` for install | Users can't preview what happens | Add dry-run flag |
| No health check after marketplace install | User doesn't know if hooks loaded | Add post-install verification skill |
| `pyflakes` only linter — no formatter | Inconsistent style across PRs | Add `ruff` (lint+format) |
| No pre-commit hooks | Contributors can push broken code | Add `.pre-commit-config.yaml` |
| No `CONTRIBUTING.md` | Unclear contribution process | Add file |
| CI doesn't run on Python 3.13 | Missing newest Python compat | Add to matrix |
| No badge in README | No visual trust signals | Add CI + coverage badges |
| No `py.typed` export verification in CI | Type checking not validated | Add mypy/pyright step |
| Smoke test in CI uses raw Python, not dispatch.py | Doesn't test real entry point | Fix smoke test |
| No editorconfig | Tab vs space inconsistency risk | Add `.editorconfig` |
| release.yml doesn't publish to PyPI | Can't `pip install cc-retrospect` | Add PyPI publish step |

### 9.1 Makefile
```makefile
.PHONY: test lint smoke install dev clean

test:        pytest tests/ -v --cov=cc_retrospect --ignore=tests/test_real_data.py
lint:        ruff check cc_retrospect/ scripts/ tests/
format:      ruff format cc_retrospect/ scripts/ tests/
smoke:       python3 scripts/dispatch.py status && python3 scripts/dispatch.py cost
install:     pip install -e ".[test]"
dev:         pip install -e ".[test]" && pip install ruff pre-commit && pre-commit install
clean:       rm -rf .coverage .pytest_cache __pycache__ dist build *.egg-info
```

### 9.2 Enhanced install.sh
- Add `--uninstall` flag (removes pip package + offers to delete `~/.cc-retrospect/`)
- Add `--upgrade` flag (pulls latest git + reinstall)
- Add `--dry-run` flag (print what would happen)
- Add Python version check (`python3 -c "import sys; assert sys.version_info >= (3, 10)"`)
- Add already-installed detection (skip pip if version unchanged)
- Add post-install health check (run `dispatch.py status` and validate output)
- Add color-coded summary with hook count + command count

### 9.3 Post-Install Verification Skill
New `skills/verify/SKILL.md`:
- Run `dispatch.py status` and parse output
- Check that hooks.json is loadable
- Verify pydantic version >=2.0
- Run a test session analysis on a sample fixture
- Report: "All 7 hooks active, 18 commands available, 9 skills loaded"

### 9.4 Developer Tooling
- Add `.pre-commit-config.yaml` with ruff + pyflakes
- Add `.editorconfig` (4 spaces, UTF-8, LF)
- Add `ruff` to CI (replace pyflakes — ruff is a superset)
- Add Python 3.13 to CI matrix
- Add README badges: CI status, coverage, Python versions, license

### 9.5 CONTRIBUTING.md
- Fork + branch workflow
- Run `make dev` for setup
- Run `make test lint` before PR
- Analyzer contribution guide (protocol, registration, test pattern)
- Skill contribution guide (SKILL.md format, hybrid pattern)

### 9.6 PyPI Publishing
- Update `release.yml` to publish to PyPI on tag push
- Add `pypi-publish` step using `pypa/gh-action-pypi-publish`
- Users can then: `pip install cc-retrospect` (no git clone needed)
- Add `[project.urls]` to pyproject.toml (Homepage, Documentation, Changelog)

---

## Phase 10: Documentation (folded into each PR)

| File | Change |
|------|--------|
| `CLAUDE.md` (new) | Dev conventions, test patterns, PR checklist |
| `CHANGELOG.md` (new) | v2.1.0 current, v2.2.0 this audit |
| `docs/commands.md` | Fix skill count (8→9+new), add /exclude |
| `docs/troubleshooting.md` (new) | Cache bloat, hook debugging, state recovery |
| `docs/architecture.md` | Add mermaid diagram for new module structure |
| `docs/configuration.md` | Add FilterConfig docs, updated pricing |

---

## Implementation Order

```
PR 1: fix/critical-bugs           — Phases 1 + 2 (bugs + hardening)
PR 2: feat/exclude-and-pricing    — Phases 3 + 4 (/exclude + cost analytics)
PR 3: refactor/split-monolith     — Phase 5 (depends on PR 1+2)
PR 4: feat/ux-improvements        — Phase 6 (depends on PR 3)
PR 5: feat/new-skills             — Phase 7 (depends on PR 3)
PR 6: feat/cc-later-integration   — Phase 8 (depends on PR 3)
PR 7: chore/devx-world-class      — Phase 9 (Makefile, install.sh, ruff, pre-commit, PyPI, badges)
PR 8: docs/comprehensive-update   — Phase 10 (folded: CLAUDE.md, CHANGELOG, troubleshooting, mermaid)
```

PRs 1+2 parallel. PRs 4-8 parallel after PR 3. Docs folded into each PR as touched.

---

## Verification

After each PR:
1. `pytest tests/ -v --cov=cc_retrospect --cov-report=term-missing`
2. `pyflakes cc_retrospect/ scripts/ tests/`
3. Smoke test: `python3 scripts/dispatch.py status`
4. Smoke test: `python3 scripts/dispatch.py cost --days 7`
5. After PR 1: verify `wc -l ~/.cc-retrospect/sessions.jsonl` shows ~129 lines (not 85K)
6. After PR 3: verify ALL existing tests pass with zero modifications
7. After PR 6: verify `ls ~/.cc-retrospect/model_recommendation.json` exists after stop hook

---

## Key Files

| File | Role |
|------|------|
| `cc_retrospect/core.py` | Monolith being split (every phase touches this) |
| `scripts/dispatch.py` | Entry point (Phase 6 argparse migration) |
| `cc_retrospect/__init__.py` | Re-exports (Phase 5) |
| `tests/test_integration.py` | Main validation (must pass after split) |
| `tests/test_full_coverage.py` | Edge case coverage (add new tests) |
| `hooks/hooks.json` | Hook definitions (verify after changes) |
| `/Users/srinivasvaddi/Projects/later/cc_later/core.py` | cc-later source (Phase 8 reference) |
