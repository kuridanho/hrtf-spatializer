#!/usr/bin/env python3
"""Source-tree entry point.

Prefer ``python -m spatializer`` after ``pip install -e .``.  This shim keeps
``python main.py`` working directly from a checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from spatializer.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
