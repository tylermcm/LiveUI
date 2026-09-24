import os
import sys
from pathlib import Path

import PySide6


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Some conda installations report ``site-packages/plugins`` through
# QLibraryInfo even though the platform DLLs live under ``PySide6/plugins``.
# Pointing at the package-owned directory is harmless on standard wheels and
# makes the test environment deterministic on those installations.
_PYSIDE_PLATFORM_PLUGINS = Path(PySide6.__file__).parent / "plugins" / "platforms"
if _PYSIDE_PLATFORM_PLUGINS.is_dir():
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_PYSIDE_PLATFORM_PLUGINS))

EXAMPLE_ROOT = Path(__file__).parents[1] / "examples" / "provenance_demo"
sys.path.insert(0, str(EXAMPLE_ROOT))
