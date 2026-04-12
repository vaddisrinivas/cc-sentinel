"""cc-retrospect — Claude Code session analysis plugin."""

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("cc-retrospect")
except Exception:
    __version__ = "3.0.0rc2"

try:
    from cc_retrospect.core import (  # noqa: F401
        AnalysisResult,
        Config,
        Recommendation,
        Section,
        SessionSummary,
    )

    __all__ = [
        "__version__",
        "AnalysisResult",
        "Config",
        "Recommendation",
        "Section",
        "SessionSummary",
    ]
except ImportError:
    __all__ = ["__version__"]
