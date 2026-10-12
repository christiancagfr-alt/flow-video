from __future__ import annotations

import json
import os
import re
import shutil
from app.services import quiet_process as subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterable

from app.core import repository as repo

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.mkv', '.webm'}


def _safe_name(value: str, fallback: str = '未命名') -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', str(value or '').strip())
    value = re.sub(r'\s+', ' ', value).strip(' .')
    return value[:120] or fallback


def edit_root() -> Path | None:
    raw = str(repo.get_setting('edit_root_path', '') or '').strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def ensure_root_layout(root: Path) -> dict[str, Path]:
    root = root.expanduser().resolve()
    paths = {
        'root': root,
        'media': root / 'Media',
        'proxy': root / 'ProxyMedia',
        'cache': root / 'CacheClip',
        'gallery': root / '.gallery',
        'exports': root / 'Exports',
        'manifests': root / '.flowstudio',
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def _unique_target(folder: Path, filename: str) -> Path:
    target = folder / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    i = 2
    while True:
        cand = folder / f'{stem}_{i}{suffix}'
        if not cand.exists():
            return cand
        i += 1


def stage_ready_videos(video_ids: Iterable[int] | None = None) -> dict:
    """Move all QC-passed source segments out of Downloads into the configured edit root.

    Database paths are updated atomically per moved file so Video QC and DaVinci always point to
    the new location. Only complete videos whose every segment passed QC are staged.
    """
    root = edit_root()
    if root is None:
        return {'ok': False, 'reason': '未设置剪辑路径根目录', 'moved': 0, 'videos': 0}
    layout = ensure_root_layout(root)
    rows = list(repo.list_edit_source_segments(video_ids=video_ids))
    if not rows:
        return {'ok': True, 'moved': 0, 'videos': 0, 'root': str(root)}

    moved = 0
    touched = set()
    for row in rows:
        src = Path(str(row['flow_output_path'] or '')).expanduser()
        if not src.is_file():
            continue
        rel_dir = (
            layout['media'] /
            _safe_name(row['work_date'], '未定日期') /
            _safe_name(row['recipient_name']) /
            _safe_name(row['host_name']) /
            f"视频_{int(row['video_seq']):02d}"
        )
        rel_dir.mkdir(parents=True, exist_ok=True)
        # Stable sequence prefix preserves Flow segment order after import.
        wanted = src.name if src.parent.resolve() == rel_dir.resolve() else f"片段_{int(row['seg_seq']):02d}_{_safe_name(src.name, 'video'+src.suffix)}"
        dst = rel_dir / wanted
        try:
            if src.resolve() != dst.resolve():
                if dst.exists() and dst.stat().st_size == src.stat().st_size:
                    # A previous stage may have completed before a crash; reuse the staged file.
                    try:
                        src.unlink()
                    except OSError:
                        pass
                else:
                    dst = _unique_target(rel_dir, wanted)
                    shutil.move(str(src), str(dst))
                repo.rebind_flow_output_path(int(row['segment_id']), str(src), str(dst))
                moved += 1
            touched.add(int(row['video_id']))
        except Exception as exc:
            repo.set_video_edit_status([int(row['video_id'])], f'移动失败：{str(exc)[:80]}')

    if touched:
        repo.set_video_edit_status(sorted(touched), '待导入DaVinci')
    return {'ok': True, 'moved': moved, 'videos': len(touched), 'root': str(root)}


def build_manifest() -> dict:
    root = edit_root()
    if root is None:
        raise ValueError('请先在“系统设置”里设置剪辑路径根目录。')
    layout = ensure_root_layout(root)
    # Stage first, so the manifest never imports files from Downloads.
    stage_ready_videos()
    rows = list(repo.list_edit_source_segments())
    grouped: dict[tuple, dict] = {}
    for r in rows:
        path = Path(str(r['flow_output_path'] or '')).expanduser()
        if not path.is_file():
            continue
        key = (int(r['recipient_id']), int(r['host_id']))
        g = grouped.setdefault(key, {
            'recipient_id': int(r['recipient_id']),
            'recipient': r['recipient_name'],
            'host_id': int(r['host_id']),
            'host': r['host_name'],
            'work_date': r['work_date'],
            'videos': {},
        })
        v = g['videos'].setdefault(int(r['video_seq']), {
            'video_id': int(r['video_id']),
            'seq': int(r['video_seq']),
            'segments': [],
        })
        speech_row = repo.get_speech_analysis(int(r['segment_id']))
        speech = {}
        if speech_row:
            try: speech = json.loads(speech_row['analysis_json'] or '{}')
            except Exception: speech = {}
        from app.services.clip_transform import for_source
        v['segments'].append({
            'transform': for_source(int(r['segment_id']),r['flow_output_path']),
            'segment_id': int(r['segment_id']),
            'seg_seq': int(r['seg_seq']),
            'path': str(path.resolve()),
            'speech': {
                'video_hash': str(speech.get('video_hash') or (speech_row['video_hash'] if speech_row else '') or ''),
                'speech_start': speech.get('speech_start'),
                'speech_end': speech.get('speech_end'),
                'match_score': speech.get('match_score'),
                'transcript': speech.get('transcript',''),
                'target_text': speech.get('target_text',''),
                'words': speech.get('words') or [],
            } if speech else {},
        })
    groups = []
    for _, g in sorted(grouped.items(), key=lambda kv: (kv[1]['work_date'], kv[1]['recipient_id'], kv[1]['host_id'])):
        g['videos'] = [g['videos'][k] for k in sorted(g['videos'])]
        for v in g['videos']:
            v['segments'].sort(key=lambda x: x['seg_seq'])
        g['export_dir'] = str((layout['exports'] / _safe_name(g['work_date']) / _safe_name(g['recipient']) / _safe_name(g['host'])).resolve())
        Path(g['export_dir']).mkdir(parents=True, exist_ok=True)
        groups.append(g)
    if not groups:
        raise ValueError('当前没有“全部片段已质检通过”的完整视频可导入 DaVinci。')
    return {
        'root': str(layout['root']),
        'project_media': str(layout['root']),
        'proxy': str(layout['proxy']),
        'cache': str(layout['cache']),
        'gallery': str(layout['gallery']),
        'exports': str(layout['exports']),
        'groups': groups,
    }


def write_manifest() -> Path:
    manifest = build_manifest()
    target_dir = ensure_root_layout(Path(manifest['root']))['manifests']
    fd, path = tempfile.mkstemp(prefix='davinci_manifest_', suffix='.json', dir=str(target_dir))
    os.close(fd)
    p = Path(path)
    payload=json.dumps(manifest, ensure_ascii=False, indent=2)
    p.write_text(payload, encoding='utf-8')
    # Stable cache consumed by DaVinci automation and future tools; no second Whisper pass.
    (target_dir/'latest_manifest.json').write_text(payload,encoding='utf-8')
    lines=['segment_id\tpath\tspeech_start\tspeech_end\tmatch_score']
    for g in manifest.get('groups',[]):
        for v in g.get('videos',[]):
            for seg in v.get('segments',[]):
                sp=seg.get('speech') or {}
                lines.append(f"{seg.get('segment_id')}\t{seg.get('path','')}\t{sp.get('speech_start','')}\t{sp.get('speech_end','')}\t{sp.get('match_score','')}")
    (target_dir/'latest_speech_cache.tsv').write_text('\n'.join(lines),encoding='utf-8')
    return p


def launch_resolve() -> None:
    if __import__('sys').platform.startswith('linux'):
        executable=Path(repo.get_setting('davinci_executable_path','') or '/opt/resolve/bin/resolve')
        if not executable.is_file():raise RuntimeError('未找到 DaVinci Resolve，请配置可执行文件路径。')
        subprocess.Popen([str(executable)]);return
    if os.name == 'nt':
        import psutil
        for process in psutil.process_iter(['name']):
            if (process.info['name'] or '').lower() == 'resolve.exe':
                return
        configured = str(repo.get_setting('davinci_executable_path', '') or '').strip()
        from app.services.resolve_windows_paths import find_executable
        executable = find_executable(configured)
        subprocess.Popen([str(executable)], cwd=str(executable.parent))
        return
    if os.name != 'posix':
        raise RuntimeError('当前 DaVinci 自动启动流程针对 macOS。')
    subprocess.Popen(['/usr/bin/open', '-a', 'DaVinci Resolve'])


def minimize_resolve() -> tuple[bool, str]:
    if __import__('sys').platform.startswith('linux'):return False,'Linux 请通过窗口管理器最小化达芬奇。'
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        found = []
        @callback_type
        def visit(hwnd, param):
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, 512)
            if 'DaVinci Resolve' in title.value:
                user32.ShowWindow(hwnd, 6)
                found.append(True)
            return True
        user32.EnumWindows(visit, 0)
        return bool(found), ''

    script = r'''
try
    tell application "System Events"
        if exists process "DaVinci Resolve" then
            tell process "DaVinci Resolve"
                set visible to false
            end tell
        end if
    end tell
    return "ok"
on error errMsg
    return errMsg
end try
'''
    p = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, text=True)
    out = (p.stdout or p.stderr or '').strip()
    return p.returncode == 0 and out == 'ok', out

