"""AI watermark configuration, Google Sheet '素材来源' host binding, RGBA PNG rendering, and Resolve batch staging."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from app.core import database, repository as repo, work_dates

SETTING_KEY = 'ai_watermark_config'

SUB_MODE_HYBRID = 'hybrid'
SUB_MODE_IMAGE = 'image'
SUB_MODE_TEXT = 'text'
SUB_MODES = (SUB_MODE_HYBRID, SUB_MODE_IMAGE, SUB_MODE_TEXT)

OVERRIDE_AUTO = 'auto'
OVERRIDE_CUSTOM_PNG = 'custom_png'
OVERRIDE_IMAGE = 'image'
OVERRIDE_TEXT = 'text'
OVERRIDE_NONE = 'none'
OVERRIDE_MODES = (OVERRIDE_AUTO, OVERRIDE_CUSTOM_PNG, OVERRIDE_IMAGE, OVERRIDE_TEXT, OVERRIDE_NONE)

POS_PRESETS = (
    ('bottom_right', '右下角'),
    ('bottom_left', '左下角'),
    ('bottom_center', '底部居中'),
    ('top_right', '右上角'),
    ('top_left', '左上角'),
    ('top_center', '顶部居中'),
    ('center', '画面正中'),
)
POS_PRESET_KEYS = {k for k, _ in POS_PRESETS}

DEFAULT_TEXT_STYLE = {
    'prefix': '',
    'font_family': '',
    'font_size': 34,
    'bold': True,
    'text_color': '#FFFFFF',
    'stroke_color': '#000000',
    'stroke_width': 3,
    'opacity_pct': 88,
    'pos_preset': 'bottom_right',
    'offset_x': 36,
    'offset_y': 96,
}

DEFAULT_CONFIG = {
    'enabled': False,
    'main_enabled': True,
    'main_png_path': '',
    'sub_mode': SUB_MODE_HYBRID,
    'sub_png_dir': '',
    'text_style': dict(DEFAULT_TEXT_STYLE),
}

_SCHEMA_READY: set[str] = set()


def _norm_cell(val) -> str:
    return re.sub(r'\s+', '', str(val or '')).strip()


def _clean_source_name(val) -> str:
    """Cell in 素材来源 contains a single plain name with no delimiter symbols."""
    text = str(val or '').replace('\r', ' ').replace('\n', ' ').strip()
    return re.sub(r'\s+', ' ', text)


def _alpha_token(raw: str, length: int = 12) -> str:
    """Digit-free deterministic token (a-p) so DaVinci Resolve never groups PNGs as an image sequence."""
    digest = hashlib.sha1(raw.encode('utf-8', errors='ignore')).hexdigest()[:length]
    table = str.maketrans('0123456789abcdef', 'abcdefghijklmnop')
    return digest.translate(table)


def ensure_schema() -> None:
    db_key = str(database.DB_PATH)
    if db_key in _SCHEMA_READY:
        return
    with database.connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS host_watermarks (
                host_id INTEGER PRIMARY KEY,
                bound_name TEXT NOT NULL DEFAULT '',
                last_sheet_name TEXT NOT NULL DEFAULT '',
                override_mode TEXT NOT NULL DEFAULT 'auto',
                custom_png_path TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    _SCHEMA_READY.add(db_key)


def _clamp_int(val, default: int, lo: int, hi: int) -> int:
    try:
        num = int(float(val))
    except (TypeError, ValueError):
        num = default
    return max(lo, min(hi, num))


def _clean_hex_color(val, default: str) -> str:
    s = str(val or '').strip()
    if re.fullmatch(r'#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?', s):
        return s.upper()
    return default


def normalize_config(raw: dict | None) -> dict:
    src = raw if isinstance(raw, dict) else {}
    raw_style = src.get('text_style') if isinstance(src.get('text_style'), dict) else {}
    pos = str(raw_style.get('pos_preset') or DEFAULT_TEXT_STYLE['pos_preset'])
    if pos not in POS_PRESET_KEYS:
        pos = DEFAULT_TEXT_STYLE['pos_preset']
    style = {
        'prefix': str(raw_style.get('prefix') or '')[:40],
        'font_family': str(raw_style.get('font_family') or '').strip()[:80],
        'font_size': _clamp_int(raw_style.get('font_size'), 34, 12, 140),
        'bold': bool(raw_style.get('bold', True)),
        'text_color': _clean_hex_color(raw_style.get('text_color'), '#FFFFFF'),
        'stroke_color': _clean_hex_color(raw_style.get('stroke_color'), '#000000'),
        'stroke_width': _clamp_int(raw_style.get('stroke_width'), 3, 0, 16),
        'opacity_pct': _clamp_int(raw_style.get('opacity_pct'), 88, 10, 100),
        'pos_preset': pos,
        'offset_x': _clamp_int(raw_style.get('offset_x'), 36, 0, 480),
        'offset_y': _clamp_int(raw_style.get('offset_y'), 96, 0, 960),
    }
    sub_mode = str(src.get('sub_mode') or SUB_MODE_HYBRID)
    if sub_mode not in SUB_MODES:
        sub_mode = SUB_MODE_HYBRID
    return {
        'enabled': bool(src.get('enabled', False)),
        'main_enabled': bool(src.get('main_enabled', True)),
        'main_png_path': str(src.get('main_png_path') or '').strip(),
        'sub_mode': sub_mode,
        'sub_png_dir': str(src.get('sub_png_dir') or '').strip(),
        'text_style': style,
    }


def load_config() -> dict:
    raw = repo.get_setting(SETTING_KEY, '') or ''
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        parsed = {}
    return normalize_config(parsed)


def save_config(cfg: dict) -> dict:
    cleaned = normalize_config(cfg)
    repo.set_setting(SETTING_KEY, json.dumps(cleaned, ensure_ascii=False))
    return cleaned


def summary_badge_text(cfg: dict | None = None) -> str:
    cfg = normalize_config(cfg) if cfg is not None else load_config()
    if not cfg.get('enabled'):
        return '💧 AI水印：未开启'
    mode_map = {
        SUB_MODE_HYBRID: '智能混合',
        SUB_MODE_IMAGE: '图片匹配',
        SUB_MODE_TEXT: '文字水印',
    }
    return f"💧 AI水印：已开启 · {mode_map.get(cfg.get('sub_mode'), '智能混合')}"


def list_hosts_for_date(day: str | None = None) -> list[dict]:
    """Return all hosts belonging to the given workspace date along with their watermark bindings."""
    ensure_schema()
    target_day = work_dates.normalize_scope(day or work_dates.active())
    with database.connect() as con:
        rec_dates = work_dates.recipient_dates(con)
        valid_rids = [int(rid) for rid, d in rec_dates.items() if d == target_day]
        if not valid_rids:
            return []
        placeholders = ','.join('?' * len(valid_rids))
        rows = con.execute(
            f"""
            SELECT h.id AS host_id,
                   h.name AS host_name,
                   r.id AS recipient_id,
                   r.name AS recipient_name,
                   COUNT(v.id) AS video_count,
                   MIN(CASE WHEN TRIM(COALESCE(v.source_row, '')) <> '' THEN CAST(v.source_row AS INTEGER) END) AS first_source_row,
                   COALESCE(hw.bound_name, '') AS bound_name,
                   COALESCE(hw.last_sheet_name, '') AS last_sheet_name,
                   COALESCE(hw.override_mode, 'auto') AS override_mode,
                   COALESCE(hw.custom_png_path, '') AS custom_png_path
              FROM hosts h
              JOIN recipients r ON r.id = h.recipient_id
              LEFT JOIN videos v ON v.host_id = h.id
              LEFT JOIN host_watermarks hw ON hw.host_id = h.id
             WHERE r.id IN ({placeholders})
             GROUP BY h.id
             ORDER BY r.id, h.id
            """,
            valid_rids,
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        if item['override_mode'] not in OVERRIDE_MODES:
            item['override_mode'] = OVERRIDE_AUTO
        out.append(item)
    return out


def get_host_bindings_map(host_ids: list[int] | set[int]) -> dict[int, dict]:
    ensure_schema()
    ids = sorted({int(x) for x in host_ids if x is not None})
    if not ids:
        return {}
    placeholders = ','.join('?' * len(ids))
    with database.connect() as con:
        rows = con.execute(
            f"""
            SELECT host_id, bound_name, last_sheet_name, override_mode, custom_png_path
              FROM host_watermarks
             WHERE host_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    found = {}
    for r in rows:
        d = dict(r)
        if d['override_mode'] not in OVERRIDE_MODES:
            d['override_mode'] = OVERRIDE_AUTO
        found[int(d['host_id'])] = d
    for hid in ids:
        found.setdefault(
            hid,
            {
                'host_id': hid,
                'bound_name': '',
                'last_sheet_name': '',
                'override_mode': OVERRIDE_AUTO,
                'custom_png_path': '',
            },
        )
    return found


