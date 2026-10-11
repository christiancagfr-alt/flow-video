"""Redirect Python and native diagnostics before Qt is imported."""
import os
import sys
from pathlib import Path
_stream = None

def configure():
    global _stream
    if _stream is not None:
        return
    folder = Path(__file__).resolve().parents[2] / 'data' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'runtime.log'
    try:
        if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
            path.replace(folder / 'runtime.previous.log')
    except OSError:
        pass
    _stream = path.open('a', encoding='utf-8', buffering=1)
    for fd in (1, 2):
        try:
            os.dup2(_stream.fileno(), fd)
        except OSError:
            pass
    sys.stdout = sys.stderr = _stream
    os.environ.setdefault('QT_LOGGING_RULES', 'qt.multimedia.*=false')
