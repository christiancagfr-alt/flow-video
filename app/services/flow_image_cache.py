"""flow_upload_images cache manager (the ONLY writer of that directory).

Identity model
  image_id    -> who the image is (stable, never derived from a physical path)
  cache_path  -> where the current file lives (rebindable)
  cache_revision / cache_source -> which version the cache currently holds

Rules
  * The original source is used only for the first initialisation and for an
    explicit restore_original_image().
  * An existing cache file is never overwritten by the original (no hash /
    mtime / size based "sync").
  * Layout: <root>/<YYYY-MM-DD>/<receiver>/<host>/<business filename>.
"""
from __future__ import annotations
import hashlib, os, re, shutil, sqlite3, threading, time, urllib.parse
from datetime import date as _date
from pathlib import Path

from app.core import database

ORIGINAL_INITIALIZED = 'ORIGINAL_INITIALIZED'
MANUAL_REPLACE = 'MANUAL_REPLACE'
STUDIO_REPLACE = 'STUDIO_REPLACE'
LEGACY_MIGRATED = 'LEGACY_MIGRATED'
PATH_REBOUND = 'PATH_REBOUND'
ORIGINAL_RESTORED = 'ORIGINAL_RESTORED'

_LOCK = threading.RLock()
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_DATE_RE = re.compile(r'(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])')


class FlowImageCacheError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ----------------------------------------------------------------- helpers
def cache_root() -> Path:
    return database.DB_PATH.parent / 'cache' / 'flow_upload_images'


def _registry_path() -> Path:
    return database.DB_PATH.parent / 'flow_image_cache.sqlite3'


def _log(event, level='INFO', **fields):
    try:
        from app.services import runtime_log
        runtime_log.log(event, level=level, **fields)
    except Exception:
        pass


def sanitize_path_component(value, fallback='未分类', limit=80) -> str:
    """Strip only filesystem-illegal characters; keep CJK, spaces, - and _."""
    s = _ILLEGAL.sub('_', str(value or '')).strip().strip('.').strip()
    s = s[:limit].strip().strip('.').strip()
    return s or fallback


def _normalize_date(value):
    if not value:
        return ''
    m = _DATE_RE.search(str(value))
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else ''


def _get(task, *names):
    for n in names:
        try:
            v = task.get(n) if hasattr(task, 'get') else task[n]
        except Exception:
            v = None
        if v not in (None, ''):
            return v
    return ''


def task_meta(task, raw_source='', work_date=None) -> dict:
    """work_date / receiver / host with the priority required by the spec."""
    d = (_normalize_date(work_date) or _normalize_date(_get(task, 'work_date'))
         or _normalize_date(_get(task, 'production_date'))
         or _normalize_date(Path(str(raw_source)).name)
         or _normalize_date(_get(task, 'batch_date')))
    if not d:
        try:
            from app.core import work_dates
            d = _normalize_date(work_dates.active())
        except Exception:
            d = ''
    d = d or _date.today().isoformat()
    return {
        'work_date': d,
        'receiver_name': str(_get(task, 'receiver_name', 'recipient_name') or ''),
        'host_name': str(_get(task, 'host_name', 'anchor_name') or ''),
        'recipient_id': str(_get(task, 'recipient_id') or ''),
        'host_id': str(_get(task, 'host_id') or ''),
    }


def _lookup_key(meta, raw):
    return hashlib.sha1(f"{meta['work_date']}|{meta['recipient_id']}|{meta['host_id']}|{raw}".encode()).hexdigest()


def _image_id(key):
    return 'IMG-' + key[:10].upper()


def _folder(meta) -> Path:
    return (cache_root() / meta['work_date'] / sanitize_path_component(meta['receiver_name'], '未分类接收人')
            / sanitize_path_component(meta['host_name'], '未分类主播'))