def save_host_binding(
    host_id: int,
    bound_name: str | None = None,
    override_mode: str | None = None,
    custom_png_path: str | None = None,
    last_sheet_name: str | None = None,
) -> dict:
    ensure_schema()
    hid = int(host_id)
    now = datetime.now().isoformat(timespec='seconds')
    current = get_host_bindings_map([hid])[hid]
    new_bound = _clean_source_name(bound_name) if bound_name is not None else current['bound_name']
    new_sheet = _clean_source_name(last_sheet_name) if last_sheet_name is not None else current['last_sheet_name']
    new_mode = str(override_mode or current['override_mode'])
    if new_mode not in OVERRIDE_MODES:
        new_mode = OVERRIDE_AUTO
    new_png = str(custom_png_path).strip() if custom_png_path is not None else current['custom_png_path']
    with database.connect() as con:
        con.execute(
            """
            INSERT INTO host_watermarks (host_id, bound_name, last_sheet_name, override_mode, custom_png_path, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(host_id) DO UPDATE SET
                bound_name = excluded.bound_name,
                last_sheet_name = excluded.last_sheet_name,
                override_mode = excluded.override_mode,
                custom_png_path = excluded.custom_png_path,
                updated_at = excluded.updated_at
            """,
            (hid, new_bound, new_sheet, new_mode, new_png, now),
        )
    return {
        'host_id': hid,
        'bound_name': new_bound,
        'last_sheet_name': new_sheet,
        'override_mode': new_mode,
        'custom_png_path': new_png,
    }


def save_host_bindings_bulk(entries: list[dict]) -> None:
    """Persist multiple host bindings edited in AIWatermarkDialog in one transaction."""
    ensure_schema()
    if not entries:
        return
    now = datetime.now().isoformat(timespec='seconds')
    existing = get_host_bindings_map([int(e['host_id']) for e in entries if e.get('host_id') is not None])
    params = []
    for e in entries:
        if e.get('host_id') is None:
            continue
        hid = int(e['host_id'])
        cur = existing.get(hid, {})
        bname = _clean_source_name(e.get('bound_name', cur.get('bound_name', '')))
        sname = _clean_source_name(e.get('last_sheet_name', cur.get('last_sheet_name', '')))
        omode = str(e.get('override_mode') or cur.get('override_mode') or OVERRIDE_AUTO)
        if omode not in OVERRIDE_MODES:
            omode = OVERRIDE_AUTO
        cpng = str(e.get('custom_png_path', cur.get('custom_png_path', '')) or '').strip()
        params.append((hid, bname, sname, omode, cpng, now))
    if not params:
        return
    with database.connect() as con:
        con.executemany(
            """
            INSERT INTO host_watermarks (host_id, bound_name, last_sheet_name, override_mode, custom_png_path, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(host_id) DO UPDATE SET
                bound_name = excluded.bound_name,
                last_sheet_name = excluded.last_sheet_name,
                override_mode = excluded.override_mode,
                custom_png_path = excluded.custom_png_path,
                updated_at = excluded.updated_at
            """,
            params,
        )


def bind_host_from_sheet_value(host_id: int, raw_source_name: str) -> None:
    """Bind or update a host's bound_name from Google Sheet's first row for that host."""
    ensure_schema()
    hid = int(host_id)
    cleaned = _clean_source_name(raw_source_name)
    cur = get_host_bindings_map([hid])[hid]
    if cur['bound_name'] == cleaned and cur['last_sheet_name'] == cleaned:
        return
    save_host_binding(hid, bound_name=cleaned, last_sheet_name=cleaned)