# ---------------------------------------------------------------------------
# Integrated Resolve AutoEdit v0.4.5.3 bridge
# ---------------------------------------------------------------------------

def resolve_bridge_root() -> Path:
    return Path.home() / "Documents" / "FlowStudioResolveBridge"


def integrated_module_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "davinci_autoedit_v0_4_5_3"


def resolve_bridge_status() -> dict:
    root = resolve_bridge_root()
    heartbeat = root / "bridge_heartbeat.txt"
    status = root / "bridge_status.txt"
    from app.services.resolve_daily import HEARTBEAT_FRESH_SECONDS
    alive = heartbeat.exists() and (time.time() - heartbeat.stat().st_mtime) < HEARTBEAT_FRESH_SECONDS
    text = ""
    try:
        text = status.read_text(encoding="utf-8").strip() if status.exists() else ""
    except Exception:
        text = ""
    return {
        "alive": alive,
        "status": text or ("Bridge 已连接" if alive else "Bridge 未连接"),
        "root": str(root),
    }


def install_integrated_bridge() -> tuple[bool, str]:
    if os.name == 'nt':
        return False, '此旧版 Bridge 安装器仅支持 macOS。'
    command = integrated_module_dir() / "00 AUTO QUIT + Install v0.4.5.3.command"
    if not command.is_file():
        return False, "集成安装脚本不存在：" + str(command)
    try:
        subprocess.Popen(["/usr/bin/open", str(command)])
        return True, "已打开 Resolve Bridge 安装脚本"
    except Exception as exc:
        return False, str(exc)


