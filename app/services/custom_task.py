"""One-off or batch custom DaVinci tasks: user-dropped media + user-pasted manuscripts.

A custom task is stored as a normal video task (recipient "自定义任务") whose
segments are the dropped files, already marked downloaded + QC-passed, so the
existing wake / import / auto-edit pipeline handles it unchanged.  The video is
tagged ``source_task_id = CUSTOM_TAG`` so the pipeline can (a) import ONLY
custom tasks while one is pending and (b) align against the typed manuscript.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path

from app.core import database, repository as repo

CUSTOM_TAG = 'CUSTOM_TASK'
RECIPIENT = '自定义任务'
HOST = '自定义'
VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.webm')


def _natural(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', Path(path).name)]


def collect_files(paths):
    """Expand dropped files/folders into a sorted, de-duplicated video list."""
    found, seen = [], set()
    for raw in paths:
        p = Path(raw).expanduser()
        items = sorted((x for x in p.rglob('*') if x.is_file()), key=_natural) if p.is_dir() else [p]
        for item in items:
            if item.name.startswith('.') or item.suffix.lower() not in VIDEO_EXTS:
                continue
            real = str(item.resolve())
            if real not in seen:
                seen.add(real)
                found.append(real)
    return found


def split_pasted_scripts(raw_script: str, expected_count: int = 0) -> list[str]:
    """Parse pasted text (e.g. from Google Sheets / Excel column copy) into individual scripts.

    Handles:
    1. CSV / TSV multi-line quoted cells (when copying multiple rows from Google Sheets/Excel).
    2. Blank-line separated blocks or line-by-line scripts when matching expected_count.
    """
    text = (raw_script or '').strip()
    if not text:
        return []
    if expected_count <= 1:
        return [text]

    # 1. Try TSV / CSV parsing (Google Sheets wraps multi-line cells in double quotes)
    try:
        rows = [
            ' '.join(c.strip() for c in r if c and c.strip()).strip()
            for r in csv.reader(io.StringIO(text), delimiter='\t')
        ]
        rows = [r for r in rows if r]
        if len(rows) == expected_count:
            return rows
    except Exception:
        rows = []

    # 2. Try blank-line separated paragraphs
    blocks = [b.strip() for b in re.split(r'\n\s*\n+', text) if b.strip()]
    if len(blocks) == expected_count:
        return blocks

    # 3. Try non-empty lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) == expected_count:
        return lines

    # 4. If CSV rows produced multiple distinct blocks (>1), return them
    if len(rows) > 1:
        return rows

    return [text]


def parse_batch_names(raw_title: str, count: int) -> list[str]:
    """Parse batch naming input into `count` names in order.

    - Never split on Chinese/English commas (， ,) or semicolons (； ;) because video titles
      naturally contain sentences with commas/semicolons!
    - Split by newlines (`\\r\\n` / `\\n`).
    - If newlines were collapsed into spaces/tabs when pasted, also split before numbered filename
      prefixes like `01-ZB-`, `02-ZB-`, etc.
    - If a single base name is provided (e.g. '自媒体男') and `count > 1`:
      generates `['自媒体男_01', '自媒体男_02', ...]`.
    """
    raw = (raw_title or '').strip()
    if count <= 0:
        return []
    if not raw:
        return [''] * count
    # Remove accidental file extension if user copied full filenames with .mp4/.mov
    lines = [ln.strip() for ln in re.split(r'[\r\n]+', raw) if ln.strip()]
    parts: list[str] = []
    for ln in lines:
        # If multiple numbered filenames (e.g. 01-ZB-... 02-ZB-...) were pasted onto a single line:
        sub = [
            s.strip()
            for s in re.split(r'(?:\t+|\s+)(?=\d{2,3}-[A-Za-z\u4e00-\u9fff])', ln)
            if s.strip()
        ]
        parts.extend(sub if len(sub) > 1 else [ln])
    cleaned_parts: list[str] = []
    for p in parts:
        p_clean = re.sub(r'\.(?:mp4|mov|m4v|mkv)$', '', p.strip(), flags=re.IGNORECASE).strip()
        if p_clean:
            cleaned_parts.append(p_clean)
    if not cleaned_parts:
        return [''] * count
    if count == 1:
        return [cleaned_parts[0]]
    if len(cleaned_parts) == 1:
        base = cleaned_parts[0]
        m_lead = re.match(r'^(\d{2,4})([-_])(.*)$', base)
        if m_lead:
            start_digits, sep, rest = m_lead.groups()
            start_num = int(start_digits)
            pad = len(start_digits)
            return [f"{start_num + i:0{pad}d}{sep}{rest}" for i in range(count)]
        m_trail = re.search(r'^(.*)([-_#])(\d{1,4})$', base)
        if m_trail:
            prefix, sep, start_digits = m_trail.groups()
            start_num = int(start_digits)
            pad = len(start_digits)
            return [f"{prefix}{sep}{start_num + i:0{pad}d}" for i in range(count)]
        return [f"{base}_{i:02d}" for i in range(1, count + 1)]
    out = []
    for i in range(count):
        if i < len(cleaned_parts):
            out.append(cleaned_parts[i])
        else:
            out.append(f"{cleaned_parts[0]}_{i + 1:02d}")
    return out


def batch_rename_files(file_paths: list[str], raw_names: str) -> list[dict]:
    """Batch rename local video files based on raw_names (multi-line or single template).

    Returns a list of dicts: [{'old_path': ..., 'new_path': ..., 'old_name': ..., 'new_name': ...}, ...]
    Raises ValueError on validation failures.
    """
    if not file_paths:
        raise ValueError('未选择任何视频文件。')
    names = parse_batch_names(raw_names, len(file_paths))
    if not names or all(not (n or '').strip() for n in names):
        raise ValueError('请输入有效的新名称或命名规则。')

    from app.core.naming import INVALID
    plan = []
    seen_dest = set()
    for idx, (path_str, name) in enumerate(zip(file_paths, names)):
        p = Path(path_str)
        if not p.is_file():
            raise ValueError(f'原文件不存在：{path_str}')
        clean_name = re.sub(INVALID, '', (name or '').strip()).strip()
        if not clean_name:
            clean_name = f"video_{idx + 1:02d}"
        ext = p.suffix
        if not clean_name.lower().endswith(ext.lower()):
            clean_name = f"{clean_name}{ext}"
        dest_p = p.with_name(clean_name)
        dest_norm = str(dest_p.resolve()) if dest_p.parent.exists() else str(dest_p)
        if dest_norm in seen_dest:
            raise ValueError(f'重命名目标重名：{dest_p.name}（第 {idx + 1} 个文件）')
        seen_dest.add(dest_norm)
        plan.append((p, dest_p))

    # Check collision against external files
    src_set = {str(p.resolve()) for p, _ in plan}
    for p, dest_p in plan:
        if str(dest_p.resolve()) != str(p.resolve()) and dest_p.exists() and str(dest_p.resolve()) not in src_set:
            raise ValueError(f'目标文件已存在，为防覆盖已中止：{dest_p.name}')

    # Safe two-stage rename to avoid cyclic renaming collisions
    tmp_plan = []
    renamed = []
    for p, dest_p in plan:
        if str(p.resolve()) == str(dest_p.resolve()):
            tmp_plan.append((p, dest_p, None, None))
            continue
        tmp_name = f"._flow_rename_{uuid.uuid4().hex[:8]}_{dest_p.name}"
        tmp_p = p.with_name(tmp_name)
        p.rename(tmp_p)
        dot_under = p.with_name(f"._{p.name}")
        tmp_dot = None
        if dot_under.is_file():
            tmp_dot = p.with_name(f"._flow_rename_{uuid.uuid4().hex[:8]}_{dot_under.name}")
            try:
                dot_under.rename(tmp_dot)
            except Exception:
                tmp_dot = None
        tmp_plan.append((p, dest_p, tmp_p, tmp_dot))

    for orig_p, dest_p, tmp_p, tmp_dot in tmp_plan:
        if tmp_p is not None and tmp_p.is_file():
            tmp_p.rename(dest_p)
        if tmp_dot is not None and tmp_dot.is_file():
            dest_dot = dest_p.with_name(f"._{dest_p.name}")
            try:
                tmp_dot.rename(dest_dot)
            except Exception:
                pass
        renamed.append({
            'old_path': str(orig_p),
            'new_path': str(dest_p),
            'old_name': orig_p.name,
            'new_name': dest_p.name,
        })

    return renamed


def batch_watermark_files(
    file_paths: list[str],
    raw_names: str,
    watermark_path: str,
    pos_preset: str = 'cover',
    output_dir: str | None = None,
    progress_cb=None,
    cancel_check=None,
) -> list[dict]:
    """Overlay watermark image and rename videos in batch.

    Returns list of dicts: [{'source_path': ..., 'output_path': ..., 'name': ...}, ...]
    """
    if not file_paths:
        raise ValueError('未选择任何视频文件。')
    wm_p = Path(watermark_path).expanduser().resolve()
    if not wm_p.is_file():
        raise ValueError(f'水印图片不存在：{watermark_path}')

    names = parse_batch_names(raw_names, len(file_paths))
    if not names or all(not (n or '').strip() for n in names):
        raise ValueError('请输入有效的新名称或命名规则。')

    from app.core.naming import INVALID
    from app.services.packaging_media import find_ffmpeg
    ffmpeg = find_ffmpeg('')
    if not ffmpeg:
        raise ValueError('未检测到 FFmpeg，请检查系统环境。')

    out_dir_path = Path(output_dir).expanduser().resolve() if output_dir else None
    if out_dir_path:
        out_dir_path.mkdir(parents=True, exist_ok=True)

    plan = []
    seen_dest = set()
    for idx, (path_str, name) in enumerate(zip(file_paths, names)):
        p = Path(path_str)
        if not p.is_file():
            raise ValueError(f'原文件不存在：{path_str}')
        clean_name = re.sub(INVALID, '', (name or '').strip()).strip()
        if not clean_name:
            clean_name = f"video_{idx + 1:02d}"
        ext = p.suffix
        if not clean_name.lower().endswith(ext.lower()):
            clean_name = f"{clean_name}{ext}"
        dest_dir = out_dir_path or p.parent
        dest_p = dest_dir / clean_name
        dest_norm = str(dest_p.resolve()) if dest_p.parent.exists() else str(dest_p)
        if dest_norm in seen_dest:
            raise ValueError(f'重命名目标重名：{dest_p.name}（第 {idx + 1} 个文件）')
        seen_dest.add(dest_norm)
        plan.append((p, dest_p))

    if pos_preset in ('cover', 'auto'):
        filter_str = '[1:v][0:v]scale2ref[wm][vid];[vid][wm]overlay=0:0'
    elif pos_preset == 'bottom_right':
        filter_str = '[0:v][1:v]overlay=W-w-24:H-h-24'
    elif pos_preset == 'top_right':
        filter_str = '[0:v][1:v]overlay=W-w-24:24'
    elif pos_preset == 'bottom_left':
        filter_str = '[0:v][1:v]overlay=24:H-h-24'
    elif pos_preset == 'top_left':
        filter_str = '[0:v][1:v]overlay=24:24'
    elif pos_preset == 'bottom_center':
        filter_str = '[0:v][1:v]overlay=(W-w)/2:H-h-24'
    else:
        filter_str = '[0:v][1:v]overlay=(W-w)/2:(H-h)/2'

    results = []
    total = len(plan)
    import subprocess, uuid

    for idx, (src_p, dest_p) in enumerate(plan):
        if cancel_check and cancel_check():
            break
        if progress_cb:
            progress_cb(idx, total, f"正在添加水印：{src_p.name} ➔ {dest_p.name} ({idx + 1}/{total})")

        tmp_out = dest_p.parent / f"._flow_wmtmp_{uuid.uuid4().hex[:8]}_{dest_p.name}"

        # Hardware-accelerated H.264 VideoToolbox
        cmd = [
            ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(src_p),
            '-i', str(wm_p),
            '-filter_complex', filter_str,
            '-c:v', 'h264_videotoolbox', '-b:v', '8M',
            '-c:a', 'copy',
            str(tmp_out),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            # Fallback to software libx264
            cmd_fb = [
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                '-i', str(src_p),
                '-i', str(wm_p),
                '-filter_complex', filter_str,
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                '-c:a', 'copy',
                str(tmp_out),
            ]
            res_fb = subprocess.run(cmd_fb, capture_output=True, text=True)
            if res_fb.returncode != 0:
                if tmp_out.exists():
                    tmp_out.unlink()
                raise RuntimeError(f'处理视频失败 [{src_p.name}]：{res_fb.stderr[:300]}')

        if dest_p.exists():
            dest_p.unlink()
        tmp_out.rename(dest_p)
        results.append({
            'source_path': str(src_p),
            'output_path': str(dest_p),
            'name': dest_p.name,
        })

    return results


def _ensure_meta(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS custom_task_meta("
        "video_id INTEGER PRIMARY KEY, language TEXT NOT NULL, task_mode TEXT NOT NULL DEFAULT 'SEGMENTS', custom_name TEXT NOT NULL DEFAULT '')"
    )
    cols = {r[1] for r in con.execute("PRAGMA table_info(custom_task_meta)").fetchall()}
    if 'task_mode' not in cols:
        con.execute("ALTER TABLE custom_task_meta ADD COLUMN task_mode TEXT NOT NULL DEFAULT 'SEGMENTS'")
    if 'custom_name' not in cols:
        con.execute("ALTER TABLE custom_task_meta ADD COLUMN custom_name TEXT NOT NULL DEFAULT ''")


def create(day, title, files, script, language=None, task_mode='SEGMENTS'):
    """``language=None`` means: follow the system setting (resolved when auto-edit starts).
    ``task_mode``:
      - 'SEGMENTS': scattered clips belonging to one task (or multiple tasks if multiple subfolders) -> blade cuts enabled.
      - 'COMPLETE': already-edited complete videos (1 video file = 1 independent task) -> no blade cuts (`no_cut=true`).
    """
    language = (language or '').strip().lower()
    if language and not re.fullmatch(r'[a-z]{2,4}', language):
        raise ValueError('无效的识别语言。')
    mode_norm = 'COMPLETE' if str(task_mode or '').upper() == 'COMPLETE' else 'SEGMENTS'
    raw_paths = list(files or [])
    collected = collect_files(raw_paths)
    script = (script or '').strip()
    title = (title or '').strip()
    if not collected:
        raise ValueError('请先拖入至少一个视频文件或包含视频的文件夹。')
    if len(script.split()) < 3 and len(script) < 10:
        raise ValueError('文案太短，无法安全对齐。')
    for f in collected:
        p = Path(f)
        if not p.is_file() or p.stat().st_size == 0:
            raise ValueError(f'素材不可用：{f}')

    # If COMPLETE mode and multiple video files are provided, create 1 video task per file!
    if mode_norm == 'COMPLETE' and len(collected) > 1:
        scripts = split_pasted_scripts(script, expected_count=len(collected))
        batch_names = parse_batch_names(title, len(collected))
        created = []
        for idx, vf in enumerate(collected):
            sc = scripts[idx] if idx < len(scripts) else (scripts[-1] if len(scripts) == 1 else script)
            cname = batch_names[idx] if idx < len(batch_names) else ''
            fallback_name = Path(vf).stem
            v_title = cname or fallback_name
            vid = _insert_single_custom_video(day, v_title, [vf], sc, language, 'COMPLETE', custom_name=cname or fallback_name)
            created.append(vid)
        return created[-1]

    # If SEGMENTS mode and multiple subfolders were dropped, or a single parent folder with multiple subfolders:
    dirs = [Path(p).expanduser() for p in raw_paths if Path(p).expanduser().is_dir()]
    if mode_norm == 'SEGMENTS':
        if len(dirs) == 1 and len(raw_paths) == 1:
            subdirs = sorted([d for d in dirs[0].iterdir() if d.is_dir() and not d.name.startswith('.')], key=_natural)
            valid_subdirs = [d for d in subdirs if collect_files([str(d)])]
            if len(valid_subdirs) > 1:
                dirs = valid_subdirs
        if len(dirs) > 1:
            scripts = split_pasted_scripts(script, expected_count=len(dirs))
            batch_names = parse_batch_names(title, len(dirs))
            created = []
            for idx, d in enumerate(dirs):
                d_files = collect_files([str(d)])
                if not d_files:
                    continue
                sc = scripts[idx] if idx < len(scripts) else (scripts[-1] if len(scripts) == 1 else script)
                cname = batch_names[idx] if idx < len(batch_names) else ''
                fallback_name = d.name
                v_title = cname or fallback_name
                vid = _insert_single_custom_video(day, v_title, d_files, sc, language, 'SEGMENTS', custom_name=cname or fallback_name)
                created.append(vid)
            if created:
                return created[-1]

    single_cname = parse_batch_names(title, 1)[0] if title else (Path(collected[0]).stem if mode_norm == 'COMPLETE' and len(collected) == 1 else '')
    return _insert_single_custom_video(day, single_cname or title, collected, script, language, mode_norm, custom_name=single_cname)


def _insert_single_custom_video(day, title: str, files: list[str], script: str, language: str, mode_norm: str, custom_name: str = '') -> int:
    rid = repo.find_or_create_recipient(RECIPIENT, 'ZB', '', day)
    hid = repo.find_or_create_host(rid, HOST)
    name = (title or '').strip() or (Path(files[0]).stem if mode_norm == 'COMPLETE' and len(files) == 1 else script.splitlines()[0][:20])
    vid = repo.add_video_to_host(
        hid,
        original_script=script,
        chinese=name,
        source_task_id=CUSTOM_TAG,
        source_row=uuid.uuid4().hex[:12],
    )
    with database.connect() as con:
        _ensure_meta(con)
        con.execute(
            'INSERT OR REPLACE INTO custom_task_meta(video_id,language,task_mode,custom_name) VALUES(?,?,?,?)',
            (vid, language, mode_norm, (custom_name or '').strip()),
        )
        for seq, f in enumerate(files, 1):
            command = 'custom-' + uuid.uuid4().hex
            cur = con.execute(
                "INSERT INTO flow_segments(video_id,seg_seq,foreign_text,status,flow_status,flow_output_path,"
                "qc_status,generation_command) VALUES(?,?,?,?,?,?,?,?)",
                (vid, seq, script if seq == 1 else '(自定义任务)', '已完成', '已完成', f, '通过', command),
            )
            con.execute(
                "INSERT INTO flow_outputs(segment_id,command_id,media_id,output_path,qc_status) VALUES(?,?,?,?,?)",
                (cur.lastrowid, command, command, f, '通过'),
            )
        con.execute("UPDATE videos SET edit_status='待剪辑' WHERE id=?", (vid,))
    return int(vid)


def inspect_pending_custom_scriptures(day=None) -> list[dict]:
    """Recognize scriptures from all active custom tasks (and current pending edit tasks) before auto-edit starts."""
    from app.core import work_dates
    from app.services.scripture_subtitles import extract_scriptures_from_text
    target_day = work_dates.normalize_scope(day) if day else work_dates.active()
    results = []
    with database.connect() as con:
        dates = work_dates.recipient_dates(con)
        rows = con.execute(
            """SELECT v.id, v.seq, v.chinese_script, v.original_script, v.script, v.source_task_id,
                      v.edit_status, h.recipient_id
               FROM videos v
               JOIN hosts h ON h.id = v.host_id
               ORDER BY v.id ASC"""
        ).fetchall()
        custom_rows = [
            r for r in rows
            if dates.get(r['recipient_id']) == target_day
            and str(r['source_task_id'] or '') == CUSTOM_TAG
            and str(r['edit_status'] or '') not in ('已导出', '已剪辑')
        ]
        target_rows = custom_rows if custom_rows else [
            r for r in rows
            if dates.get(r['recipient_id']) == target_day
            and str(r['edit_status'] or '') not in ('已导出', '已剪辑', '等待片段')
        ]
        for r in target_rows:
            orig = (r['original_script'] or r['script'] or '').strip()
            is_cust = str(r['source_task_id'] or '') == CUSTOM_TAG
            found = extract_scriptures_from_text(orig, allow_any_quote=is_cust)
            if found:
                title = (r['chinese_script'] or '').strip() or f"视频 #{r['seq']}"
                results.append({
                    'video_id': int(r['id']),
                    'title': title,
                    'is_custom': is_cust,
                    'scriptures': found,
                })
    return results


def custom_ids():
    with database.connect() as con:
        return {int(r['id']) for r in con.execute('SELECT id FROM videos WHERE source_task_id=?', (CUSTOM_TAG,))}


def languages():
    with database.connect() as con:
        _ensure_meta(con)
        return {int(r['video_id']): r['language'] for r in con.execute('SELECT video_id,language FROM custom_task_meta')}


def modes():
    with database.connect() as con:
        _ensure_meta(con)
        return {int(r['video_id']): str(r['task_mode'] or 'SEGMENTS').upper() for r in con.execute('SELECT video_id,task_mode FROM custom_task_meta')}


def custom_names():
    with database.connect() as con:
        _ensure_meta(con)
        return {int(r['video_id']): str(r['custom_name'] or '').strip() for r in con.execute('SELECT video_id,custom_name FROM custom_task_meta')}


def manuscripts():
    with database.connect() as con:
        return {int(r['id']): (r['original_script'] or '').strip()
                for r in con.execute('SELECT id,original_script FROM videos WHERE source_task_id=?', (CUSTOM_TAG,))}