def _con():
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS flow_image_cache(
        image_id TEXT PRIMARY KEY, lookup_key TEXT UNIQUE,
        original_filename TEXT, original_source_path TEXT, source_size INTEGER, source_mtime_ns INTEGER,
        cache_path TEXT, cache_initialized INTEGER DEFAULT 0, cache_revision INTEGER DEFAULT 0,
        cache_source TEXT, work_date TEXT, receiver_name TEXT, host_name TEXT,
        recipient_id TEXT, host_id TEXT, source_changed INTEGER DEFAULT 0, updated_at REAL)""")
    return con


def _valid_file(p) -> bool:
    try:
        p = Path(p)
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _original_filename(raw, resolved: Path) -> str:
    u = urllib.parse.urlsplit(str(raw))
    if u.scheme in ('http', 'https'):
        name = Path(urllib.parse.unquote(u.path)).name
        return name if Path(name).suffix else (name or 'image') + (resolved.suffix or '.jpg')
    if u.scheme == 'file':
        return Path(urllib.parse.unquote(u.path)).name
    return Path(str(raw)).name or resolved.name


def _copy_atomic(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + '.' + os.urandom(4).hex() + '.tmp')
    try:
        shutil.copy2(src, tmp)
        if tmp.stat().st_size != Path(src).stat().st_size or tmp.stat().st_size <= 0:
            raise FlowImageCacheError('CACHE_COPY_FAILED', f'图片缓存写入校验失败：{dest.name}')
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _move(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dest)
    except OSError:
        _copy_atomic(src, dest)
        src.unlink(missing_ok=True)
    if not _valid_file(dest):
        raise FlowImageCacheError('CACHE_MOVE_FAILED', f'图片缓存移动失败：{dest}')
    _prune_empty(src.parent)


def _prune_empty(folder: Path):
    root = cache_root().resolve()
    try:
        folder = folder.resolve()
        while folder != root and root in folder.parents and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    except OSError:
        pass


def _owned_by_other(con, path: Path, image_id) -> bool:
    row = con.execute('SELECT image_id FROM flow_image_cache WHERE cache_path=? AND image_id<>?',
                      (str(path), image_id)).fetchone()
    return bool(row)


def build_flow_upload_cache_path(task, image, con=None) -> Path:
    """Single place that builds a path under flow_upload_images.

    image: dict with 'image_id' and 'original_filename' (and optional 'source_path').
    Same-name conflict between different image_ids -> <stem>__<image_id>.<ext>.
    """
    meta = task_meta(task, image.get('source_path') or image.get('original_source_path') or '',
                     image.get('work_date'))
    meta['receiver_name'] = image.get('receiver_name') or meta['receiver_name']
    meta['host_name'] = image.get('host_name') or meta['host_name']
    name = sanitize_path_component(image.get('original_filename') or 'image.jpg', 'image.jpg', 150)
    path = _folder(meta) / name
    iid = image.get('image_id') or ''
    close = False
    if con is None:
        con = _con(); close = True
    try:
        if _owned_by_other(con, path, iid):
            p = Path(name)
            path = path.with_name(f"{p.stem}__{iid.replace('-', '')}{p.suffix}")
    finally:
        if close:
            con.close()
    return path


def _save(con, row_id, **fields):
    fields['updated_at'] = time.time()
    con.execute('UPDATE flow_image_cache SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE image_id=?',
                (*fields.values(), row_id))
    con.commit()


def _row(con, **where):
    k, v = next(iter(where.items()))
    r = con.execute(f'SELECT * FROM flow_image_cache WHERE {k}=?', (v,)).fetchone()
    return dict(r) if r else None


def _scoped_candidates(con, row):
    """Safe search: current work_date/receiver scope only, image_id then filename."""
    base = cache_root() / row['work_date']
    scopes = [base / sanitize_path_component(row['receiver_name'], '未分类接收人'), base]
    stem = Path(row['original_filename'] or '').stem
    token = row['image_id'].replace('-', '')
    for scope in scopes:
        if not scope.is_dir():
            continue
        hits = []
        for p in scope.rglob('*'):
            if not p.is_file() or p.name.endswith('.tmp') or not _valid_file(p):
                continue
            if _owned_by_other(con, p, row['image_id']):
                continue
            if token in p.name or p.name == row['original_filename'] or p.name.startswith(stem + '__'):
                hits.append(p)
        if hits:
            return hits
    return []


def _legacy_names(row, source: Path | None):
    """Old flat names: <stem35>-<token20><ext> (token depends on source stat) and the plain filename."""
    out = []
    if source is not None:
        try:
            from app.services.channel_pool import safe_name
            st = source.stat()
            token = hashlib.sha256(f'{source.resolve()}|{st.st_size}|{st.st_mtime_ns}'.encode()).hexdigest()[:20]
            out.append(cache_root() / f'{safe_name(source.stem, 35)}-{token}{source.suffix.lower()}')
        except Exception:
            pass
    return out


def _try_resolve(con, row, meta=None):
    """Locate the current cache file WITHOUT touching the original. Returns Path or None."""
    cur = Path(row['cache_path']) if row.get('cache_path') else None
    if cur and _valid_file(cur):
        if meta and (meta['receiver_name'], meta['host_name']) != (row['receiver_name'], row['host_name']) \
                and meta['work_date'] == row['work_date']:
            cur = _relocate(con, row, meta) or cur
        return cur, 'REUSED'
    std = build_flow_upload_cache_path(meta or row, row, con)
    if _valid_file(std):
        _rebind(con, row, std, PATH_REBOUND)
        return std, 'REBOUND'
    flat = cache_root() / (row.get('original_filename') or '\0')
    if row.get('cache_initialized') and flat.parent == cache_root() and _valid_file(flat) \
            and not _owned_by_other(con, flat, row['image_id']):
        # legacy flat file: lazy migrate (copy, current cache_path then points to new location)
        _copy_atomic(flat, std)
        _rebind(con, row, std, LEGACY_MIGRATED)
        _log('FLOW_IMAGE_CACHE_LEGACY_FALLBACK', image_id=row['image_id'], legacy=str(flat), cache_path=str(std))
        return std, 'LEGACY'
    hits = _scoped_candidates(con, row)
    if len(hits) == 1:
        _rebind(con, row, hits[0], PATH_REBOUND)
        return hits[0], 'REBOUND'
    if len(hits) > 1:
        raise FlowImageCacheError('CACHE_PATH_AMBIGUOUS',
                                  f"图片缓存存在多个候选文件（CACHE_PATH_AMBIGUOUS），请重新绑定或替换图片：{row['original_filename']}")
    return None, 'MISSING'


def _rebind(con, row, path: Path, source):
    old = row.get('cache_path')
    _save(con, row['image_id'], cache_path=str(path), cache_initialized=1)
    row['cache_path'] = str(path)
    _log('FLOW_IMAGE_CACHE_REBOUND', image_id=row['image_id'], old=old, cache_path=str(path), source=source)


def _relocate(con, row, meta):
    """Classification changed: MOVE the current cache file (never re-copy the original)."""
    cur = Path(row['cache_path'])
    new_row = dict(row, receiver_name=meta['receiver_name'], host_name=meta['host_name'], work_date=meta['work_date'])
    dest = build_flow_upload_cache_path(meta, new_row, con)
    if dest == cur:
        _save(con, row['image_id'], receiver_name=meta['receiver_name'], host_name=meta['host_name'])
        return cur
    if dest.exists():
        return None
    _move(cur, dest)
    _save(con, row['image_id'], cache_path=str(dest), receiver_name=meta['receiver_name'],
          host_name=meta['host_name'], work_date=meta['work_date'])
    row.update(cache_path=str(dest), receiver_name=meta['receiver_name'], host_name=meta['host_name'])
    _log('FLOW_IMAGE_CACHE_REBOUND', image_id=row['image_id'], old=str(cur), cache_path=str(dest), source='RELOCATED')
    return dest


# ----------------------------------------------------------------- public API
def ensure_flow_upload_cache(image, task, work_date=None):
    """image: {'source_path': raw}. Returns the registry row (dict) with a valid cache_path."""
    raw = str(image.get('source_path') or '')
    meta = task_meta(task, raw, work_date)
    key = _lookup_key(meta, raw)
    with _LOCK:
        con = _con()
        try:
            row = _row(con, lookup_key=key)
            if row:
                path, how = _try_resolve(con, row, meta)
                if path:
                    if how == 'REUSED':
                        _note_source_change(con, row, raw)
                        _log('FLOW_IMAGE_CACHE_REUSED', image_id=row['image_id'], cache_path=str(path),
                             revision=row['cache_revision'])
                    return row
                if row['cache_initialized']:
                    raise FlowImageCacheError('CACHE_FILE_MISSING',
                                              f"图片缓存文件不存在：{row['cache_path']}。请重新绑定或替换图片（不会自动用原图覆盖）")
            # ---- first initialisation: the only automatic use of the original
            from app.services.image_assets import resolve_path
            source = resolve_path(raw)
            st = source.stat()
            if not row:
                iid = _image_id(key)
                con.execute('INSERT OR IGNORE INTO flow_image_cache(image_id,lookup_key,original_filename,'
                            'original_source_path,source_size,source_mtime_ns,cache_revision,work_date,'
                            'receiver_name,host_name,recipient_id,host_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (iid, key, _original_filename(raw, source), str(source), st.st_size, st.st_mtime_ns,
                             0, meta['work_date'], meta['receiver_name'], meta['host_name'],
                             meta['recipient_id'], meta['host_id'], time.time()))
                con.commit()
                row = _row(con, lookup_key=key)
            dest = build_flow_upload_cache_path(meta, row, con)
            if _valid_file(dest):                       # user pre-placed / left-over file: bind, no overwrite
                _finish_init(con, row, dest, PATH_REBOUND, st)
                return row
            for legacy in _legacy_names(row, source):
                if _valid_file(legacy):
                    _copy_atomic(legacy, dest)
                    _finish_init(con, row, dest, LEGACY_MIGRATED, st)
                    _log('FLOW_IMAGE_CACHE_LEGACY_FALLBACK', image_id=row['image_id'], legacy=str(legacy),
                         cache_path=str(dest))
                    return row
            _copy_atomic(source, dest)
            _finish_init(con, row, dest, ORIGINAL_INITIALIZED, st, source)
            return row
        finally:
            con.close()


def _finish_init(con, row, dest: Path, source_tag, st, source=None):
    _save(con, row['image_id'], cache_path=str(dest), cache_initialized=1,
          cache_revision=max(1, int(row.get('cache_revision') or 0)), cache_source=source_tag)
    row.update(cache_path=str(dest), cache_initialized=1, cache_revision=max(1, int(row.get('cache_revision') or 0)),
               cache_source=source_tag)
    _log('FLOW_IMAGE_CACHE_INITIALIZED', image_id=row['image_id'],
         source_path=str(source or row.get('original_source_path')), cache_path=str(dest),
         revision=row['cache_revision'], source=source_tag)


def _note_source_change(con, row, raw):
    """Record SOURCE_CHANGED only; the cache is never touched."""
    if row.get('source_changed'):
        return
    try:
        src = Path(row['original_source_path'])
        st = src.stat()
        if (st.st_size, st.st_mtime_ns) != (row['source_size'], row['source_mtime_ns']):
            _save(con, row['image_id'], source_changed=1)
            _log('FLOW_IMAGE_SOURCE_CHANGED', image_id=row['image_id'], source_path=str(src))
    except OSError:
        pass


def resolve_flow_upload_image(image_id, task=None) -> Path:
    """Path to hand to the plugin. Verified: exists, is_file, size>0. Never copies the original."""
    with _LOCK:
        con = _con()
        try:
            row = _row(con, image_id=image_id)
            if not row:
                raise FlowImageCacheError('CACHE_UNKNOWN_IMAGE', f'未知图片 ID：{image_id}')
            meta = task_meta(task, row.get('original_source_path') or '', row['work_date']) if task is not None else None
            path, _ = _try_resolve(con, row, meta)
            if not path or not _valid_file(path):
                raise FlowImageCacheError('CACHE_FILE_MISSING',
                                          f"图片缓存文件不存在：{row.get('cache_path')}（可重新绑定或替换图片）")
            return path.resolve()
        finally:
            con.close()


def resolve_for_task(task, work_date=None):
    """Return a verified cache Path for the task's current image_path if it is already cached (no original access)."""
    raw = str(_get(task, 'image_path') or '')
    meta = task_meta(task, raw, work_date)
    with _LOCK:
        con = _con()
        try:
            row = _row(con, lookup_key=_lookup_key(meta, raw))
            if not row:
                return None
            path, _ = _try_resolve(con, row, meta)
            return path.resolve() if path and _valid_file(path) else None
        finally:
            con.close()


