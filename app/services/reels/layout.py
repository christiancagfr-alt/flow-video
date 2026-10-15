from __future__ import annotations
import re, os, sys, shutil, hashlib
from pathlib import Path
from PySide6.QtGui import QFont, QFontInfo, QFontMetricsF
from PySide6.QtCore import Qt
from .language_style import effective_letter_spacing
from .text_rules import normalize_subtitle_text
PRESETS = {
    # 经典黄：仅当前词黄跟读，读完立刻回原色；描边深红棕
    "Descript 经典黄": {"text": "#F8FAFC", "outline": "#7C2D12", "highlight": "#FACC15", "outline_width": 5,
                         "effect": "word_color", "font": "Arial", "font_size": 90, "line_length": 26,
                         "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                         "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "三行分色底板 · 绿白黑": {
        "text": "#FFFFFF", "outline": "#FFFFFF", "highlight": "#FFFFFF", "background": "#00A526", "active_text": "#111111",
        "effect": "three_bands", "outline_width": 0, "font": "Roboto Condensed", "font_size": 64,
        "line_length": 42, "line_width": 94, "max_lines": 3, "max_words": 30,
        "letter_spacing": 0, "line_spacing": 100, "position": "画面中间", "margin_v": 500,
        "highlight_padding": 28, "highlight_padding_y": 18, "animation_speed": 0,
    },
    # 由下往上持续滚动（自由文案，不对口型）
    "滚动字幕 · 上浮": {
        "text": "#FFFFFF", "outline": "#1C1917", "highlight": "#FACC15", "outline_width": 4,
        "effect": "outline", "font": "Arial", "font_size": 72, "line_length": 18,
        "letter_spacing": 0, "line_spacing": 110, "margin_v": 520, "max_words": 12, "max_lines": 6,
        "position": "画面中间", "caption_mode": "自由文案动画（不对口型）",
        "free_animation": "持续向上滚动", "animation_speed": 120,
    },
    # 字幕只在画面中部的固定窗口里上移，到窗口边缘淡出，不漂出画面顶部
    "滚动字幕 · 中间固定": {
        "text": "#FFFFFF", "outline": "#1C1917", "highlight": "#FACC15", "outline_width": 4,
        "effect": "outline", "font": "Arial", "font_size": 72, "line_length": 18,
        "letter_spacing": 0, "line_spacing": 110, "margin_v": 520, "max_words": 12, "max_lines": 8,
        "position": "画面中间", "caption_mode": "自由文案动画（不对口型）",
        "free_animation": "中间固定滚动", "animation_speed": 120,
    },
    # Customizable entry/exit path with a separately clipped display window.
    "滚动字幕 · 自定义区域": {
        "text": "#FFFFFF", "outline": "#1C1917", "highlight": "#FACC15", "outline_width": 4,
        "effect": "outline", "font": "Arial", "font_size": 72, "line_length": 18,
        "letter_spacing": 0, "line_spacing": 110, "margin_v": 520, "max_words": 12, "max_lines": 8,
        "position": "画面中间", "caption_mode": "自由文案动画（不对口型）",
        "free_animation": "自定义区域滚动", "animation_speed": 120,
        "scroll_area_top": 20, "scroll_area_bottom": 80,
        "scroll_start_y": 100, "scroll_end_y": -100, "scroll_end_auto": True,
    },
    "双眼皮 经典红黄黑": {"text": "#FF0000", "outline": "#FFFF00", "highlight": "#111111", "outline_width": 3,
                           "effect": "double_outline", "font": "Arial", "font_size": 90, "line_length": 26,
                           "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                           "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "双眼皮 极光绿白黑": {"text": "#FFFFFF", "outline": "#A3E635", "highlight": "#111111", "outline_width": 3,
                           "effect": "double_outline", "font": "Arial", "font_size": 90, "line_length": 26,
                           "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                           "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "双眼皮 炫彩黄蓝黑": {"text": "#FACC15", "outline": "#2563EB", "highlight": "#111111", "outline_width": 3,
                           "effect": "double_outline", "font": "Arial", "font_size": 90, "line_length": 26,
                           "letter_spacing": -4, "line_spacing": 100, "margin_v": 500,
                           "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 暖橙": {"text": "#FFFFFF", "outline": "#171717", "highlight": "#FB923C", "outline_width": 5,
                       "effect": "word_color", "font": "Arial", "font_size": 76, "line_length": 26,
                       "margin_v": 315, "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 青柠": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#A3E635", "outline_width": 5,
                       "effect": "word_color", "font": "Arial", "font_size": 76, "line_length": 26,
                       "margin_v": 315, "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 天蓝": {"text": "#FFFFFF", "outline": "#0F172A", "highlight": "#38BDF8", "outline_width": 5,
                       "effect": "word_color", "font": "Arial", "font_size": 76, "line_length": 26,
                       "margin_v": 315, "max_words": 7, "highlight_padding": 16, "animation_speed": 90},
    "Descript 紫色块": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#7C3AED", "outline_width": 4,
                         "effect": "descript", "font": "Arial", "font_size": 78, "line_length": 28,
                         "margin_v": 330, "max_words": 7, "highlight_padding": 18, "animation_speed": 150},
    "HeyGen 跟读": {"text": "#FFFFFF", "outline": "#050505", "highlight": "#F43F5E", "outline_width": 6, "effect": "heygen", "font": "Arial", "font_size": 86, "line_length": 18, "margin_v": 350},
    "逐字弹出": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#8B5CF6", "outline_width": 3, "effect": "pop"},
    "精选高亮": {"text": "#FFFFFF", "outline": "#172554", "highlight": "#7C3AED", "outline_width": 2, "effect": "highlight"},
    "小范下划线": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#FACC15", "outline_width": 2, "effect": "underline"},
    "外框字幕": {"text": "#FFFFFF", "outline": "#8B5CF6", "highlight": "#8B5CF6", "outline_width": 5, "effect": "outline"},
    "背景跟读": {"text": "#FFFFFF", "outline": "#111827", "highlight": "#2563EB", "outline_width": 2, "effect": "highlight"},
    "光晕字幕": {"text": "#F5F3FF", "outline": "#7C3AED", "highlight": "#A855F7", "outline_width": 6, "effect": "glow"},
    "网红 蓝红色块": {
        "text": "#FFFFFF", "outline": "#0B2447", "background": "#168AAD",
        "highlight": "#EF233C", "active_text": "#FFFFFF", "outline_width": 2,
        "effect": "dual_box", "font": "Arial", "font_size": 82, "line_length": 24,
        "line_width": 90, "max_lines": 2, "max_words": 8,
        "highlight_padding": 10, "highlight_padding_y": 7, "animation_speed": 90,
        "margin_v": 390,
    },
    "网红 黄黑卡点": {
        "text": "#FFFFFF", "outline": "#000000", "background": "#111111",
        "highlight": "#FACC15", "active_text": "#111111", "outline_width": 1,
        "effect": "dual_box", "font": "Arial", "font_size": 84, "line_length": 22,
        "line_width": 88, "max_lines": 2, "max_words": 7,
        "highlight_padding": 12, "highlight_padding_y": 8, "animation_speed": 80,
        "margin_v": 400,
    },
    "网红 紫粉潮流": {
        "text": "#FFFFFF", "outline": "#2E1065", "background": "#6D28D9",
        "highlight": "#EC4899", "active_text": "#FFFFFF", "outline_width": 1,
        "effect": "dual_box", "font": "Arial", "font_size": 80, "line_length": 24,
        "line_width": 90, "max_lines": 3, "max_words": 8,
        "highlight_padding": 11, "highlight_padding_y": 8, "animation_speed": 100,
        "margin_v": 380,
    },
    "网红 青柠重点": {
        "text": "#F8FAFC", "outline": "#020617", "background": "#0F172A",
        "highlight": "#A3E635", "active_text": "#111827", "outline_width": 1,
        "effect": "dual_box", "font": "Arial", "font_size": 80, "line_length": 24,
        "line_width": 90, "max_lines": 2, "max_words": 8,
        "highlight_padding": 11, "highlight_padding_y": 8, "animation_speed": 85,
        "margin_v": 380,
    },
    "网红 极简黑白": {
        "text": "#111827", "outline": "#FFFFFF", "background": "#FFFFFF",
        "highlight": "#111827", "active_text": "#FFFFFF", "outline_width": 0,
        "effect": "dual_box", "font": "Arial", "font_size": 78, "line_length": 26,
        "line_width": 92, "max_lines": 2, "max_words": 8,
        "highlight_padding": 12, "highlight_padding_y": 8, "animation_speed": 90,
        "margin_v": 380,
    },
    # CapCut/Reels：先整句语义排版定稿（位置固定），再按语速逐词弹出；句末硬切防叠字
    "Reels 语义重点": {
        "text": "#FFFFFF", "outline": "#0A0A0A", "highlight": "#FFFFFF", "outline_width": 5,
        "effect": "semantic_stack", "font_size": 86, "line_length": 22,
        "letter_spacing": -1, "line_spacing": 115, "margin_v": 480,
        "max_words": 7, "highlight_padding": 10, "animation_speed": 70,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 88,
        # 重点词约 +18%，其余约 -22%，差距能看清又不过分
        "semantic_large_ratio": 1.18,
        "semantic_small_ratio": 0.78,
        # 不再提前出字，严格跟词级时间，避免「字幕提前导致对不上」
        "semantic_lead_ms": 0,
    },
    # 语义大小号 + 当前跟读词亮黄变色（卡拉OK）
    "Reels 语义黄字跟读": {
        "text": "#FFFFFF", "outline": "#0A0A0A", "highlight": "#FFEE00", "outline_width": 5,
        "effect": "semantic_karaoke", "font_size": 86, "line_length": 22,
        "letter_spacing": -1, "line_spacing": 115, "margin_v": 480,
        "max_words": 7, "highlight_padding": 10, "animation_speed": 70,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 88,
        "semantic_large_ratio": 1.18,
        "semantic_small_ratio": 0.78,
        "semantic_lead_ms": 0,
    },
    # —— 逐词变色系列 ——
    "卡拉OK 青蓝跟读": {"text": "#FFFFFF", "outline": "#1A1A3A", "highlight": "#00E5FF", "outline_width": 4, "effect": "word_color", "font": "Arial", "font_size": 70, "line_length": 26, "margin_v": 500, "max_words": 7},
    # 逐词变色：已读保持黄（与经典黄「读完回原色」不同）
    "亮黄逐词变色": {"text": "#FFFFFF", "outline": "#222222", "highlight": "#FFEE00", "outline_width": 3, "effect": "word_color_persist", "font": "Arial", "font_size": 70, "line_length": 26, "margin_v": 500, "max_words": 7},
    # —— Facebook 参考（Downloads/视频批量下载/Facebook）——
    # 参考1：夜间卡车 · 白字+当前词亮黄荧光 · 粗黑描边 · 居中偏上 · 逐词
    "FB 卡车黄字跟读": {
        "text": "#F8FAFC", "outline": "#0A0A0A", "highlight": "#F7FF1A",
        "outline_width": 6, "effect": "word_color",
        "font": "Arial Black", "font_size": 88, "line_length": 22,
        "letter_spacing": -2, "line_spacing": 108,
        "margin_v": 520, "max_words": 5, "max_lines": 2,
        "highlight_padding": 8, "animation_speed": 85,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 86,
    },
    # 参考2：黄昏公路 · 纯白大字 + 柔和白光晕 · 居中 · 少词大字
    "FB 黄昏白字光晕": {
        "text": "#FFFFFF", "outline": "#FFFFFF", "highlight": "#FFFFFF",
        "outline_width": 4, "effect": "glow",
        "font": "Arial Black", "font_size": 96, "line_length": 18,
        "letter_spacing": 1, "line_spacing": 112,
        "margin_v": 480, "max_words": 4, "max_lines": 2,
        "highlight_padding": 6, "animation_speed": 90,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 84, "shadow": 6,
    },
    # 参考2 变体：逐词亮起（当前词更亮，其余白）
    "FB 黄昏逐词亮白": {
        "text": "#E8E8E8", "outline": "#1A1A1A", "highlight": "#FFFFFF",
        "outline_width": 5, "effect": "word_color",
        "font": "Arial Black", "font_size": 94, "line_length": 18,
        "letter_spacing": 0, "line_spacing": 110,
        "margin_v": 480, "max_words": 4, "max_lines": 2,
        "highlight_padding": 6, "animation_speed": 88,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 84,
    },
    # 白字+当前词亮黄 · 粗黑描边 · 居中（保留）
    "FB Reel 黄字跟读": {
        "text": "#FFFFFF", "outline": "#0A0A0A", "highlight": "#FFEE00",
        "outline_width": 5, "effect": "word_color",
        "font": "Arial Black", "font_size": 86, "line_length": 24,
        "letter_spacing": -2, "word_spacing": -2, "line_spacing": 108,
        "margin_v": 500, "max_words": 6, "max_lines": 2,
        "highlight_padding": 8, "animation_speed": 85,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 88,
    },
    # 参考：facebook.com/reel/1033593986178713
    # 语义大小号 + 逐词弹出 + 当前词亮红放大跟读（读完留白字）
    "FB Reel 红字跟读": {
        "text": "#FFFFFF", "outline": "#000000", "highlight": "#FF2D2D",
        "outline_width": 6, "effect": "semantic_karaoke",
        "font": "Arial Black", "font_size": 90, "line_length": 22,
        "letter_spacing": -2, "word_spacing": -4, "line_spacing": 112,
        "margin_v": 500, "max_words": 5, "max_lines": 2,
        "highlight_padding": 8, "animation_speed": 65,
        "position": "画面中间", "caption_mode": "语音同步字幕",
        "line_width": 86,
        "semantic_large_ratio": 1.22,
        "semantic_small_ratio": 0.72,
        "semantic_lead_ms": 0,
        "semantic_max_lines": 5,
    },
    # —— 弹出缩放系列 ——
    "默认白字": {"text": "#FFFFFF", "outline": "#000000", "highlight": "#FFD700", "outline_width": 3, "effect": "pop", "font": "Arial", "font_size": 74, "line_length": 26, "margin_v": 500, "max_words": 7},
    "黄字黑边 (经典)": {"text": "#FFD700", "outline": "#000000", "highlight": "#FF4444", "outline_width": 5, "effect": "pop", "font": "Arial", "font_size": 74, "line_length": 26, "margin_v": 500, "max_words": 7},
    "粗边白色弹出": {"text": "#FFFFFF", "outline": "#000000", "highlight": "#FFFFFF", "outline_width": 7, "effect": "pop", "font": "Arial", "font_size": 82, "line_length": 22, "margin_v": 500, "max_words": 5},
    "金色弹出 Segoe": {"text": "#FFFFFF", "outline": "#000000", "highlight": "#FFD700", "outline_width": 3, "effect": "pop", "font": "Segoe UI", "font_size": 76, "line_length": 26, "margin_v": 500, "max_words": 7},
    # —— 下划线系列 ——
    "金色下划线跟读": {"text": "#E0E0E0", "outline": "#000000", "highlight": "#FFD700", "outline_width": 2, "effect": "underline", "font": "Arial", "font_size": 68, "line_length": 26, "margin_v": 500, "max_words": 7},
    # —— 发光描边系列 ——
    "粉色发光描边": {"text": "#FFFFFF", "outline": "#FF69B4", "highlight": "#FF69B4", "outline_width": 5, "effect": "glow", "font": "Arial", "font_size": 72, "line_length": 26, "margin_v": 500, "max_words": 7},
    "金色发光字幕": {"text": "#FFFFF0", "outline": "#8B7500", "highlight": "#FFD700", "outline_width": 2, "effect": "glow", "font": "Arial", "font_size": 72, "line_length": 26, "margin_v": 500, "max_words": 7},
    "霓虹紫青双色发光": {"text": "#FFFFFF", "outline": "#bd00ff", "highlight": "#00f0ff", "outline_width": 2, "effect": "glow", "font": "Segoe UI", "font_size": 72, "line_length": 26, "margin_v": 500, "max_words": 7},
    # —— 描边框系列 ——
    "金框描边字幕": {"text": "#FFFFFF", "outline": "#FFD700", "highlight": "#FFD700", "outline_width": 2, "effect": "outline", "font": "Segoe UI", "font_size": 66, "line_length": 26, "margin_v": 500, "max_words": 7},
    # —— 底色框跟读系列（dual_box：普通词用 background，当前词用 highlight + active_text）——
    # 旧版误写成 descript/highlight，background 被忽略，名称与画面严重不符
    "黑底白字 (新闻)": {
        "text": "#FFFFFF", "outline": "#000000", "background": "#000000",
        "highlight": "#FFD700", "active_text": "#111111", "outline_width": 0,
        "effect": "dual_box", "font": "Arial", "font_size": 60, "line_length": 26,
        "line_width": 90, "max_lines": 2, "max_words": 7,
        "highlight_padding": 12, "highlight_padding_y": 8, "animation_speed": 90,
        "margin_v": 500,
    },
    "深蓝底色框跟读": {
        "text": "#FFFFFF", "outline": "#000000", "background": "#0A3D63",
        "highlight": "#00BFFF", "active_text": "#0A1628", "outline_width": 0,
        "effect": "dual_box", "font": "Arial", "font_size": 64, "line_length": 26,
        "line_width": 90, "max_lines": 2, "max_words": 7,
        "highlight_padding": 12, "highlight_padding_y": 8, "animation_speed": 90,
        "margin_v": 500,
    },
    "紫底金色框跟读": {
        "text": "#FFFFFF", "outline": "#000000", "background": "#6A0DAD",
        "highlight": "#FFD700", "active_text": "#1A0A2E", "outline_width": 0,
        "effect": "dual_box", "font": "Arial", "font_size": 52, "line_length": 26,
        "line_width": 90, "max_lines": 2, "max_words": 7,
        "highlight_padding": 12, "highlight_padding_y": 8, "animation_speed": 90,
        "margin_v": 500,
    },
    # 未读：深色底白字；跟读：黄底黑字
    "黄底框跟读高亮": {
        "text": "#FFFFFF", "outline": "#000000", "background": "#1F2937",
        "highlight": "#FFD700", "active_text": "#111111", "outline_width": 0,
        "effect": "dual_box", "font": "Segoe UI", "font_size": 66, "line_length": 26,
        "line_width": 90, "max_lines": 2, "max_words": 7,
        "highlight_padding": 12, "highlight_padding_y": 8, "animation_speed": 90,
        "margin_v": 500,
    },
    # —— 语义重点 ——
    "Hormozi 大字语义": {
        "text": "#FFFFFF", "outline": "#000000", "highlight": "#FFFF00", "outline_width": 7,
        "effect": "word_scale", "font": "Arial", "font_size": 86, "line_length": 18,
        "margin_v": 500, "max_words": 5,
        "semantic_large_ratio": 1.22, "semantic_small_ratio": 0.72, "semantic_lead_ms": 0,
    },
}
STATIC_BOLD_FONT_FILES = {
    "Open Sans": "OpenSans-Bold.ttf",
    "Noto Sans": "NotoSans-Bold.ttf",
    "Noto Sans SC": "NotoSansCJKsc-Bold.otf",
    "Noto Sans CJK SC": "NotoSansCJKsc-Bold.otf",
    "Poppins": "Poppins-Bold.ttf",
    "Libre Baskerville": "LibreBaskerville-Bold.ttf",
}
_EMPHASIS_STOPWORDS = {
    # English
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "for", "with", "as", "at",
    "by", "from", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did", "have", "has",
    "had", "will", "would", "can", "could", "should", "may", "might", "must", "this", "that", "these",
    "those", "it", "its", "my", "your", "his", "her", "our", "their", "me", "you", "him", "them",
    "we", "they", "i", "not", "no", "so", "than", "then", "too", "very", "just", "also", "only",
    "into", "about", "over", "after", "before", "when", "what", "who", "which", "how", "why", "all",
    "any", "some", "more", "most", "other", "such", "own", "same", "both", "each", "few", "many",
    "much", "up", "out", "off", "down", "again", "further", "once", "here", "there", "where", "while",
    "because", "though", "although", "until", "unless", "whether", "nor", "yet", "per", "via",
    # Portuguese / Spanish common function words
    "o", "os", "as", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos", "e", "em", "no",
    "na", "nos", "nas", "que", "se", "por", "para", "com", "sem", "ao", "aos", "ou", "mas", "como",
    "já", "não", "nao", "mais", "el", "la", "los", "las", "un", "una", "del", "al", "y", "en",
    "lo", "le", "les", "su", "sus", "mi", "tu", "me", "te", "nos", "vos", "es", "son", "está",
    "esta", "são", "sao", "ser", "estar", "foi", "era", "há", "ha", "tem", "ter", "um", "uma",
    "pra", "pro", "pela", "pelo", "pelas", "pelos", "entre", "sobre", "até", "ate", "depois",
    "antes", "quando", "onde", "quem", "qual", "quais", "porque", "pois", "então", "entao",
    # Chinese particles / light words
    "的", "了", "着", "过", "在", "是", "和", "与", "或", "就", "都", "也", "还", "很", "把", "被",
    "让", "给", "从", "向", "到", "对", "等", "及", "而", "并", "又", "再", "已", "将", "会", "能",
    "要", "可", "这", "那", "哪", "什么", "怎么", "一个", "一些", "没有", "不是", "我们", "你们",
    "他们", "她们", "它们", "自己",
}
SEMANTIC_LAYOUT_EFFECTS = ("semantic_stack", "word_scale", "semantic_karaoke")





def parse_srt(srt, language=None):
    blocks = re.split(r"\r?\n\s*\r?\n", srt.strip())
    result = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0: continue
        match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[timing_index])
        if not match: continue
        raw_values = match.groups(); values = [int(value) for value in raw_values]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / (10 ** len(raw_values[3]))
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / (10 ** len(raw_values[7]))
        # 保留用户手动换行；自由整段字幕需要按输入排版显示全部行。
        # 专名大小写 + 语言包引号/书写规范（希腊 «»、中文标点等）。
        text = normalize_subtitle_text("\n".join(lines[timing_index + 1:]).strip(), language=language)
        if text: result.append((start, max(start + .1, end), text))
    return result

def fix_srt_overlaps(srt, gap_ms=20, min_duration_ms=80):
    """Fix adjacent SRT overlaps without touching caption text or word timing caches."""
    entries=parse_srt(srt)
    if len(entries) < 2: return srt,0
    entries=[list(item) for item in sorted(entries,key=lambda item:(item[0],item[1]))]
    gap=max(0,int(gap_ms))/1000; minimum=max(20,int(min_duration_ms))/1000
    fixed=0
    for index in range(1,len(entries)):
        previous=entries[index-1]; current=entries[index]
        if current[0] >= previous[1]: continue
        # Subtitle Edit style: normally shorten the previous cue to just before
        # the next cue.  Only move the next start when the previous cue would
        # otherwise become too short to display.
        candidate=current[0]-gap
        if candidate >= previous[0]+minimum:
            previous[1]=candidate
        else:
            previous[1]=previous[0]+minimum
            current[0]=previous[1]+gap
            current[1]=max(current[1],current[0]+minimum)
        fixed+=1
    if not fixed: return srt,0

    def stamp(value):
        milliseconds=max(0,round(float(value)*1000)); hours,remainder=divmod(milliseconds,3600000)
        minutes,remainder=divmod(remainder,60000); seconds,millis=divmod(remainder,1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    blocks=[f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}"
            for index,(start,end,text) in enumerate(entries,1)]
    return "\n\n".join(blocks)+"\n",fixed

def group_word_srt(srt, max_chars=36, max_duration=4.6, max_words=999, return_fix_count=False):
    """把词级时间轴合并成便于阅读/编辑的逐句 SRT，保留首尾真实时间。"""
    words = parse_srt(srt)
    if not words: return (srt,0) if return_fix_count else srt
    # 已经是正常句级字幕时不重复合并。
    if len(words) <= 2 or sum(len(tokens_for(text)) for _,_,text in words) > len(words) * 2:
        fixed,count=fix_srt_overlaps(srt)
        return (fixed,count) if return_fix_count else fixed
    phrases=[]; current=[]; start=None; end=None

    def flush():
        nonlocal current, start, end
        if current:
            phrases.append((start or 0, end or (start or 0) + .4, " ".join(current)))
        current=[]; start=end=None

    for w_start,w_end,text in words:
        pause = 0 if end is None else max(0, w_start - end)
        candidate=(" ".join(current+[text])).strip()
        # 长停顿、过长句子和行宽溢出时，在当前词之前切句；避免只显示单个词。
        # 完全根据语音停顿与语义自适应，仅通过 max_chars (字宽限制，最多2行) 作硬切分
        if current and ((pause >= .52 and len(current) >= 2) or len(current) >= max_words or len(candidate) > max_chars
                        or (w_end - (start or w_start)) > max_duration):
            flush()
        if start is None: start=w_start
        current.append(text); end=w_end
        sentence_end=bool(re.search(r"[.!?。！？…][\"'”’)]?$",text))
        if sentence_end and len(current) >= 2:
            flush()
    flush()
    blocks=[]
    for index,(start,end,text) in enumerate(phrases,1):
        def stamp(value):
            ms=max(0,round(value*1000)); h,rem=divmod(ms,3600000); m,rem=divmod(rem,60000); sec,milli=divmod(rem,1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{milli:03d}"
        blocks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}")
    fixed,count=fix_srt_overlaps("\n\n".join(blocks)+"\n")
    return (fixed,count) if return_fix_count else fixed

def tokens_for(text):
    if re.search(r"[\u3400-\u9fff]", text):
        return [char for char in text if not char.isspace()]
    return re.findall(r"\S+", text)

def _token_core(token: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff']+", "", str(token or ""), flags=re.UNICODE)

def select_emphasis_words(tokens):
    """按语义启发式挑选重点词（大号）；虚词/介词等小号。结果对同一句稳定可复现。"""
    tokens = list(tokens or [])
    n = len(tokens)
    if n == 0:
        return []
    scores = []
    for index, token in enumerate(tokens):
        core = _token_core(token)
        if not core:
            scores.append(-100.0)
            continue
        low = core.casefold()
        is_cjk = bool(re.search(r"[\u3400-\u9fff]", core))
        if low in _EMPHASIS_STOPWORDS or core in _EMPHASIS_STOPWORDS:
            scores.append(-12.0)
            continue
        # 过短的拉丁虚词倾向
        if not is_cjk and len(core) <= 2:
            scores.append(-4.0)
            continue
        score = 8.0 + min(len(core), 14)
        if index == 0:
            score += 2.5
        if index == n - 1:
            score += 3.5
        # 稳定“随机”扰动：同一词在同一句里结果固定，不同句有变化
        score += (int(hashlib.sha256(f"{low}:{index}:{n}".encode()).hexdigest()[:8],16) % 9)
        scores.append(score)

    content = [i for i, s in enumerate(scores) if s > 0]
    if not content:
        # 全是虚词时至少强调首尾有字的词，避免整屏全小
        emph = [False] * n
        for i in range(n):
            if _token_core(tokens[i]):
                emph[i] = True
                break
        for i in range(n - 1, -1, -1):
            if _token_core(tokens[i]):
                emph[i] = True
                break
        return emph

    # 短句 1 个重点，中句 2 个，长句最多 3 个
    if n <= 3:
        k = 1
    elif n <= 8:
        k = 2
    else:
        k = 3
    k = min(k, len(content))

    # 优先句首/句尾实词做大号（更像参考：bless … safe），再用得分补足
    picks = []
    picks.append(content[0])
    if k >= 2 and content[-1] != content[0]:
        picks.append(content[-1])
    ranked = sorted(content, key=lambda i: scores[i], reverse=True)
    for i in ranked:
        if len(picks) >= k:
            break
        if i in picks:
            continue
        # 尽量不与已选重点相邻，中间留给小号铺陈
        if any(abs(i - p) == 1 for p in picks):
            continue
        picks.append(i)
    if len(picks) < k:
        for i in ranked:
            if i in picks:
                continue
            picks.append(i)
            if len(picks) >= k:
                break
    emph = [False] * n
    for i in picks:
        emph[i] = True
    return emph

def semantic_stack_layout(tokens, emphasized, settings):
    """
    语义堆叠排版：
    - 重点词：大号，独占一行
    - 普通词：小号，成组排成一行（自动按宽度换行）
    返回 lines: [[{token, large, size, width}, ...], ...]
    """
    tokens = list(tokens or [])
    if not tokens:
        return []
    if not emphasized or len(emphasized) != len(tokens):
        emphasized = select_emphasis_words(tokens)

    # 重点约 +18%、其余约 -22%（相对 base），层次清晰又不过分
    large_size, small_size = _semantic_font_sizes(settings)
    max_width = 1080 * max(40, min(96, int(settings.get("line_width") or 88))) / 100
    family = str(settings.get("font") or "Arial")
    bold = caption_uses_bold_face(settings)
    letter = _safe_float(settings.get("letter_spacing"), 0)

    def make_metrics(size):
        font = QFont(family)
        font.setPixelSize(size)
        font.setBold(bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter)
        return QFontMetricsF(font)

    m_large = make_metrics(large_size)
    m_small = make_metrics(small_size)
    word_gap = _safe_float(settings.get("word_spacing"), 0)
    gap_large = max(2.0, m_large.horizontalAdvance(" ") + word_gap)
    gap_small = max(2.0, m_small.horizontalAdvance(" ") + word_gap)

    lines = []
    small_buf = []
    # 小号行不宜过长，参考图一般 2～4 词一行，更整齐
    max_small_words = max(2, min(5, int(settings.get("semantic_small_words") or 3)))

    def flush_small():
        nonlocal small_buf
        if not small_buf:
            return
        current = []
        current_w = 0.0
        for item in small_buf:
            extra = gap_small if current else 0.0
            too_wide = current and current_w + extra + item["width"] > max_width * 0.90
            too_many = current and len(current) >= max_small_words
            if too_wide or too_many:
                lines.append(current)
                current = [item]
                current_w = item["width"]
            else:
                current.append(item)
                current_w += extra + item["width"]
        if current:
            lines.append(current)
        small_buf = []

    for token, is_large in zip(tokens, emphasized):
        if is_large:
            flush_small()
            width = max(large_size * 0.4, m_large.horizontalAdvance(token))
            lines.append([{
                "token": token, "large": True, "size": large_size, "width": width,
            }])
        else:
            width = max(small_size * 0.35, m_small.horizontalAdvance(token))
            small_buf.append({
                "token": token, "large": False, "size": small_size, "width": width,
            })
    flush_small()
    return lines

def _safe_float(value, default=0.0):
    """float() that treats None/'' as missing (dict.get default is skipped when key exists with None)."""
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def _semantic_font_sizes(settings):
    """与 layout 一致的大小号像素尺寸（重点明显大于其余，但不过分夸张）。"""
    base = max(24, int(settings.get("font_size") or 86))
    large_ratio = _safe_float(settings.get("semantic_large_ratio"), 1.18)
    small_ratio = _safe_float(settings.get("semantic_small_ratio"), 0.78)
    large_size = max(28, int(round(base * max(1.05, min(1.35, large_ratio)))))
    small_size = max(20, int(round(base * max(0.65, min(0.92, small_ratio)))))
    if small_size >= large_size - 4:
        small_size = max(20, large_size - 12)
    return large_size, small_size

def semantic_stack_geometry(lines, settings):
    """把语义堆叠行居中摆到 1080x1920 画布，返回与 lines 同结构的几何信息。"""
    if not lines:
        return []
    large_size, small_size = _semantic_font_sizes(settings)
    family = str(settings.get("font") or "Arial")
    bold = caption_uses_bold_face(settings)
    letter = _safe_float(settings.get("letter_spacing"), 0)

    def make_metrics(size):
        font = QFont(family)
        font.setPixelSize(size)
        font.setBold(bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter)
        return QFontMetricsF(font)

    m_large = make_metrics(large_size)
    m_small = make_metrics(small_size)
    word_gap = _safe_float(settings.get("word_spacing"), 0)
    gap_large = max(2.0, m_large.horizontalAdvance(" ") + word_gap)
    gap_small = max(2.0, m_small.horizontalAdvance(" ") + word_gap)
    spacing = max(70, min(180, int(settings.get("line_spacing") or 118))) / 100.0

    line_heights = []
    for line in lines:
        if any(item.get("large") for item in line):
            line_heights.append(max(large_size * 1.05, m_large.height()) * spacing)
        else:
            line_heights.append(max(small_size * 1.15, m_small.height()) * spacing * 0.92)

    total_h = sum(line_heights)
    position = settings.get("position") or "画面中间"
    margin_v = _safe_float(settings.get("margin_v"), 250)
    if position == "顶部":
        top = margin_v
    elif position == "画面中间":
        top = max(80.0, 960.0 - total_h / 2.0)
    else:
        top = max(80.0, 1920.0 - margin_v - total_h)

    result = []
    y_cursor = top
    for line, height in zip(lines, line_heights):
        gap = gap_large if any(item.get("large") for item in line) else gap_small
        widths = [_safe_float(item.get("width"), 0) for item in line]
        total_w = sum(widths) + gap * max(0, len(widths) - 1)
        x_cursor = (1080.0 - total_w) / 2.0
        center_y = y_cursor + height / 2.0
        metrics = m_large if any(item.get("large") for item in line) else m_small
        baseline = center_y + metrics.ascent() / 2.0 - metrics.descent() / 2.0
        row = []
        for item, width in zip(line, widths):
            row.append({
                **item,
                "left": x_cursor,
                "x": x_cursor + width / 2.0,
                "y": center_y,
                "baseline": baseline,
                "width": width,
            })
            x_cursor += width + gap
        result.append(row)
        y_cursor += height
    return result

def caption_layout_context(settings):
    """Canonical 1080x1920 caption metrics shared by live preview and ASS.

    Always resolve QFontInfo.family() first so word widths match the face
    libass will load (requested name like \"Arial Black\" may map elsewhere).
    """
    requested = str(settings.get("font") or "Arial")
    font_size = max(1, int(settings.get("font_size") or 76))
    bold = caption_uses_bold_face(settings)
    letter = _safe_float(settings.get("letter_spacing"), 0)
    font = QFont(requested)
    font.setPixelSize(font_size)
    font.setBold(bold)
    try:
        resolved = QFontInfo(font).family()
        if resolved and resolved.casefold() != requested.casefold():
            font = QFont(resolved)
            font.setPixelSize(font_size)
            font.setBold(bold)
    except Exception:
        pass
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter)
    metrics = QFontMetricsF(font)
    # Word spacing is independent from glyph/letter spacing.  Negative values
    # intentionally remain negative so the control still changes the final
    # geometry after the natural space has reached zero.
    gap = max(-font_size * 1.25, metrics.horizontalAdvance(" ") + _safe_float(settings.get("word_spacing"), 0))
    line_gap = max(font_size, metrics.height()) * max(70, min(180, int(settings.get("line_spacing") or 116))) / 100
    max_width = 1080 * max(40, min(96, int(settings.get("line_width") or 86))) / 100
    return font, metrics, gap, line_gap, max_width

def caption_uses_bold_face(settings):
    # Caption presets are designed as bold treatments. Qt and libass both use
    # weight 700 here; static Bold files are preferred, while variable fonts
    # can still provide/synthesise the same weight until upgraded.
    family=str(settings.get("font",""))
    static_name=STATIC_BOLD_FONT_FILES.get(family)
    if static_name:
        # Old releases downloaded variable/regular files.  On Windows libass
        # resolves those as Regular even when ASS requests weight 700.  Until a
        # static Bold face is present, use Regular in both Qt and libass rather
        # than previewing one face and exporting another.
        return any((folder/static_name).is_file() for folder in (custom_font_dir(),bundled_font_dir()))
    return True

def caption_wrapped_lines(text,settings,fixed_all=False,context=None):
    context=context or caption_layout_context(settings); _font,metrics,gap,_line_gap,max_width=context
    if fixed_all and "\n" in text:
        return [tokens_for(line) for line in text.splitlines() if tokens_for(line)]
    lines=[]; current=[]
    for token in tokens_for(text):
        candidate=" ".join(current+[token])
        width=sum(metrics.horizontalAdvance(value) for value in current+[token])+gap*len(current)
        if current and (len(candidate)>int(settings.get("line_length") or 18) or width>max_width):
            lines.append(current); current=[token]
        else:
            current.append(token)
    if current: lines.append(current)
    return lines

def caption_page_geometry(lines,settings,context=None):
    """Return stable token centers/baselines in the common 1080x1920 canvas."""
    context=context or caption_layout_context(settings); _font,metrics,gap,line_gap,_max_width=context
    position=settings.get("position") or "底部"
    margin_v=_safe_float(settings.get("margin_v"),250)
    if position=="顶部": center_y=margin_v+line_gap*(len(lines)-1)/2
    elif position=="画面中间": center_y=960.0
    else: center_y=1920-margin_v-line_gap*(len(lines)-1)/2
    result=[]
    font_size=_safe_float(settings.get("font_size"),76)
    for line_index,tokens in enumerate(lines):
        # 用真实字宽，禁止用 font_size*0.55 虚高撑宽——否则预览/导出词间距都会被拉开
        widths=[max(2.0, metrics.horizontalAdvance(token)) for token in tokens]
        total=sum(widths)+gap*max(0,len(widths)-1); cursor=(1080-total)/2
        y=center_y+(line_index-(len(lines)-1)/2)*line_gap
        baseline=y+metrics.ascent()/2-metrics.descent()/2
        items=[]
        for token,width in zip(tokens,widths):
            items.append({"token":token,"left":cursor,"width":width,"x":cursor+width/2,
                          "y":y,"baseline":baseline})
            cursor+=width+gap
        result.append(items)
    return result

def resolve_caption_preset(settings) -> dict:
    """Resolve effect/style preset for live preview + ASS.

    Custom saved presets may keep a display name that is not in PRESETS; fall back
    to base_preset / effect fields so semantic_stack etc. survive save→reload.
    """
    settings = settings or {}
    name = str(settings.get("preset") or "")
    if name in ("Reels 白字柔影", "Reels 重点放大"):
        name = "Reels 语义重点"
    base_name = str(settings.get("base_preset") or "")
    if base_name in ("Reels 白字柔影", "Reels 重点放大"):
        base_name = "Reels 语义重点"
    builtin = PRESETS.get(name) or PRESETS.get(base_name)
    if builtin:
        merged = dict(builtin)
    else:
        merged = dict(next(iter(PRESETS.values())))
    # Overlay effect / semantic knobs from custom snapshot
    effect = settings.get("effect")
    if effect:
        merged["effect"] = effect
    for key in (
        "semantic_large_ratio", "semantic_small_ratio", "semantic_lead_ms",
        "semantic_max_lines", "semantic_small_words",
    ):
        if key in settings and settings.get(key) not in (None, ""):
            merged[key] = settings[key]
    return merged

def ensure_font_in_render_dir(family):
    return None

def custom_font_dir():
    from app.services.app_paths import data_dir
    return data_dir() / 'fonts'

def bundled_font_dir():
    return Path(__file__).parent / 'fonts'
