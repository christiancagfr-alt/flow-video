from __future__ import annotations
from pathlib import Path
from app.services.perf_diagnostics import measured
import sqlite3
import json
import time

# Stable database layout: keep the live DB beside the app, exactly like the
# previously working releases.  Do not migrate it at startup and do not switch
# paths while the process is running.
APP_ROOT = Path(__file__).resolve().parents[2]
from app.services.app_paths import data_dir
DB_PATH = data_dir() / "studio.db"

class ClosingConnection(sqlite3.Connection):
    """Commit/rollback normally, then promptly release SQLite caches and handles."""
    @measured('DB_query')
    def execute(self, *args, **kwargs):
        return super().execute(*args, **kwargs)

    @measured('DB_query')
    def executemany(self, *args, **kwargs):
        return super().executemany(*args, **kwargs)

    def __enter__(self):
        self._context_depth = getattr(self, '_context_depth', 0) + 1
        return super().__enter__()

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self._context_depth -= 1
            if not self._context_depth:
                self.close()


def connect():
    """Open one short-lived SQLite connection using the stable app-local DB.

    WAL + busy_timeout improve concurrent reads/writes without changing the
    location or lifecycle of the database.  No migration/failover happens here.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=10.0, factory=ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    return con

BASE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    fixed_code TEXT NOT NULL DEFAULT 'ZB',
    creator TEXT NOT NULL DEFAULT '',
    work_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '等待开始',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    video_count INTEGER NOT NULL DEFAULT 12,
    image_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(recipient_id) REFERENCES recipients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    script TEXT NOT NULL DEFAULT '',
    chinese_script TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '待准备',
    UNIQUE(host_id, seq),
    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS api_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_segment_id INTEGER,
    model TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(flow_segment_id) REFERENCES flow_segments(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS flow_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    seg_seq INTEGER NOT NULL,
    foreign_text TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '待处理',
    UNIQUE(video_id, seg_seq),
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);
"""

def _has_column(con, table, column):
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)

