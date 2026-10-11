#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


def load_module():
    candidates = [
        str(Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules'),
        '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules',
        str(Path.home() / 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules'),
    ]
    for d in candidates:
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
    import DaVinciResolveScript as dvr  # type: ignore
    return dvr


def safe_name(v):
    v = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', str(v or '').strip())
    return v[:80] or 'AI主播'


def call_bool(obj, method, *args):
    try:
        return bool(getattr(obj, method)(*args))
    except Exception:
        return False


def try_setting(project, key, value):
    try:
        return bool(project.SetSetting(key, str(value)))
    except Exception:
        return False


def set_project_settings(project, m):
    applied = {}
    # User-requested vertical timeline: 1080 x 1920, 24 fps.
    for key, value in (
        ('timelineResolutionWidth', '1080'),
        ('timelineResolutionHeight', '1920'),
        ('timelineFrameRate', '24'),
        ('timelinePlaybackFrameRate', '24'),
        ('timelinePixelAspectRatio', 'Square'),
    ):
        applied[key] = try_setting(project, key, value)

    # Resolve exposes working-folder keys differently between versions/platforms.
    # Try known aliases, and report exactly which ones the running version accepted.
    folder_candidates = {
        'project_media': ['projectMediaLocation', 'mediaStorageLocation'],
        'proxy': ['proxyMediaPath', 'proxyGenerationLocation', 'perfProxyMediaPath'],
        'cache': ['cachePath', 'cacheFilesLocation', 'perfCacheClipLocation'],
        'gallery': ['galleryStillLocation', 'galleryStillsLocation', 'stillGalleryPath'],
    }
    # Also discover version-specific setting keys from the running Resolve instance.
    try:
        existing = project.GetSetting() or {}
        existing_keys = list(existing.keys()) if isinstance(existing, dict) else []
    except Exception:
        existing_keys = []
    for logical, keys in folder_candidates.items():
        dyn = []
        for key in existing_keys:
            low = str(key).lower()
            if logical == 'proxy' and 'proxy' in low and any(x in low for x in ('path', 'location', 'folder')):
                dyn.append(key)
            elif logical == 'cache' and 'cache' in low and any(x in low for x in ('path', 'location', 'folder')):
                dyn.append(key)
            elif logical == 'gallery' and ('gallery' in low or 'still' in low) and any(x in low for x in ('path', 'location', 'folder')):
                dyn.append(key)
            elif logical == 'project_media' and 'media' in low and 'proxy' not in low and any(x in low for x in ('path', 'location', 'folder')):
                dyn.append(key)
        value = m.get(logical, '')
        accepted = None
        for key in list(dict.fromkeys(keys + dyn)):
            if value and try_setting(project, key, value):
                accepted = key
                break
        applied['folder_' + logical] = accepted or False
    return applied


def import_one(media_pool, path):
    try:
        imported = media_pool.ImportMedia([path]) or []
        return imported[0] if imported else None
    except Exception:
        return None


def clip_frames(item):
    for key in ('Frames', 'Frame Count'):
        try:
            raw = item.GetClipProperty(key)
            if raw not in (None, ''):
                return max(1, int(float(str(raw).replace(',', ''))))
        except Exception:
            pass
    return None


def clip_fps(item):
    for key in ('FPS','Frame Rate'):
        try:
            raw=item.GetClipProperty(key)
            if raw not in (None,''):
                return max(1.0,float(str(raw).replace(' fps','').strip()))
        except Exception:
            pass
    return 24.0


def append_clip(media_pool, item, record_frame=None, speech=None):
    # V0.13.3: reuse Studio's cached Whisper interval. No second ASR pass in DaVinci.
    info={'mediaPoolItem':item}
    if record_frame is not None: info['recordFrame']=int(record_frame)
    if speech and speech.get('speech_start') is not None and speech.get('speech_end') is not None:
        try:
            fps=clip_fps(item)
            start=max(0,int(round(float(speech['speech_start'])*fps)))
            end=max(start+1,int(round(float(speech['speech_end'])*fps)))
            info['startFrame']=start
            info['endFrame']=end
        except Exception:
            pass
    try:
        result=media_pool.AppendToTimeline([info]) or []
        if result:return result[0]
    except Exception:
        pass
    try:
        result=media_pool.AppendToTimeline([item]) or []
        return result[0] if result else None
    except Exception:
        return None


def add_marker(timeline, abs_frame, timeline_start, name, note):
    rel = max(0, int(abs_frame) - int(timeline_start))
    try:
        return bool(timeline.AddMarker(rel, 'Blue', name, note, 1, 'FLOWSTUDIO_HOST_RANGE'))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--project-name', required=True)
    args = ap.parse_args()
    try:
        m = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        dvr = load_module()
        resolve = dvr.scriptapp('Resolve')
        if not resolve:
            raise RuntimeError('无法连接 DaVinci Resolve；请等待软件完全启动。')
        pm = resolve.GetProjectManager()
        if not pm:
            raise RuntimeError('无法取得 Project Manager。')

        base = safe_name(args.project_name)
        project = None
        project_name = base
        for i in range(1, 100):
            name = base if i == 1 else f'{base}_{i}'
            project = pm.CreateProject(name)
            if project:
                project_name = name
                break
        if not project:
            raise RuntimeError('无法新建 DaVinci 项目；可能已有同名项目或项目库不可写。')

        settings = set_project_settings(project, m)
        media_pool = project.GetMediaPool()
        if not media_pool:
            raise RuntimeError('无法取得 Media Pool。')
        root_folder = media_pool.GetRootFolder()
        media_pool.SetCurrentFolder(root_folder)

        timeline = media_pool.CreateEmptyTimeline('FlowStudio_Master')
        if not timeline:
            raise RuntimeError('无法创建 FlowStudio_Master 时间线。')
        project.SetCurrentTimeline(timeline)
        # Apply custom timeline settings too, because some Resolve versions lock project FPS after timeline creation.
        for key, value in (
            ('useCustomSettings', '1'),
            ('timelineResolutionWidth', '1080'),
            ('timelineResolutionHeight', '1920'),
            ('timelineFrameRate', '24'),
            ('timelinePlaybackFrameRate', '24'),
        ):
            try:
                timeline.SetSetting(key, value)
            except Exception:
                pass

        timeline_start = int(timeline.GetStartFrame() or 0)
        cursor = timeline_start
        imported_count = 0
        imported_videos = []
        marker_ranges = []
        gap_video = 24       # > export script default 10-frame split threshold
        gap_host = 48

        for gi, group in enumerate(m.get('groups') or []):
            host_label = safe_name(group.get('host'))
            group_key = f"H{int(group.get('host_id') or gi+1)}-{host_label}"
            host_start = cursor
            try:
                folder = media_pool.AddSubFolder(root_folder, f"{group_key}")
                if folder:
                    media_pool.SetCurrentFolder(folder)
            except Exception:
                folder = None

            first_in_host = True
            for vi, video in enumerate(group.get('videos') or []):
                if not first_in_host:
                    cursor += gap_video
                first_in_host = False
                imported_this_video = 0
                for seg in sorted(video.get('segments') or [], key=lambda x: int(x.get('seg_seq') or 0)):
                    path = str(seg.get('path') or '')
                    if not Path(path).is_file():
                        continue
                    mpi = import_one(media_pool, path)
                    if not mpi:
                        continue
                    ti = append_clip(media_pool, mpi, cursor, seg.get('speech') or {})
                    if seg.get('transform'):
                        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
                        from app.services.clip_transform import apply_resolve
                        apply_resolve(ti,seg['transform'],timeline.GetSetting('timelineResolutionWidth'),timeline.GetSetting('timelineResolutionHeight'))
                    if not ti:
                        continue
                    imported_count += 1
                    imported_this_video += 1
                    try:
                        cursor = int(ti.GetEnd())
                    except Exception:
                        frames = clip_frames(mpi) or 1
                        cursor += frames
                if imported_this_video:
                    imported_videos.append(int(video.get('video_id') or 0))

            host_end = max(host_start + 1, cursor)
            # Compatible with user's BatchVideoExporter: same group name + 1=start / +2=end.
            add_marker(timeline, host_start, timeline_start, group_key + '1', f"AI主播范围开始：{host_label}")
            add_marker(timeline, host_end, timeline_start, group_key + '2', f"AI主播范围结束：{host_label}")
            marker_ranges.append({'host': host_label, 'group': group_key, 'start': host_start, 'end': host_end})
            cursor += gap_host
            media_pool.SetCurrentFolder(root_folder)

        if imported_count == 0:
            raise RuntimeError('没有成功导入任何视频；请检查剪辑根目录中的文件是否存在。')

        try:
            resolve.OpenPage('edit')
        except Exception:
            pass
        try:
            project.Save()
        except Exception:
            pass

        print(json.dumps({
            'ok': True,
            'project': project_name,
            'timeline': timeline.GetName() or 'FlowStudio_Master',
            'imported_segments': imported_count,
            'video_ids': sorted(set(v for v in imported_videos if v)),
            'groups': marker_ranges,
            'settings': settings,
            'resolution': '1080x1920',
            'fps': 24,
            'speech_cache_reused': True,
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
