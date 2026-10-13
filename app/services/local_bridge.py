from __future__ import annotations
from app.services.bridge_security import allowed_request, published_file
from app.services import workflow
from app.services import protocol_v2
from app.services import runtime_log
from app.core import repository as repo
from app.core import database, work_dates

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import urllib.request
import urllib.error
from threading import Thread, Lock
import json
import sqlite3
import time
import secrets
from pathlib import Path
import mimetypes
import urllib.parse


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    # macOS may keep a recently closed localhost socket in TIME_WAIT.
    # SO_REUSEADDR allows Flow Studio to restart immediately without a false
    # "Address already in use" failure. It does NOT allow two live servers
    # to bind the same port.
    allow_reuse_address = True




def _segment_work_dates(segment_ids):
    ids=[int(x) for x in segment_ids if str(x or '').strip()]
    if not ids:
        return {}
    q=','.join('?'*len(ids))
    with database.connect() as con:
        date_map=work_dates.recipient_dates(con)
        rows=con.execute(f"""SELECT fs.id segment_id,h.recipient_id FROM flow_segments fs
            JOIN videos v ON v.id=fs.video_id JOIN hosts h ON h.id=v.host_id
            WHERE fs.id IN ({q})""",ids).fetchall()
    return {int(r['segment_id']):date_map.get(int(r['recipient_id'])) for r in rows}

def _job_declared_or_actual_date(job):
    declared=str(job.get('work_date') or '').strip()
    if declared:
        if declared==work_dates.LEGACY:return declared
        return work_dates.canonical(declared) or declared
    ids=[t.get('segment_id') for t in (job.get('tasks') or []) if t.get('segment_id') is not None]
    dates={d for d in _segment_work_dates(ids).values() if d}
    return next(iter(dates)) if len(dates)==1 else ''

def _job_has_live_submission(job):
    cmd=str(job.get('command_id') or '').strip()
    if not cmd:return False
    ids=[int(t.get('segment_id')) for t in (job.get('tasks') or []) if t.get('segment_id') is not None]
    with database.connect() as con:
        if ids:
            q=','.join('?'*len(ids))
            row=con.execute(f"""SELECT 1 FROM flow_segments WHERE id IN ({q}) AND generation_command=?
                AND flow_status IN ('已提交','生成中','下载中') LIMIT 1""",(*ids,cmd)).fetchone()
            if row:return True
        row=con.execute("SELECT 1 FROM flow_dispatches WHERE command_id=? AND status IN ('submitted','downloading') LIMIT 1",(cmd,)).fetchone()
        return bool(row)

def _job_visible_for_selected_date(job):
    job_day=_job_declared_or_actual_date(job)
    active=work_dates.active()
    if job_day==active:return True
    # Never interrupt a command that Flow has already accepted merely because the user
    # browses another date.  Pre-submit/upload-only work from another date is hidden.
    return _job_has_live_submission(job)

def _sanitize_job_for_declared_date(job):
    out=dict(job)
    declared=_job_declared_or_actual_date(out)
    if declared:out['work_date']=declared
    tasks=list(out.get('tasks') or [])
    if not tasks or not declared:return out
    dates=_segment_work_dates([t.get('segment_id') for t in tasks])
    kept=[t for t in tasks if dates.get(int(t.get('segment_id') or 0))==declared]
    if len(kept)!=len(tasks):
        runtime_log.log('cross_date_job_tasks_blocked',level='WARNING',command_id=out.get('command_id',''),work_date=declared,removed=len(tasks)-len(kept))
    out['tasks']=kept
    # Rebuild expected image lists from the surviving tasks when possible so a blocked
    # foreign-date image cannot remain as an upload requirement.
    if kept and len(kept)!=len(tasks):
        names=[];paths=[]
        for t in kept:
            path=str(t.get('image_path') or '')
            name=Path(path).name if path else str(t.get('image') or t.get('image_name') or '')
            if name and name not in names:names.append(name)
            if path and path not in paths:paths.append(path)
        if names:out['expected_image_names']=names
        if paths:
            out['image_files']=[x for x in (out.get('image_files') or []) if str(x.get('path') or '') in paths]
            out['image_count']=len(paths)
            out['upload_batches']=[paths[i:i+20] for i in range(0,len(paths),20)]
    return out


_EVENT_FAILURES={}
POISON_EVENT_LIMIT=6


def _poison_event(data):
    """True once the same event id has failed POISON_EVENT_LIMIT times (then it is dropped)."""
    try:
        key=str((data or {}).get('event_id') or '')
        if not key: return False
        n=_EVENT_FAILURES.get(key,0)+1
        _EVENT_FAILURES[key]=n
        if len(_EVENT_FAILURES)>5000:
            for k in list(_EVENT_FAILURES)[:2500]: _EVENT_FAILURES.pop(k,None)
        if n>=POISON_EVENT_LIMIT:
            runtime_log.log('bridge_event_dropped_poison',level='ERROR',event_id=key,event_type=str((data or {}).get('type') or ''),attempts=n)
            _EVENT_FAILURES.pop(key,None)
            return True
    except Exception:
        pass
    return False


