"""Read-only Sheets cell snapshots. Text and appearance have separate storage."""
from collections import OrderedDict
import copy
import json
from app.core.database import connect


def letter(index):
    result = ''
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def enrich(sheets, spreadsheet_id, title, parsed):
    tasks = parsed['tasks']
    if not tasks:
        return
    if sheets is None:
        raise RuntimeError('无法读取表格原始样式，请先连接 Google 账号后重新同步；本次未写入任务。')
    columns = {key: parsed['header_map'][key] for key in ('中文内容', '外文内容') if parsed.get('header_map', {}).get(key) is not None}
    if not columns:
        return
    from app.services.eye_states import reference_mode
    pending_tasks = [t for t in tasks if not t.get('_source_styles')]
    if not pending_tasks:
        for task in tasks:
            task['模式'] = reference_mode(task['_source_styles'], task.get('模式', 'TALKING'))
        return
    start, end = min(t['表格行号'] for t in pending_tasks), max(t['表格行号'] for t in pending_tasks)
    quoted = title.replace("'", "''")
    ranges = [f"'{quoted}'!{letter(c)}{start}:{letter(c)}{end}" for c in columns.values()]
    response = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=ranges,
        includeGridData=True, fields='properties(defaultFormat,spreadsheetTheme),sheets(data(startRow,startColumn,rowData(values(formattedValue,userEnteredValue,effectiveFormat,userEnteredFormat,textFormatRuns))))').execute()
    props = response.get('properties', {})
    cells = {}
    for sheet in response.get('sheets', []):
        for grid in sheet.get('data', []):
            for row_index, row in enumerate(grid.get('rowData', []), grid.get('startRow', 0)):
                for col_index, cell in enumerate(row.get('values', []), grid.get('startColumn', 0)):
                    cells[row_index + 1, col_index] = cell
    for task in tasks:
        if task.get('_source_styles'):
            task['模式'] = reference_mode(task['_source_styles'], task.get('模式', 'TALKING'))
            continue
        styles = {}
        for key, col in columns.items():
            cell = copy.deepcopy(cells.get((task['表格行号'], col), {}))
            text = cell.get('userEnteredValue', {}).get('stringValue', cell.get('formattedValue', ''))
            if text != task[key]:
                raise RuntimeError(f"第 {task['表格行号']} 行文案在读取期间发生变化，请重新同步。")
            styles[key] = {'text': text, 'base_mode': task.get('模式','TALKING'), 'cell': cell, 'defaults': props.get('defaultFormat', {}),
                           'theme': props.get('spreadsheetTheme', {})}
        task['_source_styles'] = styles
        task['模式'] = reference_mode(styles, task.get('模式', 'TALKING'))


_snapshot_cache: "OrderedDict[int, tuple]" = OrderedDict()
_ENSURED_STYLE_DBS: set[str] = set()


