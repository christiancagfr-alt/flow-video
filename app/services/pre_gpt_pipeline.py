#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import hashlib
import io
import json
import logging
import logging.handlers
from functools import wraps
import mimetypes
import os
import sys
import re
import shutil
import sqlite3
from app.services import quiet_process as subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "Flow Studio · 任务中心前置准备"
VERSION = "0.13.5-integrated"
HOST = "127.0.0.1"
PORT = 17843
BASE_DIR = Path(__file__).resolve().parents[2]
from app.services.app_paths import data_dir
DATA_DIR = data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "pre_gpt_pipeline.sqlite3"
SETTINGS_FILE = DATA_DIR / "pre_gpt_pipeline_settings_legacy.json"
TOKEN_FILE = DATA_DIR / "google_token.json"
LOG_FILE = DATA_DIR / "pre_gpt_pipeline.log"

from app.core import repository as studio_repo
from app.core.database import connect as studio_connect
from app.services.text_processing import strip_decorative_symbols
from app.services.reflow_rules import prepare_configured_speech as prepare_swahili_speech
from app.services.file_filters import is_ignored_system_path, is_valid_local_image

START_MARKER = "批量制作中"
END_MARKER = "批量已完成"
READ_HEADERS = ["需求人员", "主播名称", "中文内容", "外文内容", "需求说明", "主播图片链接"]
WRITE_HEADERS = ["作者", "制作情况"]
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8"), logging.NullHandler()],
)
log = logging.getLogger("pre-gpt-pipeline")


def norm(v):
    return re.sub(r"\s+", "", str(v or "")).strip()


def safe_name(s, fallback="unnamed"):
    s = str(s or "").strip()
    s = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:100] or fallback


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def col_letter(idx0):
    n = idx0 + 1
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def parse_sheet_url(url):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url.strip())
    if not m:
        raise ValueError("无法识别 Google Sheet ID，请填写完整 Google 表格链接。")
    sid = m.group(1)
    gid = "0"
    p = urllib.parse.urlparse(url.strip())
    q = urllib.parse.parse_qs(p.query)
    if q.get("gid"):
        gid = q["gid"][0]
    else:
        m2 = re.search(r"(?:^|[&#])gid=(\d+)", p.fragment or "")
        if m2:
            gid = m2.group(1)
    return sid, gid


