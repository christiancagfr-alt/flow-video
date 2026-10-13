"""Flow login accounts, credit estimates, and submit-time rotation.

Passwords and authenticator secrets stay in the OS credential store.
The video plugin's submit and download path is unchanged. This module only
decides how many waiting videos the current account can still pay for.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from pathlib import Path

from app.core.database import connect
from app.core import repository as repo
from app.services.app_paths import data_dir
from app.services.credential_file import CredentialStoreError

SERVICE = 'com.flowstudio.flow-account'
DAILY_QUOTA = 50
_LOCK = threading.Lock()
_REQUEST = None
_OBSERVED = {'key': None, 'at': 0.0}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_login_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '未登录',
    credits_remaining INTEGER,
    credits_checked_at TEXT NOT NULL DEFAULT '',
    daily_quota INTEGER NOT NULL DEFAULT 50,
    last_error TEXT NOT NULL DEFAULT '',
    last_attempt REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 0,
    chrome_profile TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_table():
    with connect() as con:
        con.executescript(_SCHEMA)
        columns = {row[1] for row in con.execute('PRAGMA table_info(flow_login_accounts)')}
        if 'chrome_profile' not in columns:
            con.execute("ALTER TABLE flow_login_accounts ADD COLUMN chrome_profile TEXT NOT NULL DEFAULT ''")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('flow_account_credit_cost','10')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('flow_account_rotation','1')")
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('flow_account_sheet_url','')")


def credit_cost():
    ensure_table()
    try:
        value = int(repo.get_setting('flow_account_credit_cost', '10') or 10)
    except (TypeError, ValueError):
        value = 10
    return max(0, value)


def set_credit_cost(value):
    cost = max(1, int(value))
    repo.set_setting('flow_account_credit_cost', str(cost))
    return cost


def rotation_enabled():
    ensure_table()
    return repo.get_setting('flow_account_rotation', '1') != '0'


def set_rotation_enabled(enabled):
    repo.set_setting('flow_account_rotation', '1' if enabled else '0')


_ACCOUNT_SORTS = ('ready', 'points_desc', 'points_asc', 'name', 'default')


def only_logged_flow():
    ensure_table()
    return repo.get_setting('flow_account_only_logged_in', '0') == '1'


def set_only_logged_flow(enabled):
    repo.set_setting('flow_account_only_logged_in', '1' if enabled else '0')


def account_sort_mode():
    ensure_table()
    mode = repo.get_setting('flow_account_sort', 'ready') or 'ready'
    return mode if mode in _ACCOUNT_SORTS else 'ready'


def set_account_sort_mode(mode):
    chosen = mode if mode in _ACCOUNT_SORTS else 'ready'
    repo.set_setting('flow_account_sort', chosen)
    return chosen


def totp_code(secret, timestamp=None, digits=6, period=30):
    """RFC 6238 TOTP from a base32 authenticator secret."""
    cleaned = re.sub(r'[\s-]', '', str(secret or '')).upper()
    if len(cleaned) < 8 or not re.fullmatch(r'[A-Z2-7]+', cleaned):
        raise ValueError('二步验证需要验证器密钥，不是 6 位动态码')
    padded = cleaned + '=' * ((8 - len(cleaned) % 8) % 8)
    try:
        key = base64.b32decode(padded, casefold=True)
    except Exception as exc:
        raise ValueError('二步验证密钥不是有效的验证器密钥') from exc
    if not key:
        raise ValueError('二步验证密钥不是有效的验证器密钥')
    moment = time.time() if timestamp is None else float(timestamp)
    counter = int(moment // period)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    binary = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff
    return str(binary % (10 ** digits)).zfill(digits)


def parse_account_text(text):
    """Read an email and a credit balance out of Flow page text."""
    raw = str(text or '')
    email_match = re.search(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}', raw, re.I)
    patterns = (
        r'(\d[\d,]*)\s*个\s*Google\s*Flow\s*点数',
        r'(\d[\d,]*)\s*个\s*点数',
        r'(\d[\d,]*)\s*(?:Google\s*Flow\s*)?credits?',
        r'(\d[\d,]*)\s*(?:credits?|积分)',
        r'(?:credits?|积分|剩余|余额)\s*[:：]?\s*(\d[\d,]*)',
    )
    credits = None
    for pattern in patterns:
        found = re.search(pattern, raw, re.I)
        if found:
            credits = int(found.group(1).replace(',', ''))
            break
    return {'email': email_match.group(0) if email_match else '', 'credits': credits}


def parse_account_rows(rows):
    """A=email, B=password, C=authenticator secret. A header row is skipped."""
    imported = []
    skipped = []
    header = {'邮箱', 'email', '账号', '帐号', 'mail', 'e-mail'}
    for index, row in enumerate(rows or [], start=1):
        cells = list(row or [])
        while len(cells) < 3:
            cells.append('')
        email = str(cells[0] or '').strip()
        password = str(cells[1] or '').strip()
        secret = str(cells[2] or '').strip()
        if not email and not password and not secret:
            continue
        if index == 1 and email.lower() in header and '@' not in email:
            continue
        if '@' not in email:
            skipped.append(f'第 {index} 行没有有效邮箱')
            continue
        if secret:
            try:
                totp_code(secret, timestamp=0)
            except ValueError as exc:
                skipped.append(f'第 {index} 行 {email}：{exc}')
                continue
        imported.append({'email': email, 'password': password, 'totp_secret': secret})
    return {'accounts': imported, 'skipped': skipped}


def usable_credits(account, today):
    checked = str(account.get('credits_checked_at') or '')[:10]
    remaining = account.get('credits_remaining')
    quota = int(account.get('daily_quota') or DAILY_QUOTA)
    if remaining is not None and remaining != '' and checked == today:
        return max(0, int(remaining)), False
    return max(0, quota), True


def plan_submission(accounts, task_count, rounds, cost, today):
    """How many generations each account can take, in list order."""
    rounds = max(1, int(rounds or 1))
    cost = int(cost or 0)
    need = max(0, int(task_count)) * rounds
    left = need
    assignments = []
    for account in accounts:
        if not int(account.get('enabled', 1)):
            continue
        credits, estimated = usable_credits(account, today)
        capacity = 0 if cost <= 0 else credits // cost
        take = min(capacity, left)
        if take <= 0:
            continue
        assignments.append({
            'id': account.get('id'),
            'email': account.get('email') or '',
            'credits': credits,
            'estimated': estimated,
            'generations': take,
            'videos': take // rounds,
        })
        left -= take
        if left <= 0:
            break
    return {
        'task_count': int(task_count or 0),
        'rounds': rounds,
        'cost': cost,
        'generations': need,
        'assignments': assignments,
        'accounts_needed': len(assignments),
        'generations_covered': need - left,
        'shortfall': left,
    }


def format_plan(plan):
    lines = []
    for item in plan.get('assignments') or []:
        state = '按每天 50 点数估算' if item.get('estimated') else '已核对页面'
        lines.append(f"{item['email']}：可生成 {item['generations']} 次，约 {item['videos']} 条（剩余 {item['credits']} 点数，{state}）")
    if plan.get('shortfall'):
        lines.append(f"全部账号合计还差 {plan['shortfall']} 次生成")
    if not lines:
        if int(plan.get('task_count') or 0) <= 0:
            lines.append('当前没有等待提交的视频。插件连上后按每天 50 点数计算还能生成几条。')
        else:
            lines.append('当前没有还能生成的账号')
    return '\n'.join(lines)


def _observed_addresses(observed):
    """Accept one email, a list of emails, or rows from observed_pages()."""
    if isinstance(observed, str) or observed is None:
        text = str(observed or '').strip().lower()
        return [text] if text else []
    found = []
    for item in observed or []:
        if isinstance(item, dict):
            text = str(item.get('email') or '')
        else:
            text = str(item or '')
        text = text.strip().lower()
        if text and text not in found:
            found.append(text)
    return found


def row_ready(account, observed):
    """Ready when any plugin-reported Flow page uses this row's email."""
    left = str((account or {}).get('email') or '').strip().lower()
    return bool(left) and left in _observed_addresses(observed)


