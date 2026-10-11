"""B-roll 预设持久化存储引擎。

预设使用唯一 UUID 作为主键，删除预设不影响历史任务（任务保存时
会同时保存预设 ID、名称和当前快照 JSON）。

软件关闭后预设不丢失，软件更新不覆盖用户数据。
"""
from __future__ import annotations

import copy
import json
import time
import uuid

from app.core.database import connect

# ── 预设默认模板 ──────────────────────────────────────────────

_DEFAULT_PRESET_TEMPLATE = {
    "name": "",
    "description": "",
    "visual": {
        "style": "",
        "tone": "",
        "lighting": "",
        "photography": "",
        "region": "",
    },
    "character_scene": {
        "character_requirement": "",
        "allowed_scenes": "",
        "forbidden_content": "",
    },
    "inheritance": {
        "mode": "auto",          # keep_character / inherit_visual / auto
        "character_consistency": "",
        "scene_consistency": "",
        "costume_consistency": "",
        "tone_consistency": "",
    },
    "broll_rules": {
        "default_limit": 2,
        "suggested_duration": 3.0,
        "allow_front_face": False,
        "allow_multi_person": False,
        "allow_complex_action": False,
    },
    "camera_moves": {
        "slow_push": False,
        "slow_pull": False,
        "pan_lr": False,
        "light_follow": False,
        "static": True,
        "custom": "",
    },
    "prompt_append": "",
    "prompt_forbid": "",
}

# ── 表初始化（由 database.init_db 调用） ────────────────────

