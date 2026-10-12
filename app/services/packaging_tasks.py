"""Exact task/output association; never guess a script from a filename."""
import os
from pathlib import Path
from app.core import work_dates

def edited_tasks():
    with work_dates.read_connection() as con:
        return [dict(row) for row in con.execute("SELECT id,edit_output_path,original_script,production_script,script FROM videos WHERE edit_status IN ('已导出','已完成') AND edit_output_path<>''")]

def path_key(path):
    return os.path.normcase(str(Path(path).expanduser().resolve()))

def export_key(row):
    path=Path(row['edit_output_path'])
    return str(row['id'])+':'+path_key(path)+':'+str(path.stat().st_mtime_ns)

def script_for_output(path):
    matches=[r for r in edited_tasks() if path_key(r['edit_output_path'])==path_key(path)]
    if len(matches)!=1:return ''
    row=matches[0]
    return row.get('original_script') or row.get('production_script') or row.get('script') or ''
