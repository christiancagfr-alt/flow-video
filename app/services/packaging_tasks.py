"""Exact task/output association; never guess a script from a filename."""
import os
from collections import OrderedDict
from pathlib import Path
from app.core import work_dates

_PATH_KEY_CACHE: "OrderedDict[str, tuple[str, str]]" = OrderedDict()

def edited_tasks(work_date=None):
    with work_dates.read_connection(work_date) as con:
        return [dict(row) for row in con.execute("SELECT id,edit_output_path,original_script,production_script,script FROM videos WHERE edit_status IN ('已导出','已完成') AND edit_output_path<>''")]

def resolved_path_str(path) -> str:
    raw = str(path or '')
    hit = _PATH_KEY_CACHE.get(raw)
    if hit is not None:
        _PATH_KEY_CACHE.move_to_end(raw)
        return hit[0]
    resolved = str(Path(raw).expanduser().resolve())
    normed = os.path.normcase(resolved)
    _PATH_KEY_CACHE[raw] = (resolved, normed)
    if len(_PATH_KEY_CACHE) > 1024:
        _PATH_KEY_CACHE.popitem(last=False)
    return resolved

def path_key(path):
    raw = str(path or '')
    hit = _PATH_KEY_CACHE.get(raw)
    if hit is not None:
        _PATH_KEY_CACHE.move_to_end(raw)
        return hit[1]
    resolved_path_str(raw)
    return _PATH_KEY_CACHE[raw][1]

def export_key(row, mtime_ns=None):
    raw_path = row['edit_output_path']
    if mtime_ns is None:
        mtime_ns = Path(raw_path).expanduser().stat().st_mtime_ns
    return str(row['id'])+':'+path_key(raw_path)+':'+str(mtime_ns)

def script_for_output(path):
    target_key = path_key(path)
    matches=[r for r in edited_tasks() if path_key(r['edit_output_path'])==target_key]
    if len(matches)!=1:return ''
    row=matches[0]
    return row.get('original_script') or row.get('production_script') or row.get('script') or ''
