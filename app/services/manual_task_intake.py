"""Local manual task creation service for Flow Studio Task Center.

Writes manual rows directly into the pre-GPT intake SQLite database (`spreadsheet_id='manual'`)
and promotes ready tasks into the Studio database (`studio.db`) using the exact same downstream
contract as Google Sheets synchronization (eye-state color runs, host aspect ratios, AI watermark
sub-label bindings, and local material staging).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from app.core import repository as studio_repo
from app.core import work_dates
from app.core.database import connect as studio_connect
from app.services import pre_gpt_pipeline as intake
from app.services.file_filters import is_ignored_system_path, is_valid_local_image

DRAFT_KEY_PREFIX = "manual_task_draft_v1:"

RED_RGB = {"red": 0.85, "green": 0.12, "blue": 0.12}
BLACK_RGB = {"red": 0.0, "green": 0.0, "blue": 0.0}


def _draft_key(work_date: str | None = None) -> str:
    day = work_dates.canonical(work_date) or work_dates.active()
    return f"{DRAFT_KEY_PREFIX}{day}"


def load_draft(work_date: str | None = None) -> list[dict]:
    """Return saved draft rows for work_date, or [] when none exist (never returns sample defaults)."""
    raw = str(studio_repo.get_setting(_draft_key(work_date), "") or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    except Exception:
        pass
    return []


def save_draft(rows: list[dict], work_date: str | None = None) -> None:
    cleaned = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if any(str(r.get(k) or "").strip() for k in ("recipient", "host", "perf_mode", "foreign_text", "chinese_text", "image_path", "aspect_ratio", "material_source")):
            cleaned.append({
                "recipient": str(r.get("recipient") or ""),
                "host": str(r.get("host") or ""),
                "perf_mode": str(r.get("perf_mode") or ""),
                "foreign_text": str(r.get("foreign_text") or ""),
                "chinese_text": str(r.get("chinese_text") or ""),
                "image_path": str(r.get("image_path") or ""),
                "aspect_ratio": str(r.get("aspect_ratio") or ""),
                "material_source": str(r.get("material_source") or ""),
                "red_spans": list(r.get("red_spans") or []),
            })
    studio_repo.set_setting(_draft_key(work_date), json.dumps(cleaned, ensure_ascii=False) if cleaned else "")


def clear_draft(work_date: str | None = None) -> None:
    studio_repo.set_setting(_draft_key(work_date), "")


def normalize_perf_mode(raw: str, has_red_spans: bool = False) -> tuple[str, str]:
    """Map UI / pasted performance mode text to (db_mode, requirement_label)."""
    s = re.sub(r"\s+", "", str(raw or "")).upper()
    if not s:
        if has_red_spans:
            return "PRAYING", "睁闭眼混合"
        return "TALKING", "睁眼"
    if "MIX" in s or "混合" in s or "交替" in s or ("睁" in s and "闭" in s) or ("红" in s and "黑" in s):
        return "PRAYING", "睁闭眼混合"
    if "PRAY" in s or "闭眼" in s or "祷告" in s or s == "闭":
        if has_red_spans:
            return "PRAYING", "睁闭眼混合"
        return "PRAYING", "闭眼"
    if has_red_spans:
        return "PRAYING", "睁闭眼混合"
    return "TALKING", "睁眼"


def display_perf_mode(raw: str, has_red_spans: bool = False) -> str:
    """Return canonical UI label ('', '睁眼说话', '闭眼祷告', '红睁黑闭混合')."""
    s = str(raw or "").strip()
    if not s and not has_red_spans:
        return ""
    db_mode, req = normalize_perf_mode(s, has_red_spans=has_red_spans)
    if "混合" in req:
        return "红睁黑闭混合"
    return "闭眼祷告" if db_mode == "PRAYING" else "睁眼说话"


def normalize_aspect_ratio(raw: str, fallback: str = "") -> str:
    s = str(raw or "").strip().lower()
    if not s or "自动" in s or s == "auto":
        return fallback
    if "16:9" in s or "16/9" in s or "横" in s or "landscape" in s:
        return "16:9"
    if "9:16" in s or "9/16" in s or "竖" in s or "portrait" in s:
        return "9:16"
    return fallback


def probe_image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        sz = reader.size()
        if sz.isValid() and sz.width() > 0 and sz.height() > 0:
            return int(sz.width()), int(sz.height())
    except Exception:
        pass
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            if w > 0 and h > 0:
                return int(w), int(h)
    except Exception:
        pass
    return None


def detect_aspect_ratio(path_str: str) -> str | None:
    raw = str(path_str or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    target: Path | None = None
    if p.is_file() and is_valid_local_image(p):
        target = p
    elif p.is_dir():
        candidates = sorted(
            (c for c in p.iterdir() if c.is_file() and not is_ignored_system_path(c) and is_valid_local_image(c)),
            key=lambda x: x.name.lower(),
        )
        if not candidates:
            sub = p / "素材"
            if sub.is_dir():
                candidates = sorted(
                    (c for c in sub.iterdir() if c.is_file() and not is_ignored_system_path(c) and is_valid_local_image(c)),
                    key=lambda x: x.name.lower(),
                )
        if candidates:
            target = candidates[0]
    if target is None:
        return None
    dims = probe_image_dimensions(target)
    if not dims:
        return None
    w, h = dims
    return "16:9" if w > h else "9:16"


def normalize_red_spans(text: str, spans) -> list[tuple[int, int]]:
    """Merge and clamp character-index [start, end) red spans against `text`."""
    n = len(text or "")
    if n == 0 or not spans:
        return []
    raw_list: list[tuple[int, int]] = []
    for item in spans:
        try:
            if isinstance(item, dict):
                s, e = int(item.get("start", 0)), int(item.get("end", 0))
            else:
                s, e = int(item[0]), int(item[1])
        except Exception:
            continue
        s = max(0, min(n, s))
        e = max(0, min(n, e))
        if e > s:
            raw_list.append((s, e))
    if not raw_list:
        return []
    raw_list.sort()
    merged = [raw_list[0]]
    for s, e in raw_list[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def _utf16_offset(text: str, char_idx: int) -> int:
    return len(text[:char_idx].encode("utf-16-le")) // 2


def build_source_styles(
    foreign_text: str,
    chinese_text: str,
    db_mode: str,
    red_spans=None,
) -> dict:
    """Construct Google-Sheets-compatible `_source_styles` JSON snapshot."""
    fx = str(foreign_text or "")
    zh = str(chinese_text or "")
    norm_spans = normalize_red_spans(fx, red_spans)
    runs = []
    if norm_spans and fx:
        boundaries = {0, len(fx)}
        for s, e in norm_spans:
            boundaries.add(s)
            boundaries.add(e)
        sorted_bounds = sorted(boundaries)
        for idx in range(len(sorted_bounds) - 1):
            b_start = sorted_bounds[idx]
            b_end = sorted_bounds[idx + 1]
            if b_end <= b_start:
                continue
            is_red = any(s <= b_start and b_end <= e for s, e in norm_spans)
            rgb = RED_RGB if is_red else BLACK_RGB
            runs.append({
                "startIndex": _utf16_offset(fx, b_start),
                "format": {"foregroundColorStyle": {"rgbColor": dict(rgb)}},
            })
    fx_cell: dict = {"formattedValue": fx, "userEnteredValue": {"stringValue": fx}}
    if runs:
        fx_cell["textFormatRuns"] = runs
    styles = {
        "外文内容": {
            "text": fx,
            "base_mode": "PRAYING" if (db_mode == "PRAYING" or bool(runs)) else "TALKING",
            "cell": fx_cell,
            "defaults": {},
            "theme": {},
        }
    }
    if zh:
        styles["中文内容"] = {
            "text": zh,
            "base_mode": "PRAYING" if db_mode == "PRAYING" else "TALKING",
            "cell": {"formattedValue": zh, "userEnteredValue": {"stringValue": zh}},
            "defaults": {},
            "theme": {},
        }
    return styles


def _is_css_red(color_str: str) -> bool | None:
    """Return True if CSS color is clearly red, False if clearly dark/other, None if unspecified."""
    s = str(color_str or "").strip().lower()
    if not s or s in ("inherit", "initial", "unset", "currentcolor", "windowtext", "auto"):
        return None
    if s in ("red", "crimson", "firebrick", "darkred", "orangered", "tomato"):
        return True
    if s in ("black", " nearblack"):
        return False
    m_hex6 = re.match(r"^#([0-9a-f]{6})(?:[0-9a-f]{2})?$", s)
    if m_hex6:
        hx = m_hex6.group(1)
        r, g, b = int(hx[0:2], 16) / 255.0, int(hx[2:4], 16) / 255.0, int(hx[4:6], 16) / 255.0
        return bool(r >= 0.45 and r > g * 1.5 and r > b * 1.5)
    m_hex3 = re.match(r"^#([0-9a-f]{3})$", s)
    if m_hex3:
        hx = m_hex3.group(1)
        r, g, b = int(hx[0] * 2, 16) / 255.0, int(hx[1] * 2, 16) / 255.0, int(hx[2] * 2, 16) / 255.0
        return bool(r >= 0.45 and r > g * 1.5 and r > b * 1.5)
    m_rgb = re.match(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", s)
    if m_rgb:
        r, g, b = float(m_rgb.group(1)) / 255.0, float(m_rgb.group(2)) / 255.0, float(m_rgb.group(3)) / 255.0
        return bool(r >= 0.45 and r > g * 1.5 and r > b * 1.5)
    return False


def _extract_css_color(attrs: list[tuple[str, str | None]], classes: dict[str, bool] | None = None) -> bool | None:
    attr_map = {str(k or "").lower(): str(v or "") for k, v in attrs}
    style = attr_map.get("style", "")
    if style:
        for part in style.split(";"):
            if ":" not in part:
                continue
            prop, val = part.split(":", 1)
            if prop.strip().lower() == "color":
                res = _is_css_red(val)
                if res is not None:
                    return res
    if "color" in attr_map:
        res = _is_css_red(attr_map["color"])
        if res is not None:
            return res
    cls_attr = attr_map.get("class", "")
    if cls_attr and classes:
        for token in cls_attr.split():
            if token in classes:
                return classes[token]
    return None


class _ClipboardHtmlParser(HTMLParser):
    """Parse HTML table / rich-text fragment from Google Sheets, Excel, Docs, or Numbers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_style = False
        self.in_head = False
        self.style_buf: list[str] = []
        self.css_classes: dict[str, bool] = {}
        self.has_table = False
        self.rows: list[list[dict]] = []
        self._cur_row: list[dict] | None = None
        self._in_cell = False
        self._cell_chars: list[str] = []
        self._cell_reds: list[tuple[int, int]] = []
        self._color_stack: list[tuple[str, bool]] = []
        # Fallback single-cell buffer when HTML has spans without <table>
        self._frag_chars: list[str] = []
        self._frag_reds: list[tuple[int, int]] = []

    def _parse_stylesheet(self, css_text: str):
        for m in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", css_text):
            cls_name, body = m.group(1), m.group(2)
            for part in body.split(";"):
                if ":" not in part:
                    continue
                k, v = part.split(":", 1)
                if k.strip().lower() == "color":
                    is_red = _is_css_red(v)
                    if is_red is not None:
                        self.css_classes[cls_name] = is_red

    def _current_red(self) -> bool:
        return bool(self._color_stack and self._color_stack[-1][1])

    def _append_text(self, s: str):
        if not s:
            return
        if self._in_cell:
            start = len(self._cell_chars)
            self._cell_chars.extend(list(s))
            if self._current_red():
                self._cell_reds.append((start, len(self._cell_chars)))
        elif not self.has_table and not self.in_style and not self.in_head:
            start = len(self._frag_chars)
            self._frag_chars.extend(list(s))
            if self._current_red():
                self._frag_reds.append((start, len(self._frag_chars)))

    def handle_starttag(self, tag: str, attrs):
        t = tag.lower()
        if t == "head":
            self.in_head = True
            return
        if t == "style":
            self.in_style = True
            self.style_buf.clear()
            return
        if t == "table":
            self.has_table = True
            return
        if t == "tr":
            self.has_table = True
            self._cur_row = []
            return
        if t in ("td", "th"):
            self.has_table = True
            if self._cur_row is None:
                self._cur_row = []
            self._in_cell = True
            self._cell_chars = []
            self._cell_reds = []
            c = _extract_css_color(attrs, self.css_classes)
            prev = self._current_red()
            self._color_stack.append((t, prev if c is None else c))
            return
        if t == "br":
            self._append_text("\n")
            return
        if t in ("p", "div") and (self._in_cell or not self.has_table):
            buf = self._cell_chars if self._in_cell else self._frag_chars
            if buf and buf[-1] != "\n":
                self._append_text("\n")
        c = _extract_css_color(attrs, self.css_classes)
        prev = self._current_red()
        self._color_stack.append((t, prev if c is None else c))

    def handle_endtag(self, tag: str):
        t = tag.lower()
        if t == "head":
            self.in_head = False
            return
        if t == "style":
            self.in_style = False
            self._parse_stylesheet("".join(self.style_buf))
            self.style_buf.clear()
            return
        if t in ("td", "th") and self._in_cell:
            raw_txt = "".join(self._cell_chars).replace("\r\n", "\n").replace("\r", "\n")
            spans = normalize_red_spans(raw_txt, self._cell_reds)
            if self._cur_row is not None:
                self._cur_row.append({"text": raw_txt, "red_spans": spans})
            self._in_cell = False
            while self._color_stack:
                popped_tag, _ = self._color_stack.pop()
                if popped_tag == t:
                    break
            return
        if t == "tr":
            if self._cur_row is not None:
                self.rows.append(self._cur_row)
            self._cur_row = None
            return
        for idx in range(len(self._color_stack) - 1, -1, -1):
            if self._color_stack[idx][0] == t:
                del self._color_stack[idx:]
                break

    def handle_data(self, data: str):
        if self.in_style:
            self.style_buf.append(data)
            return
        if self.in_head:
            return
        # Ignore whitespace-only formatting newlines outside cells, and collapse HTML source line-wrap
        # whitespace only when needed; inside Google Sheets <td><span>, literal spaces/text are exact.
        cleaned = data.replace("\r\n", "\n").replace("\r", "\n")
        if self._in_cell and "\n" in cleaned and len(self._cell_chars) == 0 and not cleaned.strip():
            return
        self._append_text(cleaned)