def ensure_tables(con):
    """在已有连接上创建 B-roll 相关表（幂等）。"""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS broll_presets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            visual_json TEXT NOT NULL DEFAULT '{}',
            character_scene_json TEXT NOT NULL DEFAULT '{}',
            inheritance_json TEXT NOT NULL DEFAULT '{}',
            broll_rules_json TEXT NOT NULL DEFAULT '{}',
            camera_moves_json TEXT NOT NULL DEFAULT '{}',
            prompt_append TEXT NOT NULL DEFAULT '',
            prompt_forbid TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            is_default INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS video_enhancement (
            video_id INTEGER PRIMARY KEY,
            tier TEXT NOT NULL DEFAULT 'basic',
            camera_enabled INTEGER NOT NULL DEFAULT 0,
            camera_limit INTEGER NOT NULL DEFAULT 0,
            broll_enabled INTEGER NOT NULL DEFAULT 0,
            broll_limit INTEGER NOT NULL DEFAULT 0,
            broll_preset_id TEXT NOT NULL DEFAULT '',
            broll_preset_name TEXT NOT NULL DEFAULT '',
            broll_preset_snapshot TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS video_enhancement_plans (
            video_id TEXT PRIMARY KEY,
            video_plan TEXT NOT NULL DEFAULT '[]',
            image_plan TEXT NOT NULL DEFAULT '[]',
            broll_plan TEXT NOT NULL DEFAULT '[]',
            config_snapshot TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)


# ── 制作档位定义 ─────────────────────────────────────────────

TIERS = {
    "basic": {
        "label": "基础",
        "camera_enabled": False,
        "camera_limit": 0,
        "broll_enabled": False,
        "broll_limit": 0,
    },
    "light": {
        "label": "轻量增强",
        "camera_enabled": True,
        "camera_limit": 2,
        "broll_enabled": True,
        "broll_limit": 1,
    },
    "standard": {
        "label": "标准增强",
        "camera_enabled": True,
        "camera_limit": 4,
        "broll_enabled": True,
        "broll_limit": 2,
    },
    "premium": {
        "label": "精致制作",
        "camera_enabled": True,
        "camera_limit": 6,
        "broll_enabled": True,
        "broll_limit": 4,
    },
}

TIER_KEYS = list(TIERS.keys())
TIER_LABELS = {k: v["label"] for k, v in TIERS.items()}


def tier_defaults(tier_key):
    """返回指定档位的默认参数字典。"""
    t = TIERS.get(tier_key, TIERS["basic"])
    return {
        "tier": tier_key,
        "camera_enabled": t["camera_enabled"],
        "camera_limit": t["camera_limit"],
        "broll_enabled": t["broll_enabled"],
        "broll_limit": t["broll_limit"],
    }


# ── B-roll 预设 CRUD ────────────────────────────────────────

def _row_to_dict(row):
    """将 sqlite3.Row 转为干净字典。"""
    if not row:
        return None
    d = dict(row)
    for field in ("visual_json", "character_scene_json", "inheritance_json",
                  "broll_rules_json", "camera_moves_json"):
        try:
            d[field.replace("_json", "")] = json.loads(d.pop(field, "{}") or "{}")
        except (ValueError, TypeError):
            d[field.replace("_json", "")] = {}
    return d


def _serialize_preset(data):
    """从用户字典提取各字段用于 INSERT/UPDATE。"""
    return {
        "name": str(data.get("name") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "visual_json": json.dumps(data.get("visual") or {}, ensure_ascii=False),
        "character_scene_json": json.dumps(data.get("character_scene") or {}, ensure_ascii=False),
        "inheritance_json": json.dumps(data.get("inheritance") or {}, ensure_ascii=False),
        "broll_rules_json": json.dumps(data.get("broll_rules") or {}, ensure_ascii=False),
        "camera_moves_json": json.dumps(data.get("camera_moves") or {}, ensure_ascii=False),
        "prompt_append": str(data.get("prompt_append") or "").strip(),
        "prompt_forbid": str(data.get("prompt_forbid") or "").strip(),
        "enabled": 1 if data.get("enabled", True) else 0,
        "is_default": 1 if data.get("is_default", False) else 0,
        "sort_order": int(data.get("sort_order", 0)),
    }


def list_presets(*, include_disabled=False):
    """列出所有预设，按 sort_order 排序。"""
    with connect() as con:
        ensure_tables(con)
        if include_disabled:
            rows = con.execute(
                "SELECT * FROM broll_presets ORDER BY sort_order, created_at"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM broll_presets WHERE enabled=1 ORDER BY sort_order, created_at"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_preset(preset_id):
    """按 ID 获取单个预设。"""
    with connect() as con:
        ensure_tables(con)
        row = con.execute(
            "SELECT * FROM broll_presets WHERE id=?", (str(preset_id),)
        ).fetchone()
    return _row_to_dict(row)


def create_preset(data=None):
    """新建预设，返回新预设字典。"""
    d = copy.deepcopy(_DEFAULT_PRESET_TEMPLATE)
    if data:
        for k, v in data.items():
            if k in d and isinstance(d[k], dict) and isinstance(v, dict):
                d[k].update(v)
            else:
                d[k] = v
    preset_id = str(uuid.uuid4())
    if not d.get("name"):
        d["name"] = "新预设"
    fields = _serialize_preset(d)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as con:
        ensure_tables(con)
        max_order = con.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM broll_presets"
        ).fetchone()[0]
        con.execute(
            """INSERT INTO broll_presets
               (id, name, description, visual_json, character_scene_json,
                inheritance_json, broll_rules_json, camera_moves_json,
                prompt_append, prompt_forbid, enabled, is_default, sort_order,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (preset_id, fields["name"], fields["description"],
             fields["visual_json"], fields["character_scene_json"],
             fields["inheritance_json"], fields["broll_rules_json"],
             fields["camera_moves_json"], fields["prompt_append"],
             fields["prompt_forbid"], fields["enabled"], fields["is_default"],
             max_order + 1, now, now),
        )
    return get_preset(preset_id)


def update_preset(preset_id, data):
    """更新预设。只更新 data 中提供的字段。"""
    existing = get_preset(preset_id)
    if not existing:
        raise ValueError(f"预设 {preset_id} 不存在")
    merged = copy.deepcopy(existing)
    for k, v in data.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k].update(v)
        else:
            merged[k] = v
    fields = _serialize_preset(merged)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as con:
        ensure_tables(con)
        con.execute(
            """UPDATE broll_presets SET
               name=?, description=?, visual_json=?, character_scene_json=?,
               inheritance_json=?, broll_rules_json=?, camera_moves_json=?,
               prompt_append=?, prompt_forbid=?, enabled=?, is_default=?,
               sort_order=?, updated_at=?
               WHERE id=?""",
            (fields["name"], fields["description"],
             fields["visual_json"], fields["character_scene_json"],
             fields["inheritance_json"], fields["broll_rules_json"],
             fields["camera_moves_json"], fields["prompt_append"],
             fields["prompt_forbid"], fields["enabled"], fields["is_default"],
             fields["sort_order"], now, str(preset_id)),
        )
    return get_preset(preset_id)


def copy_preset(preset_id):
    """复制预设，返回新预设字典。"""
    existing = get_preset(preset_id)
    if not existing:
        raise ValueError(f"预设 {preset_id} 不存在")
    data = copy.deepcopy(existing)
    data["name"] = data["name"] + " (副本)"
    data["is_default"] = False
    for key in ("id", "created_at", "updated_at"):
        data.pop(key, None)
    return create_preset(data)


def rename_preset(preset_id, new_name):
    """重命名预设。"""
    return update_preset(preset_id, {"name": str(new_name).strip()})


def delete_preset(preset_id):
    """删除预设。不影响已有 video_enhancement 中的快照。"""
    with connect() as con:
        ensure_tables(con)
        con.execute("DELETE FROM broll_presets WHERE id=?", (str(preset_id),))


def toggle_preset(preset_id, enabled=True):
    """启用或停用预设。"""
    return update_preset(preset_id, {"enabled": bool(enabled)})


def set_default_preset(preset_id):
    """设置默认预设（只能有一个默认）。"""
    with connect() as con:
        ensure_tables(con)
        con.execute("UPDATE broll_presets SET is_default=0")
        con.execute(
            "UPDATE broll_presets SET is_default=1 WHERE id=?",
            (str(preset_id),),
        )


def get_default_preset():
    """获取当前默认预设。"""
    with connect() as con:
        ensure_tables(con)
        row = con.execute(
            "SELECT * FROM broll_presets WHERE is_default=1 AND enabled=1 LIMIT 1"
        ).fetchone()
    return _row_to_dict(row)


def preset_snapshot(preset_id):
    """生成预设快照 JSON 字符串，用于保存到任务中。"""
    p = get_preset(preset_id)
    if not p:
        return ""
    snapshot = copy.deepcopy(p)
    snapshot.pop("sort_order", None)
    snapshot.pop("created_at", None)
    snapshot.pop("updated_at", None)
    return json.dumps(snapshot, ensure_ascii=False)


# ── 视频增强设置 CRUD ────────────────────────────────────────

def get_video_enhancement(video_id):
    """获取单个完整视频的增强设置。"""
    with connect() as con:
        ensure_tables(con)
        row = con.execute(
            "SELECT * FROM video_enhancement WHERE video_id=?",
            (int(video_id),),
        ).fetchone()
    if row:
        return dict(row)
    return tier_defaults("basic")


def set_video_enhancement(video_id, data):
    """设置单个完整视频的增强参数。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    tier = str(data.get("tier", "basic"))
    camera_enabled = 1 if data.get("camera_enabled") else 0
    camera_limit = int(data.get("camera_limit", 0))
    broll_enabled = 1 if data.get("broll_enabled") else 0
    broll_limit = int(data.get("broll_limit", 0))
    broll_preset_id = str(data.get("broll_preset_id") or "")
    broll_preset_name = str(data.get("broll_preset_name") or "")
    snap = str(data.get("broll_preset_snapshot") or "")
    if broll_preset_id and not snap:
        snap = preset_snapshot(broll_preset_id)
    with connect() as con:
        ensure_tables(con)
        con.execute(
            """INSERT INTO video_enhancement
               (video_id, tier, camera_enabled, camera_limit,
                broll_enabled, broll_limit, broll_preset_id,
                broll_preset_name, broll_preset_snapshot,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(video_id) DO UPDATE SET
                tier=excluded.tier, camera_enabled=excluded.camera_enabled,
                camera_limit=excluded.camera_limit,
                broll_enabled=excluded.broll_enabled,
                broll_limit=excluded.broll_limit,
                broll_preset_id=excluded.broll_preset_id,
                broll_preset_name=excluded.broll_preset_name,
                broll_preset_snapshot=excluded.broll_preset_snapshot,
                updated_at=excluded.updated_at""",
            (int(video_id), tier, camera_enabled, camera_limit,
             broll_enabled, broll_limit, broll_preset_id,
             broll_preset_name, snap, now, now),
        )


def batch_set_enhancement(video_ids, data):
    """批量设置多个完整视频的增强参数。"""
    for vid in video_ids:
        set_video_enhancement(vid, data)
    return len(video_ids)


def list_video_enhancements(host_id):
    """列出一个主播下所有完整视频的增强设置。"""
    with connect() as con:
        ensure_tables(con)
        rows = con.execute(
            """SELECT v.id AS video_id, v.seq, v.image_path,
                      ve.tier, ve.camera_enabled, ve.camera_limit,
                      ve.broll_enabled, ve.broll_limit,
                      ve.broll_preset_id, ve.broll_preset_name
               FROM videos v
               LEFT JOIN video_enhancement ve ON ve.video_id = v.id
               WHERE v.host_id = ?
               ORDER BY v.seq""",
            (int(host_id),),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("tier") is None:
            d.update(tier_defaults("basic"))
        result.append(d)
    return result

def save_video_plan(video_id: str, video_plan: list, image_plan: list, broll_plan: list, config_snapshot: dict):
    import json
    with connect() as con:
        ensure_tables(con)
        con.execute('''
            INSERT INTO video_enhancement_plans (video_id, video_plan, image_plan, broll_plan, config_snapshot)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                video_plan=excluded.video_plan,
                image_plan=excluded.image_plan,
                broll_plan=excluded.broll_plan,
                config_snapshot=excluded.config_snapshot,
                created_at=CURRENT_TIMESTAMP
        ''', (
            video_id,
            json.dumps(video_plan, ensure_ascii=False),
            json.dumps(image_plan, ensure_ascii=False),
            json.dumps(broll_plan, ensure_ascii=False),
            json.dumps(config_snapshot, ensure_ascii=False)
        ))

def get_video_plan(video_id: str):
    import json
    with connect() as con:
        ensure_tables(con)
        row = con.execute("SELECT * FROM video_enhancement_plans WHERE video_id=?", (video_id,)).fetchone()
        if row:
            row = dict(row)
            return {
                "video_plan": json.loads(row["video_plan"] or "[]"),
                "image_plan": json.loads(row["image_plan"] or "[]"),
                "broll_plan": json.loads(row["broll_plan"] or "[]"),
                "config_snapshot": json.loads(row["config_snapshot"] or "{}")
            }
        return None