def sync_host_sources_from_tasks(tasks: list[dict], day: str | None = None) -> int:
    """Update already-promoted hosts in studio.db from parsed sheet tasks (first row per recipient+anchor)."""
    if not tasks:
        return 0
    ensure_schema()
    first_by_pair: dict[tuple[str, str], str] = {}
    for t in tasks:
        pair = (_norm_cell(t.get('需求人员')), _norm_cell(t.get('主播名称')))
        if pair[1] and pair not in first_by_pair:
            first_by_pair[pair] = _clean_source_name(t.get('素材来源'))
    if not first_by_pair:
        return 0

    candidates_days = {work_dates.active(), work_dates.today()}
    if day:
        c = work_dates.canonical(day)
        if c:
            candidates_days.add(c)
    updated_count = 0
    for target_day in candidates_days:
        try:
            hosts = list_hosts_for_date(target_day)
        except Exception:
            continue
        for h in hosts:
            pair = (_norm_cell(h['recipient_name']), _norm_cell(h['host_name']))
            if pair not in first_by_pair:
                continue
            new_name = first_by_pair[pair]
            if h['bound_name'] != new_name or h['last_sheet_name'] != new_name:
                save_host_binding(
                    int(h['host_id']),
                    bound_name=new_name,
                    last_sheet_name=new_name,
                )
                updated_count += 1
    return updated_count


def rescan_sheet_material_sources(day: str | None = None) -> dict:
    """Lightweight Google Sheet CSV re-read to bind/refresh '素材来源' for all hosts of `day`.

    - Never modifies scripts, prompts, assets, or video production states.
    - Immediately overwrites host bound_name when a sheet name was added, modified, or cleared.
    - Never raises errors if '素材来源' column is absent or cells are empty.
    """
    ensure_schema()
    target_day = work_dates.normalize_scope(day or work_dates.active())
    hosts = list_hosts_for_date(target_day)

    from app.services import pre_gpt_pipeline as pgp
    from app.services import sheet_columns

    settings = pgp.load_settings()
    sheet_url = str(settings.get('sheet_url') or '').strip()
    if not sheet_url:
        raise ValueError('请先在「系统设置」中填写 Google Sheet 任务表格链接。')

    sid, gid = pgp.parse_sheet_url(sheet_url)
    url = pgp.export_csv_url(sid, gid)
    _status, _ctype, raw = pgp.fetch_csv(url)
    txt = pgp.decode_bytes(raw)
    if '<!doctype html' in txt[:5000].lower() or 'accounts.google.com' in txt[:5000].lower():
        raise PermissionError('Google Sheet CSV 返回登录页，请确认表格可读或在任务中心连接有权限的 Google 账号。')

    rows = list(csv.reader(io.StringIO(txt)))
    spec = sheet_columns.load_spec()
    mode = spec.get('mode')

    src_ci = None
    rec_ci = None
    anchor_ci = None
    data_start_idx = 0

    if mode == sheet_columns.MODE_CUSTOM:
        resolved = sheet_columns.resolve_columns(rows, spec)
        src_ci = resolved.get('素材来源')
        rec_ci = resolved.get('需求人员')
        anchor_ci = resolved.get('主播名称')
        data_start_idx = 0
    else:
        try:
            hidx = pgp.find_header(rows)
        except ValueError:
            hidx = None
            for cand_i, cand_row in enumerate(rows[:20]):
                cand_map = pgp.header_map(cand_row)
                if _norm_cell('主播名称') in cand_map and (
                    _norm_cell('需求人员') in cand_map or _norm_cell('素材来源') in cand_map
                ):
                    hidx = cand_i
                    break
            if hidx is None:
                raise
        hmap = pgp.header_map(rows[hidx])
        src_ci = hmap.get(_norm_cell('素材来源'))
        rec_ci = hmap.get(_norm_cell('需求人员'))
        anchor_ci = hmap.get(_norm_cell('主播名称'))
        data_start_idx = hidx + 1

    if src_ci is None:
        unused = (
            mode == sheet_columns.MODE_CUSTOM
            and str((spec.get('columns') or {}).get('素材来源') or '') == sheet_columns.CHOICE_UNUSED
        )
        reason = (
            '系统设置中「素材来源」当前设为「不使用」，未读取表格副水印名字。'
            if unused
            else '当前 Google 表格中未检测到「素材来源」列，自动剪辑将自动跳过挂载水印（不会报错）。'
        )
        return {
            'ok': True,
            'column_found': False,
            'work_date': target_day,
            'total_hosts': len(hosts),
            'matched_hosts': 0,
            'added': 0,
            'updated': 0,
            'cleared': 0,
            'unchanged': len(hosts),
            'empty_hosts': sum(1 for h in hosts if not h['bound_name']),
            'changes': [],
            'message': reason,
        }

    def _cell_str(row_cells: list[str], ci: int | None) -> str:
        if ci is None or ci < 0 or ci >= len(row_cells):
            return ''
        return str(row_cells[ci] or '').strip()

    # Locate active block (批量制作中 ~ 批量已完成) if present, plus scan all rows as fallback for moved tasks.
    active_s_row1, active_e_row1 = pgp._find_active_row_bounds(rows)  # 1-based inclusive start, 1-based exclusive/end marker idx
    active_first_by_pair: dict[tuple[str, str], str] = {}
    fallback_first_by_pair: dict[tuple[str, str], str] = {}
    row_by_1based: dict[int, tuple[str, str, str]] = {}

    s_marker = _norm_cell(pgp.START_MARKER)
    e_marker = _norm_cell(pgp.END_MARKER)

    for ri in range(data_start_idx, len(rows)):
        row = rows[ri]
        exact = {_norm_cell(c) for c in row if _norm_cell(c)}
        if s_marker in exact or e_marker in exact:
            continue
        rec_val = _cell_str(row, rec_ci)
        anc_val = _cell_str(row, anchor_ci)
        if not anc_val:
            continue
        if _norm_cell(anc_val) == _norm_cell('主播名称') and _norm_cell(rec_val) == _norm_cell('需求人员'):
            continue
        src_val = _clean_source_name(_cell_str(row, src_ci))
        pair = (_norm_cell(rec_val), _norm_cell(anc_val))
        row_no_1 = ri + 1
        row_by_1based[row_no_1] = (pair[0], pair[1], src_val)

        in_active = (
            active_s_row1 is not None
            and active_e_row1 is not None
            and active_s_row1 <= row_no_1 <= active_e_row1
        )
        if in_active:
            if pair not in active_first_by_pair:
                active_first_by_pair[pair] = src_val
        else:
            if pair not in fallback_first_by_pair:
                fallback_first_by_pair[pair] = src_val

    # Keep pre_gpt_pipeline.sqlite3 tasks.material_source in sync too for future promotions.
    try:
        pcon = pgp.init_db()
        try:
            task_rows = pcon.execute(
                'SELECT id, sheet_row, recipient, anchor_name, COALESCE(material_source, "") FROM tasks WHERE spreadsheet_id=? AND gid=? AND sheet_row>0 ORDER BY sheet_row',
                (str(sid), str(gid)),
            ).fetchall()
            updates = []
            for tid, srow, trec, tanc, old_ms in task_rows:
                pair = (_norm_cell(trec), _norm_cell(tanc))
                new_ms = active_first_by_pair.get(pair)
                if new_ms is None and int(srow) in row_by_1based:
                    r_rec, r_anc, r_src = row_by_1based[int(srow)]
                    if r_anc == pair[1]:
                        new_ms = r_src
                if new_ms is not None and new_ms != str(old_ms or ''):
                    updates.append((new_ms, int(tid)))
            if updates:
                pcon.executemany('UPDATE tasks SET material_source=? WHERE id=?', updates)
                pcon.commit()
        finally:
            pcon.close()
    except Exception:
        pass

    added = 0
    updated = 0
    cleared = 0
    unchanged = 0
    matched_hosts = 0
    empty_hosts = 0
    changes = []

    for h in hosts:
        hid = int(h['host_id'])
        pair = (_norm_cell(h['recipient_name']), _norm_cell(h['host_name']))
        new_name: str | None = None

        # Priority 1: Active task block (批量制作中 ~ 批量已完成) first row for this host
        if pair in active_first_by_pair:
            new_name = active_first_by_pair[pair]
        else:
            # Priority 2: Exact first_source_row if recorded on videos and anchor matches
            first_srow = h.get('first_source_row')
            if first_srow is not None and int(first_srow) in row_by_1based:
                r_rec, r_anc, r_src = row_by_1based[int(first_srow)]
                if r_anc == pair[1] and (not pair[0] or not r_rec or r_rec == pair[0]):
                    new_name = r_src
            # Priority 3: Fallback scan across entire sheet (e.g. rows moved below 批量已完成)
            if new_name is None and pair in fallback_first_by_pair:
                new_name = fallback_first_by_pair[pair]
            # Priority 4: Anchor-only match in active block if recipient was renamed/empty
            if new_name is None and pair[1]:
                anchor_matches = [v for (rk, ak), v in active_first_by_pair.items() if ak == pair[1]]
                if len(anchor_matches) == 1:
                    new_name = anchor_matches[0]

        if new_name is None:
            if not h['bound_name']:
                empty_hosts += 1
            unchanged += 1
            continue

        matched_hosts += 1
        old_name = _clean_source_name(h.get('bound_name', ''))
        host_label = f"{h['recipient_name']} · {h['host_name']}"
        if old_name != new_name:
            save_host_binding(hid, bound_name=new_name, last_sheet_name=new_name)
            if not old_name and new_name:
                added += 1
            elif old_name and not new_name:
                cleared += 1
            else:
                updated += 1
            changes.append({'host_id': hid, 'host_label': host_label, 'old': old_name, 'new': new_name})
        else:
            if h.get('last_sheet_name', '') != new_name:
                save_host_binding(hid, bound_name=new_name, last_sheet_name=new_name)
            unchanged += 1

        if not new_name:
            empty_hosts += 1

    col_label = sheet_columns.index_to_letter(src_ci) + ' 列'
    parts = [f"已从表格「素材来源」（{col_label}）重新识别"]
    if not hosts:
        parts.append(f"当前日期 {target_day} 暂无已导入主播（同步任务后会自动绑定）")
    else:
        parts.append(f"匹配主播 {matched_hosts}/{len(hosts)} 位")
        if added:
            parts.append(f"新绑定 {added} 位")
        if updated:
            parts.append(f"名字变更同步替换 {updated} 位")
        if cleared:
            parts.append(f"清空 {cleared} 位")
        if empty_hosts:
            parts.append(f"名字为空跳过 {empty_hosts} 位")
        if not (added or updated or cleared):
            parts.append("所有主播绑定已是最新")

    return {
        'ok': True,
        'column_found': True,
        'column_letter': sheet_columns.index_to_letter(src_ci),
        'work_date': target_day,
        'total_hosts': len(hosts),
        'matched_hosts': matched_hosts,
        'added': added,
        'updated': updated,
        'cleared': cleared,
        'unchanged': unchanged,
        'empty_hosts': empty_hosts,
        'changes': changes,
        'message': '，'.join(parts) + '。',
    }


