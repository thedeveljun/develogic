"""접속 비밀번호 (사무실 네트워크 공유용).

- 이 PC(127.0.0.1)에서 직접 열면 관리자로 자동 로그인. 단, 프록시·터널을 거친 요청(X-Forwarded-For 등)은 외부로 취급.
- 다른 PC는 비밀번호 로그인: 관리자(모든 기능) / 직원(조회·입력, 삭제·설정 불가).
- 비밀번호는 PBKDF2-SHA256(무작위 salt, 200,000회)로 data/settings.json 에 해시만 저장.
- 세션은 HMAC 서명 쿠키 (HttpOnly, SameSite=Lax, 12시간).
- 로그인 5회 실패 시 해당 IP 60초 대기.
"""
import hashlib
import hmac
import secrets
import time

from . import landinfo

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
    host = request.client.host if request.client else ''
    proxied = any(h in request.headers for h in ('x-forwarded-for', 'forwarded', 'x-real-ip', 'cf-connecting-ip'))
    return host in ('127.0.0.1', '::1') and not proxied


def role_of(request) -> str | None:
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


def admin_only(method: str, path: str) -> bool:
    if method == 'DELETE' and '/scenarios/' in path:
        return False
    if path.endswith('/open'):            # 서버 PC 탐색기 열기 — 원격 사용자에게 의미 없음
        return True
    return any(method == m and path.startswith(p) for m, p in ADMIN_ONLY)
