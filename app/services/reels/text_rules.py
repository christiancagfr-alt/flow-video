from __future__ import annotations

import re

from .language_style import format_subtitle_document, format_subtitle_text


# 字幕识别容易把专有宗教称谓输出成小写。这里保存用户要求的规范写法；
# 使用完整 Unicode 单词匹配，标点相邻时也生效，但不会误改更长单词。
_TERM_SPELLINGS = {
    "amen": "Amen",
    "amém": "Amém",
    "amén": "Amén",
    "αμήν": "Αμήν",
    "deus": "Deus",
    "jesus": "Jesus",
    "senhor": "Senhor",
    "κύριος": "Κύριος",
    "pai": "Pai",
}
_CAPITALIZED_TERMS = {term.casefold(): spelling for term, spelling in _TERM_SPELLINGS.items()}
_CAPITALIZED_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(term) for term in _TERM_SPELLINGS) + r")(?!\w)",
    flags=re.IGNORECASE,
)


def normalize_required_capitalization(text: str) -> str:
    """把指定完整单词统一为规范首字母大写，保留其余文本与时间轴格式。"""
    value = str(text or "")
    return _CAPITALIZED_PATTERN.sub(
        lambda match: _CAPITALIZED_TERMS.get(match.group(0).casefold(), match.group(0)),
        value,
    )


def normalize_subtitle_text(text: str, language: str | None = None) -> str:
    """字幕正文规范化：专名大小写 + 按语言包书写习惯（引号等）。

    language 可为 whisper 语言码（el/ar/pt…）；空则自动从文本检测。
    支持纯文本或整份 SRT（时间轴行不改）。
    """
    value = normalize_required_capitalization(str(text or ""))
    if "-->" in value:
        return format_subtitle_document(value, language)
    return format_subtitle_text(value, language)


# Whisper / turbo 在希腊语口播静音或片尾常幻觉出 YouTube 字幕社水印，
# 典型整句只有「Υπότιτλοι AUTHORWAVE」（希腊语「字幕」+ 机构名），视频里并无此声。
_ASR_JUNK_CUE_RE = re.compile(
    r"""
    ^\s*
    (?:
        # 希腊语「字幕」± AUTHORWAVE / 其它社名
        υπ[όο]τιτλοι\s*(?:authorwave|amara(?:\.org)?|www\.?)?
        |
        υποτιτλοι\s*(?:authorwave|amara(?:\.org)?|www\.?)?
        |
        # 英文水印行
        subtitles?\s*(?:by\s+)?(?:authorwave|amara(?:\.org)?|\w{2,20})?
        |
        synced\s+by\s+\w{2,30}
        |
        authorwave
        |
        amara\.org
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_asr_junk_caption(text: str) -> bool:
    """True if cue is a known ASR watermark / credit hallucination (not spoken)."""
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return False
    # 过长的正常句子即使含个别词也不删
    if len(value) > 48:
        return False
    folded = value.casefold()
    if _ASR_JUNK_CUE_RE.match(folded) or _ASR_JUNK_CUE_RE.match(value):
        return True
    # 无音调折叠后再判一次（Υπότιτλοι → υποτιτλοι）
    plain = (
        folded.replace("ό", "ο").replace("ί", "ι").replace("ά", "α")
        .replace("έ", "ε").replace("ή", "η").replace("ύ", "υ").replace("ώ", "ω")
    )
    if _ASR_JUNK_CUE_RE.match(plain):
        return True
    if "authorwave" in folded and len(value) < 40:
        return True
    return False


def filter_asr_junk_srt(srt_text: str) -> str:
    """Drop junk watermark cues from an SRT and renumber remaining blocks."""
    text = str(srt_text or "").replace("\r\n", "\n").strip()
    if not text or "-->" not in text:
        if is_asr_junk_caption(text):
            return ""
        return text
    blocks = re.split(r"\n\s*\n", text)
    kept = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        # 找到时间轴行之后的正文
        arrow_i = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if arrow_i is None:
            body = " ".join(lines)
        else:
            body = " ".join(lines[arrow_i + 1 :])
        if is_asr_junk_caption(body):
            continue
        kept.append(block.strip())
    if not kept:
        return ""
    # 重新编号
    out = []
    for idx, block in enumerate(kept, 1):
        lines = block.split("\n")
        if lines and lines[0].strip().isdigit():
            lines[0] = str(idx)
        else:
            lines.insert(0, str(idx))
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"