def display_status(account, observed):
    if not row_ready(account, observed):
        return '未连接'
    if str((account or {}).get('status') or '') == '积分不足':
        return '就绪（点数不足）'
    return '就绪'


def _note_addresses(observed):
    """Original spelling for the on-screen sentence. A plain string stays one address."""
    if isinstance(observed, str) or observed is None:
        text = str(observed or '').strip()
        return [text] if text else []
    found = []
    seen = set()
    for item in observed or []:
        if isinstance(item, dict):
            text = str(item.get('email') or '').strip()
        else:
            text = str(item or '').strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            found.append(text)
    return found


def display_note(account, observed, estimated):
    """On-screen note. A stale login error does not mean this row is connected."""
    account = account or {}
    emails = _note_addresses(observed)
    if row_ready(account, emails):
        note = '按每天 50 点数估算' if estimated else '已核对页面'
        if str(account.get('status') or '') == '积分不足':
            note = '点数不足 · ' + note
    elif len(emails) == 1 and (isinstance(observed, str) or observed is None):
        note = f'当前页面是 {emails[0]}，不是这一行'
    elif emails:
        note = '插件读到的是 ' + '、'.join(emails[:4]) + '，不是这一行'
    else:
        note = '还没有读到这一行的 Flow 页面。请在这个 Chrome 用户里装上插件并打开 Flow'
    profile = str(account.get('chrome_profile') or '').strip()
    if profile:
        note = f'Chrome 用户 {profile} · {note}'
    return note


def connection_summary(accounts, observed):
    """One sentence for the box above the account table. Do not append the scheduler plan."""
    rows = list(accounts or [])
    if isinstance(observed, str) or observed is None:
        seen = str(observed or '').strip()
        if not seen:
            return '还没有就绪。插件没有读到 Flow 页面邮箱。每个 Chrome 用户都要自己装上插件并打开 Flow，插件上的“已连接”只代表这个窗口能连上软件。'
        matched = next((account for account in rows if row_ready(account, seen)), None)
        if matched:
            email = matched.get('email') or seen
            return f'已就绪：{email}。这一行是绿色，其余账号是灰色。'
        return f'插件已连上 Flow，当前页面是 {seen}。这个邮箱不在下面的列表里，所以没有一行就绪，下面全部是灰色。'
    emails = _note_addresses(observed)
    if not emails:
        return '还没有就绪。插件没有读到 Flow 页面邮箱。每个 Chrome 用户都要自己装上插件并打开 Flow，插件上的“已连接”只代表这个窗口能连上软件。'
    ready = [str(account.get('email') or '') for account in rows if row_ready(account, emails)]
    listed = {str(account.get('email') or '').strip().lower() for account in rows}
    missing = [email for email in emails if email.lower() not in listed]
    parts = []
    if ready:
        parts.append(f'已就绪 {len(ready)} 个：' + '、'.join(ready) + '。这些行是绿色。')
    else:
        parts.append('插件已经读到 Flow 页面，但没有一个邮箱在下面的列表里，所以没有一行就绪。')
    if missing:
        parts.append('还读到了不在列表里的：' + '、'.join(missing) + '。')
    gray = len(rows) - len(ready)
    if gray:
        parts.append(f'另外 {gray} 行是灰色。每个 Chrome 用户都要自己装上插件并打开 Flow，插件上的“已连接”只代表这个窗口能连上软件。')
    elif rows:
        parts.append('列表里的账号都已就绪。')
    return ''.join(parts)