class FlowStudioBridge:
    """
    Local bridge for Flow Studio <-> Chrome extension.
    Binds only to 127.0.0.1. No cloud server and no external network exposure.
    """
    def __init__(self, host="127.0.0.1", port=17831):
        self.host = host
        self.port = int(port)
        self.token = secrets.token_urlsafe(24)
        self._lock = Lock()
        self._server = None
        self._thread = None
        self._config = {}
        self._queue = []
        self._queue_version = 0
        self._last_heartbeat = 0.0
        self._extension_meta = {}
        self._events = []
        self._prep_jobs = []
        self._prep_version = 0
        loaded_jobs = json.loads(repo.get_setting("flow_host_jobs_v124", "[]"))
        from app.services.eye_states import enrich_job
        loaded_jobs = [enrich_job(j) for j in loaded_jobs]
        if repo.get_setting('flow_channel_pool_enabled','1') == '1':
            self._host_jobs = [j for j in loaded_jobs if int(j.get('host_id') or 0) == 0]
            # V0.13.5.84: do not resurrect inert pool jobs after Studio restarts.
            # A completed generation wave used to remain persisted with
            # dispatch_tasks=false but execute_upload=true. The plugin then kept
            # reporting that stale command even though the channel card looked idle,
            # which split the scheduler's source of truth. Keep only executable waves
            # or a genuinely active upload-only wave.
            try:
                pool={str(c['channel_key']):c for c in repo.list_channel_pool(enabled_only=False)}
                upload_active={'queued','precheck','uploading','flow_verified','refreshing','post_refresh'}
                cleaned=[]
                for job in self._host_jobs:
                    cmd=str(job.get('command_id') or '')
                    if not cmd:
                        continue
                    if bool(job.get('dispatch_tasks')) or bool(job.get('auto_execute')):
                        cleaned.append(job); continue
                    if bool(job.get('execute_upload')):
                        c=pool.get(str(job.get('channel_key') or ''))
                        if c and str(c['upload_command_id'] or '')==cmd and str(c['upload_state'] or '') in upload_active:
                            cleaned.append(job); continue
                removed=len(self._host_jobs)-len(cleaned)
                self._host_jobs=cleaned
                if removed:
                    runtime_log.log('stale_pool_jobs_pruned_on_startup',removed=removed)
            except Exception as exc:
                runtime_log.log('stale_pool_jobs_startup_prune_failed',level='WARNING',error=str(exc))
            if self._host_jobs != loaded_jobs:
                repo.set_setting('flow_host_jobs_v124', json.dumps(self._host_jobs))
                removed=max(0,len(loaded_jobs)-len(self._host_jobs))
                if removed:
                    runtime_log.log('legacy_or_stale_host_jobs_cleared_for_channel_pool',removed=removed)
        else:
            self._host_jobs = loaded_jobs
        self._host_jobs_version = 0
        self._drive_jobs = []
        self._drive_jobs_version = 0
        self._drive_events = []
        # Latest per-host state reported by the new Flow Studio web plugin.
        # This survives event-queue consumption so the desktop UI can always
        # query the current browser-side state.
        self._web_plugin_hosts = {}
        self._web_plugin_channels = {}
        self._event_ids = {}
        # Shared desktop <-> extension generation control. The desktop bumps
        # progress_scan_version every 10 seconds; the extension treats a new
        # version as an explicit request to rescan Flow/download state.
        # Every Studio launch starts PAUSED; production only begins after the user
        # presses “恢复生产 / 继续全部” in the Flow generation center.
        self._generation_paused = True
        self._progress_scan_version = 0
        self._control_version = 0
        self._last_restart_attempt = 0.0
        self._bridge_generation = 0


    def reconfigure_port(self, port):
        """Safely move the localhost bridge to a new port."""
        port = int(port)
        if not (1024 <= port <= 65535):
            raise ValueError("Bridge 端口必须在 1024-65535 之间")
        if port == self.port and self._server:
            return
        self.stop()
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.start()

    def start(self):
        if self._server:
            return

        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def _cors(self):
                # Extension service worker fetches localhost; allow extension origins.
                origin=self.headers.get("Origin", "")
                if origin and allowed_request(self.headers,bridge.port):
                    self.send_header("Access-Control-Allow-Origin",origin)
                    self.send_header("Vary","Origin")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-FlowStudio-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

            def _json(self, status, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self):
                if not allowed_request(self.headers,bridge.port):return False
                # Health/heartbeat are intentionally readable locally.
                if urllib.parse.urlsplit(self.path).path in ("/health","/heartbeat"):
                    return True
                return secrets.compare_digest(self.headers.get("X-FlowStudio-Token", ""),bridge.token)

            def do_OPTIONS(self):
                if not allowed_request(self.headers,bridge.port):return self._json(403,{"ok":False,"error":"origin_denied"})
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self):
                if not self._authorized():
                    return self._json(403, {"ok": False, "error": "unauthorized"})

                if self.path.startswith("/health"):
                    return self._json(200, {
                        "ok": True,
                        "service": "Flow Studio Bridge",
                        "port": bridge.port,
                        "queue_version": bridge._queue_version,
                    })

                if self.path.startswith("/config"):
                    with bridge._lock:
                        data = dict(bridge._config)
                    return self._json(200, {"ok": True, "config": data})

                if self.path.startswith("/queue"):
                    with bridge._lock:
                        queue = list(bridge._queue)
                        version = bridge._queue_version
                    return self._json(200, {
                        "ok": True,
                        "version": version,
                        "tasks": queue,
                    })

                if self.path.startswith("/prep"):
                    with bridge._lock:
                        jobs = list(bridge._prep_jobs)
                        version = bridge._prep_version
                    return self._json(200, {
                        "ok": True,
                        "version": version,
                        "jobs": jobs,
                    })

                if self.path.startswith("/file?"):
                    try:
                        parsed = urllib.parse.urlparse(self.path)
                        qs = urllib.parse.parse_qs(parsed.query)
                        path = (qs.get("path") or [""])[0]
                        with bridge._lock:
                            allowed=published_file(path,[bridge._host_jobs,bridge._drive_jobs,bridge._queue])
                        if not allowed:return self._json(403,{"ok":False,"error":"file_not_published"})
                        p = Path(path)
                        if not p.exists() or not p.is_file():
                            return self._json(404, {"ok": False, "error": "file_not_found"})
                        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                        size = p.stat().st_size
                        self.send_response(200)
                        self.send_header("Content-Type", mime)
                        self.send_header("Content-Length", str(size))
                        self.send_header("X-FlowStudio-Filename", urllib.parse.quote(p.name))
                        self._cors()
                        self.end_headers()
                        with p.open("rb") as fh:
                            while True:
                                chunk = fh.read(1024 * 1024)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                        return
                    except Exception as exc:
                        return self._json(500, {"ok": False, "error": str(exc)})

                if self.path.startswith("/source-jobs"):
                    jobs=[]
                    for r in repo.list_web_fetch_jobs('queued'):
                        try: meta=json.loads(r['meta_json'] or '{}')
                        except Exception: meta={}
                        jobs.append({'job_id':r['job_id'],'kind':r['kind'],'url':r['url'],'meta':meta})
                    return self._json(200, {'ok':True,'jobs':jobs,'server_time':time.time()})

                if self.path.startswith("/host-jobs"):
                    now=time.time()
                    with bridge._lock:
                        visible_jobs=[j for j in bridge._host_jobs if _job_visible_for_selected_date(j)]
                        eye_capable = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('eye_reference') or [''])[0] == '1'
                        if not eye_capable:
                            visible_jobs = [j for j in visible_jobs if not j.get('dispatch_tasks') or not any(t.get('open_eye_prompt') for t in j.get('tasks',[]))]
                        all_jobs=[dict(j, settings=dict(bridge._config.get("pluginSettings", {}))) for j in visible_jobs]
                        try:
                            from app.services import pause_control as _pc
                            _manual_paused=_pc.manual_paused_channels()
                        except Exception:
                            _manual_paused=set()
                        for _j in all_jobs:
                            _j['channel_paused']=str(_j.get('channel_key') or '') in _manual_paused
                        jobs=[protocol_v2.enrich_job_with_v2_protocol(j) for j in all_jobs if float(j.get('release_at') or 0)<=now]
                        # Version changes when another delayed channel becomes visible.
                        version=f"{bridge._host_jobs_version}:{len(jobs)}"
                    channels=[]
                    try:
                        channels=[{
                            'id':int(c['id']),'channel_key':str(c['channel_key']),'role':str(c['role']),
                            'browser_group':repo.channel_browser_group(str(c['channel_key'])),
                            'collection_url':str(c['collection_url'] or ''),'download_subdir':str(c['download_subdir'] or c['channel_key'])
                        } for c in repo.list_channel_pool(enabled_only=True) if str(c['collection_url'] or '').strip()]
                    except Exception as exc:
                        runtime_log.log('bridge_channel_config_read_failed',level='ERROR',error=str(exc))
                    read_points = None
                    try:
                        from app.services import flow_accounts
                        read_points = flow_accounts.pending_point_read()
                    except Exception:
                        read_points = None
                    return self._json(200, {
                        "ok": True,
                        "version": version,
                        "jobs": jobs,
                        "channels": channels,
                        "focus_requests": bridge.focus_requests(),
                        "read_points": read_points,
                        "scheduled_total": len(all_jobs),
                        "released_total": len(jobs),
                        "server_time": now,
                    })

                if self.path.startswith("/drive-jobs"):
                    with bridge._lock:
                        jobs = list(bridge._drive_jobs)
                        version = bridge._drive_jobs_version
                    return self._json(200, {
                        "ok": True,
                        "version": version,
                        "jobs": jobs,
                    })

                if self.path.startswith("/web-plugin-state"):
                    return self._json(200, {"ok": True, "hosts": bridge.web_plugin_state()})

                if self.path.startswith("/generation-control"):
                    payload = bridge.generation_control()
                    try:
                        from app.services import flow_accounts
                        request = flow_accounts.public_request().get('account_request')
                        if request:
                            payload['account_request'] = request
                    except Exception:
                        pass
                    return self._json(200, payload)

                if self.path.startswith("/status"):
                    return self._json(200, bridge.status())

                return self._json(404, {"ok": False, "error": "not_found"})

            def do_POST(self):
                if not self._authorized():
                    return self._json(403, {"ok": False, "error": "unauthorized"})

                try:
                    length = int(self.headers.get("Content-Length", "0") or 0)
                    if length<0 or length>8*1024*1024:return self._json(413,{"ok":False,"error":"body_too_large"})
                    self.connection.settimeout(15)
                    raw = self.rfile.read(length) if length else b"{}"
                    data = json.loads(raw.decode("utf-8"))
                    if not isinstance(data,dict):raise ValueError("object_required")
                except Exception:
                    return self._json(400,{"ok":False,"error":"invalid_json"})

                if self.path == '/segment-states':
                    try:
                        ids = [int(x) for x in (data.get('segment_ids') or [])][:500]
                        states = {}
                        with database.connect() as con:
                            for sid in ids:
                                r = con.execute('SELECT status,flow_status,flow_output_path,generation_command FROM flow_segments WHERE id=?', (sid,)).fetchone()
                                if not r:
                                    states[str(sid)] = {'missing': True}
                                    continue
                                states[str(sid)] = {
                                    'command': str(r['generation_command'] or ''),
                                    'flow_status': str(r['flow_status'] or ''),
                                    'cancelled': str(r['status'] or '') in ('已撤销', '已作废'),
                                    'done': str(r['flow_status'] or '') == '已完成' and bool(str(r['flow_output_path'] or '').strip())
                                            and bool(con.execute('SELECT 1 FROM flow_outputs WHERE segment_id=? AND command_id=? LIMIT 1', (sid, r['generation_command'])).fetchone()),
                                }
                        return self._json(200, {'ok': True, 'states': states})
                    except Exception as exc:
                        return self._json(500, {'ok': False, 'error': str(exc)})

                if self.path == '/rebalance-ack':
                    try:return self._json(200,{'ok':True,'moved':bridge.ack_rebalance(data)})
                    except ValueError as exc:return self._json(400,{'ok':False,'error':str(exc)})

                if self.path == '/claim-command':
                    try:return self._json(200, {'ok':True,'owned':bridge.claim_command(str(data.get('command_id') or ''),str(data.get('owner') or ''),data.get('segment_id'),bool(data.get('recovery')))})
                    except ValueError as exc:return self._json(400,{'ok':False,'error':str(exc)})

                if self.path.startswith("/heartbeat"):
                    bridge.heartbeat(data)
                    return self._json(200, {
                        "ok": True,
                        "token": bridge.token,
                        "queue_version": bridge._queue_version,
                    })

                if self.path.startswith("/generation-control"):
                    if "paused" in data:
                        bridge.set_generation_paused(bool(data.get("paused")))
                    if data.get("request_scan"):
                        bridge.request_progress_scan()
                    return self._json(200, bridge.generation_control())

                if self.path.startswith("/flow-account-credential"):
                    try:
                        from app.services import flow_accounts
                        return self._json(200, flow_accounts.credential_for(str(data.get("id") or "")))
                    except ValueError as exc:
                        return self._json(400, {"ok": False, "error": str(exc)})
                    except Exception:
                        return self._json(500, {"ok": False, "error": "登录信息读取失败"})

                if self.path.startswith("/flow-account-result"):
                    try:
                        from app.services import flow_accounts
                        flow_accounts.finish_request(data)
                        return self._json(200, {"ok": True})
                    except ValueError as exc:
                        return self._json(400, {"ok": False, "error": str(exc)})

                if self.path.startswith("/source-result"):
                    job_id=str(data.get('job_id') or '')
                    if not job_id:
                        return self._json(400, {'ok':False,'error':'missing_job_id'})
                    error=str(data.get('error') or '')
                    repo.complete_web_fetch_job(job_id, data.get('result') or {}, error)
                    runtime_log.log('source_fetch_result',job_id=job_id,kind=data.get('kind',''),ok=not bool(error),error=error[:300])
                    return self._json(200, {'ok':True})

                if self.path.startswith("/event"):
                    try:
                        last_db_exc=None
                        # Protocol V2 interception
                        mapped_data = protocol_v2.intercept_v2_event(data)
                        if mapped_data is True:
                            # Handled internally, skip legacy workflow
                            return self._json(200, {"ok": True})
                        elif mapped_data is not False:
                            data = mapped_data

                        for attempt in range(4):
                            try:
                                workflow.accept(data)
                                last_db_exc=None
                                break
                            except sqlite3.OperationalError as exc:
                                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                                    raise
                                last_db_exc=exc
                                time.sleep(0.08 * (attempt + 1))
                        if last_db_exc is not None:
                            raise last_db_exc
                        bridge.push_event(data)
                    except (ValueError, OSError, sqlite3.OperationalError) as exc:
                        if _poison_event(data):
                            return self._json(200, {"ok": True, "dropped": True})
                        runtime_log.log("bridge_event_deferred", level="WARNING", error=str(exc)[:220], event_type=str(data.get("type") or ""))
                        return self._json(503, {"ok": False, "error": str(exc)})
                    except (IndexError, KeyError) as exc:
                        # Keep failed receipts in the plugin's persistent outbox.
                        # Never acknowledge an uncommitted schema failure as success.
                        if _poison_event(data):
                            return self._json(200, {"ok": True, "dropped": True})
                        runtime_log.log("bridge_event_schema_compat", level="WARNING", error=str(exc)[:220], event_type=str(data.get("type") or ""))
                        return self._json(503, {"ok": False, "error": str(exc), "retry": True})
                    except Exception as exc:
                        import traceback
                        runtime_log.log("bridge_event_crashed", level="ERROR", error=repr(exc)[:220], event_type=str(data.get("type") or ""), trace=traceback.format_exc()[-800:])
                        if _poison_event(data):
                            return self._json(200, {"ok": True, "dropped": True})
                        return self._json(503, {"ok": False, "error": repr(exc)})
                    return self._json(200, {"ok": True})

                return self._json(404, {"ok": False, "error": "not_found"})

            def log_message(self, fmt, *args):
                # Avoid flooding terminal every 1-2 seconds.
                return

        last_exc = None
        for attempt in range(4):
            try:
                self._server = ReusableThreadingHTTPServer((self.host, self.port), Handler)
                self._server.daemon_threads = True
                self._thread = Thread(
                    target=self._server.serve_forever,
                    name="FlowStudioBridge",
                    daemon=True,
                )
                self._thread.start()
                self._bridge_generation += 1
                runtime_log.log('bridge_started', host=self.host, port=self.port, generation=self._bridge_generation, thread_alive=bool(self._thread and self._thread.is_alive()))
                return
            except OSError as exc:
                self._server = None
                self._thread = None
                last_exc = exc
                # Errno 48 (macOS) / 98 (Linux) / 10048 (Windows): address in use.
                if getattr(exc, "errno", None) not in (48, 98, 10048):
                    raise
                # A recently closed localhost listener can need a moment to clear.
                if attempt < 3:
                    time.sleep(0.35 * (attempt + 1))

        # If another live Flow Studio Bridge owns the port, expose a precise
        # error instead of pretending the current instance is connected.
        if self._is_flowstudio_bridge_alive():
            raise OSError(
                48,
                "Flow Studio Bridge 已在 127.0.0.1:%s 运行；请关闭另一个 Flow Studio 窗口后重试" % self.port,
            )
        raise last_exc

    def _is_flowstudio_bridge_alive(self):
        try:
            with urllib.request.urlopen(
                f"http://{self.host}:{self.port}/health",
                timeout=0.45,
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok") and data.get("service") == "Flow Studio Bridge")
        except Exception:
            return False

    def ensure_running(self):
        """Background watchdog used by the UI timer; restart the localhost server if its thread died."""
        alive=bool(self._server and self._thread and self._thread.is_alive())
        if alive:
            return True
        now=time.time()
        if now-float(self._last_restart_attempt or 0)<2.5:
            return False
        self._last_restart_attempt=now
        runtime_log.log('bridge_watchdog_restart_attempt',level='WARNING',port=self.port,
                        had_server=bool(self._server),thread_alive=bool(self._thread and self._thread.is_alive()))
        try:
            if self._server:
                try:self._server.server_close()
                except Exception:pass
            self._server=None
            self._thread=None
            self.start()
            runtime_log.log('bridge_watchdog_recovered',port=self.port,generation=self._bridge_generation)
            return True
        except Exception as exc:
            runtime_log.log('bridge_watchdog_restart_failed',level='ERROR',port=self.port,error=str(exc))
            return False

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            finally:
                self._server = None
                self._thread = None

    def update_config(self, config):
        with self._lock:
            self._config = dict(config or {})

    def publish_tasks(self, tasks):
        with self._lock:
            self._queue = list(tasks or [])
            self._queue_version += 1
            return self._queue_version

    def clear_tasks(self):
        return self.publish_tasks([])

    def heartbeat(self, meta=None):
        now=time.time()
        with self._lock:
            previous=self._last_heartbeat
            self._last_heartbeat=now
            self._extension_meta=dict(meta or {})
            
            # Protocol V2 heartbeat tracking
            if meta:
                cid_str = meta.get('CHANNEL_ID') or ''
                if cid_str:
                    try:
                        cid = int(cid_str.split('_')[1] if '_' in cid_str else cid_str)
                        csnap = dict(self._web_plugin_channels.get(cid) or {})
                        csnap['state'] = meta.get('STATE')
                        csnap['current_task_id'] = meta.get('CURRENT_TASK_ID')
                        csnap['current_task_type'] = meta.get('CURRENT_TASK_TYPE')
                        csnap['capabilities'] = meta.get('CAPABILITIES')
                        csnap['last_seen'] = now
                        self._web_plugin_channels[cid] = csnap
                    except Exception:
                        pass

        # Log first contact, recovery after a gap, or roughly once per minute.
        last_logged=float(getattr(self,'_last_heartbeat_log',0.0) or 0.0)
        recovered=bool(previous and now-previous>8.0)
        if not last_logged or recovered or now-last_logged>60.0:
            self._last_heartbeat_log=now
            runtime_log.log('bridge_heartbeat', extension_version=(meta or {}).get('extensionVersion',''),
                            mode=(meta or {}).get('mode',''), recovered=recovered,
                            gap_seconds=round(now-previous,2) if previous else None,
                            browser_instance=(meta or {}).get('browserInstance',''))

    def push_event(self, event):
        with self._lock:
            row = dict(event or {})
            now = time.time()
            event_id = str(row.get("event_id") or "")
            if event_id:
                # Reliable web-plugin delivery may retry the same event. Accept once.
                if event_id in self._event_ids:
                    self._last_heartbeat = now
                    return
                self._event_ids[event_id] = now
                if len(self._event_ids) > 1200:
                    cutoff = now - 600
                    self._event_ids = {k:v for k,v in self._event_ids.items() if v >= cutoff}
            row["_received_at"] = now
            runtime_log.log('bridge_event', type=row.get('type',''), channel=row.get('channel_key',''), channel_id=row.get('channel_id',0), host_id=row.get('host_id',0), segment_id=row.get('segment_id'), command_id=row.get('command_id',''), message=row.get('message',''), error=row.get('error',''), pending=row.get('pending'), submitted=row.get('submitted'), generating=row.get('generating'), failed=row.get('failed'), downloaded=row.get('downloaded'), generation_ids=row.get('generation_ids'))
            # Account scans have no channel id, so the task-center telemetry path drops them.
            try:
                from app.services.flow_accounts import observe_page, plugin_account_report
                report = plugin_account_report(row)
                if report:
                    observe_page(report[0], report[1])
            except Exception as exc:
                runtime_log.log('flow_account_observe_failed', level='WARNING', error=str(exc)[:180])
            # Any authenticated event is proof that the browser extension is alive.
            self._last_heartbeat = now
            if row.get('type')=='generation_paused':
                from app.services.task_recovery import recover_unsubmitted
                recover_unsubmitted(str(row.get('command_id') or ''))
            if row.get('type') in ('generation_batch_finished','generation_paused'):
                typ=str(row.get('type') or '')
                deferred=int(row.get('deferred') or 0)
                command=str(row.get('command_id') or '')
                event_channel=str(row.get('channel_key') or '')
                # Submission-slot release is deliberately separate from render/download
                # ownership. Once every submit is confirmed (deferred=0), the same Flow
                # tab may immediately accept the next wave while old generations continue
                # rendering and downloading under their immutable generation_command.
                #
                # V0.13.5.83: pool waves use host_id=0 and the completion receipt can arrive
                # while the UI is already clearing/rebinding the local page state. Matching
                # only by (command + host_id) made a valid completion receipt occasionally
                # leave the Bridge job published. The channel then LOOKED idle in Studio but
                # the scheduler still treated the old command as occupied. Command identity
                # is immutable, so retire every Bridge job carrying this exact command and
                # release the command-guarded channel slot directly from the receipt.
                can_release_submission = typ=='generation_batch_finished' and deferred==0 and bool(command)
                matched_channels=[]
                kept_jobs=[]
                for job in self._host_jobs:
                    if str(job.get('command_id') or '') != command:
                        kept_jobs.append(job)
                        continue
                    ch=str(job.get('channel_key') or '')
                    if ch and ch not in matched_channels:
                        matched_channels.append(ch)
                    if can_release_submission and int(job.get('host_id') or 0)>0:
                        try:
                            if repo.get_host_task_command(int(job['host_id'])) == command:
                                repo.set_host_task_command(int(job['host_id']), '')
                        except Exception:
                            pass
                    if can_release_submission:
                        # Fully confirmed submission waves are retired, not merely
                        # disabled. Recovery of already submitted outputs still works
                        # through immutable generation_command + browser owner records.
                        # Removing the executable Bridge job prevents zombie jobs from
                        # inflating job_count or blocking the next wave.
                        continue
                    job['auto_execute'] = False
                    job['dispatch_tasks'] = False
                    kept_jobs.append(job)
                self._host_jobs=kept_jobs
                if can_release_submission:
                    release_keys=[]
                    for key in [event_channel,*matched_channels]:
                        key=str(key or '')
                        if key and key not in release_keys:
                            release_keys.append(key)
                    # Do not trust only the event's channel metadata. Release every
                    # channel that still owns this immutable command, guarded by the
                    # exact command_id so a newer wave can never be cleared.
                    try:
                        for c in repo.list_channel_pool(enabled_only=False):
                            if str(c['task_command_id'] or '')==command:
                                key=str(c['channel_key'] or '')
                                if key and key not in release_keys:
                                    release_keys.append(key)
                    except Exception:
                        pass
                    for release_key in release_keys:
                        try:
                            released=repo.release_channel_pool_submission_command(release_key, command)
                            if released:
                                runtime_log.log('channel_submission_slot_released_on_batch_finish',channel=release_key,command_id=command)
                        except Exception as exc:
                            runtime_log.log('channel_submission_slot_release_failed',level='WARNING',channel=release_key,command_id=command,error=str(exc))
                    runtime_log.log('completed_bridge_job_retired',command_id=command,channels=release_keys)
                repo.set_setting('flow_host_jobs_v124', json.dumps(self._host_jobs))
                self._host_jobs_version += 1
            if row.get('type')=='upload_verified':
                verified_cmd=str(row.get('command_id') or '')
                if verified_cmd:
                    before=len(self._host_jobs)
                    self._host_jobs=[j for j in self._host_jobs if not (
                        str(j.get('command_id') or '')==verified_cmd
                        and bool(j.get('execute_upload'))
                        and not bool(j.get('dispatch_tasks'))
                        and not bool(j.get('auto_execute'))
                    )]
                    if len(self._host_jobs)!=before:
                        repo.set_setting('flow_host_jobs_v124',json.dumps(self._host_jobs))
                        self._host_jobs_version+=1
                        runtime_log.log('completed_upload_only_bridge_job_retired',command_id=verified_cmd,removed=before-len(self._host_jobs))
            if row.get('type') in ('channel_focus_completed','channel_focus_failed'):
                self._focus_requests=[x for x in getattr(self,'_focus_requests',[]) if x['id']!=row.get('request_id')]
            self._events.append(row)
            etype = str(row.get("type") or "")
            host_id = row.get("host_id")
            if host_id is not None and (etype.startswith("web_plugin_") or etype.startswith("media_") or etype in {"upload_flow_progress","upload_verified","upload_drag_attempt"}):
                try:
                    hid = int(host_id)
                    snap = dict(self._web_plugin_hosts.get(hid) or {})
                    snap.update(row)
                    snap["host_id"] = hid
                    snap["last_seen"] = time.time()
                    self._web_plugin_hosts[hid] = snap
                    cid = int(event.get('channel_id') or 0)
                    if cid:
                        csnap = dict(self._web_plugin_channels.get(cid) or {})
                        csnap.update(event); csnap['last_seen'] = now
                        self._web_plugin_channels[cid] = csnap
                except Exception:
                    pass
            if str(row.get("type") or "").startswith("drive_"):
                self._drive_events.append(dict(row))
                if len(self._drive_events) > 500:
                    self._drive_events = self._drive_events[-500:]
            if len(self._events) > 500:
                self._events = self._events[-500:]

    def pop_events(self):
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events

    def publish_prep_jobs(self, jobs):
        with self._lock:
            self._prep_jobs = list(jobs or [])
            self._prep_version += 1
            return self._prep_version

    def clear_prep_jobs(self):
        return self.publish_prep_jobs([])

    def publish_host_jobs(self, jobs):
        with self._lock:
            sanitized=[]
            for original in (jobs or []):
                job=_sanitize_job_for_declared_date(original)
                if original.get('tasks') and not job.get('tasks') and (job.get('dispatch_tasks') or job.get('execute_upload')):
                    runtime_log.log('empty_cross_date_job_dropped',level='WARNING',command_id=job.get('command_id',''),work_date=job.get('work_date',''))
                    continue
                from app.services.eye_states import enrich_job
                job = enrich_job(job)
                sanitized.append(job)
            jobs=sanitized
            workflow.register_jobs(jobs or [])
            def ident(j):
                return (int(j.get('host_id') or 0), int(j.get('channel_id') or 0))
            incoming = {ident(j): j for j in (jobs or [])}
            if jobs:
                legacy_hosts={h for (h,c) in incoming if c==0}
                kept=[]
                for j in self._host_jobs:
                    key=ident(j)
                    if key in incoming: continue
                    if key[0] in legacy_hosts: continue
                    kept.append(j)
            else:
                kept=[]
            self._host_jobs = kept + list(incoming.values())
            repo.set_setting("flow_host_jobs_v124", json.dumps(self._host_jobs))
            self._host_jobs_version += 1
            runtime_log.log('publish_channel_jobs', version=self._host_jobs_version, jobs=[{'channel':j.get('channel_key',''),'command_id':j.get('command_id',''),'tasks':len(j.get('tasks') or []),'upload':bool(j.get('execute_upload')),'generate':bool(j.get('dispatch_tasks'))} for j in (jobs or [])])
            return self._host_jobs_version

    def clear_host_jobs(self):
        return self.publish_host_jobs([])

    def touch_host_jobs(self):
        """Bump the jobs version so every Flow tab re-reads settings / pause flags right away."""
        with self._lock:
            self._host_jobs_version += 1
            return self._host_jobs_version

    def remove_task_from_command(self, command, segment_id):
        with self._lock:
            for job in self._host_jobs:
                if job.get('command_id')==command:
                    job['tasks']=[t for t in job.get('tasks',[]) if int(t.get('segment_id') or 0)!=int(segment_id)]
            self._host_jobs=[j for j in self._host_jobs if j.get('tasks') or not j.get('dispatch_tasks')]
            self._host_jobs_version+=1
            repo.set_setting('flow_host_jobs_v124',json.dumps(self._host_jobs,ensure_ascii=False))

    def cancel_host_commands(self, command_ids):
        ids={str(x) for x in (command_ids or []) if str(x)}
        if not ids:return 0
        with self._lock:
            before=len(self._host_jobs)
            removed=[j for j in self._host_jobs if str(j.get('command_id') or '') in ids]
            self._host_jobs=[j for j in self._host_jobs if str(j.get('command_id') or '') not in ids]
            if removed:
                self._host_jobs_version += 1
                repo.set_setting('flow_host_jobs_v124', json.dumps(self._host_jobs,ensure_ascii=False))
                for j in removed:
                    if j.get('channel_key'):
                        try:repo.set_channel_pool_task_command(str(j['channel_key']),'')
                        except Exception:pass
            return before-len(self._host_jobs)

    def publish_drive_jobs(self, jobs):
        with self._lock:
            self._drive_jobs = list(jobs or [])
            self._drive_jobs_version += 1
            return self._drive_jobs_version

    def clear_drive_jobs(self):
        return self.publish_drive_jobs([])

    def pop_drive_events(self):
        with self._lock:
            events = list(self._drive_events)
            self._drive_events.clear()
        return events

    def set_generation_paused(self, paused):
        with self._lock:
            paused = bool(paused)
            if self._generation_paused != paused:
                self._generation_paused = paused
                self._control_version += 1
            return self._generation_paused

    def request_progress_scan(self):
        with self._lock:
            self._progress_scan_version += 1
            self._control_version += 1
            return self._progress_scan_version

    def generation_control(self):
        with self._lock:
            return {
                "ok": True,
                "paused": bool(self._generation_paused),
                "progress_scan_version": int(self._progress_scan_version),
                "control_version": int(self._control_version),
                "requested_at": time.time(),
            }

    def web_plugin_state(self, host_id=None):
        with self._lock:
            if host_id is not None:
                try:
                    return dict(self._web_plugin_hosts.get(int(host_id)) or {})
                except Exception:
                    return {}
            return [dict(v) for _, v in sorted(self._web_plugin_hosts.items())]

    def request_ch2_rebalance(self):
        from app.core.database import connect
        with self._lock:
            for job in self._host_jobs:
                if job.get('channel_key')!='CH2' or not job.get('dispatch_tasks'):continue
                if job.get('rebalance_request'):return
                command=job.get('command_id')
                with connect() as con:
                    waiting={r[0] for r in con.execute("SELECT id FROM flow_segments WHERE generation_command=? AND flow_status='已准备'",(command,))}
                ordered=[int(t['segment_id']) for t in job.get('tasks',[]) if int(t.get('segment_id') or 0) in waiting]
                if len(ordered)<=5:return
                job['rebalance_request']={'id':secrets.token_hex(16),'ids':ordered}
                repo.set_setting('flow_host_jobs_v124',json.dumps(self._host_jobs,ensure_ascii=False));self._host_jobs_version+=1
                return

    def ack_rebalance(self,data):
        from app.core.database import connect
        command=str(data.get('command_id') or '');owner=str(data.get('owner') or '')
        with self._lock:
            job=next((j for j in self._host_jobs if j.get('command_id')==command),None)
            req=job and job.get('rebalance_request')
            if not req or data.get('request_id')!=req['id'] or req.get('completed'):return []
            requested=set(req['ids']);safe={int(x) for x in data.get('safe_ids',[])}
            if not safe<=requested:raise ValueError('撤回确认包含未请求任务')
            with connect() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute('CREATE TABLE IF NOT EXISTS browser_command_owners(command_id TEXT PRIMARY KEY,owner TEXT NOT NULL)')
                old=con.execute('SELECT owner FROM browser_command_owners WHERE command_id=?',(command,)).fetchone()
                if old and old[0]!=owner:raise ValueError('撤回确认来自其他标签页')
                if not owner:raise ValueError('缺少插件身份')
                moved=[]
                for sid in safe:
                    current=con.execute("SELECT 1 FROM flow_segments WHERE id=? AND generation_command=? AND flow_status='已准备'",(sid,command)).fetchone()
                    submitted=con.execute("SELECT 1 FROM flow_dispatches WHERE segment_id=? AND command_id=? AND (submitted_at IS NOT NULL AND submitted_at<>'' OR status IN ('submitted','downloading','detected'))",(sid,command)).fetchone()
                    if not current or submitted:continue
                    con.execute("UPDATE flow_dispatches SET status='cancelled',stage='CANCELLED',error='插件确认未提交，返回普通队列均衡分配' WHERE segment_id=? AND command_id=?",(sid,command))
                    con.execute("UPDATE flow_segments SET generation_command='',flow_status='待生成',flow_channel_key='',flow_error='' WHERE id=?",(sid,));moved.append(sid)
                updated=json.loads(json.dumps(self._host_jobs))
                for j in updated:
                    if j.get('command_id')==command:
                        j['tasks']=[t for t in j.get('tasks',[]) if int(t.get('segment_id') or 0) not in moved]
                        # One handshake per existing batch; protected work stays owned by CH2.
                        j['rebalance_request']['completed']=True
                con.execute("INSERT OR REPLACE INTO app_settings(key,value) VALUES('flow_host_jobs_v124',?)",(json.dumps(updated,ensure_ascii=False),))
            self._host_jobs=updated;self._host_jobs_version+=1
            return moved

    def claim_command(self, command, owner, segment_id=None, recovery=False):
        from app.core.database import connect
        if not command or not owner:raise ValueError('缺少任务命令或浏览器身份')
        if recovery:
            # Recovery is bind-only. The original browser owner may recover an
            # already-submitted segment even after the channel receives a new wave.
            if segment_id is None:return False
            with connect() as con:
                con.execute('CREATE TABLE IF NOT EXISTS browser_command_owners(command_id TEXT PRIMARY KEY,owner TEXT NOT NULL)')
                row=con.execute("SELECT flow_status FROM flow_segments WHERE id=? AND generation_command=?",(int(segment_id),command)).fetchone()
                old=con.execute('SELECT owner FROM browser_command_owners WHERE command_id=?',(command,)).fetchone()
                return bool(row and row[0] != '已完成' and old and old[0]==owner)
        with self._lock:
            if not any(j.get('command_id')==command and j.get('dispatch_tasks') and (segment_id is None or any(int(t.get('segment_id') or 0)==int(segment_id) for t in j.get('tasks',[]))) for j in self._host_jobs):
                return False
        with connect() as con:
            if segment_id is not None and not con.execute('SELECT 1 FROM flow_segments WHERE id=? AND generation_command=?',(int(segment_id),command)).fetchone():return False
            con.execute('CREATE TABLE IF NOT EXISTS browser_command_owners(command_id TEXT PRIMARY KEY,owner TEXT NOT NULL)')
            con.execute('INSERT OR IGNORE INTO browser_command_owners VALUES(?,?)',(command,owner))
            return con.execute('SELECT owner FROM browser_command_owners WHERE command_id=?',(command,)).fetchone()[0]==owner

    def request_channel_focus(self, channel_id, url):
        with self._lock:
            state=self._web_plugin_channels.get(int(channel_id),{})
            if time.time()-float(state.get('last_seen') or 0)>20 or not state.get('browser_instance') or state.get('tab_id') is None:
                raise ValueError('该通道尚未回传浏览器定位信息。请打开对应浏览器，更新插件并刷新该通道网页，再试一次。')
            request={'id':secrets.token_hex(12),'browser_instance':state['browser_instance'],
                     'tab_id':state['tab_id'],'channel_id':int(channel_id),'url':url,'expires':time.time()+20}
            pending=getattr(self,'_focus_requests',[])
            self._focus_requests=[x for x in pending if x['expires']>time.time() and x['channel_id']!=int(channel_id)]+[request]
            return request['id']

    def focus_requests(self):
        with self._lock:
            self._focus_requests=[x for x in getattr(self,'_focus_requests',[]) if x['expires']>time.time()]
            return [dict(x) for x in self._focus_requests]

    def channel_state(self, channel_id=None):
        with self._lock:
            if channel_id is not None:
                return dict(self._web_plugin_channels.get(int(channel_id)) or {})
            return [dict(v) for _,v in sorted(self._web_plugin_channels.items())]

    def status(self):
        with self._lock:
            now = time.time()
            age = now - self._last_heartbeat if self._last_heartbeat else None
            host_ages = [now - float(v.get("last_seen") or 0) for v in self._web_plugin_hosts.values() if v.get("last_seen")]
            freshest_host_age = min(host_ages) if host_ages else None
            connected = bool((age is not None and age < 8.0) or (freshest_host_age is not None and freshest_host_age < 8.0))
            return {
                "ok": True,
                "connected": connected,
                "heartbeat_age": age,
                "web_plugin_age": freshest_host_age,
                "extension": dict(self._extension_meta),
                "queue_version": self._queue_version,
                "queue_count": len(self._queue),
                "port": self.port,
            }


_bridge = None

def get_bridge():
    global _bridge
    if _bridge is None:
        try:
            port = int(repo.get_setting("flow_bridge_port", "17831") or 17831)
        except (TypeError, ValueError):
            port = 17831
        _bridge = FlowStudioBridge(port=port)
    return _bridge
