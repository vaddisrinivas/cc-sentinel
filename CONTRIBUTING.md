# Contributing to cc-retrospect

Want to fix a bug or add a feature? Great! Follow these steps.

## Setup

1. Fork and clone:
   ```bash
   git clone https://github.com/YOUR_FORK/cc-retrospect
   cd cc-retrospect
   ```

2. Create a feature branch:
   ```bash
   git checkout -b fix/your-issue-name
   ```

3. Install dev dependencies:
   ```bash
   make dev
   ```

## Development workflow

- **Run tests before pushing:**
  ```bash
  make test
  ```

- **Format and lint:**
  ```bash
  make lint
  make format
  ```

- **Quick sanity check:**
  ```bash
  make smoke
  ```

## PR checklist

- [ ] Tests pass: `make test`
- [ ] Linting passes: `make lint`
- [ ] Code formatted: `make format`
- [ ] Smoke test passes: `make smoke`
- [ ] PR description explains the change
- [ ] Commits are clean (1 logical change per commit)
- [ ] No debugging print statements left in

## Code style

- Python: follow PEP 8 (enforced by ruff)
- Type hints required on public functions
- Docstrings on classes and public methods
- 88-char line limit (ruff default)

## Testing

Tests live in `tests/`. Add tests for any new commands or analyzers:

```python
def test_new_command():
    config = default_config()
    result = run_new_command({}, config=config)
    assert result == 0
```

Run with: `make test`

## Commit messages

Use conventional commits:
- `fix:` bug fixes
- `feat:` new features
- `docs:` documentation
- `test:` test additions
- `refactor:` code cleanup

Example:
```
fix: reset command requires confirmation on TTY

- Add _get_confirmation() helper for safe deletion
- Print what will be deleted before asking
- Respect non-TTY environments (no prompt)
```

## Questions?

Open an issue or ask in a PR. All contributors are welcome.
