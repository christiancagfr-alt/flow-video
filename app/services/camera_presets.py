import json
import uuid
from typing import List, Dict, Optional, Any
from app.core.database import connect

def ensure_tables(con=None):
    if con is None:
        with connect() as con:
            return ensure_tables(con)
    con.execute("""
        CREATE TABLE IF NOT EXISTS camera_presets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            rules TEXT,
            enabled INTEGER DEFAULT 1,
            is_default INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

def list_presets(include_disabled: bool = False) -> List[Dict[str, Any]]:
    query = "SELECT * FROM camera_presets"
    if not include_disabled:
        query += " WHERE enabled = 1"
    query += " ORDER BY sort_order ASC, created_at DESC"
    
    with connect() as con:
        con.row_factory = dict_factory
        rows = con.execute(query).fetchall()
        for r in rows:
            r['rules'] = json.loads(r['rules'] or '{}')
        return rows

def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    with connect() as con:
        con.row_factory = dict_factory
        row = con.execute("SELECT * FROM camera_presets WHERE id=?", (preset_id,)).fetchone()
        if row:
            row['rules'] = json.loads(row['rules'] or '{}')
        return row

def create_preset(data: Dict[str, Any]) -> Dict[str, Any]:
    new_id = str(uuid.uuid4())
    rules = json.dumps(data.get('rules', {}))
    with connect() as con:
        con.execute("""
            INSERT INTO camera_presets (id, name, description, rules, enabled, is_default)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            new_id,
            data.get('name', '新建运镜预设'),
            data.get('description', ''),
            rules,
            1, 0
        ))
    return get_preset(new_id)

def update_preset(preset_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    p = get_preset(preset_id)
    if not p: return None
    rules = json.dumps(data.get('rules', p['rules']))
    with connect() as con:
        con.execute("""
            UPDATE camera_presets
            SET name=?, description=?, rules=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (
            data.get('name', p['name']),
            data.get('description', p['description']),
            rules,
            preset_id
        ))
    return get_preset(preset_id)

def copy_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    p = get_preset(preset_id)
    if not p: return None
    p['name'] = f"{p['name']} (副本)"
    return create_preset(p)

def rename_preset(preset_id: str, new_name: str) -> bool:
    with connect() as con:
        res = con.execute("UPDATE camera_presets SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_name, preset_id))
        return res.rowcount > 0

def delete_preset(preset_id: str) -> bool:
    with connect() as con:
        res = con.execute("DELETE FROM camera_presets WHERE id=?", (preset_id,))
        return res.rowcount > 0

def toggle_preset(preset_id: str, enabled: bool) -> bool:
    with connect() as con:
        res = con.execute("UPDATE camera_presets SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (1 if enabled else 0, preset_id))
        return res.rowcount > 0

def set_default_preset(preset_id: str) -> bool:
    with connect() as con:
        con.execute("UPDATE camera_presets SET is_default=0")
        res = con.execute("UPDATE camera_presets SET is_default=1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (preset_id,))
        return res.rowcount > 0

def get_default_preset() -> Optional[Dict[str, Any]]:
    with connect() as con:
        con.row_factory = dict_factory
        row = con.execute("SELECT * FROM camera_presets WHERE is_default=1 LIMIT 1").fetchone()
        if not row:
            row = con.execute("SELECT * FROM camera_presets WHERE enabled=1 ORDER BY sort_order ASC LIMIT 1").fetchone()
        if row:
            row['rules'] = json.loads(row['rules'] or '{}')
        return row