def parse_clipboard_grid(plain_text: str, html_text: str = "") -> list[list[dict]]:
    """Parse clipboard TSV + optional HTML into a 2D grid of `{'text': str, 'red_spans': [...]}`."""
    raw = (plain_text or "").replace("\r\n", "\n").replace("\r", "\n")
    if raw.endswith("\n"):
        raw = raw[:-1]
    grid: list[list[dict]] = []
    if raw:
        try:
            reader = csv.reader(io.StringIO(raw), delimiter="\t", quotechar='"')
            for row in reader:
                grid.append([{"text": cell, "red_spans": []} for cell in row])
        except Exception:
            for line in raw.split("\n"):
                grid.append([{"text": cell, "red_spans": []} for cell in line.split("\t")])

    if html_text and ("color" in html_text.lower() or "<table" in html_text.lower()):
        try:
            hp = _ClipboardHtmlParser()
            hp.feed(html_text)
            if hp.has_table and hp.rows:
                if not grid:
                    return hp.rows
                if len(hp.rows) == len(grid):
                    for r_idx, h_row in enumerate(hp.rows):
                        g_row = grid[r_idx]
                        if len(h_row) == len(g_row):
                            for c_idx, h_cell in enumerate(h_row):
                                if not h_cell["red_spans"]:
                                    continue
                                g_txt = g_row[c_idx]["text"]
                                h_txt = h_cell["text"]
                                if h_txt == g_txt:
                                    g_row[c_idx]["red_spans"] = h_cell["red_spans"]
                                elif h_txt.strip() == g_txt.strip():
                                    lead = len(h_txt) - len(h_txt.lstrip())
                                    g_lead = len(g_txt) - len(g_txt.lstrip())
                                    shift = g_lead - lead
                                    g_row[c_idx]["red_spans"] = normalize_red_spans(
                                        g_txt, [(s + shift, e + shift) for s, e in h_cell["red_spans"]]
                                    )
            elif not hp.has_table and hp._frag_reds and len(grid) == 1 and len(grid[0]) == 1:
                frag_txt = "".join(hp._frag_chars).replace("\r\n", "\n").replace("\r", "\n")
                g_txt = grid[0][0]["text"]
                if frag_txt == g_txt:
                    grid[0][0]["red_spans"] = normalize_red_spans(g_txt, hp._frag_reds)
                elif frag_txt.strip() == g_txt.strip():
                    lead = len(frag_txt) - len(frag_txt.lstrip())
                    g_lead = len(g_txt) - len(g_txt.lstrip())
                    shift = g_lead - lead
                    grid[0][0]["red_spans"] = normalize_red_spans(
                        g_txt, [(s + shift, e + shift) for s, e in hp._frag_reds]
                    )
        except Exception:
            pass
    return grid


