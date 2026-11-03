"""Fast, complete host deletion across intake & Studio databases and local disk."""
import json
import os
from pathlib import Path
import shutil
from app.core import database, work_dates
from app.services import pre_gpt_pipeline as intake
from app.ui import workspace_intake


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _file(value):
    if not isinstance(value, str) or not value:
        return None
    value = value.strip()
    if not value or not os.path.isabs(value):
        return None
    p = Path(value)
    try:
        if p.is_symlink():
            return None
        return str(p) if p.is_file() else None
    except OSError:
        return None


def _connect():
    intake.init_db().close()
    con = database.connect()
    con.execute('ATTACH DATABASE ? AS intake', (str(intake.DB_FILE),))
    return con


def _resolve_anchor_dir(raw_dir: str) -> Path | None:
    if not raw_dir or not isinstance(raw_dir, str):
        return None
    raw_dir = raw_dir.strip()
    if not raw_dir or not os.path.isabs(raw_dir):
        return None
    p = Path(raw_dir).expanduser()
    if p.name == '素材':
        p = p.parent
    # Safety guard: anchor folder must be at least 4 path components deep
    # e.g. /Volumes/LEONARDO/000/2026-10-25/接收人/主播
    if len(p.parts) < 5:
        return None
    return p


def preview(group_key, day):
    day = work_dates.normalize_scope(day)
    groups, tasks, _ = workspace_intake.snapshot(day)
    group = next((g for g in groups if g['group_key'] == group_key), None)
    if not group:
        raise ValueError('所选日期中找不到该主播，请刷新后重试。')
    selected = [t for t in tasks if t['group_key'] == group_key]
    tids = sorted({int(t['id']) for t in selected if isinstance(t['id'], int)})
    vids_set = {int(t['video_id']) for t in selected if t.get('video_id')}

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

        if group.get('host_id'):
            vids_set.update(
                r[0]
                for r in con.execute(
                    'SELECT id FROM main.videos WHERE host_id=?', (int(group['host_id']),)
                )
            )
        if tids and 'production_links' in intake_tables:
            t_ph = ','.join('?' * len(tids))
            vids_set.update(
                r[0]
                for r in con.execute(
                    f'SELECT video_id FROM intake.production_links WHERE task_id IN ({t_ph})',
                    tids,
                )
                if r[0]
            )

        vids = sorted(vids_set)
        for vid in vids:
            if work_dates.video_work_date(con, vid) != day:
                raise ValueError('任务日期不一致，已阻止删除。')

        owned_group_keys = {group_key}
        if vids and 'production_links' in intake_tables:
            v_ph = ','.join('?' * len(vids))
            linked_tids = [
                int(r[0])
                for r in con.execute(
                    f'SELECT task_id FROM intake.production_links WHERE video_id IN ({v_ph})',
                    vids,
                )
                if r[0] is not None
            ]
            if linked_tids and 'tasks' in intake_tables:
                lt_ph = ','.join('?' * len(linked_tids))
                for tid, t_gk, s_row, t_rec, t_anc in con.execute(
                    f'SELECT id, group_key, sheet_row, recipient, anchor_name FROM intake.tasks WHERE id IN ({lt_ph})',
                    linked_tids,
                ):
                    if (
                        tid in tids
                        or int(s_row or 0) <= 0
                        or (t_rec == group['recipient'] and t_anc == group['anchor_name'])
                    ):
                        if tid not in tids:
                            tids.append(int(tid))
                        if t_gk:
                            owned_group_keys.add(str(t_gk))
                    else:
                        raise ValueError('该主播包含被其他任务引用的生产记录，已阻止删除。')
                tids = sorted(set(tids))

        if vids:
            v_ph = ','.join('?' * len(vids))
            sids = sorted(
                r[0]
                for r in con.execute(
                    f'SELECT id FROM main.flow_segments WHERE video_id IN ({v_ph})', vids
                )
            )
            hids_set = {
                int(r[0])
                for r in con.execute(
                    f'SELECT DISTINCT host_id FROM main.videos WHERE id IN ({v_ph})', vids
                )
                if r[0]
            }
        else:
            sids = []
            hids_set = set()

        if group.get('host_id'):
            hids_set.add(int(group['host_id']))
        hids = sorted(hids_set)

        empty_hosts = []
        for h in hids:
            if vids:
                v_ph = ','.join('?' * len(vids))
                rem = con.execute(
                    f'SELECT 1 FROM main.videos WHERE host_id=? AND id NOT IN ({v_ph}) LIMIT 1',
                    [h, *vids],
                ).fetchone()
            else:
                rem = con.execute(
                    'SELECT 1 FROM main.videos WHERE host_id=? LIMIT 1', (h,)
                ).fetchone()
            if not rem:
                empty_hosts.append(h)

        # Collect owned rowids in main schema using targeted SQL queries
        own_main: dict[str, list[int]] = {}

        def _add_main_rows(table: str, rowids: list[int]):
            if not rowids:
                return
            existing = set(own_main.get(table, []))
            existing.update(int(x) for x in rowids)
            own_main[table] = sorted(existing)

        if vids:
            v_ph = ','.join('?' * len(vids))
            _add_main_rows(
                'videos',
                [
                    r[0]
                    for r in con.execute(
                        f'SELECT rowid FROM main.videos WHERE id IN ({v_ph})', vids
                    )
                ],
            )
            for tbl in (
                'flow_segments',
                'flow_split_history',
                'editing_history',
                'source_tasks',
                'asset_jobs',
                'pipeline_events',
                'video_enhancement',
                'video_enhancement_plans',
                'video_source_styles',
                'davinci_video_state',
                'custom_task_meta',
            ):
                if tbl in main_tables:
                    _add_main_rows(
                        tbl,
                        [
                            r[0]
                            for r in con.execute(
                                f'SELECT rowid FROM main.{_quote(tbl)} WHERE video_id IN ({v_ph})',
                                vids,
                            )
                        ],
                    )

        if sids:
            s_ph = ','.join('?' * len(sids))
            for tbl in (
                'flow_outputs',
                'flow_dispatches',
                'flow_failure_attempts',
                'flow_recovery',
                'flow_duration_choices',
                'flow_redo',
                'flow_obsolete_segments',
                'prompt_submission_history',
                'prompt_fill_sources',
                'qc_decisions',
                'flow_task_actions',
                'speech_analysis',
                'local_qc_results',
                'ai_qc_results',
                'flow_split_history',
                'pipeline_events',
            ):
                if tbl in main_tables:
                    _add_main_rows(
                        tbl,
                        [
                            r[0]
                            for r in con.execute(
                                f'SELECT rowid FROM main.{_quote(tbl)} WHERE segment_id IN ({s_ph})',
                                sids,
                            )
                        ],
                    )
            if 'api_usage_log' in main_tables:
                _add_main_rows(
                    'api_usage_log',
                    [
                        r[0]
                        for r in con.execute(
                            f'SELECT rowid FROM main.api_usage_log WHERE flow_segment_id IN ({s_ph})',
                            sids,
                        )
                    ],
                )
            if 'qc_clip_transforms' in main_tables and 'flow_outputs' in main_tables:
                _add_main_rows(
                    'qc_clip_transforms',
                    [
                        r[0]
                        for r in con.execute(
                            f'SELECT rowid FROM main.qc_clip_transforms WHERE output_id IN (SELECT id FROM main.flow_outputs WHERE segment_id IN ({s_ph}))',
                            sids,
                        )
                    ],
                )

        if empty_hosts:
            h_ph = ','.join('?' * len(empty_hosts))
            if 'hosts' in main_tables:
                _add_main_rows(
                    'hosts',
                    [
                        r[0]
                        for r in con.execute(
                            f'SELECT rowid FROM main.hosts WHERE id IN ({h_ph})',
                            empty_hosts,
                        )
                    ],
                )
            if 'flow_channels' in main_tables:
                _add_main_rows(
                    'flow_channels',
                    [
                        r[0]
                        for r in con.execute(
                            f'SELECT rowid FROM main.flow_channels WHERE host_id IN ({h_ph})',
                            empty_hosts,
                        )
                    ],
                )

        # Collect owned rowids in intake schema
        gk_list = sorted(owned_group_keys)
        gk_ph = ','.join('?' * len(gk_list))
        exclusive_group = True

        own_intake: dict[str, list[int]] = {}
        if tids and 'tasks' in intake_tables:
            t_ph = ','.join('?' * len(tids))
            own_intake['tasks'] = [
                r[0]
                for r in con.execute(
                    f'SELECT rowid FROM intake.tasks WHERE id IN ({t_ph}) OR (group_key IN ({gk_ph}) AND sheet_row > 0)',
                    [*tids, *gk_list],
                )
            ]
        elif 'tasks' in intake_tables:
            own_intake['tasks'] = [
                r[0]
                for r in con.execute(
                    f'SELECT rowid FROM intake.tasks WHERE group_key IN ({gk_ph}) AND sheet_row > 0',
                    gk_list,
                )
            ]
        else:
            own_intake['tasks'] = []

        if 'production_links' in intake_tables:
            pl_rows = set()
            if tids:
                t_ph = ','.join('?' * len(tids))
                pl_rows.update(
                    r[0]
                    for r in con.execute(
                        f'SELECT rowid FROM intake.production_links WHERE task_id IN ({t_ph})',
                        tids,
                    )
                )
            if vids:
                v_ph = ','.join('?' * len(vids))
                pl_rows.update(
                    r[0]
                    for r in con.execute(
                        f'SELECT rowid FROM intake.production_links WHERE video_id IN ({v_ph})',
                        vids,
                    )
                )
            own_intake['production_links'] = sorted(pl_rows)

        if tids and 'task_source_styles' in intake_tables:
            t_ph = ','.join('?' * len(tids))
            own_intake['task_source_styles'] = [
                r[0]
                for r in con.execute(
                    f'SELECT rowid FROM intake.task_source_styles WHERE task_id IN ({t_ph})',
                    tids,
                )
            ]

        if 'assets' in intake_tables:
            own_intake['assets'] = [
                r[0]
                for r in con.execute(
                    f'SELECT rowid FROM intake.assets WHERE group_key IN ({gk_ph})', gk_list
                )
            ]

        if 'manual_image_modes' in intake_tables:
            own_intake['manual_image_modes'] = [
                r[0]
                for r in con.execute(
                    f'SELECT rowid FROM intake.manual_image_modes WHERE group_key IN ({gk_ph})',
                    gk_list,
                )
            ]

        if 'groups_tbl' in intake_tables:
            own_intake['groups_tbl'] = [
                r[0]
                for r in con.execute(
                    f'SELECT rowid FROM intake.groups_tbl WHERE group_key IN ({gk_ph})', gk_list
                )
            ]

        # Collect ALL local files and anchor directories for this host
        candidates: set[str] = set()
        local_dirs: list[str] = []

        raw_dirs = set()
        if group.get('local_dir'):
            raw_dirs.add(str(group['local_dir']))
        if 'groups_tbl' in intake_tables:
            for r in con.execute(
                f'SELECT local_dir FROM intake.groups_tbl WHERE group_key IN ({gk_ph})', gk_list
            ):
                if r[0]:
                    raw_dirs.add(str(r[0]))

        # Collect explicit file paths from owned DB rows
        def _collect_paths(sql: str, params=()):
            for r in con.execute(sql, params):
                for val in r:
                    f = _file(val)
                    if f:
                        candidates.add(f)
                        # If the file is inside an anchor's 素材 folder, also include that anchor folder
                        p_parent = Path(f).parent
                        if p_parent.name == '素材':
                            raw_dirs.add(str(p_parent.parent))

        if own_intake.get('assets'):
            _collect_paths(
                f'SELECT local_path FROM intake.assets WHERE group_key IN ({gk_ph})', gk_list
            )
        if tids and 'tasks' in intake_tables:
            t_ph = ','.join('?' * len(tids))
            _collect_paths(
                f'SELECT matched_asset_path FROM intake.tasks WHERE id IN ({t_ph})', tids
            )
        if own_intake.get('manual_image_modes'):
            _collect_paths(
                f'SELECT path FROM intake.manual_image_modes WHERE group_key IN ({gk_ph})',
                gk_list,
            )
        if empty_hosts and 'hosts' in main_tables:
            h_ph = ','.join('?' * len(empty_hosts))
            _collect_paths(
                f'SELECT image_path FROM main.hosts WHERE id IN ({h_ph})', empty_hosts
            )
        if vids:
            v_ph = ','.join('?' * len(vids))
            _collect_paths(
                f'SELECT image_path, edit_output_path FROM main.videos WHERE id IN ({v_ph})',
                vids,
            )
            if 'editing_history' in main_tables:
                _collect_paths(
                    f'SELECT job_path, output_path FROM main.editing_history WHERE video_id IN ({v_ph})',
                    vids,
                )
            if 'asset_jobs' in main_tables:
                _collect_paths(
                    f'SELECT local_path FROM main.asset_jobs WHERE video_id IN ({v_ph})',
                    vids,
                )
        if sids:
            s_ph = ','.join('?' * len(sids))
            if 'flow_segments' in main_tables:
                _collect_paths(
                    f'SELECT flow_output_path FROM main.flow_segments WHERE id IN ({s_ph})',
                    sids,
                )
            if 'flow_outputs' in main_tables:
                _collect_paths(
                    f'SELECT output_path FROM main.flow_outputs WHERE segment_id IN ({s_ph})',
                    sids,
                )
            if 'flow_dispatches' in main_tables:
                _collect_paths(
                    f'SELECT download_path FROM main.flow_dispatches WHERE segment_id IN ({s_ph})',
                    sids,
                )
            if 'speech_analysis' in main_tables:
                _collect_paths(
                    f'SELECT sidecar_path FROM main.speech_analysis WHERE segment_id IN ({s_ph})',
                    sids,
                )

        other_group_dirs = set()
        if 'groups_tbl' in intake_tables:
            for r in con.execute(
                f'SELECT local_dir FROM intake.groups_tbl WHERE group_key NOT IN ({gk_ph}) AND local_dir IS NOT NULL AND local_dir != ""',
                gk_list,
            ):
                od = _resolve_anchor_dir(r[0])
                if od:
                    other_group_dirs.add(str(od))

        for rd in sorted(raw_dirs):
            anchor_dir = _resolve_anchor_dir(rd)
            if not anchor_dir or str(anchor_dir) in other_group_dirs:
                continue
            if anchor_dir.exists() and anchor_dir.is_dir() and not anchor_dir.is_symlink() and str(anchor_dir) not in local_dirs:
                local_dirs.append(str(anchor_dir))
                try:
                    for sub in anchor_dir.rglob('*'):
                        if sub.is_file() and not sub.is_symlink() and sub.name != '.DS_Store':
                            candidates.add(str(sub))
                except OSError:
                    pass

        # Only protect a file if another DIFFERENT group_key in intake.assets actively references it
        protected: set[str] = set()
        if candidates and 'assets' in intake_tables:
            cand_list = sorted(candidates)
            c_ph = ','.join('?' * len(cand_list))
            for r in con.execute(
                f'SELECT local_path FROM intake.assets WHERE group_key NOT IN ({gk_ph}) AND local_path IN ({c_ph})',
                [*gk_list, *cand_list],
            ):
                if r[0]:
                    protected.add(str(r[0]))

        files = sorted(candidates - protected)

        # Collect command_ids for invalidating active Flow commands
        cmd_set: set[str] = set()
        if sids:
            s_ph = ','.join('?' * len(sids))
            if 'flow_dispatches' in main_tables:
                cmd_set.update(
                    str(r[0]).strip()
                    for r in con.execute(
                        f'SELECT command_id FROM main.flow_dispatches WHERE segment_id IN ({s_ph}) AND command_id IS NOT NULL AND command_id != ""',
                        sids,
                    )
                    if str(r[0]).strip()
                )
            if 'flow_outputs' in main_tables:
                cmd_set.update(
                    str(r[0]).strip()
                    for r in con.execute(
                        f'SELECT command_id FROM main.flow_outputs WHERE segment_id IN ({s_ph}) AND command_id IS NOT NULL AND command_id != ""',
                        sids,
                    )
                    if str(r[0]).strip()
                )
            if 'flow_segments' in main_tables:
                cmd_set.update(
                    str(r[0]).strip()
                    for r in con.execute(
                        f'SELECT generation_command FROM main.flow_segments WHERE id IN ({s_ph}) AND generation_command IS NOT NULL AND generation_command != ""',
                        sids,
                    )
                    if str(r[0]).strip()
                )
        command_ids = sorted(cmd_set)

        return dict(
            group_key=group_key,
            day=day,
            recipient=group['recipient'],
            anchor=group['anchor_name'],
            task_count=len(selected),
            video_ids=vids,
            intake_ids=tids,
            host_ids=hids,
            main=own_main,
            intake=own_intake,
            files=files,
            local_dirs=local_dirs,
            shared_files=sorted(candidates & protected),
            command_ids=command_ids,
        )
    finally:
        con.close()