def limit_tasks(accounts, tasks, rounds, cost, observed_email='', pending_action='', pending_email='', today=''):
    """Return the videos the logged-in account can pay for.

    An empty account list does not change the task list. A login that is already
    running waits instead of submitting on the previous account.
    """
    tasks = list(tasks or [])
    ordered = [account for account in accounts if int(account.get('enabled', 1))]
    ordered.sort(key=lambda account: (int(account.get('sort_order') or 0), int(account.get('id') or 0)))
    plan = plan_submission(ordered, len(tasks), rounds, cost, today)
    result = {
        'apply': bool(ordered), 'hold': False, 'tasks': tasks, 'account_id': None,
        'message': '', 'detail': format_plan(plan), 'switch_to': '', 'plan': plan,
    }
    if not ordered:
        result['apply'] = False
        return result
    rounds = max(1, int(rounds or 1))
    cost = int(cost or 0)
    if cost <= 0:
        result.update(hold=True, tasks=[], message='请在账号管理填写每条视频消耗的点数')
        return result
    if pending_action == 'login' and pending_email:
        result.update(hold=True, tasks=[], message=f'正在登录 {pending_email}')
        return result

    def generations(account):
        credits, _estimated = usable_credits(account, today)
        return 0 if cost <= 0 else credits // cost

    observed = str(observed_email or '').strip().lower()
    current = None
    if observed:
        current = next((account for account in ordered if account['email'].lower() == observed), None)
        if current is None:
            target = next((account for account in ordered if generations(account) >= rounds), ordered[0])
            result.update(hold=True, tasks=[], switch_to=target['email'],
                          message=f'页面上的账号未导入，准备登录 {target["email"]}')
            return result
        if generations(current) < rounds:
            nxt = next((account for account in ordered if account.get('id') != current.get('id') and generations(account) >= rounds), None)
            if nxt is None:
                result.update(hold=True, tasks=[], message='已导入的账号点数都不够下一条视频')
                return result
            result.update(hold=True, tasks=[], switch_to=nxt['email'],
                          message=f'当前账号点数不足，正在切换到 {nxt["email"]}')
            return result
    else:
        # The page has not reported an account yet. Cap by the ledger, but do not
        # block the existing plugin or start a login on every scheduler tick.
        current = next((account for account in ordered if generations(account) >= rounds), None)
        if current is None:
            result.update(hold=True, tasks=[], message='已导入的账号点数都不够下一条视频')
            return result
    capacity = generations(current) // rounds
    chosen = tasks[:capacity]
    credits, estimated = usable_credits(current, today)
    note = '，按每天 50 点数估算' if estimated else ''
    message = (f'{current["email"]} 剩余 {credits} 点数{note}，还可提交 {capacity} 条'
               f' · 本批 {len(tasks)} 条需要 {plan["accounts_needed"]} 个账号')
    if plan['shortfall']:
        message += f' · 全部账号仍差 {plan["shortfall"]} 次生成'
    result.update(tasks=chosen, account_id=current.get('id'), message=message)
    return result


def _row(row):
    return {
        'id': int(row['id']),
        'email': str(row['email'] or ''),
        'enabled': int(row['enabled'] or 0),
        'sort_order': int(row['sort_order'] or 0),
        'status': str(row['status'] or ''),
        'credits_remaining': None if row['credits_remaining'] is None else int(row['credits_remaining']),
        'credits_checked_at': str(row['credits_checked_at'] or ''),
        'daily_quota': int(row['daily_quota'] or DAILY_QUOTA),
        'last_error': str(row['last_error'] or ''),
        'last_attempt': float(row['last_attempt'] or 0),
        'active': int(row['active'] or 0),
        'chrome_profile': str(row['chrome_profile'] or '') if 'chrome_profile' in row.keys() else '',
    }


def list_accounts(enabled_only=False):
    ensure_table()
    sql = 'SELECT * FROM flow_login_accounts'
    if enabled_only:
        sql += ' WHERE enabled=1'
    sql += ' ORDER BY sort_order, id'
    with connect() as con:
        return [_row(row) for row in con.execute(sql)]


def get_account(account_id):
    ensure_table()
    with connect() as con:
        row = con.execute('SELECT * FROM flow_login_accounts WHERE id=?', (int(account_id),)).fetchone()
    if not row:
        raise ValueError('账号不存在')
    return _row(row)


def _secret_path(email):
    digest = hashlib.sha256(email.strip().lower().encode('utf-8')).hexdigest()
    return data_dir() / 'flow_account_secrets' / f'{digest}.json', digest


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    if os.name != 'nt':
        os.chmod(temporary, 0o600)
    temporary.replace(path)


def _dpapi_wrap(text):
    import win32crypt
    encrypted = win32crypt.CryptProtectData(text.encode('utf-8'), 'Flow Studio Flow Account', None, None, None, 1)
    return json.dumps({'windows_dpapi': base64.b64encode(encrypted).decode('ascii')})


