"""Targeted Sheets link metadata overlay; ordinary CSV values remain unchanged."""
import logging
import re

log = logging.getLogger(__name__)
URL_HEADERS = {'主播图片链接', '主播图片', '网盘链接', '图片链接', 'Drive链接', '素材链接',
               'google drive', '视频素材', 'Drive文件夹', '输出资源链接', 'url'}
_link_cache = {}


def extract_sheet_url(cell):
    if not isinstance(cell, dict):
        cell = {'formattedValue': str(cell or '')}
    display = str(cell.get('formattedValue') or cell.get('userEnteredValue', {}).get('stringValue') or '').strip()
    hyperlink = cell.get('hyperlink')
    formula = str(cell.get('userEnteredValue', {}).get('formulaValue') or '')
    match = re.match(r'^\s*=\s*HYPERLINK\s*\(\s*"((?:[^"]|"")*)"', formula, re.I)
    formula_url = match.group(1).replace('""', '"') if match else None
    chips = [r.get('chip', {}).get('richLinkProperties', {}).get('uri') for r in cell.get('chipRuns', [])]
    links = [hyperlink, formula_url] + chips + [r.get('format', {}).get('link', {}).get('uri')
                           for r in cell.get('textFormatRuns', [])] + [display]
    resolved = next((str(x).strip() for x in links if x and str(x).strip().startswith(('http://', 'https://'))), None)
    if not resolved:
        log.warning('[SHEET_LINK_ERROR] display_text=%s hyperlink=%s resolved_url=%s', display, hyperlink, resolved)
    elif resolved != display:
        log.info('[SHEET_LINK] display_text=%s hyperlink=%s resolved_url=%s', display, hyperlink, resolved)
    return resolved


def overlay_sheet_links(rows, header_index, sheets, spreadsheet_id, title, link_columns=None, start_row=None, end_row=None):
    if link_columns is None:
        header = rows[header_index] if 0 <= header_index < len(rows) else []
        columns = [i for i, h in enumerate(header)
                   if str(h).strip().lower() in {x.lower() for x in URL_HEADERS}
                   or str(h).strip().endswith('链接')]
        # J is authoritative even when its header is empty or uses another name.
        columns = sorted(set(columns + [9]))
    else:
        columns = sorted({int(i) for i in link_columns if i is not None and int(i) >= 0})
    if not columns:
        return [list(row) for row in rows]

    default_start_1b = 1 if header_index < 0 else header_index + 2
    r_start_1b = max(default_start_1b, int(start_row)) if start_row is not None else default_start_1b
    r_end_1b = min(len(rows), int(end_row)) if end_row is not None else len(rows)
    if r_start_1b > r_end_1b:
        return [list(row) for row in rows]

    result = [list(row) for row in rows]
    scoped_mode = start_row is not None or end_row is not None
    need_api_fetch = not scoped_mode

    if scoped_mode:
        # Check if any cell in the active range is a non-plain-URL text that isn't cached yet,
        # or if all link cells in the active range are blank (in case a Smart Chip exported empty).
        has_any_link_value = False
        for ri in range(r_start_1b - 1, r_end_1b):
            row = result[ri]
            for ci in columns:
                val = str(row[ci]).strip() if ci < len(row) else ''
                if not val:
                    continue
                if val.startswith(('http://', 'https://')):
                    has_any_link_value = True
                    continue
                cached = _link_cache.get((spreadsheet_id, title, ri, ci, val))
                if cached:
                    result[ri][ci] = cached
                    has_any_link_value = True
                else:
                    need_api_fetch = True
        if not has_any_link_value:
            need_api_fetch = True

    def letter(i):
        out = ''
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            out = chr(65 + rem) + out
        return out

    metadata = {}
    if need_api_fetch and sheets is not None and len(rows) >= r_start_1b:
        ranges = ["'%s'!%s%d:%s%d" % (title.replace("'", "''"), letter(i), r_start_1b,
                                          letter(i), r_end_1b) for i in columns]
        data = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=ranges,
            fields='sheets(data(startRow,startColumn,rowData(values(hyperlink,textFormatRuns,chipRuns,userEnteredValue,formattedValue))))').execute()
        for sheet in data.get('sheets', []):
            for grid in sheet.get('data', []):
                for ri, row in enumerate(grid.get('rowData', []), grid.get('startRow', 0)):
                    for ci, cell in enumerate(row.get('values', []), grid.get('startColumn', 0)):
                        metadata[ri, ci] = cell

    for ri in range(r_start_1b - 1, r_end_1b):
        for ci in columns:
            if ci >= len(result[ri]) and (ri, ci) not in metadata:
                continue
            while len(result[ri]) <= ci:
                result[ri].append('')
            raw_csv_val = str(result[ri][ci]).strip()
            cell = metadata.get((ri, ci), {'formattedValue': result[ri][ci]})
            if not cell or (not raw_csv_val and (ri, ci) not in metadata):
                continue
            resolved = extract_sheet_url(cell)
            if resolved:
                result[ri][ci] = resolved
                if raw_csv_val and not raw_csv_val.startswith(('http://', 'https://')):
                    if len(_link_cache) > 4096:
                        _link_cache.clear()
                    _link_cache[(spreadsheet_id, title, ri, ci, raw_csv_val)] = resolved
    return result