def find_matching_sub_png(sub_png_dir: str, source_name: str) -> Path | None:
    """Match `<source_name>.png` inside `sub_png_dir` (exact stem first, then case/whitespace-insensitive)."""
    name = _clean_source_name(source_name)
    folder_str = str(sub_png_dir or '').strip()
    if not name or not folder_str:
        return None
    folder = Path(folder_str).expanduser()
    if not folder.is_dir():
        return None

    direct = folder / f'{name}.png'
    if direct.is_file():
        return direct
    direct_upper = folder / f'{name}.PNG'
    if direct_upper.is_file():
        return direct_upper

    wanted_lower = name.lower()
    wanted_norm = _norm_cell(name).lower()
    norm_match: Path | None = None
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None
    for entry in entries:
        if entry.name.startswith('.') or not entry.is_file():
            continue
        if entry.suffix.lower() != '.png':
            continue
        stem = entry.stem.strip()
        if stem.lower() == wanted_lower:
            return entry
        if norm_match is None and _norm_cell(stem).lower() == wanted_norm:
            norm_match = entry
    return norm_match


def resolve_host_watermark_status(host_binding: dict, cfg: dict | None = None) -> dict:
    """Evaluate how a host's watermark will be mounted under `cfg` without writing files."""
    cfg = normalize_config(cfg) if cfg is not None else load_config()
    override = str(host_binding.get('override_mode') or OVERRIDE_AUTO)
    if override not in OVERRIDE_MODES:
        override = OVERRIDE_AUTO
    bound_name = _clean_source_name(host_binding.get('bound_name', ''))
    custom_png_str = str(host_binding.get('custom_png_path') or '').strip()

    main_png = ''
    if cfg.get('main_enabled') and cfg.get('main_png_path'):
        mp = Path(cfg['main_png_path']).expanduser()
        if mp.is_file():
            main_png = str(mp)

    if override == OVERRIDE_NONE:
        return {
            'active': False,
            'bound_name': bound_name,
            'mode_used': 'none',
            'main_png': '',
            'sub_png': '',
            'text_to_render': '',
            'status_label': '手动设为不挂载水印',
            'status_tone': 'muted',
        }

    if override == OVERRIDE_CUSTOM_PNG:
        cp = Path(custom_png_str).expanduser() if custom_png_str else None
        if cp and cp.is_file():
            return {
                'active': True,
                'bound_name': bound_name,
                'mode_used': 'custom_png',
                'main_png': main_png,
                'sub_png': str(cp),
                'text_to_render': '',
                'status_label': f'指定图片：{cp.name}',
                'status_tone': 'success',
            }
        return {
            'active': False,
            'bound_name': bound_name,
            'mode_used': 'missing_custom_png',
            'main_png': '',
            'sub_png': '',
            'text_to_render': '',
            'status_label': '未选择有效自定义 PNG（暂跳过）',
            'status_tone': 'warning',
        }

    # Empty 素材来源 rule: never error, and never auto-mount watermarks for this host.
    if not bound_name:
        return {
            'active': False,
            'bound_name': '',
            'mode_used': 'empty_skip',
            'main_png': '',
            'sub_png': '',
            'text_to_render': '',
            'status_label': '素材来源为空 · 自动跳过不挂载',
            'status_tone': 'muted',
        }

    eff_mode = cfg.get('sub_mode', SUB_MODE_HYBRID)
    if override == OVERRIDE_IMAGE:
        eff_mode = SUB_MODE_IMAGE
    elif override == OVERRIDE_TEXT:
        eff_mode = SUB_MODE_TEXT

    prefix = str((cfg.get('text_style') or {}).get('prefix') or '')
    full_text = f'{prefix}{bound_name}'

    if eff_mode in (SUB_MODE_IMAGE, SUB_MODE_HYBRID):
        matched = find_matching_sub_png(cfg.get('sub_png_dir', ''), bound_name)
        if matched is not None:
            return {
                'active': True,
                'bound_name': bound_name,
                'mode_used': 'image',
                'main_png': main_png,
                'sub_png': str(matched),
                'text_to_render': '',
                'status_label': f'方式A已匹配：{matched.name}',
                'status_tone': 'success',
            }
        if eff_mode == SUB_MODE_IMAGE:
            return {
                'active': False,
                'bound_name': bound_name,
                'mode_used': 'missing_image',
                'main_png': '',
                'sub_png': '',
                'text_to_render': '',
                'status_label': f'未找到 {bound_name}.png（补图后可点刷新水印）',
                'status_tone': 'warning',
            }

    return {
        'active': True,
        'bound_name': bound_name,
        'mode_used': 'text',
        'main_png': main_png,
        'sub_png': '',
        'text_to_render': full_text,
        'status_label': f'方式B文字生成：{full_text}',
        'status_tone': 'info',
    }


