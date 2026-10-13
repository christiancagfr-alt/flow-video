"""Column map for the task sheet. Template mode keeps the current header contract."""
import json
import re

from app.core import repository as repo

MODE_TEMPLATE = 'template'
MODE_CUSTOM = 'custom'
SETTING_MODE = 'task_sheet_column_mode'
SETTING_MAP = 'task_sheet_columns'
CHOICE_HEADER = 'header'
CHOICE_UNUSED = 'unused'
MAX_COLUMN = 51

# key, on-screen name, header text the current template uses, short note
FIELDS = (
    ('需求人员', '需求人员', '需求人员', '区分接收人'),
    ('主播名称', '主播名称', '主播名称', '同一接收人下面的主播'),
    ('中文内容', '中文文案', '中文内容', '中文对照'),
    ('外文内容', '外文文案', '外文内容', '口播文案，并读取这一列的字体颜色'),
    ('需求说明', '需求说明', '需求说明', '格子里写了「闭眼」时，这一行按闭眼处理'),
    ('主播图片链接', '图片链接', '主播图片链接', '主播素材的 Google Drive 文件夹'),
    ('日期', '日期', '日期', '新任务进入任务中心时使用的日期'),
    ('作者', '作者', '作者', '同步后把制作人写回这一列'),
    ('制作情况', '制作情况', '制作情况', '同步后把「制作中」写回这一列'),
)
FIELD_LABELS = {key: label for key, label, _header, _note in FIELDS}
FIELD_HEADERS = {key: header for key, _label, header, _note in FIELDS}
FIELD_NOTES = {key: note for key, _label, _header, note in FIELDS}
REQUIRED_CUSTOM = ('主播名称', '外文内容')


def norm_header(value):
    return re.sub(r'\s+', '', str(value or '')).strip()


def index_to_letter(index):
    number = int(index) + 1
    letters = ''
    while number:
        number, rem = divmod(number - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def template_choice(key):
    """What the current sheet template does for this field."""
    if key == '主播图片链接':
        return '9'
    if key == '日期':
        return CHOICE_UNUSED
    return CHOICE_HEADER


def valid_choice(value):
    text = str(value or '')
    if text in (CHOICE_HEADER, CHOICE_UNUSED):
        return True
    return text.isdigit() and 0 <= int(text) <= MAX_COLUMN


def choice_label(value):
    text = str(value or '')
    if text == CHOICE_HEADER:
        return '按表头'
    if text == CHOICE_UNUSED:
        return '不使用'
    if valid_choice(text) and text.isdigit():
        return index_to_letter(int(text)) + ' 列'
    return '按表头'


def load_spec():
    mode = repo.get_setting(SETTING_MODE, MODE_TEMPLATE) or MODE_TEMPLATE
    if mode not in (MODE_TEMPLATE, MODE_CUSTOM):
        mode = MODE_TEMPLATE
    raw = repo.get_setting(SETTING_MAP, '') or ''
    try:
        saved = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    columns = {}
    for key, _label, _header, _note in FIELDS:
        choice = str(saved.get(key) or template_choice(key))
        columns[key] = choice if valid_choice(choice) else template_choice(key)
    return {'mode': mode, 'columns': columns}


def save_spec(mode, columns):
    chosen = MODE_CUSTOM if mode == MODE_CUSTOM else MODE_TEMPLATE
    cleaned = {}
    for key, _label, _header, _note in FIELDS:
        choice = str((columns or {}).get(key) or template_choice(key))
        cleaned[key] = choice if valid_choice(choice) else template_choice(key)
    repo.set_setting(SETTING_MODE, chosen)
    repo.set_setting(SETTING_MAP, json.dumps(cleaned, ensure_ascii=False))
    return {'mode': chosen, 'columns': cleaned}


def duplicate_columns(columns):
    """Explicit column letters used by more than one field."""
    groups = {}
    for key, _label, _header, _note in FIELDS:
        choice = str((columns or {}).get(key) or '')
        if not choice.isdigit():
            continue
        groups.setdefault(choice, []).append(FIELD_LABELS[key])
    return [
        f"{index_to_letter(int(choice))} 列：{'、'.join(labels)}"
        for choice, labels in groups.items() if len(labels) > 1
    ]


def find_named_column(rows, header, limit=80):
    wanted = norm_header(header)
    if not wanted:
        return None
    for row in list(rows or [])[:limit]:
        for index, cell in enumerate(row):
            if norm_header(cell) == wanted:
                return index
    return None


def resolve_columns(rows, spec):
    """Custom mode only. Template parsing keeps its own header-row contract."""
    choices = (spec or {}).get('columns') or {}
    resolved = {}
    for key, _label, header, _note in FIELDS:
        choice = str(choices.get(key) or template_choice(key))
        if not valid_choice(choice):
            choice = template_choice(key)
        if choice == CHOICE_UNUSED:
            resolved[key] = None
        elif choice == CHOICE_HEADER:
            resolved[key] = find_named_column(rows, header)
        else:
            resolved[key] = int(choice)
    return resolved


def custom_problem(rows, spec):
    """A sentence naming the first custom column that cannot be read. Empty when the map is usable."""
    choices = (spec or {}).get('columns') or {}
    resolved = resolve_columns(rows, spec)
    for key in REQUIRED_CUSTOM:
        if resolved.get(key) is None:
            label = FIELD_LABELS[key]
            if str(choices.get(key) or template_choice(key)) == CHOICE_HEADER:
                return f'{label}选择了按表头，表格里没有「{FIELD_HEADERS[key]}」这一列'
            return f'{label}还没有选择表格列'
    return ''


def normalize_date(value):
    from app.core.work_dates import canonical
    return canonical(value) or ''


def task_work_day(sheet_date, created_at):
    """Prefer a date read from the sheet. Otherwise keep the day the task was first stored."""
    return normalize_date(sheet_date) or normalize_date(created_at)
