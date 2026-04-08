"""cc-retrospect — Claude Code session analysis plugin."""

__version__ = "2.1.0"

try:
    from cc_retrospect.core import (
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
