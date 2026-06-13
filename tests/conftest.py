from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOT_STR = str(ROOT)

if sys.path[0] != ROOT_STR:
    try:
        sys.path.remove(ROOT_STR)
    except ValueError:
        pass
    sys.path.insert(0, ROOT_STR)