def replace_flow_upload_cache(image_id, new_file, source=MANUAL_REPLACE) -> Path:
    """Explicit user action: overwrite the current cache with new_file; identity & business name stay."""
    new_file = Path(new_file).expanduser()
    if not _valid_file(new_file):
        raise FlowImageCacheError('REPLACE_SOURCE_INVALID', f'替换图片不可读取：{new_file}')
    with _LOCK:
        con = _con()
        try:
            row = _row(con, image_id=image_id)
            if not row:
                raise FlowImageCacheError('CACHE_UNKNOWN_IMAGE', f'未知图片 ID：{image_id}')
            dest = Path(row['cache_path']) if row.get('cache_path') else build_flow_upload_cache_path(row, row, con)
            _copy_atomic(new_file, dest)
            rev = int(row.get('cache_revision') or 0) + 1
            _save(con, image_id, cache_path=str(dest), cache_initialized=1, cache_revision=rev, cache_source=source)
            _log('FLOW_IMAGE_CACHE_REPLACED', image_id=image_id, cache_path=str(dest), revision=rev, source=source)
            return dest
        finally:
            con.close()


def restore_original_image(image_id) -> Path:
    """Explicit 'restore original': the only way the original overwrites an existing cache."""
    with _LOCK:
        con = _con()
        try:
            row = _row(con, image_id=image_id)
            if not row:
                raise FlowImageCacheError('CACHE_UNKNOWN_IMAGE', f'未知图片 ID：{image_id}')
        finally:
            con.close()
    from app.services.image_assets import resolve_path
    src = resolve_path(row['original_source_path'])
    return replace_flow_upload_cache(image_id, src, ORIGINAL_RESTORED)


