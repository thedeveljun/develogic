"""실행 방식·자료 위치.

- 내 PC (기본): 자료함/ , data/ 를 그대로 쓴다. 이 PC 는 관리자 자동 로그인 (예전과 같음).
- 클라우드 (DEVELOGIC_MULTI=1): 여러 업체가 주소로 접속. 업체마다 아이디·자료함이 따로다.
    DEVELOGIC_DATA   자료 폴더 (Cloud Run 에서는 Cloud Storage 버킷을 /data 에 연결)
        accounts.json            업체·사용자 계정 (비밀번호는 해시만)
        settings.json            브이월드 키·세션 비밀키 (공용)
        ordinances.sqlite3       조례 캐시 백업본 (공용)
        tenants/<업체>/자료함/    업체별 사업지 자료
    조례 캐시 DB 는 SQLite 라 버킷에서 직접 열지 않고 /tmp 에서 쓰고 바뀌면 버킷에 복사해 둔다.
"""
import os
import re
import shutil
import sqlite3
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).parent.parent
MULTI = os.environ.get('DEVELOGIC_MULTI') == '1'
DATA = Path(os.environ.get('DEVELOGIC_DATA') or ROOT / 'data')
SETTINGS = DATA / 'settings.json'
ACCOUNTS = DATA / 'accounts.json'
DB_PERSIST = DATA / 'ordinances.sqlite3'
DB = Path(os.environ.get('DEVELOGIC_DB') or ('/tmp/ordinances.sqlite3' if MULTI else DB_PERSIST))

# 지금 요청한 사람의 업체 (클라우드에서만). 로그인 확인(main._guard)에서 정한다.
TENANT: ContextVar[str | None] = ContextVar('tenant', default=None)
TENANT_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{1,31}$')


def inbox() -> Path:
    if not MULTI:
        return ROOT / '자료함'
    t = TENANT.get()
    if not t or not TENANT_RE.match(t):
        raise PermissionError('업체가 확인되지 않았습니다. 다시 로그인하세요')   # 다른 업체 자료로 새지 않게 막는다
    return DATA / 'tenants' / t / '자료함'


# ── 조례 캐시 DB: 클라우드에서는 /tmp 사본을 쓰고 바뀌면 버킷에 백업 ──
_synced = 0.0


def restore_db():
    global _synced
    if DB == DB_PERSIST or DB.exists() or not DB_PERSIST.exists():
        return
    DB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DB_PERSIST, DB)
    _synced = DB.stat().st_mtime


def sync_db():
    """조례 캐시가 바뀌었으면 버킷에 복사 (요청이 끝날 때마다 호출 · 바뀌지 않았으면 아무것도 안 함)."""
    global _synced
    if DB == DB_PERSIST or not DB.exists():
        return
    m = DB.stat().st_mtime
    if m <= _synced:
        return
    DB_PERSIST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PERSIST.with_suffix('.sqlite3.tmp')
    src, dst = sqlite3.connect(DB), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    os.replace(tmp, DB_PERSIST)
    _synced = m
