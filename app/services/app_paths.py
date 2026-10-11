"""Writable state outside macOS application bundles; legacy source layout stays stable."""
import os
import sys
from pathlib import Path
APP_ROOT = Path(__file__).resolve().parents[2]
def data_dir():
    override = os.environ.get('FLOWSTUDIO_DATA_DIR', '').strip()
    if override: return Path(override).expanduser()
    if sys.platform == 'darwin' and any(p.suffix == '.app' for p in APP_ROOT.parents):
        return Path.home() / 'Library/Application Support/FlowStudio/data'
    return APP_ROOT / 'data'
