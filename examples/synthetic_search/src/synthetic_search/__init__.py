"""synthetic_search — a worked long-horizon search over an editable rule table.

The package is imported in two very different environments: the orchestrator
process, which needs the taskset and therefore the eval framework, and the
rollout container, which needs only the substrate. A module-level import of
`taskset` would drag the framework into the container and fail its build, so
the accessor below is lazy (PEP 562).
"""

from __future__ import annotations

__all__ = ["taskset"]


def __getattr__(name: str):
    if name == "taskset":
        import importlib

        return importlib.import_module("synthetic_search.taskset")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