def parse_drive_folder_id(url):
    u = str(url or "").strip()
    patterns = [
        r"/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)",
        r"/folders/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, u)
        if m:
            return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{15,}", u):
        return u
    raise ValueError(f"无法识别 Google Drive 文件夹 ID：{u}")


def export_csv_url(sid, gid):
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"


def fetch_csv(url, timeout=30):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Mozilla/5.0 FlowStudioPreGPT/{VERSION}", "Accept": "text/csv,*/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(30*1024*1024+1)
        if len(raw)>30*1024*1024:raise ValueError("表格下载超过 30 MB")
        status = getattr(r, "status", 200)
        ctype = r.headers.get("Content-Type", "")
    return status, ctype, raw


def decode_bytes(raw):
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def find_header(rows, max_rows=80):
    wanted = {norm(x) for x in READ_HEADERS}
    best = (0, None)
    for i, row in enumerate(rows[:max_rows]):
        cells = {norm(c) for c in row if norm(c)}
        hits = len(wanted & cells)
        if hits > best[0]:
            best = (hits, i)
        if hits == len(wanted):
            return i
    if best[0] >= 4:
        return best[1]
    raise ValueError("未找到有效表头，需要识别：" + "、".join(READ_HEADERS))


def header_map(row):
    return {norm(v): i for i, v in enumerate(row) if norm(v)}


def classify_requirement(req):
    # 已确认规则：只有明确出现“闭眼”才是 PRAYING；其他全部 TALKING。
    return "PRAYING" if "闭眼" in str(req or "") else "TALKING"


def parse_sheet_rows(rows, spec=None):
    from app.services.sheet_columns import MODE_CUSTOM, load_spec
    spec = spec or load_spec()
    if spec.get('mode') == MODE_CUSTOM:
        return _parse_custom_rows(rows, spec)
    return _parse_template_rows(rows)


def _parse_template_rows(rows):
    hidx = find_header(rows)
    hmap = header_map(rows[hidx])
    # Task source contract: anchor material links always come from column J.
    hmap[norm("主播图片链接")] = 9
    missing = [h for h in READ_HEADERS if norm(h) not in hmap]
    if missing:
        raise ValueError("缺少必要表头：" + "、".join(missing))

    # 从表头下一行开始向下读，先找“批量制作中”，再继续向下，遇到“批量已完成”立即停止。
    start = None
    end = None
    for ri in range(hidx + 1, len(rows)):
        exact = {norm(c) for c in rows[ri] if norm(c)}
        if start is None:
            if norm(START_MARKER) in exact:
                start = ri
                log.info("命中起始标记 %s：第 %d 行", START_MARKER, ri + 1)
            continue
        if norm(END_MARKER) in exact:
            end = ri
            log.info("命中结束标记 %s：第 %d 行；停止继续读取", END_MARKER, ri + 1)
            break

    if start is None:
        raise ValueError(f"未找到“{START_MARKER}”")
    if end is None:
        raise ValueError(f"找到“{START_MARKER}”后未找到“{END_MARKER}”")

    tasks = []
    for ri in range(start + 1, end):
        row = rows[ri]
        t = {"表格行号": ri + 1}
        for h in READ_HEADERS:
            ci = hmap[norm(h)]
            t[h] = (row[ci] if h in ("中文内容", "外文内容") else row[ci].strip()) if ci < len(row) else ""
        # 空说明/正常/睁眼/其他都为 TALKING；只有“闭眼”进 PRAYING。
        t["模式"] = classify_requirement(t.get("需求说明"))
        if any(norm(t.get(k, "")) for k in ("需求人员", "主播名称", "中文内容", "外文内容", "主播图片链接")):
            tasks.append(t)

    opt_map = {}
    for h in WRITE_HEADERS:
        if norm(h) in hmap:
            opt_map[h] = hmap[norm(h)]

    return {
        "header_row": hidx + 1,
        "start_row": start + 1,
        "end_row": end + 1,
        "tasks": tasks,
        "header_map": {h: hmap[norm(h)] for h in READ_HEADERS},
        "write_header_map": opt_map,
    }


def _cell(row, index, keep_spacing):
    if index is None or index >= len(row):
        return ''
    value = row[index]
    return value if keep_spacing else str(value).strip()


def _parse_custom_rows(rows, spec):
    """Read the task block from the columns the user picked. Header names are optional."""
    from app.services.sheet_columns import custom_problem, normalize_date, resolve_columns
    problem = custom_problem(rows, spec)
    if problem:
        raise ValueError(problem)
    resolved = resolve_columns(rows, spec)
    start = None
    end = None
    for ri, row in enumerate(rows):
        exact = {norm(c) for c in row if norm(c)}
        if start is None:
            if norm(START_MARKER) in exact:
                start = ri
                log.info("命中起始标记 %s：第 %d 行", START_MARKER, ri + 1)
            continue
        if norm(END_MARKER) in exact:
            end = ri
            log.info("命中结束标记 %s：第 %d 行；停止继续读取", END_MARKER, ri + 1)
            break
    if start is None:
        raise ValueError(f"未找到“{START_MARKER}”")
    if end is None:
        raise ValueError(f"找到“{START_MARKER}”后未找到“{END_MARKER}”")

    tasks = []
    for ri in range(start + 1, end):
        row = rows[ri]
        task = {"表格行号": ri + 1}
        for header in READ_HEADERS:
            task[header] = _cell(row, resolved.get(header), header in ("中文内容", "外文内容"))
        task["日期"] = normalize_date(_cell(row, resolved.get("日期"), False))
        task["模式"] = classify_requirement(task.get("需求说明"))
        if any(norm(task.get(key, "")) for key in ("需求人员", "主播名称", "中文内容", "外文内容", "主播图片链接")):
            tasks.append(task)
    header = {key: resolved[key] for key in READ_HEADERS if resolved.get(key) is not None}
    write_map = {key: resolved[key] for key in WRITE_HEADERS if resolved.get(key) is not None}
    return {
        "header_row": start + 1,
        "start_row": start + 1,
        "end_row": end + 1,
        "tasks": tasks,
        "header_map": header,
        "write_header_map": write_map,
    }


def init_db():
    con = sqlite3.connect(DB_FILE)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS image_path_aliases(old_path TEXT PRIMARY KEY,new_path TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_source_styles(task_id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS production_links(task_id INTEGER PRIMARY KEY, video_id INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS intake_view_state(day TEXT PRIMARY KEY, hidden INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spreadsheet_id TEXT NOT NULL,
            gid TEXT NOT NULL,
            sheet_row INTEGER NOT NULL,
            recipient TEXT,
            anchor_name TEXT,
            chinese_text TEXT,
            foreign_text TEXT,
            requirement TEXT,
            mode TEXT,
            drive_url TEXT,
            drive_folder_id TEXT,
            group_key TEXT,
            content_key TEXT NOT NULL DEFAULT '',
            status TEXT DEFAULT 'IMPORTED',
            matched_asset_path TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(spreadsheet_id, gid, sheet_row)
        );
        CREATE TABLE IF NOT EXISTS groups_tbl(
            group_key TEXT PRIMARY KEY,
            recipient TEXT,
            anchor_name TEXT,
            drive_url TEXT,
            drive_folder_id TEXT,
            local_dir TEXT,
            talking_count INTEGER DEFAULT 0,
            praying_count INTEGER DEFAULT 0,
            image_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'IMPORTED',
            message TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS assets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_key TEXT NOT NULL,
            drive_file_id TEXT,
            original_name TEXT,
            local_path TEXT,
            sha256 TEXT,
            mode TEXT,
            used INTEGER DEFAULT 0,
            matched_task_id INTEGER,
            UNIQUE(group_key, drive_file_id)
        );
        """
    )
    cols={r[1] for r in con.execute("PRAGMA table_info(tasks)").fetchall()}
    if "content_key" not in cols:
        con.execute("ALTER TABLE tasks ADD COLUMN content_key TEXT NOT NULL DEFAULT ''")
    if "sheet_date" not in cols:
        con.execute("ALTER TABLE tasks ADD COLUMN sheet_date TEXT NOT NULL DEFAULT ''")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_content_key ON tasks(spreadsheet_id,gid,content_key)")
    con.commit()
    return con


def default_settings():
    return {
        "sheet_url": studio_repo.get_setting("task_source_sheet_url", ""),
        "producer": studio_repo.default_creator(),
        "local_root": studio_repo.get_setting("task_asset_root", str(Path.home() / "Documents" / "FlowStudio" / "TaskAssets")),
        "oauth_client_path": studio_repo.get_setting("google_oauth_client_path", ""),
    }


def load_settings():
    # Integrated build: the System Settings page is authoritative.
    s = default_settings()
    if SETTINGS_FILE.exists():
        try:
            legacy = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for k, v in legacy.items():
                if not s.get(k) and v:
                    s[k] = v
        except Exception:
            log.exception("读取旧版前置模块设置失败")
    return s


def save_settings(s):
    if "sheet_url" in s:
        studio_repo.set_setting("task_source_sheet_url", str(s.get("sheet_url") or "").strip())
    if "producer" in s:
        studio_repo.set_default_creator(str(s.get("producer") or "").strip())
    if "local_root" in s:
        studio_repo.set_setting("task_asset_root", str(s.get("local_root") or "").strip())
    if "oauth_client_path" in s:
        studio_repo.set_setting("google_oauth_client_path", str(s.get("oauth_client_path") or "").strip())
    SETTINGS_FILE.write_text(json.dumps({
        "sheet_url": studio_repo.get_setting("task_source_sheet_url", ""),
        "producer": studio_repo.default_creator(),
        "local_root": studio_repo.get_setting("task_asset_root", ""),
        "oauth_client_path": studio_repo.get_setting("google_oauth_client_path", ""),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def make_group_key(recipient, anchor):
    """主播任务组唯一身份：需求人员 + 主播名称。Drive 链接不参与主播身份。"""
    raw = f"{norm(recipient)}\n{norm(anchor)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def task_content_key(recipient, anchor, chinese, foreign):
    raw='\n'.join([norm(recipient),norm(anchor),norm(chinese),norm(foreign)])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]


def import_tasks(parsed, sid, gid):
    """幂等同步当前有效区间。

    - 同一 Sheet 行只更新，不重复插入。
    - 主播组只按“需求人员 + 主播名称”建立。
    - 同一主播出现多个不同 Drive 文件夹时，不拆组，标记冲突等待人工检查。
    - 保留离开任务区间的源记录及生产关联，按稳定内容身份处理移动与交换行。
    """
    now = datetime.now().isoformat(timespec="seconds")
    con = init_db()
    try:
        imported = 0
        updated = 0
        unchanged = 0
        groups = {}
        active_rows = set()
        con.execute("BEGIN IMMEDIATE")
        # Stage row positions to allow arbitrary row swaps without losing task IDs.
        prior = con.execute("SELECT recipient,anchor_name,chinese_text,foreign_text,requirement,mode,drive_url,drive_folder_id,group_key,content_key,sheet_row,id FROM tasks WHERE spreadsheet_id=? AND gid=? ORDER BY id", (sid,gid)).fetchall()
        with studio_connect() as main:
            for old_task in prior:
                legacy_key=_source_task_key(sid,gid,old_task[9])
                old_link=main.execute("SELECT video_id FROM source_tasks WHERE source_task_id=? AND source_row=?",(legacy_key,str(old_task[10]))).fetchone()
                if old_link and old_link[0]:
                    con.execute("INSERT OR IGNORE INTO production_links(task_id,video_id) VALUES(?,?)",(old_task[11],old_link[0]))
        used_ids=set()
        con.execute("UPDATE tasks SET sheet_row=-id WHERE spreadsheet_id=? AND gid=?", (sid,gid))
    
        for t in parsed["tasks"]:
            sheet_row = int(t["表格行号"])
            active_rows.add(sheet_row)
            recipient = t["需求人员"].strip()
            anchor = t["主播名称"].strip()
            drive_url = t["主播图片链接"].strip()
            foreign_text = t["外文内容"]
            if not anchor or not foreign_text:
                log.warning("Sheet第%d行字段不完整：主播=%r 外文=%r", sheet_row, anchor, foreign_text[:30])
    
            try:
                folder_id = parse_drive_folder_id(drive_url) if drive_url else ""
            except Exception:
                folder_id = ""
    
            gkey = make_group_key(recipient, anchor)
            content_key = task_content_key(recipient, anchor, t['中文内容'], foreign_text)
            signature = (
                recipient, anchor, t["中文内容"], foreign_text, t["需求说明"], t["模式"],
                drive_url, folder_id, gkey
            )
            matches=[r for r in prior if r[11] not in used_ids and r[9]==content_key and r[5]==t["模式"]]
            old=next((r for r in matches if r[10]==sheet_row), matches[0] if matches else None)
            # A corrected mode is metadata, not a new source task. Preserve the
            # durable identity only for the same content at the same source row.
            if old is None:
                old=next((r for r in prior if r[11] not in used_ids and r[9]==content_key and r[10]==sheet_row),None)
            moved=bool(old and old[10]!=sheet_row)
            if old:
                old_sig=tuple(old[:9])
                old_row=-int(old[11]);used_ids.add(old[11])
                if old_sig == signature and not moved:
                    con.execute("UPDATE tasks SET sheet_row=? WHERE id=?",(sheet_row,old[11]))
                    unchanged += 1
                else:
                    con.execute(
                        """UPDATE tasks SET sheet_row=?,recipient=?,anchor_name=?,chinese_text=?,foreign_text=?,requirement=?,mode=?,drive_url=?,drive_folder_id=?,group_key=?,content_key=?,updated_at=?,created_at=CASE WHEN content_key<>? THEN ? ELSE created_at END
                           WHERE spreadsheet_id=? AND gid=? AND sheet_row=?""",
                        (sheet_row,) + signature + (content_key,now,content_key,now,sid,gid,old_row),
                    )
                    updated += 1
            else:
                con.execute(
                    """INSERT INTO tasks(spreadsheet_id,gid,sheet_row,recipient,anchor_name,chinese_text,foreign_text,requirement,mode,drive_url,drive_folder_id,group_key,content_key,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'IMPORTED',?,?)""",
                    (sid, gid, sheet_row) + signature + (content_key, now, now),
                )
                imported += 1
            con.execute(
                "UPDATE tasks SET sheet_date=? WHERE spreadsheet_id=? AND gid=? AND sheet_row=?",
                (str(t.get("日期") or ""), sid, gid, sheet_row),
            )
    
            if '_source_styles' in t:
                task_id = con.execute('SELECT id FROM tasks WHERE spreadsheet_id=? AND gid=? AND sheet_row=?', (sid,gid,sheet_row)).fetchone()[0]
                con.execute('INSERT INTO task_source_styles VALUES(?,?) ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload',
                            (task_id, json.dumps(t['_source_styles'], ensure_ascii=False)))
                link = con.execute('SELECT video_id FROM production_links WHERE task_id=?', (task_id,)).fetchone()
                if link:
                    from app.services.sheet_style import save_video
                    save_video(link[0], t['_source_styles'])

            g = groups.setdefault(gkey, {
                "recipient": recipient,
                "anchor": anchor,
                "drive_candidates": {},
            })
            if drive_url:
                canonical = folder_id or drive_url
                g["drive_candidates"][canonical] = {"drive_url": drive_url, "folder_id": folder_id}
    
        # Source rows leaving the sheet are retained, including their stable identity.
        con.execute("UPDATE intake_view_state SET hidden=0")
    
        settings = load_settings()
        root = Path(settings["local_root"]).expanduser()
        day = datetime.now().strftime("%Y-%m-%d")
        active_group_keys = set(groups)
    
        for gkey, g in groups.items():
            counts = dict(con.execute("SELECT mode,COUNT(*) FROM tasks WHERE group_key=? AND sheet_row>0 GROUP BY mode", (gkey,)).fetchall())
            local_dir = root / day / safe_name(g["recipient"], "未命名接收人") / safe_name(g["anchor"], "未命名主播")
            local_dir.mkdir(parents=True, exist_ok=True)
            candidates = list(g["drive_candidates"].values())
            if len(candidates) == 1:
                drive_url = candidates[0]["drive_url"]
                folder_id = candidates[0]["folder_id"]
                old_group = con.execute(
                    "SELECT drive_folder_id,talking_count,praying_count,status,message FROM groups_tbl WHERE group_key=?",
                    (gkey,),
                ).fetchone()
                if (old_group and str(old_group[0] or "") == str(folder_id or "")
                        and int(old_group[1] or 0) == int(counts.get("TALKING",0))
                        and int(old_group[2] or 0) == int(counts.get("PRAYING",0))
                        and str(old_group[3] or "") in {"READY_FOR_GPT","NEEDS_MANUAL_CLASSIFY","MATERIAL_SHORTAGE","ASSETS_DOWNLOADED"}):
                    status = str(old_group[3])
                    message = str(old_group[4] or "")
                else:
                    status = "IMPORTED"
                    message = "已读取任务，等待素材同步"
            elif len(candidates) == 0:
                drive_url = ""
                folder_id = ""
                status = "MATERIAL_LINK_MISSING"
                message = "主播图片链接为空，请检查表格"
            else:
                drive_url = ""
                folder_id = ""
                status = "DRIVE_LINK_CONFLICT"
                message = f"检测到 {len(candidates)} 个不同主播素材链接，请检查表格；不会拆成多个主播"
                log.warning("主播素材链接冲突：%s / %s -> %s", g["recipient"], g["anchor"], [x["drive_url"] for x in candidates])
    
            con.execute(
                """INSERT INTO groups_tbl(group_key,recipient,anchor_name,drive_url,drive_folder_id,local_dir,talking_count,praying_count,status,message,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(group_key) DO UPDATE SET recipient=excluded.recipient,anchor_name=excluded.anchor_name,drive_url=excluded.drive_url,drive_folder_id=excluded.drive_folder_id,local_dir=excluded.local_dir,talking_count=excluded.talking_count,praying_count=excluded.praying_count,status=excluded.status,message=excluded.message,updated_at=excluded.updated_at""",
                (gkey, g["recipient"], g["anchor"], drive_url, folder_id, str(local_dir), counts.get("TALKING",0), counts.get("PRAYING",0), status, message, now),
            )
        
        # Clean up stale groups that no longer have any active tasks in the sheet
        con.execute("DELETE FROM groups_tbl WHERE group_key NOT IN (SELECT DISTINCT group_key FROM tasks WHERE sheet_row > 0)")

    
        con.commit()
        return imported, updated, unchanged, list(groups.keys())
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def clear_current_tasks(bridge=None):
    from app.services.clear_day import clear_today
    return clear_today(bridge)


def google_creds(interactive=False, force_account_picker=False):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as e:
        raise RuntimeError("Google API 依赖未安装，请重新运行 run_mac.command。") from e
    from app.services.credential_file import load, save as save_token, CredentialStoreError

    creds = None
    if TOKEN_FILE.exists() and not force_account_picker:
        try:
            creds = Credentials.from_authorized_user_info(load(TOKEN_FILE), SCOPES)
        except CredentialStoreError as exc:
            log.error("系统凭据库不可用，已保留本地 Google 令牌文件：%s", exc)
            raise
        except Exception:
            log.exception("读取 Google token 失败，将要求重新授权")
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(TOKEN_FILE, creds.to_json())
            log.info("Google OAuth token 已自动刷新")
        except CredentialStoreError as exc:
            log.error("刷新后的 Google 令牌未能写入系统凭据库，原本地文件未替换：%s", exc)
            raise
        except Exception:
            log.exception("Google OAuth token 自动刷新失败")
            creds = None
    if creds and creds.valid:
        return creds
    if not interactive:
        return None

    settings = load_settings()
    cp = Path(settings.get("oauth_client_path", "")).expanduser()
    if not cp.exists():
        raise FileNotFoundError("尚未设置 Google OAuth 桌面客户端 JSON 文件。请先在设置里选择。")
    from app.services.google_oauth_config import load_desktop_config
    flow = InstalledAppFlow.from_client_config(load_desktop_config(cp), SCOPES)
    # select_account 强制出现账号选择器，避免误用浏览器里上一次登录的 Google 账号。
    prompt = "select_account consent" if force_account_picker else "consent"
    creds = flow.run_local_server(port=0, open_browser=True, prompt=prompt, authorization_prompt_message="请在浏览器中完成 Google 授权。")
    save_token(TOKEN_FILE, creds.to_json())
    log.info("Google OAuth 授权成功，token 已保存：%s", TOKEN_FILE)
    return creds


_google_resources = threading.local()


def close_google_resources(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        previous = getattr(_google_resources, 'clients', None)
        clients = []
        _google_resources.clients = clients
        try:
            return fn(*args, **kwargs)
        finally:
            for client in reversed(clients):
                try: client.close()
                except Exception: pass
            clients.clear()
            _google_resources.clients = previous
    return run


def google_services(interactive=False, force_account_picker=False):
    creds = google_creds(interactive=interactive, force_account_picker=force_account_picker)
    if not creds:
        return None, None
    from googleapiclient.discovery import build
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    clients = getattr(_google_resources, 'clients', None)
    if clients is not None: clients.append(drive)
    try:
        sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    except Exception:
        drive.close()
        raise
    if clients is not None: clients.append(sheets)
    return drive, sheets


@close_google_resources
def google_account_info():
    """返回当前 OAuth 实际连接的 Google Drive 账号，便于核对私有文件夹权限。"""
    drive, _ = google_services(interactive=False)
    if not drive:
        return {"connected": False, "email": "", "display_name": ""}
    try:
        info = drive.about().get(fields="user(displayName,emailAddress,permissionId)").execute().get("user", {})
        return {
            "connected": True,
            "email": info.get("emailAddress", ""),
            "display_name": info.get("displayName", ""),
            "permission_id": info.get("permissionId", ""),
        }
    except Exception as e:
        log.exception("读取 Google 当前账号失败")
        return {"connected": True, "email": "", "display_name": "", "error": str(e)}


def disconnect_google():
    from app.services.credential_file import delete
    delete(TOKEN_FILE)
    log.warning("已清除 Google 登录令牌；下次将重新授权")
    return {"ok": True}

def resolve_sheet_title(sheets, sid, gid):
    meta = sheets.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(sheetId,title))").execute()
    igid = int(gid)
    for sh in meta.get("sheets", []):
        p = sh.get("properties", {})
        if int(p.get("sheetId", -1)) == igid:
            return p.get("title")
    raise ValueError(f"Google Sheets API 中找不到 gid={gid} 对应工作表")


@close_google_resources
def writeback_claim(parsed, sid, gid):
    settings = load_settings()
    producer = settings.get("producer", "").strip()
    if not producer:
        log.warning("未设置默认制作人，本次跳过作者/制作情况回写")
        return {"written": 0, "skipped": "未设置默认制作人"}
    wh = parsed.get("write_header_map") or {}
    if "作者" not in wh or "制作情况" not in wh:
        log.warning("表格缺少 作者/制作情况 表头，本次跳过回写")
        return {"written": 0, "skipped": "缺少作者/制作情况表头"}
    _, sheets = google_services(interactive=False)
    if not sheets:
        log.warning("尚未连接 Google OAuth，本次任务可读取，但无法回写作者/制作情况")
        return {"written": 0, "skipped": "未连接Google OAuth"}
    title = resolve_sheet_title(sheets, sid, gid).replace("'", "''")
    data = []
    for t in parsed["tasks"]:
        r = t["表格行号"]
        data.append({"range": f"'{title}'!{col_letter(wh['作者'])}{r}", "values": [[producer]]})
        data.append({"range": f"'{title}'!{col_letter(wh['制作情况'])}{r}", "values": [["制作中"]]})
    if not data:
        return {"written": 0}
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sid,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    log.info("已回写 %d 条任务：作者=%s，制作情况=制作中", len(parsed["tasks"]), producer)
    return {"written": len(parsed["tasks"])}


def _google_http_reason(exc):
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = ""
    try:
        payload = json.loads(exc.content.decode("utf-8", "ignore")) if getattr(exc, "content", None) else {}
        reason = payload.get("error", {}).get("message", "")
    except Exception:
        reason = str(exc)
    return status, reason or str(exc)


@close_google_resources
def download_drive_group(group_key, progress_callback=None):
    from googleapiclient.errors import HttpError
    _report_progress(progress_callback, 2, "连接 Google Drive", "正在检查 Google OAuth 与主播素材权限…")
    drive, _ = google_services(interactive=False)
    if not drive:
        raise RuntimeError("尚未连接 Google OAuth。请先点击“连接 Google”。")

    account = google_account_info()
    account_email = account.get("email") or "未知账号"
    con = init_db()
    g = con.execute("SELECT recipient,anchor_name,drive_folder_id,local_dir,talking_count,praying_count,status FROM groups_tbl WHERE group_key=?", (group_key,)).fetchone()
    if not g:
        con.close(); raise ValueError("找不到主播任务组")
    recipient, anchor, folder_id, local_dir, talk_n, pray_n, previous_status = g
    if not folder_id:
        con.close(); raise ValueError(f"主播 {anchor} 的表格单元格未检测到有效 Google Drive 链接")
    local_dir = Path(local_dir)
    source_dir = local_dir / "素材"
    source_dir.mkdir(parents=True, exist_ok=True)
    log.info("开始同步Drive素材：%s / %s folder=%s OAuth账号=%s", recipient, anchor, folder_id, account_email)
    _report_progress(progress_callback, 7, "检查主播素材", f"{recipient} · {anchor} · 正在验证 Drive 文件夹")

    # 先用 OAuth 身份直接验证文件夹是否可见/可读，避免把权限问题误报成“0张图片”。
    try:
        folder_meta = drive.files().get(
            fileId=folder_id,
            fields="id,name,mimeType,driveId,capabilities(canDownload),owners(emailAddress,displayName),shortcutDetails",
            supportsAllDrives=True,
        ).execute()
        log.info("Drive文件夹验证成功：name=%s mime=%s driveId=%s canDownload=%s canListChildren=%s",
                 folder_meta.get("name"), folder_meta.get("mimeType"), folder_meta.get("driveId"),
                 (folder_meta.get("capabilities") or {}).get("canDownload"),
                 "n/a")
        if folder_meta.get("mimeType") == "application/vnd.google-apps.shortcut":
            sd = folder_meta.get("shortcutDetails") or {}
            if sd.get("targetMimeType") == "application/vnd.google-apps.folder" and sd.get("targetId"):
                log.info("主播链接是Drive文件夹快捷方式，自动解析 targetId=%s", sd.get("targetId"))
                folder_id = sd.get("targetId")
                folder_meta = drive.files().get(fileId=folder_id, fields="id,name,mimeType,driveId", supportsAllDrives=True).execute()
        if folder_meta.get("mimeType") != "application/vnd.google-apps.folder":
            raise ValueError("主播图片链接指向的不是 Google Drive 文件夹。")
    except HttpError as e:
        status, reason = _google_http_reason(e)
        con.close()
        if status == 401:
            raise PermissionError(f"Google OAuth 登录已失效（401）。当前连接账号：{account_email}。请点击‘切换Google账号’重新授权。") from e
        if status == 403:
            raise PermissionError(f"Google Drive 权限不足（403）。当前连接账号：{account_email}。请确认这个邮箱拥有该主播文件夹的读取权限，或点击‘切换Google账号’。Google返回：{reason}") from e
        if status == 404:
            raise FileNotFoundError(f"Google Drive 文件夹不可见或不存在（404）。当前连接账号：{account_email}。如果文件夹只共享给指定邮箱，请切换到那个邮箱。") from e
        if status == 429:
            raise RuntimeError("Google Drive 请求过于频繁（429），请稍后重试。") from e
        raise

    _report_progress(progress_callback, 12, "读取主播素材", f"{recipient} · {anchor} · 正在列出 Drive 图片")
    files = []
    page_token = None
    try:
        while True:
            resp = drive.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken,files(id,name,mimeType,size,modifiedTime,md5Checksum,shortcutDetails)",
                pageSize=1000,
                pageToken=page_token,
                orderBy="name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            files.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except HttpError as e:
        status, reason = _google_http_reason(e)
        con.close()
        if status in (401,403,404):
            raise PermissionError(f"无法列出主播文件夹内容（HTTP {status}）。当前OAuth账号：{account_email}。Google返回：{reason}") from e
        raise

    # 支持 Drive 快捷方式：快捷方式指向图片时，下载真实 targetId。
    normalized = []
    for f in files:
        if f.get("mimeType") == "application/vnd.google-apps.shortcut":
            sd = f.get("shortcutDetails") or {}
            target_id = sd.get("targetId")
            target_mime = sd.get("targetMimeType")
            if target_id and (target_mime in IMAGE_MIMES or str(target_mime or "").startswith("image/")):
                nf = dict(f)
                nf["download_id"] = target_id
                nf["mimeType"] = target_mime
                normalized.append(nf)
            continue
        if f.get("mimeType") in IMAGE_MIMES or str(f.get("mimeType", "")).startswith("image/"):
            nf = dict(f); nf["download_id"] = f.get("id"); normalized.append(nf)
    image_files = sorted(
        (x for x in normalized if not is_ignored_system_path(Path(str(x.get("name") or "")))),
        key=lambda x: (x.get("name", "").lower(), x.get("id", ""))
    )
    log.info("Drive文件=%d，图片=%d，OAuth账号=%s", len(files), len(image_files), account_email)
    _report_progress(progress_callback, 18, "准备下载素材", f"{recipient} · {anchor} · 共 {len(image_files)} 张图片")

    remote_ids = {str(x.get("id") or "") for x in image_files if x.get("id")}
    existing_rows = con.execute("SELECT drive_file_id,local_path FROM assets WHERE group_key=?", (group_key,)).fetchall()
    existing_ids = {str(x[0] or "") for x in existing_rows
                    if x[0] and is_valid_local_image(Path(str(x[1] or "")).expanduser())}
    if str(previous_status or "") == "READY_FOR_GPT" and remote_ids == existing_ids:
        con.close()
        log.info("主播素材未变化且已 READY，跳过重新分类：%s / %s", recipient, anchor)
        _report_progress(progress_callback, 100, "主播素材已同步", f"{recipient} · {anchor} · 素材未变化，已沿用现有匹配")
        return {**reconcile_group(group_key), "unchanged": True}

    from googleapiclient.http import MediaIoBaseDownload
    total_images = max(1, len(image_files))
    for idx, fmeta in enumerate(image_files, 1):
        fid = fmeta["id"]
        download_id = fmeta.get("download_id") or fid
        name = safe_name(fmeta.get("name") or f"image_{idx}", f"image_{idx}")
        dest = source_dir / name
        existing = con.execute("SELECT local_path,sha256 FROM assets WHERE group_key=? AND drive_file_id=?", (group_key, fid)).fetchone()
        file_start = 20 + int(((idx - 1) / total_images) * 68)
        file_end = 20 + int((idx / total_images) * 68)
        _report_progress(progress_callback, file_start, "同步主播素材", f"{recipient} · {anchor} · 图片 {idx}/{len(image_files)}：{name}")
        if existing and is_valid_local_image(Path(existing[0]).expanduser()):
            log.info("[%d/%d] 已下载，跳过：%s", idx, len(image_files), name)
            _report_progress(progress_callback, file_end, "同步主播素材", f"{recipient} · {anchor} · 图片 {idx}/{len(image_files)} 已存在，跳过下载")
            continue
        if dest.exists():
            dest = source_dir / f"{Path(name).stem}__{fid[:8]}{Path(name).suffix}"
        try:
            request = drive.files().get_media(fileId=download_id, supportsAllDrives=True)
            with open(dest, "wb") as fh:
                dl = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)
                done = False
                while not done:
                    status_obj, done = dl.next_chunk()
                    if status_obj:
                        chunk_pct = float(status_obj.progress() or 0.0)
                        log.info("[%d/%d] 下载 %s %.0f%%", idx, len(image_files), name, chunk_pct * 100)
                        overall = file_start + int((file_end - file_start) * chunk_pct)
                        _report_progress(progress_callback, overall, "下载主播素材", f"{recipient} · {anchor} · 图片 {idx}/{len(image_files)}：{name} · {int(chunk_pct*100)}%")
        except HttpError as e:
            if dest.exists():
                try: dest.unlink()
                except Exception: pass
            status, reason = _google_http_reason(e)
            con.close()
            if status in (401,403,404):
                raise PermissionError(f"下载图片失败：{name}（HTTP {status}）。当前OAuth账号：{account_email}。Google返回：{reason}") from e
            raise
        digest = sha256_file(dest)
        con.execute(
            """INSERT INTO assets(group_key,drive_file_id,original_name,local_path,sha256,mode,used)
               VALUES(?,?,?,?,?,'UNCLASSIFIED',0)
               ON CONFLICT(group_key,drive_file_id) DO UPDATE SET original_name=excluded.original_name,local_path=excluded.local_path,sha256=excluded.sha256""",
            (group_key, fid, fmeta.get("name", ""), str(dest), digest),
        )
    con.execute("UPDATE groups_tbl SET image_count=?,status='ASSETS_DOWNLOADED',message=?,updated_at=? WHERE group_key=?",
                (len(image_files), f"已下载 {len(image_files)} 张图片", datetime.now().isoformat(timespec="seconds"), group_key))
    con.commit(); con.close()
    _report_progress(progress_callback, 94, "匹配主播素材", f"{recipient} · {anchor} · 正在按 TALKING / PRAYING 任务匹配图片")
    result = reconcile_group(group_key, auto_only=True)
    _report_progress(progress_callback, 100, "主播素材已同步", f"{recipient} · {anchor} · {result.get('message') or result.get('status') or '完成'}")
    return result

def move_file_preserve(path, target_dir):
    p = Path(path)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / p.name
    if dest.exists() and dest.resolve() != p.resolve():
        dest = target_dir / f"{p.stem}__{hashlib.sha1(str(p).encode()).hexdigest()[:6]}{p.suffix}"
    if p.exists() and p.resolve() != dest.resolve():
        shutil.move(str(p), str(dest))
    return str(dest)


def reconcile_group(group_key, auto_only=False, selected_closed=None):
    from app.services.material_assignment import image_mode, assign, reference_tasks, manual_modes
    con = init_db()
    try:
        g = con.execute('SELECT talking_count,praying_count FROM groups_tbl WHERE group_key=?', (group_key,)).fetchone()
        if not g: raise ValueError('找不到任务组')
        tasks = [dict(id=r[0], mode=r[1], asset=r[2]) for r in con.execute(
            'SELECT id,mode,matched_asset_path FROM tasks WHERE group_key=? AND sheet_row>0 ORDER BY sheet_row', (group_key,))]
        rows = con.execute('SELECT id,local_path,mode FROM assets WHERE group_key=? ORDER BY lower(original_name),id', (group_key,)).fetchall()
        rows = [r for r in rows if is_valid_local_image(Path(str(r[1] or '')).expanduser())]
        default = 'TALKING'
        manual = manual_modes(con)
        closed = {str(Path(p).resolve()) for p in selected_closed or []}
        files = [Path(r[1]).expanduser().resolve() for r in rows]
        modes = {p:('PRAYING' if str(p) in closed else image_mode(p,r[2],default,manual)) for p,r in zip(files,rows)}
        references = reference_tasks(tasks, modes)
        previous = {t['id']:Path(t['asset']).expanduser().resolve() for t in tasks if t['asset']}
        assigned = assign(references, files, modes, previous)
        missing = len(tasks)-len(assigned)
        status = 'MATERIAL_SHORTAGE' if missing else 'READY_FOR_GPT'
        if missing and files and any(t['mode']=='PRAYING' for t in tasks) and 'PRAYING' not in modes.values():
            status='NEEDS_MANUAL_CLASSIFY'
        message = f'已匹配 {len(assigned)}/{len(tasks)} 条文案，共 {len(files)} 张图片'
        if missing: message += f'；缺少 {missing} 张，可点击“随机补齐缺少的图片”'
        now = datetime.now().isoformat(timespec='seconds')
        for task in tasks:
            con.execute('UPDATE tasks SET matched_asset_path=?,status=?,updated_at=? WHERE id=?',
                        (str(assigned.get(task['id'],'')),status,now,task['id']))
        for path,row in zip(files,rows):
            con.execute('UPDATE assets SET mode=?,used=? WHERE id=?', (modes[path],int(path in assigned.values()),row[0]))
        con.execute('UPDATE groups_tbl SET image_count=?,status=?,message=?,updated_at=? WHERE group_key=?',
                    (len(files),status,message,now,group_key))
        con.commit()
        return dict(status=status,message=message,missing=missing)
    except Exception:
        con.rollback()
        raise
    finally: con.close()


def finder_open(group_key):
    con = init_db(); row = con.execute("SELECT local_dir FROM groups_tbl WHERE group_key=?", (group_key,)).fetchone(); con.close()
    if not row: raise ValueError("找不到任务组")
    p = Path(row[0]) / "素材"
    p.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        os.startfile(str(p))
    else:
        subprocess.run(["xdg-open" if sys.platform.startswith("linux") else "open", str(p)], check=False)
    log.info("已打开 Finder：%s", p)
    return str(p)


def finder_selection():
    if sys.platform.startswith('linux'):
        code="from PySide6.QtWidgets import QApplication,QFileDialog; a=QApplication([]); print('\\n'.join(QFileDialog.getOpenFileNames(None,'选择素材')[0]))"
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,encoding='utf-8',check=True)
        return result.stdout.splitlines()
    if os.name == 'nt':
        script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); $s = New-Object -ComObject Shell.Application; @($s.Windows()) | ForEach-Object { if ($_.FullName -like '*explorer.exe') { $_.Document.SelectedItems() | ForEach-Object { $_.Path } } }"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    script = r'''
    tell application "Finder"
        set theSelection to selection
        set outText to ""
        repeat with anItem in theSelection
            try
                set outText to outText & POSIX path of (anItem as alias) & linefeed
            end try
        end repeat
        return outText
    end tell
    '''
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("读取 Finder 当前选择失败：" + (p.stderr or p.stdout))
    return [x.strip() for x in p.stdout.splitlines() if x.strip()]


def choose_oauth_file():
    if os.name == 'nt' or __import__('sys').platform.startswith('linux'):
        # Run the native picker in its own GUI process, also safe from worker threads.
        code = "from PySide6.QtWidgets import QApplication, QFileDialog; app=QApplication([]); print(QFileDialog.getOpenFileName(None, 'Select credentials', '', 'JSON (*.json);;All files (*)')[0])"
        import sys
        python = str(Path(sys.executable).with_name('python.exe')) if os.name=='nt' else sys.executable
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        result = subprocess.run([python, '-c', code], capture_output=True, text=True, encoding='utf-8', env=env, check=True)
        return result.stdout.strip()
    script = r'''
    try
      set f to choose file with prompt "选择 Google OAuth 桌面客户端 JSON 文件"
      return POSIX path of f
    on error number -128
      return ""
    end try
    '''
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def choose_local_folder():
    if os.name == 'nt' or __import__('sys').platform.startswith('linux'):
        # Run the native picker in its own GUI process, also safe from worker threads.
        code = "from PySide6.QtWidgets import QApplication, QFileDialog; app=QApplication([]); print(QFileDialog.getExistingDirectory(None, 'Select folder'))"
        import sys
        python = str(Path(sys.executable).with_name('python.exe')) if os.name=='nt' else sys.executable
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        result = subprocess.run([python, '-c', code], capture_output=True, text=True, encoding='utf-8', env=env, check=True)
        return result.stdout.strip()
    script = r'''
    try
      set f to choose folder with prompt "选择 Flow Studio 任务素材根目录"
      return POSIX path of f
    on error number -128
      return ""
    end try
    '''
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def _report_progress(callback, percent, stage, detail=""):
    if callback is None:
        return
    try:
        callback(max(0, min(100, int(percent))), str(stage or ""), str(detail or ""))
    except Exception:
        log.exception("同步进度回调失败")


def share_group_links(tasks):
    """One J-column folder per recipient/anchor group, never across groups."""
    from app.services.sheet_links import extract_sheet_url
    groups = {}
    for task in tasks:
        groups.setdefault((task.get('需求人员','').strip(), task.get('主播名称','').strip()), []).append(task)
    for (recipient, anchor), members in groups.items():
        links = {}
        for task in members:
            raw = str(task.get('主播图片链接') or '').strip()
            if not raw: continue
            url = extract_sheet_url(raw)
            if not url:
                raise ValueError(f'{recipient} · {anchor}：J{task["表格行号"]} 无法读取链接；文字超链接请先连接 Google')
            folder = parse_drive_folder_id(url)
            if not folder: raise ValueError(f'{anchor}：J{task["表格行号"]} 不是有效素材文件夹链接')
            links.setdefault(folder, url)
        if not links: raise ValueError(f'{recipient} · {anchor}：任务组 J 列至少填写一个素材链接')
        if len(links)>1: raise ValueError(f'{recipient} · {anchor}：任务组 J 列存在多个不同素材文件夹，请保留一个')
        url = next(iter(links.values()))
        for task in members: task['主播图片链接'] = url
    return tasks


def scan_named_materials(group_key):
    """Scan the group's actual local files, including Finder-renamed downloads."""
    con=init_db()
    try:
        row=con.execute('SELECT local_dir FROM groups_tbl WHERE group_key=?',(group_key,)).fetchone()
        if not row: raise ValueError('找不到主播素材目录')
        from app.services.material_assignment import material_folder
        folder=material_folder(row[0])
        return sorted((p for p in folder.rglob('*') if is_valid_local_image(p)), key=lambda p:str(p))
    finally: con.close()


def confirm_named_materials(group_key, selected_closed=None):
    files=scan_named_materials(group_key)
    selected={Path(p).resolve() for p in selected_closed} if selected_closed is not None else None
    if selected is not None and not selected.issubset({p.resolve() for p in files}):raise ValueError('选择包含不属于该主播的图片，请刷新后重试')
    closed=[p for p in files if (p.resolve() in selected if selected is not None else '闭眼' in p.stem)]
    opened=[p for p in files if p not in closed]
    con=init_db()
    try:
        tasks=con.execute('SELECT id,mode FROM tasks WHERE group_key=? AND sheet_row>0 ORDER BY sheet_row',(group_key,)).fetchall()
        if any(t[1]=='PRAYING' for t in tasks) and not closed:raise ValueError('该主播有闭眼任务，请至少勾选一张闭眼图片')
        if not files:raise ValueError('没有可用图片')
        # Recover renamed paths by original content hash, retaining Drive file identities.
        assets=con.execute('SELECT id,local_path,sha256 FROM assets WHERE group_key=?',(group_key,)).fetchall()
        hashes={}
        for path in files: hashes.setdefault(sha256_file(path),[]).append(path)
        for aid,old,digest in assets:
            if not Path(old).is_file() and digest in hashes:
                new=hashes[digest].pop(0) if hashes[digest] else None
                if new:
                    con.execute('INSERT OR REPLACE INTO image_path_aliases(old_path,new_path) VALUES(?,?)',(str(Path(old).expanduser().absolute()),str(new.resolve())))
                    con.execute('UPDATE assets SET local_path=? WHERE id=?',(str(new),aid))
        indices={'PRAYING':0,'TALKING':0}
        for tid,mode in tasks:
            pool=closed if mode=='PRAYING' else (opened or closed)
            path=pool[indices[mode]%len(pool)];indices[mode]+=1
            con.execute("UPDATE tasks SET matched_asset_path=?,status='READY_FOR_GPT',updated_at=? WHERE id=?",(str(path),datetime.now().isoformat(timespec='seconds'),tid))
        for path in files:
            con.execute('UPDATE assets SET mode=? WHERE group_key=? AND local_path=?',('PRAYING' if path in closed else 'TALKING',group_key,str(path)))
        con.execute('CREATE TABLE IF NOT EXISTS manual_image_modes(group_key TEXT,path TEXT,mode TEXT,PRIMARY KEY(group_key,path))')
        for path in files:
            con.execute('INSERT OR REPLACE INTO manual_image_modes VALUES(?,?,?)',(group_key,str(path.resolve()),'PRAYING' if path in closed else 'TALKING'))
        message=f'已准备：识别闭眼图片 {len(closed)} 张，睁眼图片 {len(opened)} 张；同类任务按顺序共用素材'
        con.execute("UPDATE groups_tbl SET status='READY_FOR_GPT',image_count=?,message=? WHERE group_key=?",(len(files),message,group_key))
        con.commit();return {'status':'READY_FOR_GPT','message':message}
    finally:con.close()


@close_google_resources
def sync_sheet(progress_callback=None):
    _report_progress(progress_callback, 3, "连接任务表", "正在读取同步设置…")
    settings = load_settings()
    sheet_url = settings.get("sheet_url", "").strip()
    if not sheet_url:
        raise ValueError("请先在设置中填写 Google Sheet 任务表格链接")
    log.info("=" * 90)
    log.info("开始同步任务：%s", sheet_url)
    sid, gid = parse_sheet_url(sheet_url)
    url = export_csv_url(sid, gid)
    _report_progress(progress_callback, 8, "读取任务表", "正在从 Google Sheet 获取任务数据…")
    status, ctype, raw = fetch_csv(url)
    log.info("CSV HTTP=%s Content-Type=%s bytes=%d", status, ctype, len(raw))
    txt = decode_bytes(raw)
    if "<!doctype html" in txt[:5000].lower() or "accounts.google.com" in txt[:5000].lower():
        raise PermissionError("Google Sheet CSV 返回登录页面。请确认表格当前可由该链接读取；后续可扩展为 OAuth 读取。")
    _report_progress(progress_callback, 16, "解析任务表", f"已读取 {len(raw)} 字节，正在解析任务区间…")
    rows = list(csv.reader(io.StringIO(txt)))
    from app.services.sheet_columns import MODE_CUSTOM, load_spec, resolve_columns
    from app.services.sheet_links import overlay_sheet_links
    spec = load_spec()
    sheets = None
    title = ''
    try:
        _, sheets = google_services(interactive=False)
        title = resolve_sheet_title(sheets, sid, gid) if sheets else ''
        if spec.get('mode') == MODE_CUSTOM:
            image_column = resolve_columns(rows, spec).get('主播图片链接')
            link_columns = [] if image_column is None else [image_column]
            rows = overlay_sheet_links(rows, -1, sheets, sid, title, link_columns=link_columns)
        else:
            rows = overlay_sheet_links(rows, find_header(rows), sheets, sid, title)
    except Exception:
        log.exception('[SHEET_LINK_ERROR] 超链接元数据读取失败；保留原始 CSV，纯 URL 可继续使用')
        sheets = None
    parsed = parse_sheet_rows(rows, spec)
    from app.services.sheet_style import enrich
    enrich(sheets, sid, title if sheets else '', parsed)
    share_group_links(parsed['tasks'])
    _report_progress(progress_callback, 23, "解析任务表", f"发现 {len(parsed['tasks'])} 条有效任务")
    log.info("表头=%d；批量制作中=%d；批量已完成=%d；有效任务=%d", parsed["header_row"], parsed["start_row"], parsed["end_row"], len(parsed["tasks"]))
    _report_progress(progress_callback, 28, "写入任务中心", f"正在同步 {len(parsed['tasks'])} 条任务到本地数据库…")
    imported, updated, unchanged, group_keys = import_tasks(parsed, sid, gid)
    _report_progress(progress_callback, 36, "回写 Google Sheet", f"新增 {imported} · 更新 {updated} · 已存在 {unchanged}")
    wb = writeback_claim(parsed, sid, gid)
    _report_progress(progress_callback, 42, "任务表同步完成", f"已回写 {wb.get('written',0)} 行，准备同步主播素材…")
    try:
        studio_repo.record_sync_history(imported,updated,unchanged,'manual',{'start_row':parsed['start_row'],'end_row':parsed['end_row']})
    except Exception:
        pass
    return {"parsed": parsed, "imported": imported, "updated": updated, "unchanged": unchanged, "groups": group_keys, "writeback": wb}


def _view_hidden():
    from app.core import work_dates
    con=init_db()
    try:return bool(con.execute('SELECT 1 FROM intake_view_state WHERE day=? AND hidden=1',(work_dates.today(),)).fetchone())
    finally:con.close()


def list_groups():
    if _view_hidden():return []
    con = init_db()
    rows = con.execute("SELECT group_key,recipient,anchor_name,drive_url,local_dir,talking_count,praying_count,image_count,status,message,updated_at FROM groups_tbl ORDER BY recipient,anchor_name").fetchall()
    out = []
    for r in rows:
        out.append({"group_key":r[0],"recipient":r[1],"anchor_name":r[2],"drive_url":r[3],"local_dir":r[4],"talking":r[5],"praying":r[6],"images":r[7],"status":r[8],"message":r[9],"updated_at":r[10]})
    con.close(); return out


def list_tasks(group_key=None):
    if _view_hidden():return []
    con = init_db()
    q = "SELECT id,sheet_row,recipient,anchor_name,mode,chinese_text,foreign_text,matched_asset_path,status FROM tasks WHERE sheet_row>0"
    args = []
    if group_key:
        q += " AND group_key=?"; args=[group_key]
    q += " ORDER BY sheet_row"
    rows = con.execute(q,args).fetchall(); con.close()
    return [{"id":r[0],"sheet_row":r[1],"recipient":r[2],"anchor_name":r[3],"mode":r[4],"chinese":r[5],"foreign":r[6],"asset":r[7],"status":r[8]} for r in rows]


def _source_task_key(spreadsheet_id: str, gid: str, content_key: str='') -> str:
    return f"sheet:{spreadsheet_id}:{gid}:{content_key}" if content_key else f"sheet:{spreadsheet_id}:{gid}"


def promote_ready_to_studio(task_ids=None) -> dict:
    """Copy READY_FOR_GPT intake tasks into the main Flow Studio project database.

    Idempotent by durable intake task ID with legacy source-link recovery.
    Existing production records are never refreshed or replaced by synchronization.
    """
    con = init_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        rows = con.execute(
            """SELECT id,spreadsheet_id,gid,sheet_row,recipient,anchor_name,chinese_text,foreign_text,
                      mode,drive_url,matched_asset_path,status,content_key,created_at,sheet_date
                 FROM tasks WHERE status='READY_FOR_GPT' AND sheet_row>0 ORDER BY recipient,anchor_name,sheet_row"""
        ).fetchall()
        if task_ids is not None:
            selected_ids = {int(tid) for tid in task_ids}
            rows = [row for row in rows if row[0] in selected_ids]
        created = updated = skipped = 0
        today = datetime.now().strftime("%Y%m%d")
        fixed_code = studio_repo.get_setting("default_code", "ZB") or "ZB"
        creator = studio_repo.default_creator()
        for r in rows:
            task_id, sid, gid, sheet_row, recipient, anchor, chinese, foreign, mode, drive_url, asset_path, status, content_key, created_at, sheet_date = r
            source_task_id = _source_task_key(sid, gid, content_key)
            link = con.execute("SELECT video_id FROM production_links WHERE task_id=?", (task_id,)).fetchone()
            with studio_connect() as scon:
                old = {"video_id":link[0]} if link else scon.execute(
                    "SELECT video_id FROM source_tasks WHERE source_task_id=? AND source_row=?",
                    (source_task_id,str(sheet_row)),
                ).fetchone()
            if old and old['video_id']:
                con.execute("INSERT OR IGNORE INTO production_links(task_id,video_id) VALUES(?,?)",(task_id,old['video_id']))
            # Spoken-text preparation is deliberately inserted only here, between the immutable
            # source copy and the existing GPT/Flow production chain.
            try:
                max_chars = int(studio_repo.get_setting("default_wrap", "0") or 0)
            except (TypeError, ValueError):
                max_chars = 0
            prepared = prepare_swahili_speech(foreign or "", max_chars=max_chars or None)
            clean = prepared.spoken_text
            segments = list(prepared.segments) or ([clean] if clean.strip() else [])
            timing_meta = []
            for timing in prepared.timings:
                item = dict(timing)
                if prepared.timing_status == "UNSPLITTABLE" and item.get("needs_split"):
                    item["timing_status"] = "UNSPLITTABLE"
                elif prepared.timing_status == "INTEGRITY_FAILED":
                    item["timing_status"] = "INTEGRITY_FAILED"
                timing_meta.append(item)
            style_row = con.execute('SELECT payload FROM task_source_styles WHERE task_id=?', (task_id,)).fetchone()
            source_styles = json.loads(style_row[0]) if style_row else {}
            from app.services import eye_states
            eye_modes = []
            if source_styles.get('外文内容'):
                segments, eye_modes, timing_meta, clean = eye_states.prepare(
                    source_styles['外文内容'], lambda text: prepare_swahili_speech(text, max_chars=max_chars or None), mode)
            if old and old["video_id"]:
                # Source changes remain in intake; production IDs, text, images and all
                # downstream states are immutable to source synchronization.
                with studio_connect() as scon:
                    exists = scon.execute("SELECT id FROM videos WHERE id=?", (old["video_id"],)).fetchone()
                if exists:
                    if eye_modes:
                        from app.services.sheet_style import load_video
                        existing_style = load_video(old['video_id']).get('外文内容', {})
                        with studio_connect() as check:
                            original = check.execute('SELECT original_script FROM videos WHERE id=?', (old['video_id'],)).fetchone()
                        if original and original[0] == foreign and not existing_style.get('local_override'):
                            if studio_repo.sync_flow_segments(old['video_id'], segments, edit_unstarted=True, timing_meta=timing_meta):
                                eye_states.save_modes(old['video_id'], segments, eye_modes)
                    from app.services import selected_resubmission
                    changed=selected_resubmission.refresh_classification(old["video_id"],mode,asset_path,created_at)
                    if changed:updated += 1
                    else:skipped += 1
                    continue
            from app.core import work_dates
            from app.services.sheet_columns import task_work_day
            original_day=task_work_day(sheet_date, created_at)
            task_date=original_day.replace("-", "") if original_day else work_dates.LEGACY
            rid = studio_repo.find_or_create_recipient(recipient or "未命名接收人", fixed_code, creator, task_date)
            hid = studio_repo.find_or_create_host(rid, anchor or "未命名主播")
            video_id = studio_repo.add_video_to_host(
                hid, original_script=foreign or "", chinese=chinese or "",
                source_task_id=source_task_id, source_row=str(sheet_row), drive_url=drive_url or ""
            )
            with studio_connect() as scon:
                scon.execute(
                    """UPDATE videos SET image_path=?,asset_status='已准备',performance_mode=?,production_script=?,script=? WHERE id=?""",
                    (asset_path or "", mode or "TALKING", clean or foreign or "", clean or foreign or "", video_id),
                )
            style_row = con.execute('SELECT payload FROM task_source_styles WHERE task_id=?', (task_id,)).fetchone()
            if style_row:
                from app.services.sheet_style import save_video
                save_video(video_id, json.loads(style_row[0]))
            studio_repo.sync_flow_segments(video_id, segments, timing_meta=timing_meta)
            if eye_modes:
                eye_states.save_modes(video_id, segments, eye_modes)
            studio_repo.mark_source_task(source_task_id, str(sheet_row), video_id, "已导入")
            con.execute("INSERT INTO production_links(task_id,video_id) VALUES(?,?) ON CONFLICT(task_id) DO UPDATE SET video_id=excluded.video_id", (task_id,video_id))
            created += 1
        con.commit()
        log.info("READY -> Studio：新建 %d，更新 %d，跳过 %d", created, updated, skipped)
        return {"created": created, "updated": updated, "skipped": skipped}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def sync_download_and_prepare_all(progress_callback=None) -> dict:
    """Run the confirmed pre-GPT pipeline and continuously expose real progress to the desktop UI."""
    _report_progress(progress_callback, 0, "开始同步", "正在初始化任务同步…")
    sync_result = sync_sheet(progress_callback=progress_callback)
    download_results = []
    manual = []
    errors = []
    groups = list_groups()
    total_groups = len(groups)
    if total_groups == 0:
        _report_progress(progress_callback, 88, "素材同步", "当前没有主播素材组需要处理")
    for index, g in enumerate(groups, 1):
        group_start = 44 + int(((index - 1) / max(1, total_groups)) * 44)
        group_end = 44 + int((index / max(1, total_groups)) * 44)
        recipient = str(g.get("recipient") or "")
        anchor = str(g.get("anchor_name") or "")
        _report_progress(progress_callback, group_start, "同步主播素材", f"主播 {index}/{total_groups} · {recipient} · {anchor}")
        if g.get("status") == "DRIVE_LINK_CONFLICT":
            errors.append({"group_key": g["group_key"], "error": g.get("message", "")})
            _report_progress(progress_callback, group_end, "跳过素材冲突", f"主播 {index}/{total_groups} · {recipient} · {anchor}")
            continue
        try:
            def group_progress(local_pct, stage, detail, gs=group_start, ge=group_end, idx=index, total=total_groups):
                pct = gs + int((ge - gs) * (max(0, min(100, int(local_pct))) / 100.0))
                prefix = f"主播 {idx}/{total} · " if total else ""
                _report_progress(progress_callback, pct, stage, prefix + str(detail or ""))
            result = download_drive_group(g["group_key"], progress_callback=group_progress)
            download_results.append({"group_key": g["group_key"], **result})
            if result.get("status") == "NEEDS_MANUAL_CLASSIFY":
                manual.append({"group_key": g["group_key"], "required_closed": result.get("required_closed", 0)})
        except Exception as exc:
            log.exception("自动素材准备失败：%s / %s", g.get("recipient"), g.get("anchor_name"))
            errors.append({"group_key": g["group_key"], "error": str(exc)})
            _report_progress(progress_callback, group_end, "主播素材失败", f"主播 {index}/{total_groups} · {recipient} · {anchor} · {exc}")
    _report_progress(progress_callback, 91, "导入 Flow Studio", "正在把 READY FOR GPT 任务写入 Studio 主数据库…")
    promote = promote_ready_to_studio()
    _report_progress(progress_callback, 98, "刷新任务中心", f"新建 {promote.get('created',0)} · 更新 {promote.get('updated',0)}")
    _report_progress(progress_callback, 100, "同步完成", f"本轮共处理 {len(sync_result.get('parsed',{}).get('tasks',[]))} 条任务 · {total_groups} 个主播")
    return {"sync": sync_result, "downloads": download_results, "manual": manual, "errors": errors, "promote": promote}



HTML = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Flow Studio Pre-GPT</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial;background:#f4f7fb;color:#16213a;margin:0}.wrap{max-width:1320px;margin:24px auto;padding:0 18px}.card{background:#fff;border:1px solid #e4e9f2;border-radius:16px;box-shadow:0 8px 28px rgba(20,33,61,.055);padding:20px;margin-bottom:15px}.top{display:flex;justify-content:space-between;align-items:center}.muted{color:#6b7280}.btn{border:0;border-radius:10px;padding:10px 15px;font-size:14px;font-weight:650;cursor:pointer}.primary{background:#2563eb;color:#fff}.secondary{background:#eef2ff;color:#1d4ed8}.warn{background:#fff7ed;color:#9a3412}.danger{background:#fef2f2;color:#b91c1c}.ok{background:#ecfdf5;color:#065f46}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.field{margin:10px 0}.field label{display:block;font-size:13px;color:#475569;margin-bottom:5px}.field input{width:100%;box-sizing:border-box;padding:11px;border:1px solid #cbd5e1;border-radius:9px;font-size:14px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pill{display:inline-block;padding:4px 8px;border-radius:999px;font-size:12px;font-weight:700}.p-ready{background:#dcfce7;color:#166534}.p-manual{background:#fef3c7;color:#92400e}.p-error{background:#fee2e2;color:#991b1b}.p-normal{background:#e0e7ff;color:#3730a3}.groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.group{border:1px solid #e7ebf2;border-radius:13px;padding:14px}.group h3{margin:0 0 6px}.stat{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:10px 0}.mini{background:#f8fafc;border-radius:9px;padding:8px;text-align:center}.mini b{display:block;font-size:18px}.log{background:#0f172a;color:#d1fae5;border-radius:12px;padding:12px;height:240px;overflow:auto;white-space:pre-wrap;font:12px ui-monospace,SFMono-Regular,Menlo,monospace}.status{padding:10px 12px;border-radius:9px;background:#eef6ff;margin-top:9px;white-space:pre-wrap}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:8px;border-bottom:1px solid #eef2f7;text-align:left;vertical-align:top}.tablewrap{max-height:350px;overflow:auto;border:1px solid #eef2f7;border-radius:11px}@media(max-width:900px){.groups,.grid2{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div class="card"><div class="top"><div><h1 style="margin:0">Flow Studio · GPT前置任务准备</h1><div class="muted">Google Sheet → Drive主播素材 → 睁眼/闭眼分类 → 自动配图 → READY FOR GPT</div></div><div class="row"><button class="btn secondary" onclick="connectGoogle()">连接 Google</button><button class="btn warn" onclick="switchGoogle()">切换 Google 账号</button><button class="btn primary" onclick="syncAll()">同步任务</button><button class="btn danger" onclick="clearTasks(false)">清空当前任务</button><button class="btn warn" onclick="clearTasks(true)">清空并重新同步</button></div></div><div id="topstatus" class="status">等待操作…</div><div id="googleAccount" class="muted" style="margin-top:8px">Google账号：正在检测…</div></div>
<div class="card"><h2>设置</h2><div class="grid2"><div class="field"><label>Google Sheet 任务表格链接</label><input id="sheet_url"></div><div class="field"><label>默认制作人（回写“作者”列）</label><input id="producer"></div><div class="field"><label>本地任务素材根目录</label><div class="row"><input id="local_root" style="flex:1"><button class="btn secondary" onclick="pickRoot()">选择</button></div></div><div class="field"><label>Google OAuth 桌面客户端 JSON</label><div class="row"><input id="oauth_client_path" style="flex:1"><button class="btn secondary" onclick="pickOauth()">选择</button></div></div></div><button class="btn secondary" onclick="saveSettings()">保存设置</button></div>
<div class="card"><div class="top"><h2>主播任务组</h2><button class="btn secondary" onclick="refreshGroups()">刷新</button></div><div id="groups" class="groups"></div></div>
<div class="card"><h2>READY FOR GPT 任务</h2><div class="tablewrap"><table><thead><tr><th>Sheet行</th><th>接收人</th><th>主播</th><th>类型</th><th>外文文案</th><th>图片</th><th>状态</th></tr></thead><tbody id="tasks"></tbody></table></div></div>
<div class="card"><div class="top"><h2>详细运行日志</h2><button class="btn secondary" onclick="loadLog()">刷新日志</button></div><div id="log" class="log"></div></div>
</div><script>
function e(s){return String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function api(path,opt={}){let r=await fetch(path,opt);let d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'操作失败');return d}
async function loadSettings(){let s=await api('/api/settings');for(let k of ['sheet_url','producer','local_root','oauth_client_path'])document.getElementById(k).value=s[k]||''}
async function saveSettings(){let s={};for(let k of ['sheet_url','producer','local_root','oauth_client_path'])s[k]=document.getElementById(k).value.trim();await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(s)});status('设置已保存。','ok')}
function status(t,cl=''){let x=document.getElementById('topstatus');x.textContent=t;x.className='status '+cl}
async function pickOauth(){let d=await api('/api/pick-oauth',{method:'POST'});if(d.path){document.getElementById('oauth_client_path').value=d.path;await saveSettings()}}
async function pickRoot(){let d=await api('/api/pick-root',{method:'POST'});if(d.path){document.getElementById('local_root').value=d.path;await saveSettings()}}
async function refreshGoogleAccount(){try{let d=await api('/api/google-account');document.getElementById('googleAccount').textContent=d.connected?('Google账号：🟢 '+(d.email||d.display_name||'已连接')):'Google账号：🔴 未连接'}catch(e){document.getElementById('googleAccount').textContent='Google账号：状态读取失败'}}
async function connectGoogle(){try{await saveSettings();status('正在打开 Google 官方授权页面…');let d=await api('/api/connect-google',{method:'POST'});status('Google 已连接：'+(d.email||d.message),'ok');await refreshGoogleAccount()}catch(err){status('连接失败：'+err.message,'danger')}}
async function switchGoogle(){try{await saveSettings();if(!confirm('将清除当前本地Google登录并重新选择账号。继续吗？'))return;status('正在打开 Google 账号选择页面…');let d=await api('/api/switch-google',{method:'POST'});status('已切换 Google 账号：'+(d.email||d.message),'ok');await refreshGoogleAccount()}catch(err){status('切换账号失败：'+err.message,'danger')}}
async function syncAll(){try{await saveSettings();status('正在读取任务并建立本地任务…');let d=await api('/api/sync',{method:'POST'});status(`同步完成：新增 ${d.imported}，更新 ${d.updated}，已存在 ${d.unchanged||0}；回写 ${d.writeback.written||0} 行。重复点击不会重复导入。`,'ok');await refreshGroups()}catch(err){status('同步失败：'+err.message,'danger');await loadLog()}}
function pill(g){let c=g.status==='READY_FOR_GPT'?'p-ready':g.status==='NEEDS_MANUAL_CLASSIFY'?'p-manual':(g.status==='MATERIAL_SHORTAGE'?'p-error':'p-normal');return `<span class="pill ${c}">${e(g.status)}</span>`}
function confirmClear(){return new Promise(resolve=>{const d=document.createElement('dialog');d.innerHTML='<p>仅清空任务中心显示。全部生产数据与素材保留。</p><button id="cancelClear">取消</button> <button id="confirmClear">确定清除</button>';document.body.appendChild(d);const done=v=>{d.close();d.remove();resolve(v)};d.querySelector('#cancelClear').onclick=()=>done(false);d.querySelector('#confirmClear').onclick=()=>done(true);d.oncancel=e=>{e.preventDefault();done(false)};d.showModal();d.querySelector('#cancelClear').focus()})}
async function clearTasks(resync){

  if(!await confirmClear())return;
  try{
    let d=await api('/api/clear-tasks',{method:'POST',body:JSON.stringify({confirmation:'确定清除'})});
    status('任务中心显示已清空，全部生产数据和素材保留。','ok');
    await refreshGroups();
    if(resync) await syncAll();
  }catch(err){status('清空失败：'+err.message,'danger');await loadLog()}
}
async function refreshGroups(){let d=await api('/api/groups');let box=document.getElementById('groups');box.innerHTML=d.groups.map(g=>`<div class="group"><div class="top"><div><h3>${e(g.recipient)} · ${e(g.anchor_name)}</h3>${pill(g)}</div></div><div class="stat"><div class="mini">睁眼<b>${g.talking}</b></div><div class="mini">闭眼<b>${g.praying}</b></div><div class="mini">图片<b>${g.images}</b></div><div class="mini">任务<b>${g.talking+g.praying}</b></div></div><div class="muted" style="min-height:34px">${e(g.message||'')}</div><div class="row" style="margin-top:9px"><button class="btn secondary" onclick="downloadGroup('${g.group_key}')">同步Drive素材</button>${g.status==='NEEDS_MANUAL_CLASSIFY'?`<button class="btn warn" onclick="openFinder('${g.group_key}')">打开Finder改文件名</button><button class="btn primary" onclick="confirmFinder('${g.group_key}')">扫描命名并确认</button>`:''}</div><div class="muted" style="font-size:11px;margin-top:8px">${e(g.local_dir)}</div></div>`).join('');await refreshTasks()}
async function downloadGroup(k){try{status('正在同步主播Drive图片…');let d=await api('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group_key:k})});status(d.message||d.status,'ok');await refreshGroups()}catch(err){status('素材同步失败：'+err.message,'danger');await loadLog()}}
async function openFinder(k){try{let d=await api('/api/open-finder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group_key:k})});status('已打开：'+d.path+'。请将闭眼图片的文件名加上“闭眼”，然后点击“扫描命名并确认”。')}catch(err){status(err.message,'danger')}}
async function confirmFinder(k){try{let d=await api('/api/confirm-finder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group_key:k})});status(d.message||d.status,'ok');await refreshGroups()}catch(err){status('确认失败：'+err.message,'danger')}}
async function refreshTasks(){let d=await api('/api/tasks');document.getElementById('tasks').innerHTML=d.tasks.map(t=>`<tr><td>${t.sheet_row}</td><td>${e(t.recipient)}</td><td>${e(t.anchor_name)}</td><td>${e(t.mode)}</td><td>${e(t.foreign)}</td><td>${e(t.asset? t.asset.split('/').pop():'')}</td><td>${e(t.status)}</td></tr>`).join('')}
async function loadLog(){try{let r=await fetch('/api/log');document.getElementById('log').textContent=await r.text();let x=document.getElementById('log');x.scrollTop=x.scrollHeight}catch(e){}}
loadSettings().then(()=>{refreshGroups();refreshGoogleAccount()});loadLog();setInterval(loadLog,3000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def send_any(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, (bytes, bytearray)):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send_any(code, json.dumps(obj, ensure_ascii=False))

    def body_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n<0 or n>8*1024*1024:raise ValueError("request body too large")
        self.connection.settimeout(15)
        data=json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(data,dict):raise ValueError("JSON object required")
        return data

    def log_message(self, fmt, *args):
        log.info("WEB %s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        from app.services.bridge_security import allowed_request
        if not allowed_request(self.headers,self.server.server_port,extensions=False):return self.send_json({"error":"origin_denied"},403)
        try:
            if self.path == "/": return self.send_any(200, HTML, "text/html; charset=utf-8")
            if self.path == "/api/settings": return self.send_json(load_settings())
            if self.path == "/api/google-account": return self.send_json({"connected": TOKEN_FILE.exists(), "email": ""})
            if self.path == "/api/groups": return self.send_json({"groups": list_groups()})
            if self.path == "/api/tasks": return self.send_json({"tasks": list_tasks()})
            if self.path == "/api/log":
                from app.services.runtime_log import read_tail
                txt = read_tail(LOG_FILE)
                return self.send_any(200, txt, "text/plain; charset=utf-8")
            return self.send_json({"error":"Not Found"},404)
        except Exception as e:
            log.error("GET失败：%s\n%s", e, traceback.format_exc()); return self.send_json({"error":str(e)},500)

    def do_POST(self):
        from app.services.bridge_security import allowed_request
        if not allowed_request(self.headers,self.server.server_port,extensions=False):return self.send_json({"error":"origin_denied"},403)
        if self.headers.get("Content-Type", "").split(";")[0]!="application/json":return self.send_json({"error":"json_required"},415)
        try:
            if self.path == "/api/settings":
                s = load_settings(); s.update(self.body_json()); save_settings(s); return self.send_json({"ok":True})
            if self.path == "/api/pick-oauth": return self.send_json({"path":choose_oauth_file()})
            if self.path == "/api/pick-root": return self.send_json({"path":choose_local_folder()})
            if self.path == "/api/connect-google":
                google_creds(interactive=True); info=google_account_info(); return self.send_json({"message":"授权成功","email":info.get("email","")})
            if self.path == "/api/switch-google":
                disconnect_google(); google_creds(interactive=True, force_account_picker=True); info=google_account_info(); return self.send_json({"message":"切换成功","email":info.get("email","")})
            if self.path == "/api/sync":
                d = sync_sheet(); return self.send_json({"imported":d["imported"],"updated":d["updated"],"unchanged":d.get("unchanged",0),"writeback":d["writeback"]})
            if self.path == "/api/clear-tasks":
                if self.body_json().get("confirmation") != "确定清除":
                    return self.send_json({"error":"请先点击确定清除"}, 400)
                return self.send_json(clear_current_tasks())
            if self.path == "/api/download":
                d = download_drive_group(self.body_json().get("group_key")); return self.send_json(d)
            if self.path == "/api/open-finder":
                p = finder_open(self.body_json().get("group_key")); return self.send_json({"path":p})
            if self.path == "/api/confirm-finder":
                payload = self.body_json()
                d = confirm_named_materials(payload.get("group_key")); return self.send_json(d)
            return self.send_json({"error":"Not Found"},404)
        except Exception as e:
            log.error("POST %s 失败：%s\n%s", self.path, e, traceback.format_exc()); return self.send_json({"error":str(e)},400)


def main():
    init_db().close()
    log.info("启动 %s v%s", APP_NAME, VERSION)
    log.info("数据库=%s", DB_FILE)
    log.info("日志=%s", LOG_FILE)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    def opener():
        time.sleep(.8); webbrowser.open(url)
    threading.Thread(target=opener, daemon=True).start()
    print(f"\n{APP_NAME} v{VERSION}\n浏览器将自动打开：{url}\n关闭本终端即可停止。\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
