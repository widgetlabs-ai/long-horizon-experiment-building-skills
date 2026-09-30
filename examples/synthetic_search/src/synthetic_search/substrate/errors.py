"""Exit codes and the two error kinds, shared by every command.

The distinction is the whole point: a candidate that lost is ordinary and the
run continues; a substrate that cannot score anything must stop the run, or a
weekend of generations measures nothing and says so in no way anybody notices.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_LOST = 1
EXIT_SUBSTRATE = 2


class SubstrateError(RuntimeError):
    """The measuring apparatus is broken. Stop the run (exit 2)."""


class CandidateError(RuntimeError):
    """This candidate is unusable. Score it zero and keep going (exit 1)."""
