
from __future__ import annotations
import re

INVALID = r'[\\/:*?"<>|\r\n\t]'

def safe_piece(text: str) -> str:
    text = re.sub(INVALID, "", text or "")
    text = "".join(c for c in text if ord(c)<=0xFFFF and c not in "\ufffd\ufe0f\u200d")
    text = re.sub(r"\s+", "", text)
    return text.strip(" .-_")

def chinese_preview(text: str, max_chars: int = 38) -> str:
    cleaned = safe_piece(text)
    return cleaned[:max_chars] if cleaned else "中文文案待填写"

def final_filename(seq: int, fixed_code: str, recipient: str, host: str,
                   creator: str, chinese_script: str, work_date: str) -> str:
    parts = [
        f"{seq:02d}",
        safe_piece(fixed_code or "ZB"),
        safe_piece(recipient),
        safe_piece(host),
        safe_piece(creator),
        chinese_preview(chinese_script),
        safe_piece(work_date),
    ]
    return "-".join(p for p in parts if p) + ".mp4"

def resolve_export_filename(name: str) -> str:
    # Resolve macOS may replace supplementary Unicode characters in output names.
    name = ''.join(c for c in name if ord(c)<=0xFFFF and c not in '\ufffd\ufe0f\u200d')
    return name[:-4]+'.mp4' if name.lower().endswith('.mp4') else name+'.mp4'
