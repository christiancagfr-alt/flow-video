"""Reviewable deletion by stable IDs, with shared-file protection and rollback staging."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from app.core import database, work_dates
from app.services import pre_gpt_pipeline as intake
from app.ui import workspace_intake


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _rows(con, schema):
    tables = [r[0] for r in con.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: [dict(r) for r in con.execute(f'SELECT rowid AS __rowid__, * FROM {schema}.{_quote(t)} ORDER BY rowid')]
            for t in tables}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _file(value):
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        return None
    p = Path(value)
    try:
        # Never follow a symlink, including any parent directory.
        if p.is_symlink() or any(parent.is_symlink() for parent in p.parents):
            return None
        return str(p.resolve()) if p.is_file() else None
    except OSError:
        return None


def _paths(value):
    """Find explicit file references, including paths stored inside JSON payloads."""
    if isinstance(value, dict):
        return set().union(*(_paths(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_paths(v) for v in value)) if value else set()
    if isinstance(value, str) and os.path.isabs(value):
        try:
            if Path(value).is_file():
                return {str(Path(value).resolve())}
        except OSError:
            pass
    if isinstance(value, str) and value[:1] in ('{', '['):
        try:
            return _paths(json.loads(value))
        except (ValueError, TypeError):
            pass
    return set()


def _connect():
    intake.init_db().close()
    con = database.connect()
    con.execute('ATTACH DATABASE ? AS intake', (str(intake.DB_FILE),))
    return con


def preview(group_key, day):
    day = work_dates.normalize_scope(day)
    groups, tasks, _ = workspace_intake.snapshot(day)
    group = next((g for g in groups if g['group_key'] == group_key), None)
    if not group:
        raise ValueError('所选日期中找不到该主播，请刷新后重试。')
    selected = [t for t in tasks if t['group_key'] == group_key]
    tids = {t['id'] for t in selected if isinstance(t['id'], int)}
    vids = {int(t['video_id']) for t in selected if t.get('video_id')}
    con = _connect()
    try:
        con.execute('BEGIN')
        main, incoming = _rows(con, 'main'), _rows(con, 'intake')
        for vid in vids:
            if work_dates.video_work_date(con, vid) != day:
                raise ValueError('任务日期不一致，已阻止删除。')
        # A production row linked to another intake task must never be swept along.
        if any(r['video_id'] in vids and r['task_id'] not in tids for r in incoming.get('production_links', [])):
            raise ValueError('该主播包含被其他任务引用的生产记录，已阻止删除。')
        legacy_links = {(r['source_task_id'], str(r['source_row'])): r['video_id']
                        for r in main.get('source_tasks', [])}
        for task in incoming.get('tasks', []):
            if task['id'] in tids:
                if task.get('group_key') != group_key:
                    raise ValueError('任务分组已变化，已阻止删除。')
                continue
            legacy_key = intake._source_task_key(task['spreadsheet_id'], task['gid'], task.get('content_key', ''))
            if legacy_links.get((legacy_key, str(task['sheet_row']))) in vids:
                raise ValueError('其他任务仍关联该主播的生产记录，已阻止删除。')
        sids = {r['id'] for r in main.get('flow_segments', []) if r['video_id'] in vids}
        hids = {r['host_id'] for r in main.get('videos', []) if r['id'] in vids}
        empty_hosts = {h for h in hids if not any(r['host_id'] == h and r['id'] not in vids for r in main.get('videos', []))}
        own_main = {}
        for table, rows in main.items():
            owned = []
            for row in rows:
                yes = ((table == 'videos' and row['id'] in vids)
                       or (table == 'hosts' and row['id'] in empty_hosts)
                       or row.get('video_id') in vids
                       or row.get('segment_id') in sids or row.get('flow_segment_id') in sids
                       or (table == 'flow_channels' and row.get('host_id') in empty_hosts))
                if yes:
                    if row.get('video_id') and row['video_id'] not in vids:
                        raise ValueError('检测到跨任务关联，已阻止删除。')
                    owned.append(row['__rowid__'])
                    # Deletion is authoritative for this host. Active/queued downstream work
                    # is invalidated during execute() instead of blocking the user's delete.
            if owned:
                own_main[table] = owned
        exclusive_group = not any(r['group_key'] == group_key and r['id'] not in tids for r in incoming.get('tasks', []))
        own_intake = {'tasks': sorted(tids)}
        for table in ('production_links', 'assets', 'groups_tbl'):
            own_intake[table] = [r['__rowid__'] for r in incoming.get(table, []) if
                (table == 'production_links' and r['task_id'] in tids) or
                (table in ('assets', 'groups_tbl') and exclusive_group and r.get('group_key') == group_key)]
        candidates, protected = set(), set()
        protected_text = []
        path_columns = {'flow_output_path', 'edit_output_path', 'output_path',
                        'download_path', 'sidecar_path', 'job_path'}
        for rows_by_table, ownership in ((main, own_main), (incoming, own_intake)):
            for table, rows in rows_by_table.items():
                for row in rows:
                    if table == 'image_path_aliases':
                        continue
                    if row['__rowid__'] in ownership.get(table, []):
                        # Only typed file columns establish ownership, never arbitrary text/JSON.
                        for key in path_columns:
                            path = _file(row.get(key))
                            if path:
                                candidates.add(path)
                    else:
                        protected.update(_paths(row))
                        protected_text.append(json.dumps(row, ensure_ascii=False))
        # Shared group folders protect unselected tasks, including unindexed local additions.
        for row in incoming.get('groups_tbl', []):
            if row['__rowid__'] in own_intake['groups_tbl'] or not row.get('local_dir'):
                continue
            other_root = Path(row['local_dir']).expanduser().resolve()
            protected.update(p for p in candidates if other_root in Path(p).parents)
        # Old paths can resolve through aliases after Finder renames.
        protected_blob = '\n'.join(protected_text)
        for row in incoming.get('image_path_aliases', []):
            new = _file(row.get('new_path'))
            if new and row.get('old_path') and row['old_path'] in protected_blob:
                protected.add(new)
        # Unregistered files and entire directories are deliberately never deleted.
        files = sorted(candidates - protected)
        fingerprints = {p: (Path(p).stat().st_size, Path(p).stat().st_mtime_ns, intake.sha256_file(p)) for p in files}
        command_ids = sorted({str(r.get('command_id') or '').strip()
                              for table in ('flow_dispatches', 'flow_outputs') for r in main.get(table, [])
                              if (r.get('segment_id') in sids) and str(r.get('command_id') or '').strip()} |
                             {str(r.get('generation_command') or '').strip() for r in main.get('flow_segments', [])
                              if r.get('id') in sids and str(r.get('generation_command') or '').strip()})
        return dict(group_key=group_key, day=day, recipient=group['recipient'], anchor=group['anchor_name'],
                    task_count=len(selected), video_ids=sorted(vids), intake_ids=sorted(tids), host_ids=sorted(hids),
                    main=own_main, intake=own_intake, files=files, shared_files=sorted(candidates & protected),
                    command_ids=command_ids, fingerprints=fingerprints, database_digest=_digest([main, incoming]))
    finally:
        con.close()


def execute(plan):
    """Apply only the reviewed plan. Stage files first and restore them if DB work fails."""
    # The task center is live: Flow/plugin/status callbacks may update the selected host
    # while the confirmation dialog is open. Deletion is host-authoritative, so refresh
    # the deletion plan after confirmation instead of rejecting it because status changed.
    # preview() still performs the important scope / cross-task / shared-file safety checks.
    plan = preview(plan['group_key'], plan['day'])
    con = _connect()
    staged = []
    recovery = intake.DB_FILE.parent / 'deleted_host_recovery' / uuid.uuid4().hex
    try:
        con.execute('BEGIN IMMEDIATE')
        # Acquire a write lock in both databases. Background status/progress updates are
        # expected and must not cancel a user-confirmed host deletion. The reviewed host
        # identity and ownership boundaries were re-evaluated by preview() immediately above.
        con.execute('UPDATE intake.tasks SET id=id WHERE 0')
        recovery.mkdir(parents=True)
        backup = {schema: {table: [r for r in rows if r['__rowid__'] in plan[schema].get(table, [])]
                               for table, rows in _rows(con, schema).items()}
                  for schema in ('main', 'intake')}
        (recovery / 'records.json').write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding='utf-8')
        (recovery / 'manifest.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        # Make every old browser command permanently stale before removing its rows.
        # Late Flow/plugin callbacks therefore cannot recreate a deleted host chain.
        for cmd in plan.get('command_ids', []):
            con.execute("INSERT OR REPLACE INTO main.flow_obsolete_commands(command_id,host_id,reason,invalidated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                        (cmd, int(plan.get('host_ids', [0])[0] if plan.get('host_ids') else 0), '任务中心删除主播'))
        setting = con.execute("SELECT value FROM main.app_settings WHERE key='flow_host_jobs_v124'").fetchone()
        if setting and plan.get('command_ids'):
            try:
                jobs = json.loads(setting['value'] or '[]')
                stale = set(plan['command_ids'])
                if isinstance(jobs, list):
                    jobs = [j for j in jobs if str((j or {}).get('command_id') or '') not in stale]
                    con.execute("UPDATE main.app_settings SET value=? WHERE key='flow_host_jobs_v124'", (json.dumps(jobs, ensure_ascii=False),))
            except Exception:
                pass
        for index, source in enumerate(plan['files']):
            p = Path(source)
            # A running Flow/download task may finish, replace, or remove an owned output
            # during confirmation. That is not a reason to block deletion. Only move the
            # file if the exact reviewed absolute path still resolves to a regular file.
            current = _file(source)
            if current != source:
                continue
            dest = recovery / f'{index}_{p.name}'
            shutil.move(str(p), str(dest))
            staged.append((p, dest))
        # Delete dependent records before parents; no name-based or directory-wide deletes.
        ordered = sorted(plan['main'], key=lambda t: (t in ('flow_segments', 'videos', 'hosts'),
                         {'flow_segments': 1, 'videos': 2, 'hosts': 3}.get(t, 0)))
        for table in ordered:
            for rowid in plan['main'][table]:
                con.execute(f'DELETE FROM main.{_quote(table)} WHERE rowid=?', (rowid,))
        for table, ids in plan['intake'].items():
            for rowid in ids:
                con.execute(f'DELETE FROM intake.{_quote(table)} WHERE rowid=?', (rowid,))
        con.commit()
    except Exception:
        con.rollback()
        for source, dest in reversed(staged):
            if dest.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    raise RuntimeError(f'原路径出现新文件，恢复副本已保留在 {recovery}，未覆盖该文件。')
                shutil.move(str(dest), str(source))
        raise
    finally:
        con.close()
    # macOS Trash makes deletion recoverable; failure keeps a recovery copy, never purges it.
    from PySide6.QtCore import QFile
    trash_result = QFile.moveToTrash(str(recovery))
    # PySide6 bindings differ by version/platform: some return only bool,
    # while others expose (bool, pathInTrash). Accept both contracts.
    if isinstance(trash_result, tuple):
        trashed = bool(trash_result[0]) if trash_result else False
        trash_path = str(trash_result[1] or '') if len(trash_result) > 1 else ''
    else:
        trashed = bool(trash_result)
        trash_path = ''
    message = f'已删除 {plan["task_count"]} 条任务及关联记录，移除 {len(staged)} 个本地文件。'
    if plan['shared_files']:
        message += f'另有 {len(plan["shared_files"])} 个共享文件仍被其他任务使用，已保留。'
    if not trashed:
        message += f'文件恢复副本保留在：{recovery}'
    return dict(message=message, deleted_tasks=plan['task_count'], deleted_files=len(staged),
                old_command_ids=list(plan.get('command_ids') or []),
                recovery=str(trash_path or recovery) if trashed else str(recovery))
