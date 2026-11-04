"""Temporary test databases must release intentional pools before Windows deletion."""
from pathlib import Path
import sys
import tempfile


class DatabaseTemporaryDirectory(tempfile.TemporaryDirectory):
    def cleanup(self):
        root = Path(self.name).resolve()
        database = sys.modules.get('app.core.database')
        if database is not None:
            pool = getattr(database._TLS, 'pool', {})
            for key in list(pool):
                if Path(key).resolve().is_relative_to(root):
                    for connection in pool.pop(key):
                        connection._real_close()
                    with database._WAL_LOCK:
                        database._WAL_READY.discard(key)
        dates = sys.modules.get('app.core.work_dates')
        if dates is not None:
            handles = getattr(dates._SCOPED_TLS, 'handles', {})
            for key in list(handles):
                if Path(key).resolve().is_relative_to(root):
                    connection = handles.pop(key)
                    if connection._in_use:
                        raise RuntimeError('Test database still has an active scoped reader')
                    connection.close()
        cache = sys.modules.get('app.services.flow_image_cache')
        if cache is not None:
            with cache._LOCK:
                key = cache._POOLED_REG_PATH
                if key and Path(key).resolve().is_relative_to(root):
                    if cache._POOLED_REG_CON is not None:
                        cache._POOLED_REG_CON._real_close()
                    cache._POOLED_REG_CON = None
                    cache._POOLED_REG_PATH = None
        super().cleanup()