def format_tsv_grid(matrix: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for row in matrix:
        writer.writerow([str(c or "") for c in row])
    return buf.getvalue().rstrip("\n")


def _stage_local_image(src: Path, dest_dir: Path) -> tuple[Path, str]:
    """Stage `src` into `dest_dir` via hardlink (fallback copy2) without mutating user's original file."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    digest = intake.sha256_file(src)
    safe_stem = intake.safe_name(src.stem, "image")
    suffix = src.suffix.lower() or ".jpg"
    dest = dest_dir / f"{safe_stem}{suffix}"
    if dest.exists():
        if dest.resolve() == src.resolve() or intake.sha256_file(dest) == digest:
            return dest, digest
        dest = dest_dir / f"{safe_stem}__{digest[:8]}{suffix}"
    if not dest.exists():
        try:
            os.link(src, dest)
        except OSError:
            shutil.copy2(src, dest)
    return dest, digest


def import_manual_tasks(rows: list[dict], work_date: str | None = None) -> dict:
    """Validate, stage local materials, insert into intake DB, and promote into Studio DB."""
    day = work_dates.canonical(work_date) or work_dates.active()
    if day == work_dates.LEGACY:
        day = work_dates.today()

    # 1. Filter out completely empty rows while preserving 1-based UI row numbers for clear error messages.
    active_entries: list[tuple[int, dict]] = []
    for ui_idx, raw in enumerate(rows or [], 1):
        if not isinstance(raw, dict):
            continue
        rec = str(raw.get("recipient") or "").strip()
        host = str(raw.get("host") or "").strip()
        fx = str(raw.get("foreign_text") or "")
        zh = str(raw.get("chinese_text") or "")
        img = str(raw.get("image_path") or "").strip()
        wm = str(raw.get("material_source") or "").strip()
        if not any((rec, host, fx.strip(), zh.strip(), img, wm)):
            continue
        active_entries.append((ui_idx, raw))

    if not active_entries:
        raise ValueError("表格当前为空，请至少填写或粘贴 1 行任务后再导入。")

    # 2. Validate required text columns first, and collect shared image paths per (recipient, host).
    shared_path_by_group: dict[tuple[str, str], str] = {}
    for ui_idx, raw in active_entries:
        rec = str(raw.get("recipient") or "").strip()
        host = str(raw.get("host") or "").strip()
        fx = str(raw.get("foreign_text") or "").strip()
        img = str(raw.get("image_path") or "").strip()
        if not rec:
            raise ValueError(f"第 {ui_idx} 行缺少「接收人」，请补全后再导入。")
        if not host:
            raise ValueError(f"第 {ui_idx} 行缺少「主播名称」，请补全后再导入。")
        if not fx:
            raise ValueError(f"第 {ui_idx} 行缺少「外文口播文案」，请补全后再导入。")
        if img:
            p = Path(img).expanduser()
            if not p.exists():
                raise ValueError(f"第 {ui_idx} 行图片或目录不存在：{img}")
            if p.is_file() and not is_valid_local_image(p):
                raise ValueError(f"第 {ui_idx} 行选择的文件不是有效图片：{p.name}")
            if p.is_dir():
                sub_imgs = [
                    c for c in p.iterdir()
                    if c.is_file() and not is_ignored_system_path(c) and is_valid_local_image(c)
                ]
                if not sub_imgs and (p / "素材").is_dir():
                    sub_imgs = [
                        c for c in (p / "素材").iterdir()
                        if c.is_file() and not is_ignored_system_path(c) and is_valid_local_image(c)
                    ]
                if not sub_imgs:
                    raise ValueError(f"第 {ui_idx} 行选择的目录中没有找到可用图片：{img}")
            gpair = (intake.norm(rec), intake.norm(host))
            shared_path_by_group.setdefault(gpair, img)

    normalized_rows: list[dict] = []
    for ui_idx, raw in active_entries:
        rec = str(raw.get("recipient") or "").strip()
        host = str(raw.get("host") or "").strip()
        fx = str(raw.get("foreign_text") or "")
        zh = str(raw.get("chinese_text") or "")
        gpair = (intake.norm(rec), intake.norm(host))
        img = str(raw.get("image_path") or "").strip() or shared_path_by_group.get(gpair, "")
        if not img:
            raise ValueError(f"第 {ui_idx} 行（{rec} · {host}）缺少「图片 / 素材路径」，请选择单张图片或主播图片目录。")
        red_spans = normalize_red_spans(fx, raw.get("red_spans"))
        db_mode, req_label = normalize_perf_mode(raw.get("perf_mode", ""), has_red_spans=bool(red_spans))
        detected_ar = detect_aspect_ratio(img) or "9:16"
        aspect_ratio = normalize_aspect_ratio(raw.get("aspect_ratio", ""), fallback=detected_ar)
        mat_source = str(raw.get("material_source") or "").strip()
        styles = build_source_styles(fx, zh, db_mode, red_spans)
        normalized_rows.append({
            "ui_row": ui_idx,
            "recipient": rec,
            "host": host,
            "foreign_text": fx,
            "chinese_text": zh,
            "db_mode": db_mode,
            "requirement": req_label,
            "image_path": img,
            "aspect_ratio": aspect_ratio,
            "material_source": mat_source,
            "styles": styles,
        })

    # 3. Stage files & write into pre_gpt_pipeline.sqlite3 transactionally.
    settings = intake.load_settings()
    local_root = Path(settings["local_root"]).expanduser()
    now_time = datetime.now().strftime("%H:%M:%S")
    created_ts = f"{day}T{now_time}"

    con = intake.init_db()
    created_task_ids: list[int] = []
    touched_groups: dict[str, dict] = {}
    group_aspect: dict[str, str] = {}
    group_watermark: dict[str, tuple[bool, str]] = {}

    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("UPDATE intake_view_state SET hidden=0 WHERE day IN (?,?)", (day, work_dates.today()))
        max_row_rec = con.execute("SELECT COALESCE(MAX(sheet_row), 0) FROM tasks").fetchone()
        next_sheet_row = max(100001, int((max_row_rec[0] if max_row_rec else 0) or 0) + 1)

        # Group normalized rows by group_key
        rows_by_group: dict[str, list[dict]] = {}
        for item in normalized_rows:
            gkey = intake.make_group_key(item["recipient"], item["host"])
            item["group_key"] = gkey
            rows_by_group.setdefault(gkey, []).append(item)
            if gkey not in group_aspect or item["aspect_ratio"] == "16:9":
                group_aspect[gkey] = item["aspect_ratio"]
            if item["material_source"]:
                group_watermark.setdefault(gkey, (True, item["material_source"]))
            else:
                group_watermark.setdefault(gkey, (False, ""))

        for gkey, members in rows_by_group.items():
            rec = members[0]["recipient"]
            host = members[0]["host"]
            existing_grp = con.execute(
                "SELECT local_dir, drive_url, drive_folder_id FROM groups_tbl WHERE group_key=?",
                (gkey,),
            ).fetchone()
            if existing_grp and existing_grp[0] and Path(str(existing_grp[0])).expanduser().exists():
                local_dir = Path(str(existing_grp[0])).expanduser()
                drive_url = str(existing_grp[1] or "local:manual")
                drive_fid = str(existing_grp[2] or "")
            else:
                local_dir = local_root / day / intake.safe_name(rec, "未命名接收人") / intake.safe_name(host, "未命名主播")
                drive_url = "local:manual"
                drive_fid = ""
            mat_dir = local_dir / "素材"
            mat_dir.mkdir(parents=True, exist_ok=True)

            all_single_files = all(Path(m["image_path"]).expanduser().is_file() for m in members)
            staged_by_src: dict[str, tuple[Path, str]] = {}

            for m in members:
                src_p = Path(m["image_path"]).expanduser().resolve()
                if src_p.is_file():
                    if str(src_p) not in staged_by_src:
                        staged_by_src[str(src_p)] = _stage_local_image(src_p, mat_dir)
                    staged_path, digest = staged_by_src[str(src_p)]
                    fid = f"manual:{digest[:16]}"
                    con.execute(
                        """INSERT INTO assets(group_key,drive_file_id,original_name,local_path,sha256,mode,used)
                           VALUES(?,?,?,?,?,?,1)
                           ON CONFLICT(group_key,drive_file_id) DO UPDATE SET
                             original_name=excluded.original_name,
                             local_path=excluded.local_path,
                             sha256=excluded.sha256""",
                        (gkey, fid, staged_path.name, str(staged_path), digest, m["db_mode"]),
                    )
                    m["staged_asset_path"] = str(staged_path)
                else:
                    # Directory source: stage all valid images inside the chosen directory
                    dir_imgs = sorted(
                        (c for c in src_p.iterdir() if c.is_file() and not is_ignored_system_path(c) and is_valid_local_image(c)),
                        key=lambda x: x.name.lower(),
                    )
                    if not dir_imgs and (src_p / "素材").is_dir():
                        dir_imgs = sorted(
                            (c for c in (src_p / "素材").iterdir() if c.is_file() and not is_ignored_system_path(c) and is_valid_local_image(c)),
                            key=lambda x: x.name.lower(),
                        )
                    for img_file in dir_imgs:
                        rp = img_file.resolve()
                        if str(rp) not in staged_by_src:
                            staged_by_src[str(rp)] = _stage_local_image(rp, mat_dir)
                        staged_path, digest = staged_by_src[str(rp)]
                        fid = f"manual:{digest[:16]}"
                        from app.services.material_assignment import image_mode
                        detected_mode = image_mode(staged_path)
                        con.execute(
                            """INSERT INTO assets(group_key,drive_file_id,original_name,local_path,sha256,mode,used)
                               VALUES(?,?,?,?,?,?,0)
                               ON CONFLICT(group_key,drive_file_id) DO UPDATE SET
                                 original_name=excluded.original_name,
                                 local_path=excluded.local_path,
                                 sha256=excluded.sha256""",
                            (gkey, fid, staged_path.name, str(staged_path), digest, detected_mode),
                        )
                    m["staged_asset_path"] = ""

                srow = next_sheet_row
                next_sheet_row += 1
                ckey = intake.task_content_key(rec, host, m["chinese_text"], m["foreign_text"])
                init_status = "READY_FOR_GPT" if all_single_files else "IMPORTED"
                cur = con.execute(
                    """INSERT INTO tasks(
                         spreadsheet_id, gid, sheet_row, recipient, anchor_name,
                         chinese_text, foreign_text, requirement, mode,
                         drive_url, drive_folder_id, group_key, matched_asset_path,
                         status, created_at, updated_at, content_key, sheet_date, material_source
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "manual",
                        day,
                        srow,
                        rec,
                        host,
                        m["chinese_text"],
                        m["foreign_text"],
                        m["requirement"],
                        m["db_mode"],
                        drive_url,
                        drive_fid,
                        gkey,
                        m["staged_asset_path"],
                        init_status,
                        created_ts,
                        created_ts,
                        ckey,
                        day,
                        m["material_source"],
                    ),
                )
                tid = int(cur.lastrowid)
                created_task_ids.append(tid)
                con.execute(
                    """INSERT INTO task_source_styles(task_id, payload) VALUES(?,?)
                       ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload""",
                    (tid, json.dumps(m["styles"], ensure_ascii=False)),
                )

            counts = dict(
                con.execute(
                    "SELECT mode, COUNT(*) FROM tasks WHERE group_key=? AND sheet_row>0 GROUP BY mode",
                    (gkey,),
                ).fetchall()
            )
            img_total = int(
                (con.execute("SELECT COUNT(*) FROM assets WHERE group_key=?", (gkey,)).fetchone() or [0])[0] or 0
            )
            grp_status = "READY_FOR_GPT" if all_single_files else "ASSETS_DOWNLOADED"
            grp_msg = (
                f"手动导入：已绑定 {len(members)} 条任务与本地图片"
                if all_single_files
                else f"手动导入：共 {img_total} 张本地图片，正在匹配文案…"
            )
            con.execute(
                """INSERT INTO groups_tbl(
                     group_key, recipient, anchor_name, drive_url, drive_folder_id,
                     local_dir, talking_count, praying_count, image_count, status, message, updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(group_key) DO UPDATE SET
                     recipient=excluded.recipient,
                     anchor_name=excluded.anchor_name,
                     drive_url=excluded.drive_url,
                     drive_folder_id=excluded.drive_folder_id,
                     local_dir=excluded.local_dir,
                     talking_count=excluded.talking_count,
                     praying_count=excluded.praying_count,
                     image_count=excluded.image_count,
                     status=excluded.status,
                     message=excluded.message,
                     updated_at=excluded.updated_at""",
                (
                    gkey,
                    rec,
                    host,
                    drive_url,
                    drive_fid,
                    str(local_dir),
                    int(counts.get("TALKING", 0)),
                    int(counts.get("PRAYING", 0)),
                    img_total,
                    grp_status,
                    grp_msg,
                    created_ts,
                ),
            )
            touched_groups[gkey] = {
                "group_key": gkey,
                "recipient": rec,
                "anchor_name": host,
                "all_single_files": all_single_files,
                "local_dir": str(local_dir),
            }
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    # 4. Reconcile directory-backed groups via standard material_assignment rules.
    needs_manual_classify: list[str] = []
    shortage_groups: list[str] = []
    for gkey, ginfo in touched_groups.items():
        if not ginfo["all_single_files"]:
            rec_res = intake.reconcile_group(gkey)
            st = str(rec_res.get("status") or "")
            if st == "NEEDS_MANUAL_CLASSIFY":
                needs_manual_classify.append(gkey)
            elif st == "MATERIAL_SHORTAGE":
                shortage_groups.append(gkey)

    # 5. Promote READY_FOR_GPT tasks into studio.db immediately.
    promoted = intake.promote_ready_to_studio(task_ids=created_task_ids)

    # 6. Apply host aspect_ratio & explicit material_source watermark binding on promoted Studio hosts.
    if created_task_ids:
        con = intake.init_db()
        try:
            ph = ",".join("?" for _ in created_task_ids)
            link_rows = con.execute(
                f"SELECT t.group_key, p.video_id FROM tasks t JOIN production_links p ON p.task_id=t.id WHERE t.id IN ({ph})",
                created_task_ids,
            ).fetchall()
        finally:
            con.close()
        vid_to_gkey = {int(v): str(gk) for gk, v in link_rows if v}
        if vid_to_gkey:
            with studio_connect() as scon:
                vph = ",".join("?" for _ in vid_to_gkey)
                host_rows = scon.execute(
                    f"SELECT id, host_id FROM videos WHERE id IN ({vph})",
                    list(vid_to_gkey.keys()),
                ).fetchall()
            host_by_gkey: dict[str, int] = {}
            for vid, hid in host_rows:
                gk = vid_to_gkey.get(int(vid))
                if gk and hid:
                    host_by_gkey[gk] = int(hid)
            for gk, hid in host_by_gkey.items():
                ar = group_aspect.get(gk)
                if ar in ("9:16", "16:9"):
                    studio_repo.set_host_aspect_ratio(hid, ar)
                has_wm, wm_val = group_watermark.get(gk, (False, ""))
                if has_wm:
                    try:
                        from app.services import ai_watermark
                        ai_watermark.bind_host_from_sheet_value(hid, wm_val)
                    except Exception:
                        intake.log.exception("手动导入绑定主播水印失败")

    clear_draft(day)
    first_row = normalized_rows[0]
    return {
        "work_date": day,
        "created_tasks": len(created_task_ids),
        "promoted_created": int(promoted.get("created", 0)),
        "groups": list(touched_groups.keys()),
        "needs_manual_classify_groups": needs_manual_classify,
        "shortage_groups": shortage_groups,
        "first_recipient": first_row["recipient"],
        "first_group_key": first_row["group_key"],
    }