def relocate_flow_upload_cache(image_id, *, work_date=None, receiver_name=None, host_name=None) -> Path:
    """Explicit reclassification (date / receiver / host): MOVE current cache, image_id unchanged."""
    with _LOCK:
        con = _con()
        try:
            row = _row(con, image_id=image_id)
            if not row:
                raise FlowImageCacheError('CACHE_UNKNOWN_IMAGE', f'未知图片 ID：{image_id}')
            path, _ = _try_resolve(con, row, None)
            if not path:
                raise FlowImageCacheError('CACHE_FILE_MISSING', f"图片缓存文件不存在：{row.get('cache_path')}")
            meta = {'work_date': _normalize_date(work_date) or row['work_date'],
                    'receiver_name': receiver_name if receiver_name is not None else row['receiver_name'],
                    'host_name': host_name if host_name is not None else row['host_name'],
                    'recipient_id': row['recipient_id'], 'host_id': row['host_id']}
            dest = build_flow_upload_cache_path(meta, dict(row, work_date=None, receiver_name=None, host_name=None), con)
            if dest != path:
                if dest.exists():
                    raise FlowImageCacheError('CACHE_TARGET_EXISTS', f'目标位置已存在文件：{dest}')
                _move(path, dest)
            raw_key_old = row['lookup_key']
            fields = dict(cache_path=str(dest), work_date=meta['work_date'],
                          receiver_name=meta['receiver_name'], host_name=meta['host_name'])
            if meta['work_date'] != row['work_date']:
                # keep lookups by the task's new date pointing at the same image_id
                raw = row['original_source_path']
                fields['lookup_key'] = _lookup_key(meta, raw)
            _save(con, image_id, **fields)
            _log('FLOW_IMAGE_CACHE_REBOUND', image_id=image_id, old=str(path), cache_path=str(dest), source='RELOCATE')
            return dest
        finally:
            con.close()


def cache_folder_for_task(task, work_date=None) -> Path:
    """Folder for the 'open cache folder' action."""
    meta = task_meta(task, '', work_date)
    return _folder(meta)


def is_cache_path_referenced(path) -> bool:
    """Cleanup guard: True if any image record currently points at this file."""
    with _LOCK:
        con = _con()
        try:
            return bool(con.execute('SELECT 1 FROM flow_image_cache WHERE cache_path=?', (str(path),)).fetchone())
        finally:
            con.close()