def _ensure_column(con, table, column, ddl):
    if not _has_column(con, table, column):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS flow_failure_attempts(
            segment_id INTEGER NOT NULL,command_id TEXT NOT NULL,reason TEXT DEFAULT '',
            created_at REAL NOT NULL,PRIMARY KEY(segment_id,command_id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS flow_recovery(
            segment_id INTEGER PRIMARY KEY,failures INTEGER DEFAULT 0,blocked INTEGER DEFAULT 0,
            notified INTEGER DEFAULT 0,queued INTEGER DEFAULT 0,preferred_channel TEXT DEFAULT '')""")

        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(BASE_SCHEMA)
        con.executescript("""
            CREATE TABLE IF NOT EXISTS flow_duration_choices(segment_id INTEGER PRIMARY KEY,
                dialogue TEXT NOT NULL, force_submit INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS flow_split_history(id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL, segment_id INTEGER NOT NULL, original_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS editing_history(id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL, job_path TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                output_path TEXT NOT NULL DEFAULT '', source_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        _ensure_column(con, "flow_duration_choices", "duration", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_duration_choices", "locked", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "recipients", "work_date", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "chinese_script", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "image_path", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "prompt_rule", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "special_requirements", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "segment_rule", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "ai_original_prompt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "model", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "input_tokens", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_segments", "cached_tokens", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_segments", "output_tokens", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_segments", "cost_usd", "REAL NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_segments", "flow_status", "TEXT NOT NULL DEFAULT '待生成'")
        _ensure_column(con, "flow_segments", "flow_output_path", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "flow_error", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "flow_attempts", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_segments", "flow_submitted_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "flow_completed_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "recipients", "flow_project_name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_collection_name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_prep_status", "TEXT NOT NULL DEFAULT '未准备'")
        _ensure_column(con, "hosts", "flow_window_key", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_images_uploaded", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "hosts", "flow_images_total", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "hosts", "flow_last_refresh_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_collection_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_link_status", "TEXT NOT NULL DEFAULT '未绑定'")
        _ensure_column(con, "hosts", "flow_upload_state", "TEXT NOT NULL DEFAULT 'idle'")
        _ensure_column(con, "hosts", "flow_upload_command_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_upload_fingerprint", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_upload_verified_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_upload_error", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "hosts", "flow_task_command_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "qc_status", "TEXT NOT NULL DEFAULT '待质检'")
        _ensure_column(con, "flow_segments", "qc_note", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "edit_status", "TEXT NOT NULL DEFAULT '等待片段'")
        _ensure_column(con, "videos", "edit_output_path", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "upload_status", "TEXT NOT NULL DEFAULT '未上传'")
        _ensure_column(con, "videos", "upload_target", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "upload_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "upload_confirm_mode", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "upload_confirmed_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "flow_output_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "recipients", "drive_folder_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "drive_file_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "drive_folder_url", "TEXT NOT NULL DEFAULT ''")

        _ensure_column(con, "videos", "original_script", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "production_script", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "source_task_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "source_row", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "source_drive_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "videos", "asset_status", "TEXT NOT NULL DEFAULT '未准备'")
        _ensure_column(con, "videos", "performance_mode", "TEXT NOT NULL DEFAULT 'TALKING'")
        _ensure_column(con, "videos", "prompt_template_snapshot", "TEXT NOT NULL DEFAULT ''")

        _ensure_column(con, "flow_segments", "generation_mode", "TEXT NOT NULL DEFAULT 'FRAME'")
        _ensure_column(con, "flow_segments", "generation_command", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "flow_channel_key", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "flow_retry_count", "INTEGER NOT NULL DEFAULT 0")
        # Incremental spoken-text timing metadata.  These columns are advisory only and
        # never drive/overwrite downstream production state by themselves.
        _ensure_column(con, "flow_segments", "estimated_speech_duration", "REAL NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_segments", "flow_duration_seconds", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_segments", "timing_status", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "manual_text_lock", "INTEGER NOT NULL DEFAULT 0")
        # V0.13.5: explicit human gates between GPT -> Flow and QC -> editing.
        _ensure_column(con, "flow_segments", "prompt_review_status", "TEXT NOT NULL DEFAULT '待检查'")
        _ensure_column(con, "flow_segments", "prompt_submitted_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "qc_reject_reason", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_segments", "qc_decided_at", "TEXT NOT NULL DEFAULT ''")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS flow_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                channel_key TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'normal',
                collection_url TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                max_inflight INTEGER NOT NULL DEFAULT 8,
                upload_state TEXT NOT NULL DEFAULT 'idle',
                upload_command_id TEXT NOT NULL DEFAULT '',
                upload_fingerprint TEXT NOT NULL DEFAULT '',
                images_uploaded INTEGER NOT NULL DEFAULT 0,
                images_total INTEGER NOT NULL DEFAULT 0,
                upload_verified_at TEXT NOT NULL DEFAULT '',
                upload_error TEXT NOT NULL DEFAULT '',
                task_command_id TEXT NOT NULL DEFAULT '',
                last_seen REAL NOT NULL DEFAULT 0,
                last_status TEXT NOT NULL DEFAULT '',
                UNIQUE(host_id, channel_key),
                FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_flow_channels_host ON flow_channels(host_id);
            CREATE TABLE IF NOT EXISTS flow_receipts (
                event_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS flow_pending_downloads (
                event_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                last_attempt REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS flow_outputs (
                id INTEGER PRIMARY KEY, segment_id INTEGER NOT NULL,
                command_id TEXT NOT NULL, media_id TEXT NOT NULL,
                output_path TEXT NOT NULL, qc_status TEXT DEFAULT '待质检',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(segment_id, command_id, media_id));
            CREATE TABLE IF NOT EXISTS flow_redo (
                segment_id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS flow_obsolete_segments (
                segment_id INTEGER NOT NULL, command_id TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(segment_id,command_id)
            );
            CREATE TABLE IF NOT EXISTS flow_obsolete_commands (
                command_id TEXT PRIMARY KEY,
                host_id INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                invalidated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS prompt_submission_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, segment_id INTEGER NOT NULL, prompt_snapshot TEXT NOT NULL DEFAULT '',
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(segment_id) REFERENCES flow_segments(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS flow_channel_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_key TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'normal',
                collection_url TEXT NOT NULL DEFAULT '',
                download_subdir TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                upload_state TEXT NOT NULL DEFAULT 'idle',
                upload_command_id TEXT NOT NULL DEFAULT '',
                upload_fingerprint TEXT NOT NULL DEFAULT '',
                images_uploaded INTEGER NOT NULL DEFAULT 0,
                images_total INTEGER NOT NULL DEFAULT 0,
                upload_verified_at TEXT NOT NULL DEFAULT '',
                upload_error TEXT NOT NULL DEFAULT '',
                task_command_id TEXT NOT NULL DEFAULT '',
                last_seen REAL NOT NULL DEFAULT 0,
                last_status TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS flow_dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL,
                channel_key TEXT NOT NULL,
                command_id TEXT NOT NULL,
                dispatch_order INTEGER NOT NULL DEFAULT 0,
                round_no INTEGER NOT NULL DEFAULT 1,
                task_name TEXT NOT NULL,
                expected_filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                download_path TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                submitted_at TEXT NOT NULL DEFAULT '',
                detected_at TEXT NOT NULL DEFAULT '',
                UNIQUE(segment_id, command_id, round_no),
                FOREIGN KEY(segment_id) REFERENCES flow_segments(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_flow_dispatch_channel ON flow_dispatches(channel_key,status);
            CREATE INDEX IF NOT EXISTS idx_flow_dispatch_filename ON flow_dispatches(expected_filename);
        """)
        for i in range(1,5):
            con.execute("INSERT OR IGNORE INTO flow_channel_pool(channel_key,role,download_subdir,sort_order) VALUES(?,?,?,?)", (f'CH{i}','normal',f'CH{i}',i))
        con.execute("INSERT OR IGNORE INTO flow_channel_pool(channel_key,role,download_subdir,sort_order) VALUES('R1','fast','R1',99)")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('flow_channel_pool_enabled','1')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('flow_channel_download_root','')")

        _ensure_column(con, "flow_channel_pool", "browser_group", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_channel_pool", "health_status", "TEXT NOT NULL DEFAULT 'unknown'")
        _ensure_column(con, "flow_channel_pool", "page_status", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_channel_pool", "consecutive_failures", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_channel_pool", "quarantine_until", "REAL NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_channel_pool", "last_success_at", "REAL NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_dispatches", "dispatch_uid", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "flow_dispatches", "stage", "TEXT NOT NULL DEFAULT 'QUEUED'")
        _ensure_column(con, "flow_dispatches", "release_at", "REAL NOT NULL DEFAULT 0")
        _ensure_column(con, "flow_dispatches", "last_update_at", "REAL NOT NULL DEFAULT 0")

        con.executescript("""
            CREATE TABLE IF NOT EXISTS source_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_task_id TEXT NOT NULL DEFAULT '',
                source_row TEXT NOT NULL DEFAULT '',
                video_id INTEGER,
                status TEXT NOT NULL DEFAULT '待导入',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_task_id, source_row),
                FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS asset_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL,
                source_url TEXT NOT NULL,
                asset_index INTEGER NOT NULL DEFAULT 1,
                expected_name TEXT NOT NULL DEFAULT '',
                local_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(video_id, source_url, asset_index),
                FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS web_fetch_jobs (
                job_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                url TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS speech_analysis (
                segment_id INTEGER PRIMARY KEY,
                video_hash TEXT NOT NULL DEFAULT '',
                sidecar_path TEXT NOT NULL DEFAULT '',
                analysis_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(segment_id) REFERENCES flow_segments(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS local_qc_results (
                segment_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                result_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(segment_id) REFERENCES flow_segments(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS ai_qc_results (
                segment_id INTEGER PRIMARY KEY,
                light TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}',
                cost_usd REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(segment_id) REFERENCES flow_segments(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS pipeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER,
                video_id INTEGER,
                stage TEXT NOT NULL DEFAULT '',
                level TEXT NOT NULL DEFAULT 'INFO',
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_asset_jobs_status ON asset_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_fetch_jobs_status ON web_fetch_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_pipeline_events_created ON pipeline_events(created_at);
            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imported INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                unchanged INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual',
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS qc_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                recipient_name TEXT NOT NULL DEFAULT '',
                host_name TEXT NOT NULL DEFAULT '',
                performance_mode TEXT NOT NULL DEFAULT 'TALKING',
                prompt_snapshot TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(segment_id) REFERENCES flow_segments(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_qc_decisions_created ON qc_decisions(created_at);
        """)
        _ensure_column(con, "asset_jobs", "job_type", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(con, "asset_jobs", "job_id", "TEXT NOT NULL DEFAULT ''")
        con.execute("CREATE INDEX IF NOT EXISTS idx_asset_camera ON asset_jobs(video_id,job_type,job_id)")
        _ensure_column(con, "asset_jobs", "image_width", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "asset_jobs", "image_height", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(con, "asset_jobs", "download_method", "TEXT NOT NULL DEFAULT ''")


        # Cover live joins/lookups without changing scheduling or date predicates.
        con.executescript("""
            CREATE INDEX IF NOT EXISTS idx_perf_hosts_recipient ON hosts(recipient_id);
            CREATE INDEX IF NOT EXISTS idx_perf_segments_video ON flow_segments(video_id);
            CREATE INDEX IF NOT EXISTS idx_perf_dispatch_segment_command ON flow_dispatches(segment_id,command_id,status);
            CREATE INDEX IF NOT EXISTS idx_perf_segments_command ON flow_segments(generation_command);
        """)
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('default_creator','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('task_source_sheet_url','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('task_asset_root','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('segment_output_root','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('drive_upload_root_url','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('google_oauth_client_path','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('talking_base_prompt','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('praying_base_prompt','')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('ai_qc_enabled','0')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('ai_qc_frames','4')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('backpressure_qc_limit','250')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('backpressure_edit_limit','80')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('task_auto_sync_enabled','0')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('task_auto_sync_minutes','5')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('flow_auto_production_enabled','1')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('flow_production_paused','0')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('ai_qc_enabled','0')")

        con.execute("""UPDATE flow_segments SET generation_command='legacy-import'
            WHERE generation_command='' AND flow_status='已完成' AND flow_output_path<>''""")
        con.execute("""INSERT OR IGNORE INTO flow_outputs
            (segment_id,command_id,media_id,output_path,qc_status)
            SELECT id,generation_command,'legacy-import',flow_output_path,qc_status
            FROM flow_segments WHERE generation_command='legacy-import' AND flow_output_path<>''""")

        # One-time recovery of completed receipts acknowledged by older releases.
        if not con.execute("SELECT 1 FROM app_settings WHERE key='qc_download_recovery_v20'").fetchone():
            for receipt in con.execute("SELECT event_id,payload FROM flow_receipts"):
                try:
                    event = json.loads(receipt['payload'])
                    if isinstance(event,dict) and event.get('type') == 'video_download_completed':
                        con.execute("INSERT OR IGNORE INTO flow_pending_downloads(event_id,payload) VALUES(?,?)", (receipt['event_id'], receipt['payload']))
                except (ValueError, TypeError):
                    continue
            con.execute("INSERT INTO app_settings(key,value) VALUES('qc_download_recovery_v20','1')")

        # V0.13.5.97: B-roll 预设和视频增强表。
        from app.services.broll_presets import ensure_tables as _ensure_broll_tables
        _ensure_broll_tables(con)
        
