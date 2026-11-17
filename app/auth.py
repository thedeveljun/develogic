"""접속 비밀번호 (사무실 네트워크 공유용).

- 이 PC(127.0.0.1)에서 직접 열면 관리자로 자동 로그인. 단, 프록시·터널을 거친 요청(X-Forwarded-For 등)은 외부로 취급.
- 다른 PC는 비밀번호 로그인: 관리자(모든 기능) / 직원(조회·입력, 삭제·설정 불가).
- 비밀번호는 PBKDF2-SHA256(무작위 salt, 200,000회)로 data/settings.json 에 해시만 저장.
- 세션은 HMAC 서명 쿠키 (HttpOnly, SameSite=Lax, 12시간).
- 로그인 5회 실패 시 해당 IP 60초 대기.

클라우드(여러 업체, config.MULTI)에서는 파일 아래쪽 '업체 계정'을 쓴다:
- 아이디 + 비밀번호. 사용자는 업체 하나에 속하고 역할은 운영자(operator) / 관리자(admin) / 직원(staff).
- 운영자 = 프로그램 공급자: 업체·계정 추가/삭제, 브이월드 키·공용 조례 관리. 업체 사람은 자기 업체 자료만 본다.
- 계정은 DEVELOGIC_DATA/accounts.json (비밀번호는 해시만). 첫 운영자는 환경변수 DEVELOGIC_OPERATOR_PW 로 만든다.
- 세션 서명에 비밀번호 해시 일부를 넣어, 비밀번호를 바꾸거나 계정을 지우면 기존 로그인이 바로 끊긴다.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from . import config, landinfo

COOKIE = 'dl_session'
TTL = 12 * 3600
ITER = 200_000
_fails: dict[str, list[float]] = {}


def _settings() -> dict:
    return landinfo.load_settings()


def _secret() -> bytes:
    s = _settings()
    sec = s.get('session_secret')
    if not sec:
        sec = secrets.token_hex(32)
        landinfo.save_settings(session_secret=sec)
    return bytes.fromhex(sec)


def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, ITER)
    return f'pbkdf2${ITER}${salt.hex()}${dk.hex()}'


def check_pw(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, it, salt, dk = stored.split('$')
        got = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(got.hex(), dk)
    except (ValueError, TypeError):
        return False


def status() -> dict:
    a = _settings().get('auth') or {}
    return {'admin_set': bool(a.get('admin')), 'staff_set': bool(a.get('staff'))}


def set_passwords(admin: str | None, staff: str | None, clear_staff: bool = False, clear_all: bool = False) -> dict:
    a = dict(_settings().get('auth') or {})
    for role, pw in (('admin', admin), ('staff', staff)):
        if pw:
            if len(pw) < 4:
                raise ValueError('비밀번호는 4자 이상으로 정하세요')
            a[role] = hash_pw(pw)
    if clear_staff:
        a.pop('staff', None)
    if clear_all:            # 비밀번호 해제: 다른 PC 접속 차단 상태로 돌아감
        a = {}
    if a.get('staff') and not a.get('admin'):
        raise ValueError('관리자 비밀번호를 먼저 정하세요')
    landinfo.save_settings(auth=a)
    return status()


def login(pw: str, ip: str) -> str | None:
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 60]
    if len(recent) >= 5:
        raise PermissionError('비밀번호를 5번 틀렸습니다. 1분 뒤 다시 시도하세요')
    a = _settings().get('auth') or {}
    role = 'admin' if check_pw(pw, a.get('admin')) else 'staff' if check_pw(pw, a.get('staff')) else None
    if not role:
        _fails[ip] = recent + [now]
        return None
    _fails.pop(ip, None)
    return make_token(role)


def make_token(role: str) -> str:
    exp = int(time.time()) + TTL
    msg = f'{role}.{exp}'
    sig = hmac.new(_secret(), msg.encode(), hashlib.sha256).hexdigest()
    return f'{msg}.{sig}'


def read_token(tok: str | None) -> str | None:
    if not tok or tok.count('.') != 2:
        return None
    role, exp, sig = tok.split('.')
    good = hmac.new(_secret(), f'{role}.{exp}'.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good) or not exp.isdigit() or int(exp) < time.time() or role not in ('admin', 'staff'):
        return None
    # 비밀번호를 지우면(직원 비밀번호 해제) 기존 직원 세션도 무효
    st = status()
    if (role == 'staff' and not st['staff_set']) or (role == 'admin' and not st['admin_set']):
        return None   # 비밀번호 해제 시 기존 로그인도 무효
    return role


def is_local(request) -> bool:
    if config.MULTI:
        return False
    host = request.client.host if request.client else ''
    proxied = any(h in request.headers for h in ('x-forwarded-for', 'forwarded', 'x-real-ip', 'cf-connecting-ip'))
    return host in ('127.0.0.1', '::1') and not proxied


def role_of(request) -> str | None:
    if config.MULTI:
        u = user_of(request)
        return None if not u else 'staff' if u['role'] == 'staff' else 'admin'
    if is_local(request):
        return 'admin'
    return read_token(request.cookies.get(COOKIE))


# 직원 계정으로 막는 요청 (method, 경로 접두사)
ADMIN_ONLY = [
    ('DELETE', '/api/v4/sites/'),          # 사업지 삭제 (시나리오 삭제는 아래에서 허용)
    ('DELETE', '/api/v4/sites-trash/'),    # 영구 삭제
    ('PUT', '/api/v4/settings'),           # API 키·서비스 URL
    ('POST', '/api/v4/auth/passwords'),    # 비밀번호 변경
]


OPERATOR_ONLY = [
    ('PUT', '/api/v4/settings'),           # 브이월드 키 (모든 업체 공용)
    ('POST', '/api/v4/auth/passwords'),    # 내 PC용 공용 비밀번호 (클라우드에서는 쓰지 않음)
    ('', '/api/v4/accounts'),              # 업체·계정 관리
    ('POST', '/api/v2/ordinances'),        # 공용 조례 근거 등록
    ('POST', '/api/v4/ordinance/review'),  # 공용 조례 검토 표시
]


def operator_only(method: str, path: str) -> bool:
    if not config.MULTI:
        return False
    if path.endswith('/open'):             # 서버 탐색기 열기 — 클라우드에서는 쓸 수 없음
        return True
    return any((not m or method == m) and path.startswith(p) for m, p in OPERATOR_ONLY)


def admin_only(method: str, path: str) -> bool:
    if method == 'DELETE' and '/scenarios/' in path:
        return False
    if path.endswith('/open'):            # 서버 PC 탐색기 열기 — 원격 사용자에게 의미 없음
        return True
    return any(method == m and path.startswith(p) for m, p in ADMIN_ONLY)


# ═════════════ 클라우드: 업체 계정 ═════════════
ROLES = ('operator', 'admin', 'staff')
UID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{2,31}$')


def client_ip(request) -> str:
    if config.MULTI:   # Cloud Run 앞단이 맨 뒤에 붙인 실제 접속 IP (앞쪽은 접속자가 꾸밀 수 있음)
        xff = request.headers.get('x-forwarded-for', '')
        if xff:
            return xff.split(',')[-1].strip()
    return request.client.host if request.client else ''


def load_accounts() -> dict:
    try:
        d = json.loads(config.ACCOUNTS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        d = {}
    d.setdefault('companies', {})
    d.setdefault('users', {})
    return d


def _save_accounts(d: dict):
    config.ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.ACCOUNTS.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, config.ACCOUNTS)


def ensure_operator():
    """운영자 계정이 하나도 없으면 DEVELOGIC_OPERATOR_PW 로 'develogic' 운영자를 만든다 (서버 시작 시)."""
    pw = os.environ.get('DEVELOGIC_OPERATOR_PW', '').strip()
    d = load_accounts()
    if not pw or any(u.get('role') == 'operator' for u in d['users'].values()):
        return
    d['companies'].setdefault('develogic', {'name': '디벨로직 (운영)', 'created': time.strftime('%Y-%m-%d')})
    d['users']['develogic'] = {'company': 'develogic', 'role': 'operator', 'name': '운영자', 'pw': hash_pw(pw)}
    _save_accounts(d)


def _sig(uid: str, exp: str, pw_hash: str) -> str:
    return hmac.new(_secret(), f'u.{uid}.{exp}.{pw_hash[-16:]}'.encode(), hashlib.sha256).hexdigest()


def login_user(uid: str, pw: str, ip: str) -> str | None:
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 60]
    if len(recent) >= 5:
        raise PermissionError('비밀번호를 5번 틀렸습니다. 1분 뒤 다시 시도하세요')
    uid = (uid or '').strip().lower()
    d = load_accounts()
    u = d['users'].get(uid)
    if not u or not check_pw(pw, u.get('pw')) or u.get('company') not in d['companies']:
        _fails[ip] = recent + [now]
        return None
    _fails.pop(ip, None)
    exp = str(int(now) + TTL)
    return f'{uid}.{exp}.{_sig(uid, exp, u["pw"])}'


def user_of(request) -> dict | None:
    tok = request.cookies.get(COOKIE)
    if not tok or tok.count('.') != 2:
        return None
    uid, exp, sig = tok.split('.')
    if not exp.isdigit() or int(exp) < time.time():
        return None
    d = load_accounts()
    u = d['users'].get(uid)
    if not u or u.get('role') not in ROLES or u.get('company') not in d['companies']:
        return None
    if not hmac.compare_digest(sig, _sig(uid, exp, u.get('pw', ''))):
        return None
    return {'uid': uid, 'role': u['role'], 'name': u.get('name', ''), 'company': u['company'],
            'company_name': d['companies'][u['company']].get('name', u['company'])}


def list_accounts() -> dict:
    d = load_accounts()
    users = [{'uid': k, 'company': v['company'], 'role': v['role'], 'name': v.get('name', '')} for k, v in sorted(d['users'].items())]
    return {'companies': [{'id': k, **v, 'users': [u for u in users if u['company'] == k]} for k, v in sorted(d['companies'].items())]}


def add_company(cid: str, name: str) -> dict:
    cid = (cid or '').strip().lower()
    if not config.TENANT_RE.match(cid):
        raise ValueError('업체 코드는 영문 소문자·숫자·-·_ 2~32자로 정하세요 (예: hanbit-law)')
    if not (name or '').strip():
        raise ValueError('업체 이름을 입력하세요')
    d = load_accounts()
    if cid in d['companies']:
        raise ValueError(f'이미 있는 업체 코드입니다: {cid}')
    d['companies'][cid] = {'name': name.strip()[:60], 'created': time.strftime('%Y-%m-%d')}
    _save_accounts(d)
    return list_accounts()


def delete_company(cid: str) -> dict:
    """업체와 그 계정을 지운다. 자료(tenants/<업체>)는 지우지 않고 남긴다 (운영자가 버킷에서 직접 정리)."""
    d = load_accounts()
    if cid not in d['companies']:
        raise LookupError('없는 업체입니다')
    if any(u['role'] == 'operator' and u['company'] == cid for u in d['users'].values()):
        raise ValueError('운영자 계정이 있는 업체는 지울 수 없습니다')
    d['companies'].pop(cid)
    d['users'] = {k: v for k, v in d['users'].items() if v['company'] != cid}
    _save_accounts(d)
    return list_accounts()


def save_user(uid: str, company: str, role: str, password: str | None, name: str = '') -> dict:
    """계정 추가 또는 수정 (비밀번호를 비우면 기존 비밀번호 유지)."""
    uid = (uid or '').strip().lower()
    if not UID_RE.match(uid):
        raise ValueError('아이디는 영문 소문자·숫자·-·_ 3~32자로 정하세요')
    if role not in ('admin', 'staff'):
        raise ValueError('역할은 관리자 또는 직원입니다')
    d = load_accounts()
    if company not in d['companies']:
        raise ValueError('없는 업체입니다')
    old = d['users'].get(uid)
    if old and old.get('company') != company:
        raise ValueError(f'다른 업체가 이미 쓰는 아이디입니다: {uid}')
    if old and old.get('role') == 'operator':
        raise ValueError('운영자 계정은 여기서 바꿀 수 없습니다 (내 비밀번호 변경을 쓰세요)')
    if not old and not password:
        raise ValueError('새 계정은 비밀번호가 필요합니다')
    if password and len(password) < 8:
        raise ValueError('비밀번호는 8자 이상으로 정하세요')
    d['users'][uid] = {'company': company, 'role': role, 'name': (name or '').strip()[:30],
                       'pw': hash_pw(password) if password else old['pw']}
    _save_accounts(d)
    return list_accounts()


def delete_user(uid: str) -> dict:
    d = load_accounts()
    u = d['users'].get(uid)
    if not u:
        raise LookupError('없는 계정입니다')
    if u['role'] == 'operator':
        raise ValueError('운영자 계정은 지울 수 없습니다')
    d['users'].pop(uid)
    _save_accounts(d)
    return list_accounts()


def change_own_password(uid: str, current: str, new: str):
    d = load_accounts()
    u = d['users'].get(uid)
    if not u or not check_pw(current, u.get('pw')):
        raise PermissionError('현재 비밀번호가 맞지 않습니다')
    if len(new or '') < 8:
        raise ValueError('비밀번호는 8자 이상으로 정하세요')
    u['pw'] = hash_pw(new)
    _save_accounts(d)
