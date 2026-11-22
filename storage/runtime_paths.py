"""Optional external directory for mutable AION data.

Without AION_DATA_DIR the historical checkout paths remain unchanged.  The
Termux widget sets a stable private directory so Git checkouts can change
without moving the owner's operational memory.
"""

import os
from pathlib import Path


def runtime_root(project_root: Path) -> Path:
    configured = os.getenv("AION_DATA_DIR", "").strip()
    if not configured:
        return project_root
    path = Path(configured).expanduser()
    if not path.is_absolute():
        raise ValueError("AION_DATA_DIR должен быть абсолютным путём")
    return path
