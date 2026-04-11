"""cc-retrospect exceptions — Custom exception hierarchy for specific error handling."""
from __future__ import annotations


class CCRetroError(Exception):
    """Base exception for all cc-retrospect errors."""


class SessionParseError(CCRetroError):
    """Raised when a session JSONL file cannot be parsed."""


class CacheCorruptError(CCRetroError):
    """Raised when cache data is malformed or corrupted."""


class ConfigError(CCRetroError):
    """Raised when configuration is invalid or cannot be loaded."""


class DashboardError(CCRetroError):
    """Raised when dashboard generation or serving fails."""