def save_secret(email, password, totp_secret):
    payload = json.dumps({'password': password, 'totp_secret': totp_secret}, ensure_ascii=False)
    path, digest = _secret_path(email)
    if os.name == 'nt':
        _atomic_write(path, _dpapi_wrap(payload))
        return
    from app.services.credential_pool import backend
    vault = backend()
    account = 'flow-account:' + digest
    vault.set_password(SERVICE, account, payload)
    stored = vault.get_password(SERVICE, account)
    if stored != payload:
        raise CredentialStoreError('系统凭据库回读校验失败，未保存 Flow 账号。')
    _atomic_write(path, json.dumps({'keyring': {'service': SERVICE, 'account': account}}, ensure_ascii=False))


def load_secret(email):
    path, _digest = _secret_path(email)
    if not path.is_file():
        raise CredentialStoreError('找不到该账号的登录信息，请重新导入。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, dict) and 'windows_dpapi' in data:
        if os.name != 'nt':
            raise CredentialStoreError('这个账号的登录信息保存在 Windows 凭据里，需要在 Windows 上使用。')
        import win32crypt
        blob = base64.b64decode(data['windows_dpapi'])
        raw = win32crypt.CryptUnprotectData(blob, None, None, None, 1)[1].decode('utf-8')
        return json.loads(raw)
    if isinstance(data, dict) and 'keyring' in data:
        from app.services.credential_pool import backend
        info = data['keyring']
        stored = backend().get_password(info.get('service') or SERVICE, info.get('account') or '')
        if not stored:
            raise CredentialStoreError('系统凭据库里找不到该账号，请重新导入。')
        return json.loads(stored)
    raise CredentialStoreError('登录信息格式无效，请重新导入。')


def delete_secret(email):
    path, digest = _secret_path(email)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            data = None
        if isinstance(data, dict) and 'keyring' in data and os.name != 'nt':
            from app.services.credential_pool import backend
            info = data['keyring']
            try:
                backend().delete_password(info.get('service') or SERVICE, info.get('account') or '')
            except Exception:
                pass
        path.unlink()
    if os.name != 'nt':
        from app.services.credential_pool import backend
        try:
            backend().delete_password(SERVICE, 'flow-account:' + digest)
        except Exception:
            pass


def add_account(email, password='', totp_secret='', enabled=True, chrome_profile=''):
    email = str(email or '').strip()
    password = str(password or '')
    totp_secret = str(totp_secret or '').strip()
    chrome_profile = str(chrome_profile or '').strip()
    if '@' not in email:
        raise ValueError('请填写邮箱')
    if totp_secret:
        totp_code(totp_secret, timestamp=0)
    if password or totp_secret:
        save_secret(email, password, totp_secret)
    ensure_table()
    with connect() as con:
        existing = con.execute('SELECT id FROM flow_login_accounts WHERE lower(email)=lower(?)', (email,)).fetchone()
        if existing:
            if chrome_profile:
                con.execute(
                    'UPDATE flow_login_accounts SET enabled=?, chrome_profile=? WHERE id=?',
                    (1 if enabled else 0, chrome_profile, int(existing['id'])))
            else:
                con.execute('UPDATE flow_login_accounts SET enabled=? WHERE id=?', (1 if enabled else 0, int(existing['id'])))
            account_id = int(existing['id'])
        else:
            order = con.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM flow_login_accounts').fetchone()[0]
            cur = con.execute(
                'INSERT INTO flow_login_accounts(email,enabled,sort_order,status,daily_quota,chrome_profile) VALUES(?,?,?,?,?,?)',
                (email, 1 if enabled else 0, int(order), '未登录', DAILY_QUOTA, chrome_profile))
            account_id = int(cur.lastrowid)
    return get_account(account_id)


def delete_account(account_id):
    account = get_account(account_id)
    delete_secret(account['email'])
    with connect() as con:
        con.execute('DELETE FROM flow_login_accounts WHERE id=?', (account['id'],))


def set_enabled(account_id, enabled):
    ensure_table()
    with connect() as con:
        con.execute('UPDATE flow_login_accounts SET enabled=? WHERE id=?', (1 if enabled else 0, int(account_id)))


def set_remaining(account_id, credits):
    value = max(0, int(credits))
    stamp = _dt.datetime.now().isoformat(timespec='seconds')
    with connect() as con:
        con.execute(
            'UPDATE flow_login_accounts SET credits_remaining=?, credits_checked_at=?, status=CASE WHEN ?>=? THEN ? ELSE ? END WHERE id=?',
            (value, stamp, value, credit_cost(), '已核对', '积分不足', int(account_id)))
    return get_account(account_id)


def import_sheet(url):
    rows = _read_sheet_rows(url)
    parsed = parse_account_rows(rows)
    saved = []
    for account in parsed['accounts']:
        saved.append(add_account(account['email'], account['password'], account['totp_secret']))
    repo.set_setting('flow_account_sheet_url', str(url or '').strip())
    return {'imported': len(saved), 'skipped': parsed['skipped'], 'accounts': saved}


def _read_sheet_rows(url):
    raw = str(url or '').strip()
    if not raw:
        raise ValueError('请先填写表格链接')
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', raw)
    if not match:
        raise ValueError('表格链接里没有 Google 表格编号')
    sid = match.group(1)
    from urllib.parse import parse_qs, urlparse
    gid = (parse_qs(urlparse(raw).query).get('gid') or [''])[0]
    if not gid:
        found = re.search(r'[#&]gid=(\d+)', raw)
        gid = found.group(1) if found else '0'
    from app.services.pre_gpt_pipeline import google_services, resolve_sheet_title
    _drive, sheets = google_services(interactive=False)
    if sheets:
        title = resolve_sheet_title(sheets, sid, gid).replace("'", "''")
        result = sheets.spreadsheets().values().get(spreadsheetId=sid, range=f"'{title}'!A:C").execute()
        return result.get('values') or []
    from app.services.task_intake import fetch_csv_public
    import csv
    import io
    text = fetch_csv_public(raw)
    return list(csv.reader(io.StringIO(text)))


def sheet_url():
    ensure_table()
    return repo.get_setting('flow_account_sheet_url', '')


def public_request():
    with _LOCK:
        if not _REQUEST or _REQUEST.get('done'):
            return {'account_request': None}
        return {'account_request': {
            'id': _REQUEST['id'], 'email': _REQUEST['email'], 'action': _REQUEST['action'],
        }}


def request_action(account_id, action):
    account = get_account(account_id)
    action = 'login' if action == 'login' else 'read'
    now = time.time()
    with _LOCK:
        global _REQUEST
        _REQUEST = {
            'id': secrets.token_hex(8), 'account_id': account['id'], 'email': account['email'],
            'action': action, 'done': False,
        }
        request_id = _REQUEST['id']
    with connect() as con:
        con.execute(
            'UPDATE flow_login_accounts SET status=?, last_attempt=?, last_error=? WHERE id=?',
            ('登录中' if action == 'login' else account['status'], now, '', account['id']))
    return request_id


def credential_for(request_id):
    with _LOCK:
        current = dict(_REQUEST) if _REQUEST else None
    if not current or current.get('done') or current.get('id') != str(request_id or ''):
        raise ValueError('登录请求已结束')
    # The plugin only checks whether this Chrome profile already has Flow open.
    # Never return the stored password, authenticator secret, or a live code.
    action = 'login' if current.get('action') == 'login' else 'read'
    return {'ok': True, 'action': action, 'email': current['email']}


def login_failure_status(error):
    """Checking credits never means the account needs Google verification."""
    return '失败'


def interpret_credit_check(account_email, account_status, observed_email, observed_credits):
    """Read credits already seen on the open Flow page. Never ask Google to verify."""
    email = str(observed_email or '').strip()
    status = '已登录' if account_status == '需要验证' else account_status
    credits = None
    raw = str(observed_credits or '').strip()
    if raw:
        try:
            credits = max(0, int(raw))
        except ValueError:
            credits = None
    same = bool(email) and email.lower() == str(account_email or '').lower()
    if credits is not None and (not email or same):
        return {
            'apply_email': account_email, 'credits': credits, 'status': status, 'note': '',
            'message': f'这一行已就绪。页面剩余 {credits} 点数。',
        }
    if credits is not None and email:
        return {
            'apply_email': email, 'credits': credits, 'status': status,
            'note': f'当前页面是 {email}，不是这一行',
            'message': f'这一行还没就绪。当前页面是 {email}，点数记在那个账号上。',
        }
    if same:
        logged = status if status in ('已登录', '积分不足', '已核对') else '已登录'
        return {
            'apply_email': '', 'credits': None, 'status': logged, 'note': '',
            'message': '这一行已就绪。页面上还没有读到点数，仍按每天 50 点数估算。请在 chrome://extensions 把 Flow Studio 插件重新加载到 0.9.67，打开 Flow 右上角账号卡片后再点一次检查。',
        }
    if not email:
        return {
            'apply_email': '', 'credits': None, 'status': status,
            'note': '还没有读到 Flow 页面邮箱',
            'message': '插件还没有读到 Flow 页面邮箱。打开对应的 Flow 页面后，和这一行相同才会就绪。',
        }
    return {
        'apply_email': '', 'credits': None, 'status': status,
        'note': f'当前页面是 {email}，不是这一行',
        'message': f'这一行还没就绪。插件读到的页面是 {email}。',
    }


def automatic_login_allowed(account, now):
    """One automatic attempt. A failed or already-opened profile waits for the user."""
    error = str(account.get('last_error') or '').strip()
    if error.startswith('已打开'):
        return False
    if str(account.get('status') or '') in ('失败', '需要验证') and error:
        return False
    return float(now) - float(account.get('last_attempt') or 0) >= 60


def finish_request(data):
    request_id = str((data or {}).get('id') or '')
    with _LOCK:
        current = dict(_REQUEST) if _REQUEST else None
        if not current or current.get('id') != request_id:
            raise ValueError('登录请求已结束')
        _REQUEST['done'] = True
    text = str((data or {}).get('text') or '')[:4000]
    parsed = parse_account_text(text) if text else {'email': '', 'credits': None}
    email = str((data or {}).get('email') or parsed['email'] or current['email']).strip()
    credits = (data or {}).get('credits')
    if credits is None:
        credits = parsed['credits']
    error = str((data or {}).get('error') or '')[:300]
    ok = bool((data or {}).get('ok'))
    account = get_account(current['account_id'])
    now = _dt.datetime.now().isoformat(timespec='seconds')
    if email:
        repo.set_setting('flow_account_observed_email', email)
    if not ok:
        status = '已登录' if account['status'] == '需要验证' else account['status']
        if current.get('action') == 'login':
            status = login_failure_status(error)
        with connect() as con:
            con.execute(
                'UPDATE flow_login_accounts SET status=?, last_error=?, last_attempt=? WHERE id=?',
                (status, error or '没有读到点数', time.time(), account['id']))
        return get_account(account['id'])
    if email and email.lower() != account['email'].lower():
        _store_page_credits(email, credits, trust_page=True)
        status = '已登录' if account['status'] == '需要验证' else account['status']
        with connect() as con:
            con.execute(
                'UPDATE flow_login_accounts SET status=?, last_error=?, last_attempt=? WHERE id=?',
                (status, f'当前 Flow 页面是 {email}', time.time(), account['id']))
        return get_account(account['id'])
    _store_page_credits(account['email'], credits, trust_page=True, checked_at=now)
    return get_account(account['id'])


def _mark_plugin_connected(email):
    """The plugin reported this Flow login. Credits stay on the daily estimate until the page shows a number."""
    with connect() as con:
        row = con.execute(
            'SELECT id, status, last_error FROM flow_login_accounts WHERE lower(email)=lower(?)', (email,)
        ).fetchone()
        if not row:
            return
        status = str(row['status'] or '')
        if status not in ('已登录', '积分不足', '已核对'):
            status = '已登录'
        note = str(row['last_error'] or '')
        if note.startswith('Flow 页面还没有报出积分') or note.startswith('插件还没有连上') or '验证' in note or '密码' in note:
            note = ''
        con.execute('UPDATE flow_login_accounts SET status=?, last_error=? WHERE id=?', (status, note, int(row['id'])))


def _store_page_credits(email, credits, trust_page=False, checked_at=''):
    if credits is None or credits == '':
        if trust_page:
            with connect() as con:
                con.execute("UPDATE flow_login_accounts SET status='已登录', last_error='' WHERE lower(email)=lower(?)", (email,))
        return
    try:
        page = max(0, int(credits))
    except (TypeError, ValueError):
        return
    today = _dt.date.today().isoformat()
    stamp = checked_at or _dt.datetime.now().isoformat(timespec='seconds')
    with connect() as con:
        row = con.execute('SELECT * FROM flow_login_accounts WHERE lower(email)=lower(?)', (email,)).fetchone()
        if not row:
            return
        account = _row(row)
        current, estimated = usable_credits(account, today)
        if not trust_page and not estimated and page >= current:
            con.execute("UPDATE flow_login_accounts SET status='已登录', last_error='' WHERE id=?", (account['id'],))
            return
        status = '已登录' if page >= credit_cost() else '积分不足'
        con.execute(
            'UPDATE flow_login_accounts SET credits_remaining=?, credits_checked_at=?, status=?, last_error=? WHERE id=?',
            (page, stamp, status, '', account['id']))


_SEEN_TTL = 90


def merge_seen(rows, email, credits, now, ttl=_SEEN_TTL):
    """Keep every Flow page the plugin reported recently. A later page does not erase an earlier one."""
    now = float(now)
    fresh = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        address = str(row.get('email') or '').strip()
        try:
            at = float(row.get('at') or 0)
        except (TypeError, ValueError):
            at = 0
        if not address or now - at > float(ttl):
            continue
        fresh.append({'email': address, 'credits': row.get('credits'), 'at': at})
    credit_value = None
    if credits not in (None, ''):
        try:
            credit_value = max(0, int(credits))
        except (TypeError, ValueError):
            credit_value = None
    if email:
        email = str(email).strip()
        kept = []
        for row in fresh:
            if row['email'].lower() == email.lower():
                if credit_value is None:
                    credit_value = row.get('credits')
                continue
            kept.append(row)
        kept.append({'email': email, 'credits': credit_value, 'at': now})
        fresh = kept
    return fresh


def _load_seen(now=None):
    raw = repo.get_setting('flow_account_seen_pages', '') or '[]'
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError):
        rows = []
    return merge_seen(rows if isinstance(rows, list) else [], '', None, time.time() if now is None else now)


