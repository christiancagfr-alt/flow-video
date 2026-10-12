"""多语言字幕书写规范与 RTL 兼容（内置语言包，不依赖系统语言包）。

内置：en/pt/es/fr/de/it/el/ru/tr/zh/ar/he
- 标点与引号习惯、西语 ¿¡
- 文本语言粗检（字符区间 + 可选 whisper 语言码）
- 阿拉伯语/希伯来语 RTL 的 ASS 方向标记与渲染策略
- 外部 JSON 可覆盖：resources/language_packs/*.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# UI 选项：（显示名, 代码）空字符串 = 自动检测
# ---------------------------------------------------------------------------

WRITING_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("自动检测（推荐）", ""),
    ("English 英语", "en"),
    ("Português 葡语", "pt"),
    ("Español 西语", "es"),
    ("Français 法语", "fr"),
    ("Deutsch 德语", "de"),
    ("Italiano 意大利语", "it"),
    ("Ελληνικά 希腊语", "el"),
    ("Русский 俄语", "ru"),
    ("Türkçe 土耳其语", "tr"),
    ("Malagasy 马达加斯加语", "mg"),
    ("中文", "zh"),
    ("العربية 阿拉伯语", "ar"),
    ("עברית 希伯来语", "he"),
]

BUILTIN_PACKS: dict[str, dict] = {
    "en": {
        "name": "English",
        "rtl": False,
        "quote_open": "\u201c",
        "quote_close": "\u201d",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI", "Calibri"],
    },
    "pt": {
        "name": "Português",
        "rtl": False,
        "quote_open": "\u201c",
        "quote_close": "\u201d",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI"],
    },
    "es": {
        "name": "Español",
        "rtl": False,
        "quote_open": "\u00ab",
        "quote_close": "\u00bb",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "ensure_inverted_marks": True,
        "font_hints": ["Arial", "Segoe UI"],
    },
    "fr": {
        "name": "Français",
        "rtl": False,
        "quote_open": "\u00ab\u00a0",
        "quote_close": "\u00a0\u00bb",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI"],
    },
    "de": {
        "name": "Deutsch",
        "rtl": False,
        "quote_open": "\u201e",
        "quote_close": "\u201c",
        "single_open": "\u201a",
        "single_close": "\u2018",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI"],
    },
    "it": {
        "name": "Italiano",
        "rtl": False,
        "quote_open": "\u00ab",
        "quote_close": "\u00bb",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI"],
    },
    "el": {
        "name": "Ελληνικά",
        "rtl": False,
        "quote_open": "\u00ab",
        "quote_close": "\u00bb",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI", "Tahoma", "DejaVu Sans"],
    },
    "ru": {
        "name": "Русский",
        "rtl": False,
        "quote_open": "\u00ab",
        "quote_close": "\u00bb",
        "single_open": "\u201e",
        "single_close": "\u201c",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI", "Tahoma"],
    },
    "tr": {
        "name": "Türkçe",
        "rtl": False,
        "quote_open": "\u201c",
        "quote_close": "\u201d",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "font_hints": ["Arial", "Segoe UI"],
    },
    "zh": {
        "name": "中文",
        "rtl": False,
        "quote_open": "\u201c",
        "quote_close": "\u201d",
        "book_open": "\u300a",
        "book_close": "\u300b",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "prefer_cjk_punctuation": True,
        "font_hints": ["Microsoft YaHei", "SimHei", "Noto Sans SC", "Arial"],
    },
    "ar": {
        "name": "العربية",
        "rtl": True,
        "quote_open": "\u00ab",
        "quote_close": "\u00bb",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "disable_letter_spacing": True,
        "disable_word_highlight": True,  # 默认整句；UI 可开实验性逐词
        "font_hints": [
            "Segoe UI", "Tahoma", "Arial", "Traditional Arabic",
            "Arabic Typesetting", "Noto Naskh Arabic", "Noto Sans Arabic",
        ],
    },
    "he": {
        "name": "עברית",
        "rtl": True,
        "quote_open": "\u201c",
        "quote_close": "\u201d",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        "disable_letter_spacing": True,
        "disable_word_highlight": True,
        "font_hints": ["Segoe UI", "Tahoma", "Arial", "Noto Sans Hebrew", "David"],
    },
    "mg": {
        "name": "Malagasy",
        "rtl": False,
        "quote_open": "\u201c",
        "quote_close": "\u201d",
        "single_open": "\u2018",
        "single_close": "\u2019",
        "normalize_ascii_quotes": True,
        # 马达加斯加语为拉丁字母；自动检测易误判为英语/法语，请手动选「Malagasy」
        "font_hints": ["Arial", "Segoe UI", "Calibri", "Noto Sans"],
        "whisper_code": "mg",
    },
}

_LANG_ALIASES = {
    "eng": "en", "en-us": "en", "en-gb": "en",
    "por": "pt", "pt-br": "pt", "pt-pt": "pt",
    "spa": "es", "es-es": "es", "es-mx": "es", "castilian": "es",
    "fra": "fr", "fre": "fr",
    "ger": "de", "deu": "de",
    "ita": "it", "italian": "it",
    "ell": "el", "gre": "el", "greek": "el",
    "rus": "ru", "russian": "ru",
    "tur": "tr", "turkish": "tr",
    "cmn": "zh", "zho": "zh", "zh-cn": "zh", "zh-tw": "zh", "chi": "zh",
    "ara": "ar", "arabic": "ar",
    "heb": "he", "iw": "he", "hebrew": "he",
    # 马达加斯加语（Malagasy）— Whisper / ISO 639-1: mg
    "mg": "mg", "mlg": "mg", "malagasy": "mg", "madagascar": "mg",
    "马达加斯加": "mg", "马达加斯加语": "mg", "马拉加斯语": "mg",
}

_RLE = "\u202b"
_PDF = "\u202c"
_RLM = "\u200f"
_LRM = "\u200e"

_SCRIPT_RANGES = {
    "el": [(0x0370, 0x03FF), (0x1F00, 0x1FFF)],
    "ar": [(0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
    "he": [(0x0590, 0x05FF)],
    "ru": [(0x0400, 0x04FF)],  # 西里尔（俄/乌等粗归 ru 包）
    "zh": [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)],
}

_PACK_CACHE: dict[str, dict] | None = None


def language_packs_dir() -> Path:
    """安装包/工程内置语言包目录。"""
    here = Path(__file__).resolve().parent
    candidate = here.parent / "resources" / "language_packs"
    if candidate.is_dir():
        return candidate
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "resources" / "language_packs"
        if bundled.is_dir():
            return bundled
    return candidate


def user_language_packs_dir() -> Path:
    """用户导入的语言包目录（可写，优先覆盖内置）。"""
    try:
        from app.services.app_paths import data_dir as app_data_dir
        folder = app_data_dir() / "language_packs"
    except Exception:
        folder = Path.home() / "VideoToolkit" / "language_packs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _merge_pack_folder(packs: dict[str, dict], folder: Path) -> None:
    if not folder.is_dir():
        return
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            code = str(data.get("code") or path.stem).strip().lower()
            if not code:
                continue
            base = packs.get(code, {})
            packs[code] = {**base, **{k: v for k, v in data.items() if k != "code"}}
        except (OSError, ValueError, TypeError):
            continue


def _load_packs() -> dict[str, dict]:
    global _PACK_CACHE
    if _PACK_CACHE is not None:
        return _PACK_CACHE
    packs = {code: dict(data) for code, data in BUILTIN_PACKS.items()}
    _merge_pack_folder(packs, language_packs_dir())
    _merge_pack_folder(packs, user_language_packs_dir())
    _PACK_CACHE = packs
    return packs


def import_language_pack_file(source: str | Path) -> tuple[bool, str]:
    """导入 JSON 语言包到用户目录，成功返回 (True, 说明)。"""
    path = Path(source)
    if not path.is_file():
        return False, "文件不存在"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"无法解析 JSON：{exc}"
    code = str(data.get("code") or path.stem).strip().lower()
    if not code or not re.fullmatch(r"[a-z]{2,8}", code):
        return False, "语言包需包含合法 code 字段（如 el、ar、my）"
    if "quote_open" not in data and "name" not in data:
        return False, "语言包至少应包含 name 或 quote_open 等字段"
    payload = {"code": code, **{k: v for k, v in data.items() if k != "code"}}
    dest = user_language_packs_dir() / f"{code}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    reload_language_packs()
    return True, f"已导入语言包「{payload.get('name', code)}」({code}) → {dest}"


def reload_language_packs() -> None:
    global _PACK_CACHE
    _PACK_CACHE = None
    _load_packs()


def normalize_lang_code(language: str | None) -> str:
    if not language:
        return ""
    code = str(language).strip().lower().replace("_", "-")
    # UI 显示名 "English 英语" → 取 code 已由调用方处理；此处兼容
    if code in ("auto", "unknown", "none", "自动", "自动检测", "自动检测（推荐）"):
        return ""
    if code in _LANG_ALIASES:
        return _LANG_ALIASES[code]
    primary = code.split("-", 1)[0]
    # 若传入 "english 英语" 取第一个词
    if " " in primary:
        primary = primary.split()[0]
    return _LANG_ALIASES.get(primary, primary)


def writing_language_from_ui(text: str) -> str:
    """从下拉框当前文本解析语言码。"""
    value = str(text or "").strip()
    if not value or value.startswith("自动"):
        return ""
    for label, code in WRITING_LANGUAGE_OPTIONS:
        if value == label or value == code:
            return code
    # 兼容直接输入 el / ar
    return normalize_lang_code(value)


def _count_script(text: str, ranges) -> int:
    total = 0
    for ch in text:
        cp = ord(ch)
        for start, end in ranges:
            if start <= cp <= end:
                total += 1
                break
    return total


def detect_language(text: str, hint: str | None = None) -> str:
    hinted = normalize_lang_code(hint)
    packs = _load_packs()
    if hinted in packs:
        return hinted

    sample = str(text or "")
    if not sample.strip():
        return hinted or "en"

    ar = _count_script(sample, _SCRIPT_RANGES["ar"])
    he = _count_script(sample, _SCRIPT_RANGES["he"])
    el = _count_script(sample, _SCRIPT_RANGES["el"])
    ru = _count_script(sample, _SCRIPT_RANGES["ru"])
    zh = _count_script(sample, _SCRIPT_RANGES["zh"])
    letters = sum(
        1 for ch in sample
        if ch.isalpha() or "\u4e00" <= ch <= "\u9fff"
        or "\u0600" <= ch <= "\u06ff" or "\u0590" <= ch <= "\u05ff"
        or "\u0400" <= ch <= "\u04ff"
    )
    letters = max(1, letters)

    if ar / letters >= 0.25 or ar >= 8:
        return "ar"
    if he / letters >= 0.25 or he >= 6:
        return "he"
    if el / letters >= 0.25 or el >= 6:
        return "el"
    if ru / letters >= 0.35 or ru >= 8:
        return "ru"
    if zh / letters >= 0.35 or zh >= 6:
        return "zh"
    if hinted:
        return hinted if hinted in packs else "en"
    return "en"


def get_pack(language: str | None = None, text: str = "") -> dict:
    code = detect_language(text, language)
    packs = _load_packs()
    return packs.get(code) or packs["en"]


def is_rtl_text(text: str, language: str | None = None) -> bool:
    pack = get_pack(language, text)
    if pack.get("rtl"):
        return True
    ar = _count_script(str(text or ""), _SCRIPT_RANGES["ar"])
    he = _count_script(str(text or ""), _SCRIPT_RANGES["he"])
    return ar >= 3 or he >= 3


def should_disable_letter_spacing(text: str, language: str | None = None) -> bool:
    pack = get_pack(language, text)
    return bool(pack.get("disable_letter_spacing") or pack.get("rtl") or is_rtl_text(text, language))


def should_disable_word_highlight(
    text: str, language: str | None = None, allow_rtl_word_highlight: bool = False,
) -> bool:
    """默认 RTL 整句；allow_rtl_word_highlight=True 时允许实验性逐词。"""
    if allow_rtl_word_highlight and is_rtl_text(text, language):
        return False
    pack = get_pack(language, text)
    return bool(pack.get("disable_word_highlight") or pack.get("rtl") or is_rtl_text(text, language))


def _replace_ascii_double_quotes(text: str, open_q: str, close_q: str) -> str:
    if '"' not in text:
        return text
    parts = text.split('"')
    if len(parts) == 1:
        return text
    out = [parts[0]]
    for index, chunk in enumerate(parts[1:], 1):
        mark = open_q if index % 2 == 1 else close_q
        out.append(mark)
        out.append(chunk)
    return "".join(out)


def _replace_ascii_single_quotes(text: str, open_q: str, close_q: str) -> str:
    if "'" not in text:
        return text

    def repl(match: re.Match) -> str:
        return f"{open_q}{match.group(1)}{close_q}"

    return re.sub(r"(?<!\w)'([^']{1,80})'(?!\w)", repl, text)


def _prefer_cjk_punctuation(text: str) -> str:
    table = str.maketrans({
        ",": "，", "!": "！", "?": "？", ":": "：", ";": "；", "(": "（", ")": "）",
    })
    zh = _count_script(text, _SCRIPT_RANGES["zh"])
    latin = sum(1 for ch in text if "A" <= ch <= "Z" or "a" <= ch <= "z")
    if zh >= 2 and zh >= latin:
        return text.translate(table)
    return text


def _ensure_spanish_inverted_marks(text: str) -> str:
    """句末为 ? / ! 且句首缺少 ¿ / ¡ 时补全（西语规范）。"""
    value = text.strip()
    if not value:
        return text

    # 按句子粗分（保留分隔）
    parts = re.split(r"(?<=[.!?…])\s+", value)
    fixed = []
    for part in parts:
        piece = part.strip()
        if not piece:
            fixed.append(part)
            continue
        # 去掉已有倒标再判断
        core = piece.lstrip("¿¡ \t")
        if piece.endswith("?") and not piece.lstrip().startswith("¿"):
            piece = "¿" + core
        elif piece.endswith("!") and not piece.lstrip().startswith("¡"):
            piece = "¡" + core
        fixed.append(piece)
    # 尽量保留原空白结构：简单用空格重拼
    result = " ".join(fixed)
    # 若原文以空白开头结尾，尽量保留
    leading = re.match(r"^\s*", text).group(0)
    trailing = re.search(r"\s*$", text).group(0)
    return f"{leading}{result.strip()}{trailing}"


def format_subtitle_text(text: str, language: str | None = None) -> str:
    value = str(text or "")
    if not value.strip():
        return value
    value = value.replace(_RLE, "").replace(_PDF, "").replace(_RLM, "").replace(_LRM, "")
    pack = get_pack(language, value)
    code = detect_language(value, language)

    if pack.get("normalize_ascii_quotes", True):
        value = _replace_ascii_double_quotes(
            value, pack.get("quote_open", "\u201c"), pack.get("quote_close", "\u201d"))
        value = _replace_ascii_single_quotes(
            value, pack.get("single_open", "\u2018"), pack.get("single_close", "\u2019"))

    if pack.get("prefer_cjk_punctuation"):
        value = _prefer_cjk_punctuation(value)

    if pack.get("ensure_inverted_marks") or code == "es":
        value = _ensure_spanish_inverted_marks(value)

    if code == "el":
        value = re.sub(r"[ \t]{2,}", " ", value)

    return value


def format_subtitle_document(text: str, language: str | None = None) -> str:
    raw = str(text or "")
    if not raw.strip():
        return raw
    if "-->" not in raw:
        return format_subtitle_text(raw, language)

    blocks = re.split(r"(\r?\n\s*\r?\n)", raw)
    out = []
    for block in blocks:
        if not block or re.fullmatch(r"\r?\n\s*\r?\n", block):
            out.append(block)
            continue
        lines = block.splitlines()
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            out.append(block)
            continue
        head = lines[: timing_index + 1]
        body = lines[timing_index + 1 :]
        formatted = [format_subtitle_text(line, language) if line.strip() else line for line in body]
        out.append("\n".join(head + formatted))
    result = "".join(out)
    if raw.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


def wrap_rtl_for_ass(text: str) -> str:
    value = str(text or "")
    if not value:
        return value
    if value.startswith(_RLE) and value.endswith(_PDF):
        return value
    cleaned = value.replace(_RLE, "").replace(_PDF, "")
    return f"{_RLE}{cleaned}{_PDF}"


def prepare_ass_dialogue_text(text: str, language: str | None = None) -> str:
    formatted = format_subtitle_text(text, language)
    if is_rtl_text(formatted, language):
        return wrap_rtl_for_ass(formatted)
    return formatted


def effective_letter_spacing(settings: dict, sample_text: str = "") -> float:
    spacing = float(settings.get("letter_spacing", 0) or 0)
    lang = settings.get("caption_language") or settings.get("language") or settings.get("writing_language")
    if should_disable_letter_spacing(sample_text, lang):
        return 0.0
    return spacing


def suggest_font_for_text(current_font: str, text: str, language: str | None = None) -> str:
    pack = get_pack(language, text)
    hints = pack.get("font_hints") or []
    if not pack.get("rtl") and not is_rtl_text(text, language):
        return current_font
    current = (current_font or "").strip()
    lower = current.casefold()
    markers = ("arabic", "naskh", "kufi", "hebrew", "david", "tahoma", "segoe")
    if any(marker in lower for marker in markers):
        return current
    return hints[0] if hints else current


def export_builtin_packs(target_dir: Path | None = None) -> Path:
    folder = target_dir or language_packs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for code, data in BUILTIN_PACKS.items():
        payload = {"code": code, **data}
        (folder / f"{code}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def strip_bidi_marks(text: str) -> str:
    for mark in (_RLE, _PDF, _RLM, _LRM):
        text = text.replace(mark, "")
    return text


def fill_writing_language_combo(combo, current: str = "") -> None:
    """填充可编辑下拉：自动 + 各语言包。"""
    from PySide6.QtWidgets import QComboBox
    if not isinstance(combo, QComboBox):
        return
    combo.blockSignals(True)
    combo.clear()
    for label, code in WRITING_LANGUAGE_OPTIONS:
        combo.addItem(label, code)
    combo.setEditable(True)
    code = normalize_lang_code(current) if current and current != "auto" else ""
    if not code and current and str(current).strip() not in ("auto", ""):
        # 保留用户自定义码
        combo.setEditText(str(current).strip())
    else:
        index = next((i for i in range(combo.count()) if combo.itemData(i) == code), 0)
        combo.setCurrentIndex(index)
    combo.blockSignals(False)