def execute(plan):
    """Delete all database records and all local files & folders for the selected host."""
    if not isinstance(plan, dict) or 'main' not in plan or 'intake' not in plan:
        plan = preview(plan['group_key'], plan['day'])
    con = _connect()
    try:
        con.execute('BEGIN IMMEDIATE')
        con.execute('UPDATE intake.tasks SET id=id WHERE 0')

        for cmd in plan.get('command_ids', []):
            con.execute(
                "INSERT OR REPLACE INTO main.flow_obsolete_commands(command_id,host_id,reason,invalidated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                (
                    cmd,
                    int(plan.get('host_ids', [0])[0] if plan.get('host_ids') else 0),
                    '任务中心删除主播',
                ),
            )
        setting = con.execute(
            "SELECT value FROM main.app_settings WHERE key='flow_host_jobs_v124'"
        ).fetchone()
        if setting and plan.get('command_ids'):
            try:
                jobs = json.loads(setting['value'] or '[]')
                stale = set(plan['command_ids'])
                if isinstance(jobs, list):
                    jobs = [
                        j
                        for j in jobs
                        if str((j or {}).get('command_id') or '') not in stale
                    ]
                    con.execute(
                        "UPDATE main.app_settings SET value=? WHERE key='flow_host_jobs_v124'",
                        (json.dumps(jobs, ensure_ascii=False),),
                    )
            except Exception:
                pass

        # Delete dependent records in main before parent tables
        ordered = sorted(
            plan['main'],
            key=lambda t: (
                t in ('flow_segments', 'videos', 'hosts'),
                {'flow_segments': 1, 'videos': 2, 'hosts': 3}.get(t, 0),
            ),
        )
        for table in ordered:
            rowids = plan['main'][table]
            if not rowids:
                continue
            r_ph = ','.join('?' * len(rowids))
            con.execute(f'DELETE FROM main.{_quote(table)} WHERE rowid IN ({r_ph})', rowids)

        # Clean up empty recipients for this work_date
        try:
            con.execute(
                'DELETE FROM main.recipients WHERE work_date=? AND id NOT IN (SELECT DISTINCT recipient_id FROM main.hosts WHERE recipient_id IS NOT NULL)',
                (plan['day'],),
            )
        except Exception:
            pass

        for table, ids in plan['intake'].items():
            if not ids:
                continue
            r_ph = ','.join('?' * len(ids))
            con.execute(f'DELETE FROM intake.{_quote(table)} WHERE rowid IN ({r_ph})', ids)

        if plan.get('files'):
            try:
                f_list = list(plan['files'])
                f_ph = ','.join('?' * len(f_list))
                con.execute(
                    f'DELETE FROM intake.image_path_aliases WHERE old_path IN ({f_ph}) OR new_path IN ({f_ph})',
                    [*f_list, *f_list],
                )
            except Exception:
                pass

        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    # Delete the host's local directory trees first (fast bulk removal), then any remaining individual files
    deleted_files = len(plan.get('files') or [])
    deleted_dirs = 0
    shared_set = set(plan.get('shared_files') or [])
    removed_dir_paths: list[Path] = []

    for d_str in plan.get('local_dirs', []):
        d_path = Path(d_str)
        if not d_path.exists() or not d_path.is_dir() or d_path.is_symlink():
            continue
        has_shared = any(d_path in Path(sf).parents for sf in shared_set)
        if not has_shared:
            try:
                shutil.rmtree(d_path, ignore_errors=True)
                deleted_dirs += 1
                removed_dir_paths.append(d_path)
                parent_dir = d_path.parent
                if parent_dir.exists() and parent_dir.is_dir():
                    remaining = [
                        x for x in parent_dir.iterdir() if x.name != '.DS_Store'
                    ]
                    if not remaining:
                        ds = parent_dir / '.DS_Store'
                        if ds.exists():
                            ds.unlink(missing_ok=True)
                        parent_dir.rmdir()
            except OSError:
                pass

    for source in plan.get('files', []):
        p = Path(source)
        if any(dp in p.parents for dp in removed_dir_paths):
            continue
        try:
            if p.is_file() and not p.is_symlink():
                p.unlink()
        except OSError:
            pass

    message = f'已删除 {plan["task_count"]} 条任务及关联记录，彻底删除 {deleted_files} 个本地文件'
    if deleted_dirs:
        message += f'（含主播本地目录）'
    message += '。'
    if plan['shared_files']:
        message += f'另有 {len(plan["shared_files"])} 个共享文件仍被其他任务使用，已保留。'
    return dict(
        message=message,
        deleted_tasks=plan['task_count'],
        deleted_files=deleted_files,
        deleted_dirs=deleted_dirs,
        old_command_ids=list(plan.get('command_ids') or []),
    )