def observed_pages(now=None):
    """Flow emails reported by any connected plugin window in the last 90 seconds."""
    ensure_table()
    return _load_seen(now)


def seen_page(email, now=None):
    wanted = str(email or '').strip().lower()
    if not wanted:
        return None
    for row in observed_pages(now):
        if str(row.get('email') or '').strip().lower() == wanted:
            return row
    return None


def observe_page(email, credits):
    """Heartbeat hint. A higher page balance does not erase a reservation or another window."""
    email = str(email or '').strip()
    if not email and credits in (None, ''):
        return
    key = (email.lower(), None if credits in (None, '') else int(credits))
    now = time.time()
    ensure_table()
    with _LOCK:
        remembered = merge_seen(_load_seen(now), email, credits, now)
        repo.set_setting('flow_account_seen_pages', json.dumps(remembered, ensure_ascii=False))
    if email and _OBSERVED.get('key') == key and now - float(_OBSERVED.get('at') or 0) < 30:
        return
    _OBSERVED['key'] = key
    _OBSERVED['at'] = now
    if email:
        repo.set_setting('flow_account_observed_email', email)
    if credits not in (None, ''):
        repo.set_setting('flow_account_observed_credits', str(int(credits)))
        _store_page_credits(email, credits, trust_page=False)
    elif email:
        _mark_plugin_connected(email)


