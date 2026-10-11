"""Targeted Sheets link metadata overlay; ordinary CSV values remain unchanged."""
import logging
import re

log = logging.getLogger(__name__)
URL_HEADERS = {'主播图片链接', '主播图片', '网盘链接', '图片链接', 'Drive链接', '素材链接',
               'google drive', '视频素材', 'Drive文件夹', '输出资源链接', 'url'}


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
    log.log(logging.INFO if resolved else logging.WARNING,
            '[%s] display_text=%s hyperlink=%s resolved_url=%s',
            'SHEET_LINK' if resolved else 'SHEET_LINK_ERROR', display, hyperlink, resolved)
    return resolved


def overlay_sheet_links(rows, header_index, sheets, spreadsheet_id, title):
    columns = [i for i, h in enumerate(rows[header_index])
               if str(h).strip().lower() in {x.lower() for x in URL_HEADERS}
               or str(h).strip().endswith('链接')]
    # J is authoritative even when its header is empty or uses another name.
    columns = sorted(set(columns + [9]))
    def letter(i):
        result = ''
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            result = chr(65 + rem) + result
        return result
    ranges = ["'%s'!%s%d:%s%d" % (title.replace("'", "''"), letter(i), header_index + 2,
                                      letter(i), len(rows)) for i in columns]
    metadata = {}
    if sheets is not None and len(rows) > header_index + 1:
        data = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, ranges=ranges,
            fields='sheets(data(startRow,startColumn,rowData(values(hyperlink,textFormatRuns,chipRuns,userEnteredValue,formattedValue))))').execute()
        for sheet in data.get('sheets', []):
            for grid in sheet.get('data', []):
                for ri, row in enumerate(grid.get('rowData', []), grid.get('startRow', 0)):
                    for ci, cell in enumerate(row.get('values', []), grid.get('startColumn', 0)):
                        metadata[ri, ci] = cell
    result = [list(row) for row in rows]
    for ri in range(header_index + 1, len(result)):
        for ci in columns:
            if ci >= len(result[ri]) and (ri, ci) not in metadata: continue
            while len(result[ri]) <= ci: result[ri].append('')
            cell = metadata.get((ri, ci), {'formattedValue': result[ri][ci]})
            if not cell or (not result[ri][ci].strip() and (ri, ci) not in metadata): continue
            resolved = extract_sheet_url(cell)
            if resolved:
                result[ri][ci] = resolved
    return result
