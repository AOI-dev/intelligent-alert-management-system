"""Built-in reference plugins.

These are minimal, pass-through implementations that keep the platform running
when no external plugins are configured. Replace or extend them by adding
paths to PLUGIN_PATHS.
"""

from app.plugins.builtins.correlation import PassThroughCorrelator
from app.plugins.builtins.enrichment import IdentityEnricher
from app.plugins.builtins.execution import LoggingExecutor

__all__ = ["PassThroughCorrelator", "IdentityEnricher", "LoggingExecutor"]
