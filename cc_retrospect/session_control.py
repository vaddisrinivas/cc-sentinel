"""cc-retrospect session control — auto-compact and model nudge."""
from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger("cc_retrospect")


def send_compact(session_id: str) -> bool:
    """Send /compact to a running Claude session via subprocess.

    Returns True if the command was dispatched successfully.
    """
    if not session_id:
        return False
    try:
        result = subprocess.run(
            ["claude", "-p", "--resume", session_id, "/compact"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info("Auto-compact sent to session %s", session_id)
            return True
        logger.warning("Auto-compact failed for session %s: %s", session_id, result.stderr)
        return False
    except FileNotFoundError:
        logger.warning("claude CLI not found — auto-compact unavailable")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Auto-compact timed out for session %s", session_id)
        return False
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("Auto-compact error: %s", e)
        return False


def model_nudge(context: dict) -> str | None:
    """Generate a model nudge string if Opus is being used for simple tasks.

    Args:
        context: dict with keys like 'tool_name', 'tool_input', 'model', 'live_state'

    Returns:
        additionalContext string if nudge should be shown, None otherwise.
    """
    tool_name = context.get("tool_name", "")
    # Simple tools that don't need Opus
    simple_tools = {"Read", "Edit", "Write", "Glob", "Grep", "Bash"}
    # Complex tools that justify Opus
    complex_tools = {"Agent", "WebSearch", "WebFetch", "EnterPlanMode", "TodoWrite"}

    if tool_name in complex_tools:
        return None  # Opus is justified

    live = context.get("live_state")
    if not live:
        return None

    # Only nudge if we've seen enough simple-only tool usage
    tool_count = getattr(live, "tool_count", 0)
    subagent_count = getattr(live, "subagent_count", 0)

    if tool_count < 10:
        return None  # Too early to judge

    if subagent_count > 0:
        return None  # Session uses complex features

    if tool_name in simple_tools:
        return "[cc-retrospect] This session uses only simple tools (Read/Edit/Bash). Consider switching to Sonnet for ~80% cost savings: /model sonnet"

    return None