def _video_job_rows(video_ids=None, *, reedit=False):
    from app.core.database import connect
    requested = {int(x) for x in (video_ids or [])}
    ids = [r['video_id'] for r in repo.list_edit_queue()
           if (r['editing_stage']=='READY_TO_EDIT' or (reedit and r['materials_ready'] and r['editing_stage'] not in ('EDITING','EXPORTING'))) and (not requested or r['video_id'] in requested)]
    if not ids:
        return []
    with connect() as con:
        where = ""
        args = []
        if ids:
            where = " AND v.id IN (%s)" % ",".join("?" for _ in ids)
            args = ids
        return con.execute(f"""SELECT v.id video_id,v.seq video_seq,v.chinese_script,
                   r.name recipient_name,r.work_date,h.name host_name
            FROM videos v JOIN hosts h ON h.id=v.host_id JOIN recipients r ON r.id=h.recipient_id
            WHERE 1=1 {where}
            ORDER BY r.id,h.id,v.seq""", args).fetchall()


def submit_autoedit_jobs(video_ids=None, auto_cleanup=True, auto_export=True, auto_start_render=True, *, reedit=False) -> dict:
    """Write v0.4.5.3 .job files directly from Flow Studio's QC-passed database."""
    if reedit and not video_ids:raise ValueError('请选择要重新剪辑的视频')
    rows = list(_video_job_rows(video_ids,reedit=reedit))
    candidate_ids = [int(r["video_id"]) for r in rows]
    if not candidate_ids:
        return {"ok": True, "submitted": 0, "jobs": [], "bridge": resolve_bridge_status()}
    stage = {'ok':True} if reedit else stage_ready_videos(video_ids=candidate_ids)
    if not stage.get("ok"):
        return stage
    jobs = resolve_bridge_root() / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    sheet = repo.get_setting("task_source_sheet_url", "").strip()
    creator = repo.default_creator().strip()
    root = edit_root()
    if root is None:
        return {"ok": False, "reason": "未设置剪辑路径根目录", "submitted": 0}
    layout = ensure_root_layout(root)
    submitted = []
    from app.core.naming import final_filename
    for row in rows:
        segs = [r for r in repo.list_edit_source_segments([int(row["video_id"])],reedit=reedit) if Path(str(r["flow_output_path"] or "")).is_file()]
        if not segs:
            continue
        final = final_filename(
            int(row["video_seq"]), "ZB", row["recipient_name"], row["host_name"],
            creator, row["chinese_script"] or "", row["work_date"] or ""
        )
        out = layout["exports"] / _safe_name(row["work_date"]) / _safe_name(row["recipient_name"]) / _safe_name(row["host_name"])
        out.mkdir(parents=True, exist_ok=True)
        import uuid
        attempt=uuid.uuid4().hex[:12]
        if reedit:
            final=Path(final).stem+'_重剪_'+attempt+Path(final).suffix
            out=out/('重剪_'+attempt);out.mkdir(parents=True,exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(row['video_id']):06d}"
        path = jobs / f"{stamp}_{attempt}.job"
        lines = [
            "version=4.5.3",
            f"recipient={row['recipient_name']}",
            f"anchor={row['host_name']}",
            f"video_no={int(row['video_seq']):02d}",
            "timeline_width=1080", "timeline_height=1920", "timeline_fps=25",
            f"sheet_link={sheet}", f"output_dir={out}", f"final_name={Path(final).stem}",
            "start_number=1",
            f"auto_cleanup={1 if auto_cleanup else 0}",
            f"auto_export={1 if auto_export else 0}",
            f"auto_start_render={1 if auto_start_render else 0}",
        ] + [f"media={Path(str(x['flow_output_path'])).resolve()}" for x in segs]
        if reedit:lines.append(f"timeline_name={int(row['video_seq']):02d}-{row['host_name']}-重剪-{attempt}")
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        from app.services import editing_history
        # Record the attempt before exposing its job to Resolve.
        history_id=editing_history.record_submission(int(row['video_id']),path,segs)
        try:tmp.replace(path)
        except Exception:
            editing_history.mark_failed(history_id,'任务文件发布失败');raise
        repo.set_video_edit_status([int(row["video_id"])], "剪辑中")
        submitted.append({"video_id": int(row["video_id"]), "job": str(path), "final_name": final, "segments": len(segs)})
    if submitted:
        launch_resolve()
    return {"ok": True, "submitted": len(submitted), "jobs": submitted, "bridge": resolve_bridge_status()}
