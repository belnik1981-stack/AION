"""The widget installer must preserve a pre-existing owner shortcut."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install_termux_widget.sh"

with TemporaryDirectory() as temporary:
    shortcut_dir = Path(temporary) / "shortcuts"
    environment = dict(os.environ, AION_WIDGET_SHORTCUTS_DIR=str(shortcut_dir))

    first = subprocess.run(["bash", str(INSTALLER)], env=environment,
                           capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    shortcut = shortcut_dir / "AION_stage1"
    original = shortcut.read_bytes()
    assert shortcut.stat().st_mode & 0o077 == 0
    assert b"termux_widget_start.sh" in original
    assert b"AION_API_KEY" not in original

    repeated = subprocess.run(["bash", str(INSTALLER)], env=environment,
                              capture_output=True, text=True)
    assert repeated.returncode == 0 and shortcut.read_bytes() == original

    shortcut.write_text("owner shortcut\n", encoding="utf-8")
    conflict = subprocess.run(["bash", str(INSTALLER)], env=environment,
                              capture_output=True, text=True)
    assert conflict.returncode != 0
    assert shortcut.read_text(encoding="utf-8") == "owner shortcut\n"

print("TERMUX WIDGET INSTALLER: PASS")
