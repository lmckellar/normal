from __future__ import annotations

from pathlib import Path
from typing import Any


def contained_resolve(raw: Any, source: Path) -> tuple[Path, bool]:
    resolved = Path(str(raw)).expanduser().resolve()
    try:
        resolved.relative_to(source.resolve())
    except ValueError:
        return resolved, False
    return resolved, True
