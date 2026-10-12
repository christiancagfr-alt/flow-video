"""Explicit, date-scoped local rescan. Never downloads or removes user files."""
from pathlib import Path
from datetime import datetime
from app.core import database, work_dates
from app.services import pre_gpt_pipeline as intake
from app.services.file_filters import IMAGE_EXTENSIONS, is_valid_local_image
from app.ui import workspace_intake

EXTENSIONS = IMAGE_EXTENSIONS


def rescan(group_key, day, progress_callback=None, *, random_fill=False):
    day = work_dates.normalize_scope(day)
    groups, tasks, _ = workspace_intake.snapshot(day)
    group = next((g for g in groups if g['group_key'] == group_key), None)
    if not group:
        raise ValueError('所选日期中找不到该主播，请刷新任务中心后重试。')
    tasks = [t for t in tasks if t['group_key'] == group_key]
    raw_folder = str(group.get('local_dir') or '').strip()
    if not raw_folder or not Path(raw_folder).expanduser().is_dir():
        raise ValueError('该主播的本地素材目录不存在，请先同步素材或恢复原目录。')
    folder = Path(raw_folder).expanduser().resolve()
    intake._report_progress(progress_callback, 5, '扫描本地素材', str(folder))
    candidates = list(folder.iterdir())
    for name in ('素材', '多余素材'):
        sub = folder / name
        if sub.is_dir() and not sub.is_symlink():
            candidates.extend(sub.rglob('*'))
    # Archived hosts may point directly at the material subfolder.
    if folder.name in ('素材', '多余素材'):
        candidates.extend(folder.rglob('*'))
    files = sorted({p.resolve() for p in candidates if is_valid_local_image(p)
                    and folder in p.resolve().parents}, key=str)
    if not tasks:
        raise ValueError('该主播没有可匹配的任务。')
    con = intake.init_db()
    try:
        assets = con.execute('SELECT id,local_path,sha256,mode FROM assets WHERE group_key=?', (group_key,)).fetchall()
        by_path = {str(Path(a[1]).expanduser().resolve()): a for a in assets if a[1]}
        old_missing = [a for a in assets if a[1] and not Path(a[1]).expanduser().is_file()]
        renamed = {}
        modes = {}
        for index, path in enumerate(files):
            digest = intake.sha256_file(path)
            old = by_path.get(str(path))
            if not old:
                old = next((a for a in old_missing if a[2] == digest), None)
                if old:
                    old_missing.remove(old)
                    renamed[str(Path(old[1]).expanduser().resolve())] = str(path)
                    con.execute('INSERT OR REPLACE INTO image_path_aliases(old_path,new_path) VALUES(?,?)',
                                (str(Path(old[1]).expanduser().resolve()), str(path)))
            from app.services.material_assignment import image_mode, manual_modes
            default = 'TALKING'
            mode = image_mode(path, old[3] if old else None, default, manual_modes(con))
            modes[path] = mode
            if old:
                con.execute('UPDATE assets SET local_path=?,original_name=?,sha256=?,mode=? WHERE id=?',
                            (str(path), path.name, digest, mode, old[0]))
            else:
                # NULL Drive ID means a local addition, not a remote download identity.
                con.execute('INSERT INTO assets(group_key,original_name,local_path,sha256,mode) VALUES(?,?,?,?,?)',
                            (group_key, path.name, str(path), digest, mode))
            intake._report_progress(progress_callback, 10 + int(60 * (index + 1) / max(1, len(files))),
                                    '识别本地图片', f'{index + 1}/{len(files)} · {path.name}')
        mixed = len({t.get('mode') or 'TALKING' for t in tasks}) > 1
        from app.services.material_assignment import assign, reference_tasks
        previous = {}
        for task in tasks:
            old = str(task.get('asset') or '')
            if old:
                old = str(Path(old).expanduser().resolve())
                previous[task['id']] = Path(renamed.get(old, old))
        assigned = assign(reference_tasks(tasks, modes), files, modes, previous, random_fill)
        missing = len(tasks) - len(assigned)
        status = 'READY_FOR_GPT' if not missing else ('NEEDS_MANUAL_CLASSIFY' if mixed and files else 'MATERIAL_SHORTAGE')
        if missing and files and any(t.get('mode')=='PRAYING' for t in tasks) and 'PRAYING' not in modes.values():status='NEEDS_MANUAL_CLASSIFY'
        message = f'本地扫描：发现 {len(files)} 张图片，已匹配 {len(assigned)}/{len(tasks)} 条任务'
        if missing:
            message += f'；还有 {missing} 条未匹配' + ('，请在闭眼图片文件名中添加“闭眼”后重新扫描' if mixed and files else '，请补充图片后重新扫描')
        now = datetime.now().isoformat(timespec='seconds')
        intake_ids = []
        for task in tasks:
            if isinstance(task['id'], int):
                intake_ids.append(task['id'])
                path = str(assigned.get(task['id'], ''))
                con.execute('UPDATE tasks SET matched_asset_path=?,status=?,updated_at=? WHERE id=? AND group_key=?',
                            (path, status, now, task['id'], group_key))
        con.execute('UPDATE groups_tbl SET image_count=?,status=?,message=?,updated_at=? WHERE group_key=?',
                    (len(files), status, message, now, group_key))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    # Repair only missing production references; keep existing editor choices and outputs.
    repaired = 0
    with database.connect() as studio:
        for task in tasks:
            vid = task.get('video_id')
            path = assigned.get(task['id'])
            if not vid or not path:
                continue
            if work_dates.video_work_date(studio, vid) != day:
                raise ValueError('主播任务日期已变化，请刷新后重试。')
            row = studio.execute('SELECT image_path FROM videos WHERE id=?', (vid,)).fetchone()
            if row and (not row[0] or not is_valid_local_image(Path(row[0]).expanduser())):
                studio.execute("UPDATE videos SET image_path=?,asset_status='已准备' WHERE id=?", (str(path), vid))
                repaired += 1
    promoted = intake.promote_ready_to_studio(task_ids=intake_ids) if status == 'READY_FOR_GPT' and intake_ids else {}
    intake._report_progress(progress_callback, 100, '本地扫描完成', message)
    return dict(status=status, message=message, images=len(files), matched=len(assigned), missing=missing,
                repaired=repaired, promote=promoted)