def commit_use(account_id, generations):
    generations = max(0, int(generations or 0))
    if not account_id or generations <= 0:
        return None
    cost = credit_cost()
    if cost <= 0:
        return None
    today = _dt.date.today().isoformat()
    stamp = _dt.datetime.now().isoformat(timespec='seconds')
    with _LOCK:
        account = get_account(account_id)
        credits, _estimated = usable_credits(account, today)
        remaining = max(0, credits - generations * cost)
        status = '已登录' if remaining >= cost else '积分不足'
        with connect() as con:
            con.execute(
                'UPDATE flow_login_accounts SET credits_remaining=?, credits_checked_at=?, status=? WHERE id=?',
                (remaining, stamp, status, account['id']))
    return get_account(account_id)


def apply_account_gate(tasks, rounds=1):
    """Scheduler hook. No imported accounts leaves the original task list alone."""
    tasks = list(tasks or [])
    if not rotation_enabled():
        return {'apply': False, 'hold': False, 'tasks': tasks, 'account_id': None, 'message': '', 'detail': ''}
    accounts = list_accounts(enabled_only=True)
    if not accounts:
        return {'apply': False, 'hold': False, 'tasks': tasks, 'account_id': None, 'message': '', 'detail': ''}
    with _LOCK:
        pending = _REQUEST if _REQUEST and not _REQUEST.get('done') else None
    decision = limit_tasks(
        accounts, tasks, rounds, credit_cost(),
        observed_email=repo.get_setting('flow_account_observed_email', ''),
        pending_action=(pending or {}).get('action') or '',
        pending_email=(pending or {}).get('email') or '',
        today=_dt.date.today().isoformat(),
    )
    target = decision.get('switch_to') or ''
    if target:
        row = next((account for account in accounts if account['email'].lower() == target.lower()), None)
        if row and automatic_login_allowed(row, time.time()):
            opened = _open_chrome_once(row)
            decision['message'] = '已在对应 Chrome 用户中打开 Flow' if opened else '请在账号管理勾选这个邮箱对应的 Chrome 用户'
        elif row:
            decision['message'] = row['last_error'] or '请在账号管理勾选这个邮箱对应的 Chrome 用户'
    return decision


