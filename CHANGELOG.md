# Changelog

All notable changes to cc-retrospect.

## v2.2.0 (audit improvements) — In Development

### Added
- **PR 4: UX Improvements**
  - `--help`, `--verbose`, `--project`, `--days`, `--exclude`, `--json` flags
  - Argparse support for better CLI help
  - `/reset` command requires "y" confirmation on TTY
  - `/reset` prints what will be deleted before confirming
  - `/status` shows "No sessions yet" instead of "unknown"
  - Progress printing on large cache scans ("Scanning... 50 sessions")

- **PR 5: New Skills**
  - `/cc-retrospect:fix` — Run waste analysis, Claude generates concrete fixes
  - `/cc-retrospect:budget` — Cost analysis with budget planning
  - `/cc-retrospect:diff` — Compare two sessions side-by-side
  - `/cc-retrospect:optimize-later` — Optimize dispatch model selection
  - `/cc-retrospect:exclude` — Manage exclusion patterns

- **PR 6: cc-later Integration**
  - `HintsConfig.waste_to_later: bool` — write waste entries to `~/.claude/LATER.md`
  - `model_recommendation.json` written after each session
  - Tag dispatch sessions in cost output

- **PR 7: DevX World-Class**
  - `Makefile` with 8 targets (test, lint, format, smoke, install, dev, clean, help)
  - `.pre-commit-config.yaml` (ruff + pyright)
  - `.editorconfig` (4 spaces, UTF-8, LF)
  - `install.sh` supports `--uninstall`, `--upgrade`, `--dry-run`
  - `CONTRIBUTING.md` (fork/branch, dev setup, PR checklist)
  - `.github/workflows/test.yml` (Python 3.10-3.13, ruff, pytest, smoke test)
  - `pyproject.toml` ruff as dev dep, project URLs added

- **PR 8: Documentation**
  - `CLAUDE.md` — dev conventions, test patterns, PR checklist
  - `CHANGELOG.md` — this file
  - `docs/troubleshooting.md` — cache bloat, hook debug, state recovery
  - `docs/architecture.md` — mermaid diagram of modules

### Changed
- `/status` health check now shows count on large caches with progress
- `/reset` is now interactive (requires confirmation)
- README badges and install clarity

## v2.1.0 (current stable)

- Token tracking and waste detection
- 18 slash commands
- Cost breakdowns by model
- Daily digest and health checks
- Compaction tracking
- Weekly trends
- 8 behavioral skills
