#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import sys
from pathlib import Path


def load_resolve_module():
    candidates = [
        str(Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules'),
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
        str(Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
    ]
    for d in candidates:
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
    try:
        import DaVinciResolveScript as dvr  # type: ignore
        return dvr
    except Exception as exc:
        raise RuntimeError("未找到 DaVinci Resolve Scripting 模块。请确认 Resolve 已安装并已启动。") from exc


def main():
    try:
        dvr = load_resolve_module()
        resolve = dvr.scriptapp("Resolve")
        if not resolve:
            raise RuntimeError("无法连接 DaVinci Resolve；请等待 Resolve 完全启动后再试。")
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
        if not project:
            raise RuntimeError("DaVinci 已连接，但当前没有打开项目。")
        timeline = project.GetCurrentTimeline()
        if not timeline:
            raise RuntimeError("当前项目没有打开 Timeline。")

        video_tracks = int(timeline.GetTrackCount("video") or 0)
        audio_tracks = int(timeline.GetTrackCount("audio") or 0)
        video_clips = 0
        audio_clips = 0
        for i in range(1, video_tracks + 1):
            try:
                video_clips += len(timeline.GetItemListInTrack("video", i) or [])
            except Exception:
                pass
        for i in range(1, audio_tracks + 1):
            try:
                audio_clips += len(timeline.GetItemListInTrack("audio", i) or [])
            except Exception:
                pass

        print(json.dumps({
            "ok": True,
            "project": project.GetName() or "",
            "timeline": timeline.GetName() or "",
            "video_tracks": video_tracks,
            "audio_tracks": audio_tracks,
            "video_clips": video_clips,
            "audio_clips": audio_clips,
        }, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