def estimate_waiting(task_count, rounds=1):
    accounts = list_accounts(enabled_only=True)
    plan = plan_submission(accounts, task_count, rounds, credit_cost(), _dt.date.today().isoformat())
    return plan


def plugin_account_report(event):
    """Email reported by a plugin window. Channel-less account scans still count."""
    event = event or {}
    kind = str(event.get('type') or '')
    if kind not in ('web_plugin_heartbeat', 'flow_account_seen'):
        return None
    email = str(event.get('account_email') or '').strip()
    channel = str(event.get('channel_key') or '')
    if not email and channel.lower().startswith('account:'):
        email = channel.split(':', 1)[1].strip()
    credits = event.get('credits_remaining')
    if not email and credits in (None, ''):
        return None
    return email, credits


def account_rows(profiles, accounts):
    """Chrome users and sheet accounts in one list. A sheet email already on a Chrome user is not repeated."""
    profiles = list(profiles or [])
    accounts = list(accounts or [])
    by_profile = {}
    by_email = {}
    for account in accounts:
        directory = str(account.get('chrome_profile') or '').strip()
        if directory and directory not in by_profile:
            by_profile[directory] = account
        email = str(account.get('email') or '').strip().lower()
        if email and email not in by_email:
            by_email[email] = account
    rows = []
    used = set()
    for profile in profiles:
        email = str(profile.get('email') or '').strip()
        account = by_profile.get(str(profile.get('directory') or '')) or (by_email.get(email.lower()) if email else None)
        if account:
            used.add(int(account.get('id') or 0))
        rows.append({
            'kind': 'chrome',
            'name': str(profile.get('name') or profile.get('directory') or ''),
            'email': email,
            'profile': profile,
            'account': account,
        })
    for account in accounts:
        if int(account.get('id') or 0) in used:
            continue
        rows.append({
            'kind': 'sheet',
            'name': '表格账号',
            'email': str(account.get('email') or ''),
            'profile': None,
            'account': account,
        })
    return rows


def account_row_on_flow(row, seen):
    """A row is on Flow when the plugin just reported it, or Chrome already has a Flow session."""
    account = (row or {}).get('account')
    profile = (row or {}).get('profile') or {}
    if account and row_ready(account, seen):
        return True
    return str(profile.get('state') or '') == '已登录 Flow'


def arrange_account_rows(rows, seen, only_logged=False, sort_mode='ready', today=''):
    """Filter and sort the account table. The scheduler order is unchanged."""
    rows = list(rows or [])
    logged = [row for row in rows if account_row_on_flow(row, seen)]
    shown = logged if only_logged else list(rows)
    mode = sort_mode if sort_mode in _ACCOUNT_SORTS else 'ready'
    if mode == 'default':
        return shown, len(logged)
    today = today or _dt.date.today().isoformat()

    def points(row):
        account = row.get('account')
        if not account:
            return -1
        credits, _estimated = usable_credits(account, today)
        return credits

    def name(row):
        return str(row.get('name') or row.get('email') or '').lower()

    def ready_rank(row):
        account = row.get('account')
        if account and row_ready(account, seen):
            return 0
        if str((row.get('profile') or {}).get('state') or '') == '已登录 Flow':
            return 1
        return 2

    if mode == 'name':
        shown.sort(key=name)
    elif mode == 'points_desc':
        shown.sort(key=lambda row: (-points(row), name(row)))
    elif mode == 'points_asc':
        shown.sort(key=lambda row: (points(row) < 0, points(row), name(row)))
    else:
        shown.sort(key=lambda row: (ready_rank(row), name(row)))
    return shown, len(logged)


def observed_email():
    ensure_table()
    return repo.get_setting('flow_account_observed_email', '')


def clear_legacy_login_errors():
    """Drop the old password-form failure. Checking credits is not a verification request."""
    ensure_table()
    where = """status='需要验证'
                  OR last_error LIKE '%没有找到密码框%'
                  OR last_error LIKE '%没有找到二步验证%'
                  OR last_error LIKE '%没有找到邮箱输入框%'
                  OR last_error LIKE '%可能要求额外验证%'
                  OR last_error LIKE '%页面登录的是%'"""
    with connect() as con:
        # An empty update still writes the database and makes every other page reload.
        if con.execute(f"SELECT 1 FROM flow_login_accounts WHERE {where} LIMIT 1").fetchone() is None:
            return
        con.execute(
            f"""UPDATE flow_login_accounts
               SET last_error='', status=CASE WHEN status='需要验证' THEN '已登录' ELSE status END
               WHERE {where}"""
        )


