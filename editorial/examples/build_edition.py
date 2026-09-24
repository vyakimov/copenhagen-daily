#!/usr/bin/env python3
"""Rebuild a golden example's contract from its spec.

The real tool is `edit_news.sh build`; this shim keeps the archived examples rebuildable from the
repository root: `editorial/examples/build_edition.py <spec.json> <edition.json>`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[1] / "edit_news.sh"

if __name__ == "__main__":
    spec, out = sys.argv[1], sys.argv[2]
    run_dir = Path(spec).resolve().parent
    sys.exit(subprocess.call([str(WRAPPER), "build", "--run", str(run_dir), "--spec", spec, "--output", out]))
