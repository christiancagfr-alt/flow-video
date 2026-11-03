"""Clear all historical task records and move used image materials & Flow video segments to the system Trash, while strictly preserving final exported edited videos."""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path, PureWindowsPath
from typing import Callable, Optional

from app.core import database, repository as repo
from app.services import pre_gpt_pipeline as intake
from app.services import resolve_daily as daily

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _connect():
    intake.init_db().close()
    con = database.connect()
    con.execute("ATTACH DATABASE ? AS intake", (str(intake.DB_FILE),))
    return con


def _abs_path(raw: str | Path | None) -> Path | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text or not os.path.isabs(text):
        return None
    return Path(os.path.normpath(os.path.expanduser(text)))


def _is_subpath(child: Path | str, parent: Path | str) -> bool:
    if not str(child) or not str(parent):
        return False
    try:
        # Component comparisons work with Windows separators and drive-letter case.
        # Resolve native paths so a symlink cannot hide a protected export subtree.
        if os.name != 'nt' and PureWindowsPath(str(child)).drive and PureWindowsPath(str(parent)).drive:
            c, p = PureWindowsPath(str(child)), PureWindowsPath(str(parent))
        else:
            c, p = Path(child).resolve(), Path(parent).resolve()
        return c != p and c.is_relative_to(p)
    except (OSError, ValueError, RuntimeError):
        return False


def _resolve_anchor_dir(raw_dir: str | None) -> Path | None:
    p = _abs_path(raw_dir)
    if p is None:
        return None
    if p.name == "素材":
        p = p.parent
    if len(p.parts) < 5:
        return None
    return p


def move_to_trash(target: str | Path) -> bool:
    """Use the platform recycle bin; never fall back to permanent deletion."""
    p = Path(target).expanduser()
    try:
        if not p.exists() or p.is_symlink():
            return False
    except OSError:
        return False

    if os.name == 'nt':
        from PySide6.QtCore import QFile
        try:
            ok, _destination = QFile.moveToTrash(str(p))
            return bool(ok)
        except (OSError, RuntimeError):
            return False

    # 1. Native macOS NSFileManager.trashItemAtURL (supports external volumes & Finder 'Put Back')
    try:
        import Foundation
        fm = Foundation.NSFileManager.defaultManager()
        url = Foundation.NSURL.fileURLWithPath_(str(p))
        ok, _res_url, _err = fm.trashItemAtURL_resultingItemURL_error_(url, None, None)
        if ok:
            return True
    except Exception:
        pass

    # 2. Fallback: move into ~/.Trash with collision-safe naming
    try:
        trash_dir = Path.home() / ".Trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        dest = trash_dir / p.name
        if dest.exists():
            stem = p.stem
            suffix = p.suffix
            stamp = int(time.time() * 1000)
            dest = trash_dir / f"{stem}_{stamp}{suffix}"
        shutil.move(str(p), str(dest))
        return True
    except Exception:
        return False