def request_point_read(email):
    """Ask the open Flow plugin to read the account card once. This is not a login."""
    email = str(email or '').strip()
    if '@' not in email:
        raise ValueError('这一行没有邮箱')
    token = f'{time.time():.3f}'
    repo.set_setting('flow_account_point_read', json.dumps({
        'email': email,
        'id': token,
        'until': time.time() + 20,
    }, ensure_ascii=False))
    return token


def pending_point_read():
    raw = repo.get_setting('flow_account_point_read', '') or ''
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        until = float(data.get('until') or 0)
    except (TypeError, ValueError):
        return None
    email = str(data.get('email') or '').strip()
    if until < time.time() or '@' not in email:
        return None
    return {'email': email, 'id': str(data.get('id') or '')}


def read_page_credits(account_id):
    """Apply credits the open Flow page already reported. Do not ask the plugin to log in."""
    account = get_account(account_id)
    page = seen_page(account['email'])
    if page:
        credits = '' if page.get('credits') is None else page.get('credits')
        decision = interpret_credit_check(account['email'], account['status'], page.get('email') or account['email'], credits)
    else:
        decision = interpret_credit_check(account['email'], account['status'], '', '')
        others = [row['email'] for row in observed_pages()]
        if others:
            decision = dict(decision)
            shown = '、'.join(others[:6])
            decision['note'] = f'插件读到的是 {shown}，不是这一行'
            decision['message'] = f'这一行还没就绪。插件目前读到的是 {shown}。每个 Chrome 用户都要自己打开 Flow，并且这个窗口里装了插件。'
    same_account = str(decision['apply_email'] or '').lower() == account['email'].lower()
    if decision['credits'] is not None and same_account:
        _store_page_credits(account['email'], decision['credits'], trust_page=True)
        return get_account(account_id), decision['message']
    if decision['credits'] is not None and decision['apply_email']:
        _store_page_credits(decision['apply_email'], decision['credits'], trust_page=True)
    with connect() as con:
        con.execute(
            'UPDATE flow_login_accounts SET status=?, last_error=? WHERE id=?',
            (decision['status'], decision['note'], account['id']))
    return get_account(account_id), decision['message']


def list_chrome_profiles():
    from app.services.chrome_profiles import classify_session, list_chrome_profiles as read_profiles, session_flags
    profiles = []
    for item in read_profiles():
        email = str(item.get('email') or '').strip()
        flow_cookie, google_cookie = session_flags(item.get('path') or '')
        profiles.append({**item, 'state': classify_session(email, flow_cookie, google_cookie)})
    rank = {'已登录 Flow': 0, '可打开 Flow': 1, '未登录': 2}
    profiles.sort(key=lambda item: (rank.get(item['state'], 9), str(item.get('name') or '').lower()))
    return profiles


def use_chrome_profile(profile):
    """Remember a checked Chrome user. Login state comes from that browser, not a password."""
    from app.services.chrome_profiles import valid_profile_directory
    email = str((profile or {}).get('email') or '').strip()
    directory = str((profile or {}).get('directory') or '').strip()
    state = str((profile or {}).get('state') or '')
    if not valid_profile_directory(directory):
        raise ValueError('Chrome 用户目录无效')
    if '@' not in email:
        raise ValueError(f'{profile.get("name") or directory} 还没有登录 Google，无法作为 Flow 账号')
    status = '已登录' if state in ('已登录 Flow', '可打开 Flow') else '未登录'
    note = '' if status == '已登录' else '这个 Chrome 用户还没有登录 Google'
    add_account(email, enabled=True, chrome_profile=directory)
    with connect() as con:
        con.execute(
            'UPDATE flow_login_accounts SET status=?, last_error=?, chrome_profile=? WHERE lower(email)=lower(?)',
            (status, note, directory, email))
    return get_account_by_email(email)


def disable_chrome_profile(profile):
    ensure_table()
    directory = str((profile or {}).get('directory') or '').strip()
    email = str((profile or {}).get('email') or '').strip()
    with connect() as con:
        if directory:
            con.execute('UPDATE flow_login_accounts SET enabled=0 WHERE chrome_profile=?', (directory,))
        if email:
            con.execute('UPDATE flow_login_accounts SET enabled=0 WHERE lower(email)=lower(?)', (email,))


def get_account_by_email(email):
    ensure_table()
    with connect() as con:
        row = con.execute('SELECT * FROM flow_login_accounts WHERE lower(email)=lower(?)', (email,)).fetchone()
    if not row:
        raise ValueError('账号不存在')
    return _row(row)


def open_account_browser(account):
    """Open Flow in the Chrome user that already has this login. Do not type a password."""
    from app.services.chrome_profiles import launch_flow, list_chrome_profiles as read_profiles
    directory = str((account or {}).get('chrome_profile') or '').strip()
    if not directory:
        email = str((account or {}).get('email') or '').strip().lower()
        match = next((item for item in read_profiles() if str(item.get('email') or '').lower() == email), None)
        directory = match['directory'] if match else ''
    if not directory:
        raise ValueError('请先勾选这个邮箱对应的 Chrome 用户')
    try:
        launch_flow(directory, 'https://flow.google.com/')
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    return directory


def _open_chrome_once(account):
    try:
        directory = open_account_browser(account)
    except ValueError:
        return False
    with connect() as con:
        con.execute(
            'UPDATE flow_login_accounts SET last_attempt=?, last_error=? WHERE id=?',
            (time.time(), f'已打开 Chrome 用户 {directory} 的 Flow', int(account['id'])))
    return True
