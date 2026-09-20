"""Babysitter — a local runtime supervisor for AI coding agents.

A model can claim success. Babysitter requires evidence.
"""

__version__ = "0.1.0"

from .schema import SCHEMA_VERSION, STAGES, TASK_STATUSES, TERMINAL_STATUSES

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "STAGES",
    "TASK_STATUSES",
    "TERMINAL_STATUSES",
]
