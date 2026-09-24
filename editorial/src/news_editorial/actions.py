"""Action handlers. Each takes the parsed arguments and returns the `result` object."""

from __future__ import annotations

import argparse
from typing import Any

from .cli import ACTIONS, action


@action("list-actions")
def list_actions(_: argparse.Namespace) -> dict[str, Any]:
    return {"actions": [{"name": name, **spec} for name, spec in sorted(ACTIONS.items())]}
