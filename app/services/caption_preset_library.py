from __future__ import annotations

"""Data-driven caption preset library for Flow Studio video packaging.

Built-in presets are read from app/data/caption_presets/builtin/*.json.
User presets are stored outside the application bundle so upgrades do not
overwrite them.  On macOS the default folder is:
~/Library/Application Support/FlowStudio/caption_presets
"""

import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CaptionPreset:
    id: str
    name: str
    category: str
    tags: tuple[str, ...]
    description: str
    style: dict[str, Any]
    builtin: bool
    path: str = ""
    schema_version: int = SCHEMA_VERSION


class CaptionPresetLibrary:
    """Load, validate and manage caption presets without hard-coding UI choices."""

    DEFAULT_STYLE: dict[str, Any] = {
        "font": "Arial",
        "size": 54,
        "color": "#FFFFFF",
        "position": "底部居中",
        "weight": 800,
        "strokeColor": "#111111",
        "strokeWidth": 5,
        "background": False,
        "backgroundColor": "#000000",
        "backgroundOpacity": 0,
        "shadow": True,
        "shadowColor": "rgba(0,0,0,.9)",
        "shadowBlur": 10,
        "shadowY": 4,
        "radius": 16,
        "paddingX": 18,
        "paddingY": 10,
        "animation": "淡入",
        "maxWidth": 88,
        "lineHeight": 1.22,
        "letterSpacing": 0,
        "karaokeEnabled": False,
        "karaokeMode": "逐词高亮",
        "karaokeActiveColor": "#FFD54A",
        "karaokeReadColor": "#FFFFFF",
        "karaokeUnreadColor": "#C9C9C9",
        "karaokeActiveScale": 108,
        "karaokeTiming": "auto",
    }

    def __init__(self, builtin_dir: str | Path | None = None, user_dir: str | Path | None = None):
        root = Path(__file__).resolve().parents[1]
        self.builtin_dir = Path(builtin_dir) if builtin_dir else root / "data" / "caption_presets" / "builtin"
        self.user_dir = Path(user_dir) if user_dir else self.default_user_dir()
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self._presets: list[CaptionPreset] = []
        self._errors: list[str] = []
        self.reload()

    @staticmethod
    def default_user_dir() -> Path:
        override = os.environ.get("FLOWSTUDIO_CAPTION_PRESET_DIR", "").strip()
        if override:
            return Path(override).expanduser()
        home = Path.home()
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "FlowStudio" / "caption_presets"
        return home / ".flowstudio" / "caption_presets"

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors)

    @property
    def presets(self) -> tuple[CaptionPreset, ...]:
        return tuple(self._presets)

    def reload(self) -> tuple[CaptionPreset, ...]:
        self._errors = []
        loaded: list[CaptionPreset] = []
        for builtin, folder in ((True, self.builtin_dir), (False, self.user_dir)):
            folder.mkdir(parents=True, exist_ok=True)
            for path in sorted(folder.glob("*.json")):
                try:
                    preset = self._load_file(path, builtin=builtin)
                    loaded.append(preset)
                except Exception as exc:
                    self._errors.append(f"{path.name}: {exc}")
        # User preset with a matching id wins, enabling intentional user-side migration.
        by_id: dict[str, CaptionPreset] = {}
        for p in loaded:
            if p.id not in by_id or not p.builtin:
                by_id[p.id] = p
        self._presets = sorted(by_id.values(), key=lambda p: (p.category, 0 if p.builtin else 1, p.name.casefold()))
        return self.presets

    def _load_file(self, path: Path, builtin: bool) -> CaptionPreset:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("预设必须是 JSON 对象")
        version = int(raw.get("schemaVersion", 0) or 0)
        if version < 1:
            raise ValueError("缺少 schemaVersion")
        if version > SCHEMA_VERSION:
            raise ValueError(f"schemaVersion {version} 高于当前支持版本 {SCHEMA_VERSION}")
        pid = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not pid or not name:
            raise ValueError("缺少 id 或 name")
        style_raw = raw.get("style") or {}
        if not isinstance(style_raw, dict):
            raise ValueError("style 必须是对象")
        style = self.normalize_style(style_raw)
        return CaptionPreset(
            id=pid,
            name=name,
            category=str(raw.get("category") or "自定义").strip() or "自定义",
            tags=tuple(str(x).strip() for x in (raw.get("tags") or []) if str(x).strip()),
            description=str(raw.get("description") or "").strip(),
            style=style,
            builtin=builtin,
            path=str(path),
            schema_version=version,
        )

    @classmethod
    def normalize_style(cls, style: dict[str, Any]) -> dict[str, Any]:
        result = dict(cls.DEFAULT_STYLE)
        result.update(style or {})
        # Clamp common numeric values so hand-authored JSON cannot break the UI/render.
        def num(key, lo, hi, integer=False):
            try:
                v = float(result.get(key, cls.DEFAULT_STYLE.get(key, lo)))
            except Exception:
                v = float(cls.DEFAULT_STYLE.get(key, lo))
            v = max(lo, min(hi, v))
            result[key] = int(round(v)) if integer else v
        num("size", 18, 110, True)
        num("weight", 100, 900, True)
        num("strokeWidth", 0, 12, True)
        num("backgroundOpacity", 0, 100, True)
        num("shadowBlur", 0, 30, True)
        num("shadowY", 0, 20, True)
        num("radius", 0, 60, True)
        num("paddingX", 0, 80, True)
        num("paddingY", 0, 60, True)
        num("maxWidth", 50, 96, True)
        num("lineHeight", 0.9, 1.8, False)
        num("letterSpacing", -3, 12, True)
        num("karaokeActiveScale", 100, 140, True)
        for key in ("background", "shadow", "karaokeEnabled"):
            result[key] = bool(result.get(key, False))
        result["karaokeMode"] = str(result.get("karaokeMode") or "逐词高亮")
        result["karaokeTiming"] = str(result.get("karaokeTiming") or "auto")
        return result

    def categories(self) -> list[str]:
        preferred = ["基础", "短视频", "宗教", "卡拉OK", "自定义"]
        found = {p.category for p in self._presets}
        ordered = [x for x in preferred if x in found]
        ordered.extend(sorted(found.difference(ordered)))
        return ordered

    def filtered(self, category: str = "全部", query: str = "") -> list[CaptionPreset]:
        q = str(query or "").strip().casefold()
        out = []
        for p in self._presets:
            if category and category != "全部" and p.category != category:
                continue
            hay = " ".join((p.name, p.category, p.description, *p.tags)).casefold()
            if q and q not in hay:
                continue
            out.append(p)
        return out

    def get(self, preset_id_or_name: str) -> CaptionPreset | None:
        key = str(preset_id_or_name or "").strip()
        for p in self._presets:
            if p.id == key or p.name == key:
                return p
        return None

    @staticmethod
    def _slug(text: str) -> str:
        slug = re.sub(r"[^0-9A-Za-z_-]+", "-", text.strip()).strip("-").lower()
        return slug[:48] or "preset"

    def save_custom(self, *, name: str, style: dict[str, Any], category: str = "自定义",
                    description: str = "", tags: Iterable[str] = (), preset_id: str | None = None) -> CaptionPreset:
        name = str(name or "").strip()
        if not name:
            raise ValueError("预设名称不能为空")
        if preset_id:
            existing = self.get(preset_id)
            if existing and existing.builtin:
                raise ValueError("系统内置预设不能直接覆盖，请先复制为自定义预设")
            pid = preset_id
        else:
            pid = f"user.{self._slug(name)}.{uuid.uuid4().hex[:8]}"
        data = {
            "schemaVersion": SCHEMA_VERSION,
            "id": pid,
            "name": name,
            "category": str(category or "自定义").strip() or "自定义",
            "tags": [str(x).strip() for x in tags if str(x).strip()],
            "description": str(description or "").strip(),
            "style": self.normalize_style(style),
        }
        path = self.user_dir / f"{self._slug(name)}-{pid.rsplit('.', 1)[-1]}.json"
        # If updating an existing custom preset, keep its current file when possible.
        existing = self.get(pid)
        if existing and not existing.builtin and existing.path:
            path = Path(existing.path)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.reload()
        preset = self.get(pid)
        if not preset:
            raise RuntimeError("预设保存后未能重新加载")
        return preset

    def duplicate(self, preset_id_or_name: str, new_name: str | None = None) -> CaptionPreset:
        source = self.get(preset_id_or_name)
        if not source:
            raise KeyError("找不到要复制的预设")
        name = str(new_name or f"{source.name} 副本").strip()
        return self.save_custom(name=name, style=source.style, category="自定义",
                                description=source.description, tags=source.tags)

    def rename_custom(self, preset_id: str, new_name: str) -> CaptionPreset:
        source = self.get(preset_id)
        if not source:
            raise KeyError("找不到预设")
        if source.builtin:
            raise ValueError("系统内置预设不能重命名，请先复制")
        return self.save_custom(name=new_name, style=source.style, category=source.category,
                                description=source.description, tags=source.tags, preset_id=source.id)

    def delete_custom(self, preset_id: str) -> None:
        source = self.get(preset_id)
        if not source:
            raise KeyError("找不到预设")
        if source.builtin:
            raise ValueError("系统内置预设不能删除")
        if source.path:
            Path(source.path).unlink(missing_ok=True)
        self.reload()