def ensure_table(con):
    db_key = getattr(con, '_pool_db_str', None)
    if db_key and db_key in _ENSURED_STYLE_DBS:
        return
    con.execute('CREATE TABLE IF NOT EXISTS video_source_styles(video_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
    if db_key:
        _ENSURED_STYLE_DBS.add(db_key)


def save_video(video_id, payload):
    if not payload:
        return
    _snapshot_cache.pop(int(video_id), None)
    with connect() as con:
        ensure_table(con)
        previous = con.execute('SELECT payload FROM video_source_styles WHERE video_id=?', (video_id,)).fetchone()
        payload = copy.deepcopy(payload)
        if previous:
            old = json.loads(previous[0])
            for key in ('中文内容', '外文内容'):
                if old.get(key, {}).get('local_override') and key in payload:
                    payload[key]['local_override'] = True
        con.execute('INSERT INTO video_source_styles VALUES(?,?) ON CONFLICT(video_id) DO UPDATE SET payload=excluded.payload',
                    (video_id, json.dumps(payload, ensure_ascii=False)))


def load_video(video_id):
    with connect() as con:
        ensure_table(con)
        row = con.execute('SELECT payload FROM video_source_styles WHERE video_id=?', (video_id,)).fetchone()
    return json.loads(row[0]) if row else {}


def color_rgb(fmt, theme, name='foregroundColor'):
    style = fmt.get(name + 'Style', {})
    if 'rgbColor' in style:
        return style['rgbColor']
    theme_name = style.get('themeColor')
    if theme_name:
        colors = {x['colorType']: x.get('color', {}) for x in theme.get('themeColors', [])}
        return colors.get(theme_name, {}).get('rgbColor')
    return fmt.get(name)


def runs(snapshot):
    """Yield UTF-16 boundaries as used by both Google Sheets and QTextCursor."""
    text = snapshot.get('text', '')
    total = len(text.encode('utf-16-le')) // 2
    cell = snapshot.get('cell', {})
    defaults = snapshot.get('defaults', {})
    base = dict(defaults.get('textFormat', {}))
    base.update(cell.get('effectiveFormat', cell.get('userEnteredFormat', {})).get('textFormat', {}))
    entries = {0: {}}
    entries.update({int(run.get('startIndex', 0)): run.get('format', {}) for run in cell.get('textFormatRuns', [])})
    indexes = sorted(i for i in entries if 0 <= i < total)
    for n, start in enumerate(indexes):
        end = indexes[n+1] if n+1 < len(indexes) else total
        fmt = dict(base)
        override = entries[start]
        if 'foregroundColor' in override or 'foregroundColorStyle' in override:
            fmt.pop('foregroundColor', None); fmt.pop('foregroundColorStyle', None)
        fmt.update(override)
        yield start, end, fmt


def mark_edited(video_id, key):
    _snapshot_cache.pop(int(video_id), None)
    with connect() as con:
        ensure_table(con)
        row = con.execute('SELECT payload FROM video_source_styles WHERE video_id=?', (video_id,)).fetchone()
        if not row: return
        payload = json.loads(row[0])
        if key in payload: payload[key]['local_override'] = True
        con.execute('UPDATE video_source_styles SET payload=? WHERE video_id=?', (json.dumps(payload, ensure_ascii=False), video_id))


def _compute_video_snapshots(video_id, raw_payload, rows):
    if not raw_payload:
        return {}
    vid_int = int(video_id)
    seg_sig = tuple((int(r['id']), str(r['foreign_text'] or '')) for r in rows)
    cached = _snapshot_cache.get(vid_int)
    if cached and cached[0] == raw_payload and cached[1] == seg_sig:
        _snapshot_cache.move_to_end(vid_int)
        return cached[2]
    source = json.loads(raw_payload).get('外文内容', {})
    if not source or source.get('local_override'):
        _snapshot_cache[vid_int] = (raw_payload, seg_sig, {})
        while len(_snapshot_cache) > 96:
            _snapshot_cache.popitem(last=False)
        return {}
    original = source.get('text', '')
    # Legacy speech splitting inserted punctuation at clip ends. Map those clips
    # only when the complete letter/digit sequence is identical to the source.
    letters = lambda text: ''.join(c for c in text if c.isalnum())
    combined = ''.join(r['foreign_text'] or '' for r in rows)
    punctuation_only = ''.join(original.split()) != ''.join(combined.split()) and bool(letters(original)) and letters(original) == letters(combined)
    significant = (lambda c: c.isalnum()) if punctuation_only else (lambda c: not c.isspace())
    positions = [i for i,c in enumerate(original) if significant(c)]
    compact = ''.join(original[i] for i in positions)
    utf16 = [0]
    for char in original: utf16.append(utf16[-1] + len(char.encode('utf-16-le'))//2)
    source_runs = list(runs(source))
    base_cell = dict(source.get('cell', {}))
    result, offset = {}, 0
    for row in rows:
        text = row['foreign_text'] or ''
        key = ''.join(c for c in text if significant(c))
        start = compact.find(key, offset) if key else -1
        if start < 0: continue
        index, destination, entries, last = start, 0, [], None
        for char in text:
            aligned_index = max(start,index-1) if punctuation_only and not significant(char) else index
            source_index = positions[min(aligned_index, len(positions)-1)]
            fmt = next((fmt for a,b,fmt in source_runs if a <= utf16[source_index] < b), {})
            if fmt != last:
                entries.append({'startIndex': destination, 'format': fmt});last=fmt
            destination += len(char.encode('utf-16-le'))//2
            if significant(char): index += 1
        offset = start + len(key)
        snapshot = {**source, 'text': text, 'cell': {**base_cell, 'textFormatRuns': entries}}
        result[row['id']] = snapshot
    _snapshot_cache[int(video_id)] = (raw_payload, seg_sig, result)
    while len(_snapshot_cache) > 96:
        _snapshot_cache.popitem(last=False)
    return result


def segment_snapshots(video_id):
    vid = int(video_id)
    with connect() as con:
        ensure_table(con)
        prow = con.execute('SELECT payload FROM video_source_styles WHERE video_id=?', (vid,)).fetchone()
        if not prow or not prow[0]:
            return {}
        rows = con.execute('SELECT id,foreign_text FROM flow_segments WHERE video_id=? AND seg_seq<1000 ORDER BY seg_seq', (vid,)).fetchall()
    return _compute_video_snapshots(vid, prow[0], rows)


def segment_snapshots_for_videos(video_ids):
    vids = sorted({int(v) for v in (video_ids or []) if v})
    if not vids:
        return {}
    placeholders = ','.join('?' for _ in vids)
    with connect() as con:
        ensure_table(con)
        prows = {int(r['video_id']): r['payload'] for r in con.execute(
            f'SELECT video_id, payload FROM video_source_styles WHERE video_id IN ({placeholders})', vids
        ).fetchall() if r['payload']}
        if not prows:
            return {}
        active_vids = sorted(prows.keys())
        ap = ','.join('?' for _ in active_vids)
        seg_rows = con.execute(
            f'SELECT id, video_id, foreign_text FROM flow_segments WHERE video_id IN ({ap}) AND seg_seq<1000 ORDER BY video_id, seg_seq',
            active_vids,
        ).fetchall()
    by_vid = {}
    for r in seg_rows:
        by_vid.setdefault(int(r['video_id']), []).append(r)
    out = {}
    for vid, raw_payload in prows.items():
        out.update(_compute_video_snapshots(vid, raw_payload, by_vid.get(vid, ())))
    return out
