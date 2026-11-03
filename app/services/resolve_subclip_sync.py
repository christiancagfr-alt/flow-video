"""Ultra-fast pure-stdlib Project.db frame-exact sub-clip synchronizer for DaVinci Resolve autoedit.

After `Autoediting_V1.7_FlowStudio.lua` batch-appends the right-hand sub-clip instances via `MediaPool:AppendToTimeline`
and saves the project once (`pm:SaveProject()`), this module atomically updates `Start`, `Duration`, `"In"`
(`NULL` when `0`, `str(in_offset)` when `> 0`), re-orders `Sm2TiItem_Sm2TiTrack.DbIndex` in ascending timeline
start order, and refreshes `Sm2Sequence.MediaExtents` in a single SQLite transaction (< 30 ms) before `pm:LoadProject()`.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import struct
import sys


def _resolve_project_db_path(project_name: str, explicit_db_path: str = '') -> Path | None:
    if explicit_db_path:
        cand = Path(explicit_db_path).expanduser()
        return cand if cand.is_file() else None
    if not project_name:
        return None
    users_root = (
        Path.home()
        / 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Project Library/Resolve Projects/Users'
    )
    guest_db = users_root / 'guest' / 'Projects' / str(project_name) / 'Project.db'
    if guest_db.is_file():
        return guest_db
    if users_root.is_dir():
        for user_dir in sorted(users_root.iterdir()):
            cand = user_dir / 'Projects' / str(project_name) / 'Project.db'
            if cand.is_file():
                return cand
    return None


def sync_resolve_project_subclips(spec_path: str | Path) -> int:
    spath = Path(spec_path).expanduser()
    if not spath.is_file():
        return 0

    spec: dict[str, str] = {}
    for line in spath.read_text(encoding='utf-8', errors='replace').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            spec[k.strip()] = v.strip()

    item_count = int(spec.get('item_count') or 0)
    if item_count <= 0:
        return 0

    pdb = _resolve_project_db_path(
        spec.get('project_name', ''),
        spec.get('project_db_path', ''),
    )
    if pdb is None:
        return 0

    try:
        timeline_fps = float(spec.get('timeline_fps') or 25.0)
    except ValueError:
        timeline_fps = 25.0
    if timeline_fps <= 0:
        timeline_fps = 25.0

    updated = 0
    with sqlite3.connect(str(pdb), timeout=10.0) as con:
        tables = {
            str(r[0])
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        item_cols = {
            str(r[1])
            for r in con.execute('PRAGMA table_info("Sm2TiItem")').fetchall()
        }
        has_selector_idx = 'CurrentSelectorIdx' in item_cols

        timeline_uid = spec.get('timeline_uid', '')
        timeline_name = spec.get('timeline_name', '')
        seq_id = ''
        if 'Sm2Timeline' in tables:
            seq_row = None
            if timeline_uid:
                seq_row = con.execute(
                    'SELECT Sequence FROM Sm2Timeline WHERE Sm2Timeline_id = ? LIMIT 1',
                    (timeline_uid,),
                ).fetchone()
            if not seq_row and timeline_name:
                seq_row = con.execute(
                    'SELECT Sequence FROM Sm2Timeline WHERE Name = ? LIMIT 1',
                    (timeline_name,),
                ).fetchone()
            if seq_row and seq_row[0]:
                seq_id = str(seq_row[0])

        vtrack_ids: list[str] = []
        atrack_ids: list[str] = []
        if seq_id and 'Sm2TiTrack' in tables:
            vtrack_ids = [
                str(r[0])
                for r in con.execute(
                    'SELECT Sm2TiTrack_id FROM Sm2TiTrack WHERE Sequence = ? AND Type = 0',
                    (seq_id,),
                ).fetchall()
            ]
            atrack_ids = [
                str(r[0])
                for r in con.execute(
                    'SELECT Sm2TiTrack_id FROM Sm2TiTrack WHERE Sequence = ? AND Type = 1',
                    (seq_id,),
                ).fetchall()
            ]

        uid_batch: list[tuple[str, str, str | None, str]] = []
        fallbacks: list[tuple[str, int, int, str | None, str]] = []

        for idx in range(1, item_count + 1):
            pre = f'item_{idx}_'
            try:
                start_val = int(float(spec[pre + 'start']))
                dur_val = int(float(spec[pre + 'duration']))
                in_val = int(float(spec.get(pre + 'in') or '0'))
            except (KeyError, ValueError):
                continue
            if dur_val <= 0:
                continue

            in_db: str | None = str(in_val) if in_val > 0 else None
            clip_uid = spec.get(pre + 'uid', '')
            kind = spec.get(pre + 'kind', 'video')
            media_path = spec.get(pre + 'path', '')

            if clip_uid:
                uid_batch.append((str(start_val), str(dur_val), in_db, clip_uid))
            else:
                fallbacks.append((kind, start_val, dur_val, in_db, media_path))

        if uid_batch:
            if has_selector_idx:
                sql_uid = (
                    'UPDATE Sm2TiItem SET Start = ?, Duration = ?, "In" = ?, CurrentSelectorIdx = 0 '
                    'WHERE Sm2TiItem_id = ?'
                )
            else:
                sql_uid = 'UPDATE Sm2TiItem SET Start = ?, Duration = ?, "In" = ? WHERE Sm2TiItem_id = ?'
            for start_s, dur_s, in_db, clip_uid in uid_batch:
                cur = con.execute(sql_uid, (start_s, dur_s, in_db, clip_uid))
                updated += cur.rowcount or 0

        for kind, start_val, dur_val, in_db, media_path in fallbacks:
            t_ids = atrack_ids if kind == 'audio' else vtrack_ids
            db_type = 'Sm2TiAudioClip' if kind == 'audio' else 'Sm2TiVideoClip'
            if t_ids and media_path:
                q_marks = ','.join('?' for _ in t_ids)
                cur = con.execute(
                    f'UPDATE Sm2TiItem SET Start = ?, Duration = ?, "In" = ? '
                    f'WHERE Sm2TiTrack_id IN ({q_marks}) AND DbType = ? AND MediaFilePath = ? '
                    f'AND ABS(CAST(Start AS INTEGER) - ?) <= 2',
                    (str(start_val), str(dur_val), in_db, *t_ids, db_type, media_path, start_val),
                )
                updated += cur.rowcount or 0

        if updated > 0:
            # Keep Sm2TiItem_Sm2TiTrack DbIndex strictly sorted by timeline Start frame on V1 & A1.
            if 'Sm2TiItem_Sm2TiTrack' in tables:
                for trk_id in (vtrack_ids[:1] + atrack_ids[:1]):
                    has_assoc = con.execute(
                        "SELECT 1 FROM Sm2TiItem_Sm2TiTrack WHERE DbOwner = ? AND DbPropertyName = 'Items' LIMIT 1",
                        (trk_id,),
                    ).fetchone()
                    if has_assoc:
                        ordered_ids = [
                            str(r[0])
                            for r in con.execute(
                                'SELECT Sm2TiItem_id FROM Sm2TiItem WHERE Sm2TiTrack_id = ? '
                                'ORDER BY CAST(Start AS INTEGER) ASC, CAST(Duration AS INTEGER) ASC, Sm2TiItem_id ASC',
                                (trk_id,),
                            ).fetchall()
                        ]
                        con.execute(
                            "DELETE FROM Sm2TiItem_Sm2TiTrack WHERE DbOwner = ? AND DbPropertyName = 'Items'",
                            (trk_id,),
                        )
                        con.executemany(
                            "INSERT INTO Sm2TiItem_Sm2TiTrack (DbOwner, DbAssociate, DbPropertyName, DbIndex) "
                            "VALUES (?, ?, 'Items', ?)",
                            [(trk_id, item_id, idx) for idx, item_id in enumerate(ordered_ids)],
                        )

            # Refresh Sm2Sequence.MediaExtents so any temporary tail-appended frames do not inflate timeline end.
            if seq_id and 'Sm2Sequence' in tables and 'Sm2TiTrack' in tables:
                me_row = con.execute(
                    'SELECT MediaExtents FROM Sm2Sequence WHERE Sm2Sequence_id = ? LIMIT 1',
                    (seq_id,),
                ).fetchone()
                max_row = con.execute(
                    'SELECT MAX(CAST(i.Start AS INTEGER) + CAST(i.Duration AS INTEGER)) '
                    'FROM Sm2TiItem i JOIN Sm2TiTrack t ON i.Sm2TiTrack_id = t.Sm2TiTrack_id '
                    'WHERE t.Sequence = ?',
                    (seq_id,),
                ).fetchone()
                if me_row and isinstance(me_row[0], (bytes, bytearray)) and len(me_row[0]) == 16 and max_row and max_row[0]:
                    tl_start_sec, _ = struct.unpack('<dd', bytes(me_row[0]))
                    tl_start_frame = int(round(tl_start_sec * timeline_fps))
                    max_end_frame = int(max_row[0])
                    new_dur_sec = max(0, max_end_frame - tl_start_frame) * (1.0 / timeline_fps)
                    new_me = struct.pack('<dd', tl_start_sec, new_dur_sec)
                    con.execute(
                        'UPDATE Sm2Sequence SET MediaExtents = ? WHERE Sm2Sequence_id = ?',
                        (new_me, seq_id),
                    )

            con.commit()
    return updated


if __name__ == '__main__':
    if len(sys.argv) > 1:
        cnt = sync_resolve_project_subclips(sys.argv[1])
        print(f'SUBCLIPS_SYNCED:{cnt}' if cnt > 0 else 'SUBCLIPS_NOOP')
        sys.exit(0)
    print('SUBCLIPS_NOOP')