def _ensure_qt_gui_app():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        app = QGuiApplication([])
    return app


def render_text_watermark_qimage(
    text: str,
    style: dict | None = None,
    width: int = 720,
    height: int = 1280,
):
    """Render crisp anti-aliased stroked text onto a transparent RGBA QImage (1:1 timeline size)."""
    _ensure_qt_gui_app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import (
        QColor,
        QFont,
        QFontDatabase,
        QFontMetricsF,
        QImage,
        QPainter,
        QPainterPath,
        QPen,
    )

    norm_cfg = normalize_config({'text_style': style or {}})
    st = norm_cfg['text_style']

    img = QImage(int(width), int(height), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    label = str(text or '').strip()
    if not label:
        return img

    family = st['font_family']
    if not family:
        avail = set(QFontDatabase.families())
        for candidate in ('PingFang SC', 'Hiragino Sans GB', 'Heiti SC', 'Microsoft YaHei', 'Arial Unicode MS', 'Arial'):
            if candidate in avail:
                family = candidate
                break

    font_size = float(st['font_size'])
    font = QFont(family) if family else QFont()
    font.setPixelSize(max(12, int(round(font_size))))
    font.setBold(bool(st['bold']))

    # Auto-fit if text exceeds safe horizontal width so long names never clip.
    max_text_w = max(120.0, float(width) - 2.0 * float(st['offset_x']) - 24.0)
    fm = QFontMetricsF(font)
    tw = fm.horizontalAdvance(label)
    if tw > max_text_w and tw > 1.0:
        scaled_px = max(12, int(font.pixelSize() * (max_text_w / tw)))
        font.setPixelSize(scaled_px)
        fm = QFontMetricsF(font)
        tw = fm.horizontalAdvance(label)

    ascent = fm.ascent()
    descent = fm.descent()
    th = ascent + descent

    preset = st['pos_preset']
    ox = float(st['offset_x'])
    oy = float(st['offset_y'])

    if 'left' in preset:
        x = ox
    elif 'right' in preset:
        x = float(width) - ox - tw
    else:
        x = (float(width) - tw) * 0.5

    if preset.startswith('top_'):
        baseline_y = oy + ascent
    elif preset.startswith('bottom_'):
        baseline_y = float(height) - oy - descent
    else:
        baseline_y = (float(height) - th) * 0.5 + ascent

    x = max(8.0, min(float(width) - tw - 8.0, x))
    baseline_y = max(ascent + 8.0, min(float(height) - descent - 8.0, baseline_y))

    path = QPainterPath()
    path.addText(x, baseline_y, font, label)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setOpacity(max(0.1, min(1.0, float(st['opacity_pct']) / 100.0)))

    stroke_w = int(st['stroke_width'])
    if stroke_w > 0:
        stroke_col = QColor(st['stroke_color'])
        pen = QPen(stroke_col, float(stroke_w * 2), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    fill_col = QColor(st['text_color'])
    painter.setPen(Qt.NoPen)
    painter.setBrush(fill_col)
    painter.drawPath(path)
    painter.end()
    return img


def render_text_watermark_png(
    text: str,
    out_path: str | Path,
    style: dict | None = None,
    width: int = 720,
    height: int = 1280,
) -> Path:
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = render_text_watermark_qimage(text, style=style, width=width, height=height)
    if not img.save(str(dest), 'PNG'):
        raise RuntimeError(f'生成文字透明水印 PNG 失败：{dest}')
    return dest


def _image_alpha_bbox(img) -> tuple[int, int, int, int] | None:
    """Return exact (x0, y0, x1, y1) bounding box of pixels with alpha > 4, or None if fully transparent."""
    from PySide6.QtGui import QImage

    if img is None or img.isNull():
        return None
    rgba = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = rgba.width(), rgba.height()
    stride = rgba.bytesPerLine()
    mv = memoryview(rgba.constBits())
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        row = mv[y * stride : y * stride + w * 4]
        alphas = row[3::4]
        if max(alphas, default=0) > 4:
            if y < min_y:
                min_y = y
            max_y = y
            for x, a in enumerate(alphas):
                if a > 4:
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
    if max_x < 0:
        return None
    return min_x, min_y, max_x + 1, max_y + 1


def _landscape_offset_for_bbox(
    bbox: tuple[int, int, int, int] | None,
    w_src: int,
    h_src: int,
    w_dst: int,
    h_dst: int,
) -> tuple[int, int]:
    """Compute corner/edge-preserving (dx, dy) from a portrait (w_src, h_src) watermark onto (w_dst, h_dst)."""
    if not bbox:
        return 0, 0
    x0, y0, x1, y1 = bbox
    left_m = x0
    right_m = max(0, w_src - x1)
    top_m = y0
    bot_m = max(0, h_src - y1)

    if left_m <= 96 and left_m <= right_m:
        dx = 0
    elif right_m <= 96 and right_m < left_m:
        dx = w_dst - w_src
    elif left_m < right_m * 0.6:
        dx = 0
    elif right_m < left_m * 0.6:
        dx = w_dst - w_src
    else:
        dx = int(round((w_dst - (x0 + x1)) * 0.5))

    span_h = y1 - y0
    if y1 <= h_dst and (top_m <= 160 or top_m <= bot_m * 0.6):
        dy = 0
    elif span_h <= h_dst and (bot_m <= 240 or bot_m < top_m * 0.6):
        dy = h_dst - h_src
    else:
        dy = int(round((h_dst - (y0 + y1)) * 0.5))
    return dx, dy


def _adapt_portrait_png_to_landscape(
    src_path: Path,
    dest_path: Path,
    shared_bbox: tuple[int, int, int, int] | None = None,
) -> Path:
    """Adapt a full-frame portrait PNG overlay (e.g. 1080x1920) onto a matching 16:9 canvas (e.g. 1920x1080)
    so DaVinci Resolve renders it at the exact same physical corner size on 16:9 exports without shrinking."""
    _ensure_qt_gui_app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    img = QImage(str(src_path))
    if img.isNull():
        shutil.copy2(src_path, dest_path)
        return dest_path
    w_src, h_src = img.width(), img.height()
    # Already landscape/square or small standalone logo badge: keep as-is.
    if w_src >= h_src or h_src < 720:
        shutil.copy2(src_path, dest_path)
        return dest_path

    w_dst, h_dst = h_src, w_src
    bbox = shared_bbox if shared_bbox is not None else _image_alpha_bbox(img)
    out = QImage(w_dst, h_dst, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        if (y1 - y0) > h_dst:
            scaled = img.scaled(w_dst, h_dst, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter = QPainter(out)
            painter.drawImage((w_dst - scaled.width()) // 2, (h_dst - scaled.height()) // 2, scaled)
            painter.end()
        else:
            dx, dy = _landscape_offset_for_bbox(bbox, w_src, h_src, w_dst, h_dst)
            painter = QPainter(out)
            painter.drawImage(int(dx), int(dy), img)
            painter.end()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if not out.save(str(dest_path), 'PNG'):
        shutil.copy2(src_path, dest_path)
    return dest_path


def prepare_batch_watermark_plan(batch_id: str, batch_dir: str | Path) -> Path:
    """Stage digit-free PNG files and write `watermark_plan.ini` for `FlowStudio_Finish_Batch.lua`.

    - Main watermark goes on lower watermark track (`baseTrack`).
    - Sub watermark goes on upper watermark track (`subTrack`, stacked above main watermark).
    - Consecutive videos belonging to the same `host_id` and orientation share a single continuous `[first_start, last_end)` span.
    - 16:9 landscape videos automatically receive 16:9-adapted transparent watermark PNGs so watermarks never shrink or clip.
    - Hosts with empty `素材来源` (and no manual custom PNG) have `wm_active=0` and mount nothing.
    """
    from app.services import resolve_daily as daily

    ensure_schema()
    bdir = Path(batch_dir)
    wm_dir = bdir / 'watermarks'
    wm_dir.mkdir(parents=True, exist_ok=True)
    plan_path = bdir / 'watermark_plan.ini'

    cfg = load_config()
    with database.connect() as con:
        vrows = con.execute(
            """
            SELECT d.video_id, d.rowid AS row_ord, v.host_id, h.name AS host_name, r.name AS recipient_name,
                   (SELECT fs.flow_output_path FROM flow_segments fs
                     WHERE fs.video_id = v.id AND fs.seg_seq < 1000
                       AND COALESCE(fs.flow_output_path, '') <> ''
                     ORDER BY fs.seg_seq ASC LIMIT 1) AS first_seg_path
              FROM davinci_video_state d
              JOIN videos v ON v.id = d.video_id
              JOIN hosts h ON h.id = v.host_id
              JOIN recipients r ON r.id = h.recipient_id
             WHERE d.batch_id = ?
             ORDER BY COALESCE(d.timeline_start_frame, 999999999), d.rowid
            """,
            (str(batch_id),),
        ).fetchall()

    pairs: dict[str, str | int] = {
        'enabled': '1' if cfg.get('enabled') else '0',
        'batch_id': str(batch_id),
        'video_count': len(vrows),
    }

    if not cfg.get('enabled') or not vrows:
        daily.atomic_pairs(plan_path, pairs)
        return plan_path

    host_ids = {int(r['host_id']) for r in vrows}
    bindings = get_host_bindings_map(host_ids)

    video_orients: dict[int, str] = {}
    need_landscape_by_host: dict[int, bool] = {}
    for r in vrows:
        vid = int(r['video_id'])
        hid = int(r['host_id'])
        fseg = str(r['first_seg_path'] or '').strip()
        ew, eh, _ear = daily.resolve_video_export_size(
            host_id=hid,
            seg_paths=[fseg] if fseg else None,
        )
        orient = 'landscape' if ew > eh else 'portrait'
        video_orients[vid] = orient
        if orient == 'landscape':
            need_landscape_by_host[hid] = True

    # Stage Main PNG once (portrait + optional landscape) with digit-free content-addressed filenames.
    staged_main_png = ''
    main_src_path: Path | None = None
    main_bbox: tuple[int, int, int, int] | None = None
    main_dims: tuple[int, int] | None = None
    main_label = ''
    if cfg.get('main_enabled') and cfg.get('main_png_path'):
        mp = Path(cfg['main_png_path']).expanduser()
        if mp.is_file():
            main_src_path = mp
            st = mp.stat()
            tok = _alpha_token(f'main|{mp.resolve()}|{st.st_size}|{st.st_mtime_ns}')
            dest_main = wm_dir / f'flowstudio_wm_main_{tok}_base.png'
            if not dest_main.is_file():
                shutil.copy2(mp, dest_main)
            staged_main_png = str(dest_main)
            main_label = mp.name if mp.name.lower().endswith('.png') else f'{mp.name}.png'
            if need_landscape_by_host:
                _ensure_qt_gui_app()
                from PySide6.QtGui import QImage
                m_qimg = QImage(str(mp))
                if not m_qimg.isNull():
                    main_dims = (m_qimg.width(), m_qimg.height())
                    main_bbox = _image_alpha_bbox(m_qimg)
    if main_label:
        pairs['main_label'] = main_label

    # Stage Sub PNG per (host, orient).
    host_stage_cache: dict[tuple[int, str], tuple[bool, str, str, str, str]] = {}
    style_json = json.dumps(cfg.get('text_style') or {}, sort_keys=True, ensure_ascii=False)

    for hid in sorted(host_ids):
        ev = resolve_host_watermark_status(bindings[hid], cfg)
        orients_needed = ['portrait']
        if need_landscape_by_host.get(hid):
            orients_needed.append('landscape')
        for orient in orients_needed:
            if not ev['active']:
                host_stage_cache[(hid, orient)] = (False, '', '', '', ev['status_label'])
                continue

            is_land = orient == 'landscape'
            cur_main = staged_main_png
            staged_sub = ''
            sub_label = ''

            if ev['sub_png']:
                sp = Path(ev['sub_png'])
                if sp.is_file():
                    st = sp.stat()
                    sub_label = sp.name if sp.name.lower().endswith('.png') else f'{sp.name}.png'
                    if not is_land:
                        tok = _alpha_token(f'subimg|{hid}|{sp.resolve()}|{st.st_size}|{st.st_mtime_ns}')
                        dest_sub = wm_dir / f'flowstudio_wm_sub_{tok}_layer.png'
                        if not dest_sub.is_file():
                            shutil.copy2(sp, dest_sub)
                        staged_sub = str(dest_sub)
                    else:
                        # Compute shared bbox if main_png and sub_png are same-size portrait overlays in the same vertical band
                        shared_box = None
                        sub_box = None
                        _ensure_qt_gui_app()
                        from PySide6.QtGui import QImage
                        s_qimg = QImage(str(sp))
                        if not s_qimg.isNull():
                            sub_box = _image_alpha_bbox(s_qimg)
                            if (
                                main_dims == (s_qimg.width(), s_qimg.height())
                                and main_bbox is not None
                                and sub_box is not None
                                and max(main_bbox[1], sub_box[1]) <= min(main_bbox[3], sub_box[3]) + 80
                            ):
                                shared_box = (
                                    min(main_bbox[0], sub_box[0]),
                                    min(main_bbox[1], sub_box[1]),
                                    max(main_bbox[2], sub_box[2]),
                                    max(main_bbox[3], sub_box[3]),
                                )
                        tok_s = _alpha_token(f'subimgL|{hid}|{sp.resolve()}|{st.st_size}|{st.st_mtime_ns}|{shared_box}')
                        dest_sub = wm_dir / f'flowstudio_wm_sub_{tok_s}_landscape.png'
                        if not dest_sub.is_file():
                            _adapt_portrait_png_to_landscape(sp, dest_sub, shared_bbox=shared_box or sub_box)
                        staged_sub = str(dest_sub)
                        if main_src_path is not None:
                            mst = main_src_path.stat()
                            tok_m = _alpha_token(f'mainL|{main_src_path.resolve()}|{mst.st_size}|{mst.st_mtime_ns}|{shared_box}')
                            dest_main_l = wm_dir / f'flowstudio_wm_main_{tok_m}_landscape.png'
                            if not dest_main_l.is_file():
                                _adapt_portrait_png_to_landscape(main_src_path, dest_main_l, shared_bbox=shared_box or main_bbox)
                            cur_main = str(dest_main_l)
            elif ev['text_to_render']:
                txt_label = ev['text_to_render']
                sub_label = txt_label if txt_label.lower().endswith('.png') else f'{txt_label}.png'
                if not is_land:
                    tok = _alpha_token(f'subtxt|{hid}|{txt_label}|{style_json}')
                    dest_sub = wm_dir / f'flowstudio_wm_sub_{tok}_layer.png'
                    if not dest_sub.is_file():
                        render_text_watermark_png(txt_label, dest_sub, style=cfg.get('text_style'), width=720, height=1280)
                    staged_sub = str(dest_sub)
                else:
                    tok = _alpha_token(f'subtxtL|{hid}|{txt_label}|{style_json}')
                    dest_sub = wm_dir / f'flowstudio_wm_sub_{tok}_landscape.png'
                    if not dest_sub.is_file():
                        render_text_watermark_png(txt_label, dest_sub, style=cfg.get('text_style'), width=1280, height=720)
                    staged_sub = str(dest_sub)
                    if main_src_path is not None:
                        mst = main_src_path.stat()
                        tok_m = _alpha_token(f'mainL|{main_src_path.resolve()}|{mst.st_size}|{mst.st_mtime_ns}|{main_bbox}')
                        dest_main_l = wm_dir / f'flowstudio_wm_main_{tok_m}_landscape.png'
                        if not dest_main_l.is_file():
                            _adapt_portrait_png_to_landscape(main_src_path, dest_main_l, shared_bbox=main_bbox)
                        cur_main = str(dest_main_l)
            elif is_land and main_src_path is not None:
                mst = main_src_path.stat()
                tok_m = _alpha_token(f'mainL|{main_src_path.resolve()}|{mst.st_size}|{mst.st_mtime_ns}|{main_bbox}')
                dest_main_l = wm_dir / f'flowstudio_wm_main_{tok_m}_landscape.png'
                if not dest_main_l.is_file():
                    _adapt_portrait_png_to_landscape(main_src_path, dest_main_l, shared_bbox=main_bbox)
                cur_main = str(dest_main_l)

            has_any = bool(cur_main or staged_sub)
            host_stage_cache[(hid, orient)] = (has_any, cur_main if has_any else '', staged_sub, sub_label, ev['status_label'])

    active_hosts = 0
    skipped_hosts = 0
    seen_hosts = set()
    for idx, r in enumerate(vrows, start=1):
        vid = int(r['video_id'])
        hid = int(r['host_id'])
        orient = video_orients.get(vid, 'portrait')
        wm_active, main_p, sub_p, sub_lbl, note = host_stage_cache[(hid, orient)]
        _p_act, port_main_p, port_sub_p, _p_lbl, _p_note = host_stage_cache[(hid, 'portrait')]
        if hid not in seen_hosts:
            seen_hosts.add(hid)
            if wm_active:
                active_hosts += 1
            else:
                skipped_hosts += 1
        pairs[f'v{idx}_id'] = vid
        pairs[f'v{idx}_host_key'] = f'host_{_alpha_token(str(hid), 8)}'
        pairs[f'v{idx}_host_name'] = f"{r['recipient_name']} · {r['host_name']}"
        pairs[f'v{idx}_orient'] = orient
        pairs[f'v{idx}_wm_active'] = '1' if wm_active else '0'
        pairs[f'v{idx}_main_png'] = main_p
        pairs[f'v{idx}_sub_png'] = sub_p
        pairs[f'v{idx}_main_png_portrait'] = port_main_p
        pairs[f'v{idx}_sub_png_portrait'] = port_sub_p
        pairs[f'v{idx}_sub_label'] = sub_lbl
        pairs[f'v{idx}_note'] = note

    pairs['active_host_count'] = active_hosts
    pairs['skipped_host_count'] = skipped_hosts
    daily.atomic_pairs(plan_path, pairs)
    return plan_path


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


def sync_resolve_project_watermark_durations(spec_path: str | Path) -> bool:
    """Sync exact [Start, Duration) frame spans for plain PNG still watermarks in Resolve's `Project.db`.

    DaVinci Resolve's `AppendToTimeline` ignores `endFrame` on Still Images (`In='90000'`), clamping every
    newly appended PNG clip to `<StillDurationFrames>` (typically 125 frames = 5.0s). Updating `Sm2TiItem.Start`
    and `Sm2TiItem.Duration` after `pm:SaveProject()` and reloading via `pm:LoadProject()` yields native
    single-clip plain PNG Still items (`Sm2TiVideoClip`) with infinite trim/stretch handles on both edges and
    zero-frame overrun across host boundaries.
    """
    import sqlite3

    spath = Path(spec_path).expanduser()
    if not spath.is_file():
        return False

    spec: dict[str, str] = {}
    for line in spath.read_text(encoding='utf-8', errors='replace').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            spec[k.strip()] = v.strip()

    item_count = int(spec.get('item_count') or 0)
    if item_count <= 0:
        return False

    pdb = _resolve_project_db_path(
        spec.get('project_name', ''),
        spec.get('project_db_path', ''),
    )
    if pdb is None:
        return False

    need_main_fallback = any(
        spec.get(f'item_{i}_kind', '') == 'main' and spec.get(f'item_{i}_label', '') in ('', '主水印.png')
        for i in range(1, item_count + 1)
    )
    main_basename = ''
    if need_main_fallback:
        try:
            cfg = load_config()
            if cfg.get('main_png_path'):
                mp_name = Path(str(cfg['main_png_path'])).expanduser().name
                if mp_name:
                    main_basename = mp_name if mp_name.lower().endswith('.png') else f'{mp_name}.png'
        except Exception:
            main_basename = ''

    updated = 0
    with sqlite3.connect(str(pdb), timeout=10.0) as con:
        timeline_uid = spec.get('timeline_uid', '')
        timeline_name = spec.get('timeline_name', '')
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

        vtrack_ids: list[str] = []
        if seq_row and seq_row[0]:
            vtrack_ids = [
                str(r[0])
                for r in con.execute(
                    'SELECT Sm2TiTrack_id FROM Sm2TiTrack WHERE Sequence = ? AND Type = 0',
                    (seq_row[0],),
                ).fetchall()
            ]

        for idx in range(1, item_count + 1):
            pre = f'item_{idx}_'
            clip_uid = spec.get(pre + 'uid', '')
            try:
                start_val = int(float(spec[pre + 'start']))
                dur_val = int(float(spec[pre + 'duration']))
            except (KeyError, ValueError):
                continue
            if dur_val <= 0:
                continue

            kind = spec.get(pre + 'kind', '')
            label = spec.get(pre + 'label', '')
            png_path = spec.get(pre + 'png', '')
            if kind == 'main' and (not label or label == '主水印.png') and main_basename:
                label = main_basename

            row_hits = 0
            if clip_uid:
                if label:
                    cur = con.execute(
                        'UPDATE Sm2TiItem SET Start = ?, Duration = ?, Name = ? WHERE Sm2TiItem_id = ?',
                        (str(start_val), str(dur_val), label, clip_uid),
                    )
                else:
                    cur = con.execute(
                        'UPDATE Sm2TiItem SET Start = ?, Duration = ? WHERE Sm2TiItem_id = ?',
                        (str(start_val), str(dur_val), clip_uid),
                    )
                row_hits = cur.rowcount or 0

            if row_hits == 0 and vtrack_ids and png_path:
                q_marks = ','.join('?' for _ in vtrack_ids)
                if label:
                    cur = con.execute(
                        f'UPDATE Sm2TiItem SET Start = ?, Duration = ?, Name = ? '
                        f'WHERE Sm2TiTrack_id IN ({q_marks}) AND MediaFilePath = ? AND CAST(Start AS INTEGER) = ?',
                        (str(start_val), str(dur_val), label, *vtrack_ids, png_path, start_val),
                    )
                else:
                    cur = con.execute(
                        f'UPDATE Sm2TiItem SET Start = ?, Duration = ? '
                        f'WHERE Sm2TiTrack_id IN ({q_marks}) AND MediaFilePath = ? AND CAST(Start AS INTEGER) = ?',
                        (str(start_val), str(dur_val), *vtrack_ids, png_path, start_val),
                    )
                row_hits = cur.rowcount or 0

            updated += row_hits

        if updated > 0:
            con.commit()
    return updated > 0


# Backward-compatible alias used by combined Lua/CLI callers
sync_project_db_watermark_durations = sync_resolve_project_watermark_durations


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 2 and sys.argv[1] == '--sync-durations':
        synced = sync_resolve_project_watermark_durations(sys.argv[2])
        print('WM_DURATIONS_SYNCED' if synced else 'WM_DURATIONS_NOOP')
        sys.exit(0)
    if len(sys.argv) > 3 and sys.argv[1] == '--prepare-batch':
        out_p = prepare_batch_watermark_plan(sys.argv[2], sys.argv[3])
        print(f'WM_PLAN_READY:{out_p}')
        sys.exit(0)
