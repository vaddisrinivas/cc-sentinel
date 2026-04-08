# /cc-retrospect:exclude

Manage exclusion patterns for session filtering.

## Description

Configure which projects, entrypoints, or session types to exclude from cost tracking and analysis. Useful for filtering out test sessions, demo projects, or internal tools that shouldn't count toward your spending analysis.

## Usage

```
/cc-retrospect:exclude [--list]
/cc-retrospect:exclude [--add PROJECT_PATTERN]
/cc-retrospect:exclude [--remove PROJECT_PATTERN]
```

## Configuration

Edit `~/.cc-retrospect/config.env`:

```env
# Exclude projects by name
FILTER__EXCLUDE_PROJECTS=test-project,demo,sandbox

# Exclude by entrypoint (e.g., cc-retrospect self-runs, cc-later)
FILTER__EXCLUDE_ENTRYPOINTS=cc-retrospect,cc-later

# Exclude sessions shorter than N minutes
FILTER__EXCLUDE_SESSIONS_SHORTER_THAN=2
```

## Examples

### List current exclusions

```
/cc-retrospect:exclude --list
```

Output:
```
Exclusion patterns:

  Projects: test-project, demo, sandbox
  Entrypoints: cc-retrospect, cc-later
  Min duration: 2 minutes
```

### Add exclusion

```
/cc-retrospect:exclude --add my-temp-project
```

### Remove exclusion

```
/cc-retrospect:exclude --remove test-project
```

## Notes

- Patterns are case-sensitive
- Changes apply immediately to cost analysis
- Excluded sessions still logged (not deleted)
- Useful for A/B testing or separating work streams