def preview() -> dict:
    """Fast (<20ms) scan of historical tasks, image materials, Flow segments, and protected edited exports."""
    con = _connect()
    try:
        main_tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        intake_tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM intake.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

        edit_root = _abs_path(repo.get_setting("edit_root_path", ""))
        exports_root = (edit_root / "Exports") if edit_root else None
        media_root = (edit_root / "Media") if edit_root else None
        segment_root = _abs_path(repo.get_setting("segment_output_root", ""))
        asset_root = _abs_path(repo.get_setting("task_asset_root", ""))

        # 1. Protected final exported edited videos (保留视频剪辑成品)
        protected_files: set[Path] = set()
        if "videos" in main_tables:
            for (out_p,) in con.execute(
                "SELECT edit_output_path FROM main.videos WHERE edit_output_path IS NOT NULL AND edit_output_path != ''"
            ):
                np = _abs_path(out_p)
                if np:
                    protected_files.add(np)
        if "editing_history" in main_tables:
            for (out_p,) in con.execute(
                "SELECT output_path FROM main.editing_history WHERE output_path IS NOT NULL AND output_path != ''"
            ):
                np = _abs_path(out_p)
                if np:
                    protected_files.add(np)

        protected_export_count = len(protected_files)
        if exports_root and exports_root.is_dir():
            try:
                # Quick top-level date count if DB count is 0
                if protected_export_count == 0:
                    protected_export_count = sum(
                        1 for x in exports_root.iterdir() if not x.name.startswith(".")
                    )
            except OSError:
                pass

        def _is_protected(path: Path) -> bool:
            if path in protected_files:
                return True
            if exports_root and (path == exports_root or _is_subpath(path, exports_root)):
                return True
            for root_dir in (edit_root, exports_root, media_root, segment_root, asset_root):
                if root_dir and path == root_dir:
                    return True
            return False

        def _contains_protected(dir_path: Path) -> bool:
            if exports_root and (dir_path == exports_root or _is_subpath(exports_root, dir_path)):
                return True
            if edit_root and (dir_path == edit_root or _is_subpath(edit_root, dir_path)):
                return True
            return any(_is_subpath(pf, dir_path) for pf in protected_files)

        # 2. Collect Used Image Materials & Anchor/Date Directories
        image_paths: set[Path] = set()
        anchor_dirs: set[Path] = set()

        def _add_img(val: str | None):
            p = _abs_path(val)
            if not p or p in image_paths or _is_protected(p):
                return
            image_paths.add(p)
            if p.parent.name == "素材":
                ad = _resolve_anchor_dir(str(p.parent.parent))
                if ad and ad not in anchor_dirs and not _is_protected(ad) and not _contains_protected(ad):
                    anchor_dirs.add(ad)

        if "assets" in intake_tables:
            for (lp,) in con.execute("SELECT local_path FROM intake.assets WHERE local_path IS NOT NULL AND local_path != ''"):
                _add_img(lp)
        if "tasks" in intake_tables:
            for (mp,) in con.execute("SELECT matched_asset_path FROM intake.tasks WHERE matched_asset_path IS NOT NULL AND matched_asset_path != ''"):
                _add_img(mp)
        if "manual_image_modes" in intake_tables:
            for (mp,) in con.execute("SELECT path FROM intake.manual_image_modes WHERE path IS NOT NULL AND path != ''"):
                _add_img(mp)
        if "groups_tbl" in intake_tables:
            for (ld,) in con.execute("SELECT local_dir FROM intake.groups_tbl WHERE local_dir IS NOT NULL AND local_dir != ''"):
                ad = _resolve_anchor_dir(ld)
                if ad and ad not in anchor_dirs and not _is_protected(ad) and not _contains_protected(ad):
                    anchor_dirs.add(ad)
        if "hosts" in main_tables:
            for (ip,) in con.execute("SELECT image_path FROM main.hosts WHERE image_path IS NOT NULL AND image_path != ''"):
                _add_img(ip)
        if "videos" in main_tables:
            for (ip,) in con.execute("SELECT image_path FROM main.videos WHERE image_path IS NOT NULL AND image_path != ''"):
                _add_img(ip)
        if "asset_jobs" in main_tables:
            for (lp,) in con.execute("SELECT local_path FROM main.asset_jobs WHERE local_path IS NOT NULL AND local_path != ''"):
                _add_img(lp)

        # Also check date-named folders (YYYY-MM-DD) directly under asset_root so whole date folders can be trashed cleanly
        date_asset_dirs: set[Path] = set()
        if asset_root and asset_root.is_dir():
            try:
                for child in asset_root.iterdir():
                    if _DATE_DIR_RE.match(child.name) and child.is_dir() and not child.is_symlink():
                        cp = _abs_path(child)
                        if cp and not _is_protected(cp) and not _contains_protected(cp):
                            date_asset_dirs.add(cp)
            except OSError:
                pass

        # 3. Collect Generated Flow Video Segments (生成好的flow视频片段)
        segment_paths: set[Path] = set()
        segment_dirs: set[Path] = set()

        def _add_seg(val: str | None):
            p = _abs_path(val)
            if not p or _is_protected(p):
                return
            segment_paths.add(p)

        if "flow_segments" in main_tables:
            for (fp,) in con.execute("SELECT flow_output_path FROM main.flow_segments WHERE flow_output_path IS NOT NULL AND flow_output_path != ''"):
                _add_seg(fp)
        if "flow_outputs" in main_tables:
            for (op,) in con.execute("SELECT output_path FROM main.flow_outputs WHERE output_path IS NOT NULL AND output_path != ''"):
                _add_seg(op)
        if "flow_dispatches" in main_tables:
            for (dp,) in con.execute("SELECT download_path FROM main.flow_dispatches WHERE download_path IS NOT NULL AND download_path != ''"):
                _add_seg(dp)
        if "speech_analysis" in main_tables:
            for (sp,) in con.execute("SELECT sidecar_path FROM main.speech_analysis WHERE sidecar_path IS NOT NULL AND sidecar_path != ''"):
                _add_seg(sp)

        if media_root and media_root.is_dir():
            try:
                for child in media_root.iterdir():
                    if child.name.startswith(".") or child.is_symlink():
                        continue
                    cp = _abs_path(child)
                    if cp and not _is_protected(cp) and not _contains_protected(cp):
                        segment_dirs.add(cp)
            except OSError:
                pass

        channel_Download_dirs: list[Path] = []
        if segment_root and segment_root.is_dir():
            try:
                for child in segment_root.iterdir():
                    if child.name.startswith(".") or child.is_symlink():
                        continue
                    cp = _abs_path(child)
                    if cp and not _is_protected(cp) and not _contains_protected(cp):
                        channel_Download_dirs.append(cp)
            except OSError:
                pass

        segment_paths -= image_paths

        video_count = 0
        if "videos" in main_tables:
            video_count = int(con.execute("SELECT COUNT(*) FROM main.videos").fetchone()[0] or 0)
        intake_task_count = 0
        if "tasks" in intake_tables:
            intake_task_count = int(
                con.execute("SELECT COUNT(*) FROM intake.tasks WHERE sheet_row > 0").fetchone()[0] or 0
            )

        cmd_set: set[str] = set()
        for tbl, col in (
            ("flow_dispatches", "command_id"),
            ("flow_outputs", "command_id"),
            ("flow_segments", "generation_command"),
        ):
            if tbl in main_tables:
                for (cid,) in con.execute(
                    f"SELECT {col} FROM main.{tbl} WHERE {col} IS NOT NULL AND {col} != ''"
                ):
                    if str(cid).strip():
                        cmd_set.add(str(cid).strip())

        return {
            "image_count": max(len(image_paths), len(anchor_dirs)),
            "segment_count": max(len(segment_paths), len(segment_dirs)),
            "protected_export_count": protected_export_count,
            "task_count": max(video_count, intake_task_count),
            "date_asset_dirs": sorted(str(p) for p in date_asset_dirs),
            "anchor_dirs": sorted(str(p) for p in anchor_dirs),
            "image_files": sorted(str(p) for p in image_paths),
            "segment_dirs": sorted(str(p) for p in segment_dirs),
            "channel_dirs": sorted(str(p) for p in channel_Download_dirs),
            "segment_files": sorted(str(p) for p in segment_paths),
            "protected_files": sorted(str(p) for p in protected_files),
            "exports_root": str(exports_root) if exports_root else "",
            "command_ids": sorted(cmd_set),
        }
    finally:
        con.close()


def execute(
    plan: Optional[dict] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """Move all used image materials and Flow video segments to the Trash and clear DB task history."""
    if plan is None:
        plan = preview()

    def _report(pct: int, msg: str):
        if progress_callback:
            try:
                progress_callback(max(0, min(100, int(pct))), msg)
            except Exception:
                pass

    _report(8, "正在核对并锁定保护视频剪辑成品（Exports）…")

    protected_set = {Path(p) for p in plan.get("protected_files", [])}
    exports_root = Path(plan["exports_root"]) if plan.get("exports_root") else None
    trashed_dirs: list[Path] = []
    trashed_items_count = 0

    def _safe_to_trash_dir(d_path: Path) -> bool:
        if not d_path.exists() or d_path.is_symlink():
            return False
        if exports_root and (d_path == exports_root or _is_subpath(exports_root, d_path) or _is_subpath(d_path, exports_root)):
            return False
        if any(_is_subpath(pf, d_path) for pf in protected_set):
            return False
        if any(_is_subpath(d_path, td) for td in trashed_dirs):
            return False
        return True

    # 1. Trash date-level material folders & anchor folders
    dir_queue: list[tuple[Path, str, bool]] = []
    for d in plan.get("date_asset_dirs", []):
        dir_queue.append((Path(d), "历史素材日期目录", False))
    for d in plan.get("anchor_dirs", []):
        dir_queue.append((Path(d), "主播图片素材目录", False))
    for d in plan.get("segment_dirs", []):
        dir_queue.append((Path(d), "Flow 片段缓存目录", False))
    for d in plan.get("channel_dirs", []):
        # Recreate empty channel folder after trashing so Chrome download path stays valid
        dir_queue.append((Path(d), "Flow 通道下载目录", True))

    total_dirs = max(1, len(dir_queue))
    for idx, (d_path, label, recreate_empty) in enumerate(dir_queue, 1):
        if not _safe_to_trash_dir(d_path):
            continue
        pct = 12 + int((idx / total_dirs) * 45)
        _report(pct, f"正在丢入回收站：{label} ({d_path.name})")
        was_dir = d_path.is_dir()
        if move_to_trash(d_path):
            trashed_dirs.append(d_path)
            trashed_items_count += 1
            if recreate_empty and was_dir:
                try:
                    d_path.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass

    # 2. Trash any remaining standalone image / segment files outside already-trashed directories
    _report(62, "正在清理散落的图片素材与 Flow 片段文件…")
    standalone_files = [Path(f) for f in plan.get("image_files", [])] + [
        Path(f) for f in plan.get("segment_files", [])
    ]
    for f_path in standalone_files:
        if f_path in protected_set:
            continue
        if exports_root and _is_subpath(f_path, exports_root):
            continue
        if any(_is_subpath(f_path, td) for td in trashed_dirs):
            continue
        if f_path.exists() and f_path.is_file() and not f_path.is_symlink():
            if move_to_trash(f_path):
                trashed_items_count += 1

    # 3. Trash intermediate DaVinci Bridge batch temp folders (audio/whisper cache, NOT exports)
    _report(75, "正在清理自动剪辑临时音频与对齐缓存…")
    try:
        batches_dir = daily.bridge_root() / "v0_5_0" / "batches"
        if batches_dir.is_dir():
            for child in batches_dir.iterdir():
                if not child.name.startswith("."):
                    move_to_trash(child)
    except Exception:
        pass

    # 4. Clear historical task tables in main & intake databases
    _report(86, "正在清空任务日历与历史数据库记录…")
    con = _connect()
    try:
        main_tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        intake_tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM intake.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

        con.execute("BEGIN IMMEDIATE")

        for cmd in plan.get("command_ids", []):
            if "flow_obsolete_commands" in main_tables:
                con.execute(
                    "INSERT OR REPLACE INTO main.flow_obsolete_commands(command_id,host_id,reason,invalidated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                    (cmd, 0, "清空所有历史记录"),
                )

        if "app_settings" in main_tables:
            con.execute(
                "UPDATE main.app_settings SET value='[]' WHERE key='flow_host_jobs_v124'"
            )
            con.execute(
                "UPDATE main.app_settings SET value='' WHERE key='active_batch_id'"
            )

        main_clear_order = [
            "qc_clip_transforms",
            "api_usage_log",
            "flow_outputs",
            "flow_dispatches",
            "flow_failure_attempts",
            "flow_recovery",
            "flow_duration_choices",
            "flow_redo",
            "flow_obsolete_segments",
            "prompt_submission_history",
            "prompt_fill_sources",
            "qc_decisions",
            "flow_task_actions",
            "speech_analysis",
            "local_qc_results",
            "ai_qc_results",
            "flow_split_history",
            "pipeline_events",
            "flow_segments",
            "editing_history",
            "source_tasks",
            "asset_jobs",
            "web_fetch_jobs",
            "video_enhancement",
            "video_enhancement_plans",
            "video_source_styles",
            "custom_task_meta",
            "videos",
            "davinci_video_state",
            "davinci_autoedit_runs",
            "davinci_batches",
            "davinci_rebuild_receipts",
            "flow_channels",
            "flow_receipts",
            "flow_pending_downloads",
            "browser_command_owners",
            "sync_history",
            "hosts",
            "recipients",
        ]
        for tbl in main_clear_order:
            if tbl in main_tables:
                con.execute(f'DELETE FROM main."{tbl}"')

        intake_clear_order = [
            "production_links",
            "task_source_styles",
            "manual_image_modes",
            "image_path_aliases",
            "assets",
            "tasks",
            "groups_tbl",
            "intake_view_state",
        ]
        for tbl in intake_clear_order:
            if tbl in intake_tables:
                con.execute(f'DELETE FROM intake."{tbl}"')

        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    _report(100, "处理完成，所有历史素材与 Flow 片段已移入回收站。")

    return {
        "image_count": int(plan.get("image_count", 0)),
        "segment_count": int(plan.get("segment_count", 0)),
        "protected_export_count": int(plan.get("protected_export_count", 0)),
        "task_count": int(plan.get("task_count", 0)),
        "trashed_items_count": trashed_items_count,
    }
