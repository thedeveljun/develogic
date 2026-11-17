import json
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .types import Project
from .engine import run_model
from .regulations import review
from .nationwide import PROVINCES, Rule, Feasibility, save_rule, evaluate
from .proforma import Proforma, analyze

ROOT = Path(__file__).parent.parent
WEB = ROOT / 'web'
SAMPLES = {'general': 'general.json', 'renewal': 'renewal.json', 'proforma': 'proforma.json'}

app = FastAPI(title='디벨로직 부동산 개발사업 통합 분석 API', version='0.4.0')
app.mount('/static', StaticFiles(directory=WEB / 'static'), name='static')

# ── 접속 비밀번호: 이 PC는 관리자 자동, 다른 PC는 로그인 (관리자 / 직원) ──
from urllib.parse import quote as _quote
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from . import auth

_PUBLIC = ('/login', '/api/v4/auth/login', '/static/', '/favicon.ico')


@app.middleware('http')
async def _guard(request: Request, call_next):
    path = request.url.path
    role = auth.role_of(request)
    if not role and not path.startswith(_PUBLIC):
        if path.startswith('/api/') or path in ('/openapi.json', '/docs', '/redoc'):
            if path.startswith('/api/'):
                return JSONResponse({'detail': '로그인이 필요합니다'}, status_code=401)
        return RedirectResponse('/login?next=' + _quote(path if path != '/login' else '/'), status_code=303)
    if role == 'staff' and auth.admin_only(request.method, path):
        return JSONResponse({'detail': '관리자만 할 수 있는 작업입니다 (직원 계정)'}, status_code=403)
    request.state.role = role
    return await call_next(request)


class _Pw(BaseModel):
    password: str


class _PwSet(BaseModel):
    admin: str | None = None
    staff: str | None = None
    clear_staff: bool = False
    clear_all: bool = False


@app.get('/login', response_class=HTMLResponse)
def login_page():
    return HTMLResponse((WEB / 'login.html').read_text(encoding='utf-8'), headers={'Cache-Control': 'no-cache'})


@app.post('/api/v4/auth/login')
def auth_login(body: _Pw, request: Request):
    if not auth.status()['admin_set']:
        raise HTTPException(403, '아직 접속 비밀번호가 설정되지 않았습니다. 프로그램이 설치된 PC에서 설정 화면 › 접속 비밀번호를 먼저 정하세요.')
    try:
        tok = auth.login(body.password, request.client.host if request.client else '')
    except PermissionError as exc:
        raise HTTPException(429, str(exc)) from exc
    if not tok:
        raise HTTPException(401, '비밀번호가 맞지 않습니다')
    r = JSONResponse({'role': auth.read_token(tok)})
    r.set_cookie(auth.COOKIE, tok, max_age=auth.TTL, httponly=True, samesite='lax')
    return r


@app.post('/api/v4/auth/logout')
def auth_logout():
    r = JSONResponse({'ok': True})
    r.delete_cookie(auth.COOKIE)
    return r


def _lan_urls() -> list[str]:
    import socket
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(('127.', '169.254.')):
                ips.add(ip)
    except OSError:
        pass
    return [f'http://{ip}:8001/' for ip in sorted(ips)]


@app.get('/api/v4/auth/me')
def auth_me(request: Request):
    return {'role': request.state.role, 'local': auth.is_local(request), **auth.status(),
            'lan_urls': _lan_urls() if request.state.role == 'admin' else []}


@app.post('/api/v4/auth/passwords')
def auth_passwords(body: _PwSet):
    try:
        return auth.set_passwords(body.admin, body.staff, body.clear_staff, body.clear_all)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# ── 웹 화면: 모든 화면은 하나의 앱 셸(app.html)에서 좌측 메뉴로 전환 ──
def _shell() -> str:
    html = (WEB / 'app.html').read_text(encoding='utf-8')
    # 정적 파일이 바뀌면 주소가 달라지도록 수정 시각을 붙여 브라우저 캐시 문제를 막는다
    for name in ('ci.css', 'app.js', 'logo.svg'):
        v = int((WEB / 'static' / name).stat().st_mtime)
        html = html.replace(f'/static/{name}"', f'/static/{name}?v={v}"')
    # 화면 HTML 자체는 캐시하지 않아 항상 최신 정적 파일 주소를 받도록 한다
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})

@app.get('/', response_class=HTMLResponse)
def home(): return _shell()

@app.get('/dashboard', response_class=HTMLResponse)
def dashboard(): return _shell()   # 이전 주소 호환 → Cash Flow 화면

@app.get('/nationwide', response_class=HTMLResponse)
def nationwide_dashboard(): return _shell()   # 이전 주소 호환 → 법규·수지 화면

@app.get('/sample')
def sample(name: str = Query('general')):
    if name not in SAMPLES:
        raise HTTPException(404, '샘플이 없습니다')
    return json.loads((ROOT / 'samples' / SAMPLES[name]).read_text(encoding='utf-8'))


# ── v1: Cash Flow · 내장 조례 간이 검토 ──
@app.post('/api/v1/cashflow')
def calculate(project: Project):
    try: return run_model(project.model_dump())
    except (ValueError, KeyError) as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

class SiteRequest(BaseModel):
    jurisdiction: str
    zone: str
    project_type: str = 'general_housing'
    site_area_sqm: float | None = None
    station_distance_m: float | None = None
    district_plan_verified: bool = False
    parcel_zoning_verified: bool = False

@app.post('/api/v1/legal-review')
def legal_review(site: SiteRequest):
    try: return review(site.model_dump())
    except ValueError as e: raise HTTPException(status_code=422, detail=str(e))


# ── v2: 전국 조례 근거 등록 · 게이트 검토 ──
@app.get('/api/v2/provinces')
def provinces(): return {'provinces': PROVINCES, 'coverage': '전국 행정구역 선택 지원. 조례 수치 자동 수집·검증은 별도 구축 필요'}

@app.post('/api/v2/ordinances')
def register_ordinance(rule: Rule):
    try: return save_rule(rule)
    except Exception as exc:
        if isinstance(exc, ValueError): raise HTTPException(422, str(exc)) from exc
        raise

@app.post('/api/v2/feasibility')
def feasibility(q: Feasibility): return evaluate(q)


# ── v3: 시행사 사업수지 ──
@app.post('/api/v3/proforma')
def proforma(p: Proforma):
    try: return analyze(p)
    except (ValueError, ArithmeticError) as exc: raise HTTPException(422, str(exc)) from exc


# ── v4: 법령·조례 데이터 (국가법령정보센터) ──
from fastapi import UploadFile, File
from fastapi.responses import Response
from . import lawdata, documents
from .report import build as build_report

SAMPLES['garoju'] = 'garoju.json'
SAMPLES['rental'] = 'rental.json'
for _t in json.loads((ROOT / 'samples' / 'templates.json').read_text(encoding='utf-8')):   # 용도별 템플릿 (tools/build_templates.py)
    SAMPLES['tpl_' + _t['key']] = f"tpl_{_t['key']}.json"
lawdata.seed_builtin()
import threading as _th


@app.on_event('startup')
def _refresh_ordinances():   # 이전 판독기 결과 갱신 — 서버 시작 시에만 (테스트에서 import 할 때는 돌지 않게)
    _th.Thread(target=lawdata.refresh_stale, daemon=True, name='ordinance-refresh').start()
documents.ensure_inbox()


class Place(BaseModel):
    province: str
    municipality: str = ''


@app.get('/api/v4/zoning')
def zoning(province: str, municipality: str = '', zone: str = '제2종일반주거지역', fetch: bool = True):
    return lawdata.resolve(province, municipality or province, zone, fetch=fetch)


@app.get('/api/v4/ordinance')
def ordinance(province: str, municipality: str = ''):
    o = lawdata.cached(province, municipality or province)
    from . import parking
    pk = parking.cached(province, municipality or '')
    return {'ordinance': o, 'national': lawdata.NATIONAL, 'national_source': lawdata.NATIONAL_SOURCE,
            'parking': pk if pk and pk.get('parser', 0) >= parking.PARSER_VERSION else None}


@app.post('/api/v4/parking/fetch')
def parking_fetch(pl: Place):
    """지자체 주차장 조례(부설주차장 설치기준 별표) 수집·판독."""
    from . import parking
    try:
        return {'parking': parking.fetch(pl.province, pl.municipality or '')}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:   # 네트워크·HWP 판독 오류 → 500 대신 502 (화면은 국가 기준으로 계속 계산)
        raise HTTPException(502, f'주차장 조례를 불러오지 못했습니다: {exc}') from exc


@app.post('/api/v4/ordinance/fetch')
def ordinance_fetch(pl: Place):
    try:
        o = lawdata.fetch_ordinance(pl.province, pl.municipality or pl.province)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(502, f'국가법령정보센터 연결 실패: {exc}') from exc
    from . import parking   # 같은 지자체의 주차장 조례(부설주차장 설치기준)도 함께 — 실패해도 도시계획 조례 결과는 돌려준다
    try:
        pk = parking.fetch(pl.province, pl.municipality or '')
    except Exception as exc:
        pk = {'error': str(exc)}
    return {'ordinance': o, 'parking': pk}


class ReviewMark(BaseModel):
    province: str
    municipality: str = ''
    reviewer: str
    reviewed_on: str


@app.post('/api/v4/ordinance/review')
def ordinance_review(m: ReviewMark):
    try: lawdata.mark_reviewed(m.province, m.municipality or m.province, m.reviewer, m.reviewed_on)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    return {'ok': True}


@app.get('/api/v4/ordinances')
def ordinances(): return {'items': lawdata.list_cached()}


# ── v4: 사업지 자료함 ──
class SiteName(BaseModel):
    name: str


@app.get('/api/v4/templates')
def templates():
    idx = json.loads((ROOT / 'samples' / 'templates.json').read_text(encoding='utf-8'))
    return idx + [{'key': 'garoju', 'title': '가로주택정비사업', 'desc': '조합 방식 · 종전자산·비례율·분담금 · 빈집법 임대 20% 완화'},
                  {'key': 'rental', 'title': '공공지원민간임대', 'desc': '10년 임대 운영 후 매각 · 주택도시기금 · 지특법 감면 · 임대수익률·DSCR'}]


@app.get('/api/v4/sites')
def sites(): return {'inbox': str(documents.INBOX), 'sites': documents.list_sites()}


@app.post('/api/v4/sites')
def site_create(n: SiteName):
    try: return documents.create_site(n.name)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.get('/api/v4/sites-trash')
def sites_trash(): return {'trash': documents.list_trash()}


@app.delete('/api/v4/sites-trash/{trash_id}')
def site_purge(trash_id: str):
    try: return documents.purge_site(trash_id)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc


@app.post('/api/v4/sites-trash/{trash_id}/restore')
def site_restore(trash_id: str):
    try: return documents.restore_site(trash_id)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@app.delete('/api/v4/sites/{name}')
def site_delete(name: str):
    try: return documents.delete_site(name)
    except (FileNotFoundError, ValueError) as exc: raise HTTPException(404, str(exc)) from exc


@app.get('/api/v4/sites/{name}/design')
def site_design(name: str, files: str = ''):
    """설계도서(설계개요·층별개요·분양면적표 PDF) 인식. files=쉼표 구분 파일명(없으면 폴더의 설계도서 전체)."""
    from . import design
    d = documents.site_dir(name)
    if not d.is_dir(): raise HTTPException(404, '사업지 폴더가 없습니다')
    paths = [d / Path(n).name for n in files.split(',') if n.strip()] if files else documents.design_files(name)
    paths = [p for p in paths if p.is_file() and p.suffix.lower() == '.pdf']
    if not paths: raise HTTPException(404, '설계도서 PDF가 없습니다 (설계개요·층별개요·분양면적표)')
    return design.parse_pdfs(paths)


@app.get('/api/v4/sites/{name}')
def site_analyze(name: str):
    try: return documents.analyze_site(name)
    except (FileNotFoundError, ValueError) as exc: raise HTTPException(404, str(exc)) from exc


class LandReportReq(BaseModel):
    items: list[dict] = Field(default_factory=list, max_length=200)


@app.post('/api/v4/sites/{name}/landuse-report')
def site_landuse_report(name: str, req: LandReportReq):
    """필지들의 토지특성·토지이용계획을 최신으로 조회해 '토지이용계획 열람본(참고용)' PDF를 사업지 자료함에 저장."""
    from . import landreport
    d = documents.site_dir(name)
    if not d.is_dir(): raise HTTPException(404, '사업지 폴더가 없습니다')
    items = [{'address': str(x.get('address') or ''), 'pnu': str(x.get('pnu') or '')} for x in req.items if x.get('address') or x.get('pnu')]
    if not items: raise HTTPException(422, '조회할 필지가 없습니다 (지번 미확정 토지는 제외)')
    try:
        return landreport.make_report(name, d, items)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    except OSError as exc: raise HTTPException(502, f'브이월드 연결 실패: {exc}') from exc


@app.post('/api/v4/sites/{name}/upload')
async def site_upload(name: str, files: list[UploadFile] = File(...)):
    d = documents.site_dir(name)
    if not d.is_dir(): raise HTTPException(404, '사업지 폴더가 없습니다')
    saved = []
    for f in files:
        fn = Path(f.filename or '').name
        if not fn or fn.startswith('.'): continue
        (d / fn).write_bytes(await f.read())
        saved.append(fn)
    return {'saved': saved}


@app.post('/api/v4/sites/{name}/open')
def site_open(name: str):
    import os
    d = documents.site_dir(name)
    if not d.is_dir(): raise HTTPException(404, '사업지 폴더가 없습니다')
    if os.name == 'nt':
        _open_folder_front(d)
    return {'path': str(d)}


def _open_folder_front(d: Path):
    """탐색기로 폴더를 열고 맨 앞으로 가져온다.
    서버(백그라운드 프로세스)가 연 창은 Windows 포커스 보호 때문에 브라우저 뒤에 숨으므로,
    이미 열린 같은 폴더 창은 재사용하고 창 핸들을 찾아 앞으로 올린다."""
    import ctypes
    import os
    import subprocess
    p = str(d).replace("'", "''")
    ps = (f"$p='{p}'; $sh=New-Object -ComObject Shell.Application;"
          "function F { $sh.Windows() | Where-Object { try { $_.Document.Folder.Self.Path -eq $p } catch { $false } } | Select-Object -First 1 };"
          "$w=F; if(-not $w){ Start-Process explorer.exe -ArgumentList ('\"'+$p+'\"');"
          " for($i=0; $i -lt 40 -and -not $w; $i++){ Start-Sleep -Milliseconds 150; $w=F } };"
          "if($w){ $w.HWND }")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True,
                             timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()
        hwnd = int(out.splitlines()[-1]) if out else 0
    except (subprocess.SubprocessError, ValueError, OSError):
        hwnd = 0
    if not hwnd:
        os.startfile(d)
        return
    u = ctypes.windll.user32
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)                 # SW_RESTORE
    u.keybd_event(0x12, 0, 0, 0)              # Alt 누름: 포커스 보호 해제 관례
    u.SetForegroundWindow(hwnd)
    u.keybd_event(0x12, 0, 2, 0)              # Alt 뗌
    u.BringWindowToTop(hwnd)


# ── v3: 사업수지분석표 Excel ──
@app.post('/api/v3/proforma/report.xlsx')
def proforma_report(p: Proforma):
    try: r = analyze(p)
    except (ValueError, ArithmeticError) as exc: raise HTTPException(422, str(exc)) from exc
    from urllib.parse import quote
    name = quote(f'사업수지분석표_{p.project_name}.xlsx')
    return Response(build_report(p, r), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{name}"})


# ── v4: 필지 정보 자동 조회 (브이월드 토지특성정보) · API 설정 ──
from . import landinfo


class ApiSettings(BaseModel):
    vworld_key: str | None = None
    vworld_domain: str | None = None


@app.get('/api/v4/settings')
def settings_get(): return landinfo.public_settings()


@app.put('/api/v4/settings')
def settings_put(s: ApiSettings):
    return landinfo.save_settings(vworld_key=(s.vworld_key or '').strip() or None, vworld_domain=(s.vworld_domain or '').strip() or None)


class ShapeItem(BaseModel):
    address: str = ''
    pnu: str = ''


class ShapeReq(BaseModel):
    items: list[ShapeItem] = Field(default_factory=list, max_length=200)


@app.post('/api/v4/land/shapes')
def land_shapes(req: ShapeReq):
    """여러 필지의 경계를 한 번에 (필지 통합 지도). 실패한 필지는 error 로 돌려준다."""
    from concurrent.futures import ThreadPoolExecutor
    def one(i_it):
        i, it = i_it
        try:
            pnu = it.pnu if len(re.sub(r'\D', '', it.pnu or '')) == 19 else landinfo.geocode_pnu(it.address)[0]
            f = landinfo.parcel_shape(pnu)
            return {**f, 'properties': {**f['properties'], 'idx': i, 'address': it.address}}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except Exception as exc:
            return {'type': 'Feature', 'geometry': None, 'properties': {'idx': i, 'address': it.address, 'error': str(exc)[:120]}}
    with ThreadPoolExecutor(max_workers=6) as ex:
        feats = list(ex.map(one, enumerate(req.items)))
    return {'type': 'FeatureCollection', 'features': feats}


@app.get('/api/v4/land/at')
def land_at(lat: float, lon: float):
    """지도에서 누른 위치의 필지 (지도에서 선택)."""
    try: return landinfo.parcel_at(lat, lon)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    except LookupError as exc: raise HTTPException(404, str(exc)) from exc
    except OSError as exc: raise HTTPException(502, f'연속지적도를 불러오지 못했습니다: {exc}') from exc


@app.get('/api/v4/land/center')
def land_center(q: str = ''):
    """시·군·구 이름 → 지도 시작 위치. 못 찾으면 null."""
    c = landinfo.area_center(q)
    return {'lat': c[0], 'lon': c[1]} if c else {'lat': None, 'lon': None}


@app.get('/api/v4/maptile/{layer}/{z}/{y}/{x}')
def maptile(layer: str, z: int, y: int, x: int):
    try:
        data, ctype = landinfo.map_tile(layer, z, y, x)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    except LookupError as exc: raise HTTPException(404, str(exc)) from exc
    except OSError as exc: raise HTTPException(502, f'지도 타일을 불러오지 못했습니다: {exc}') from exc
    return Response(data, media_type=ctype, headers={'Cache-Control': 'public, max-age=604800'})


@app.get('/api/v4/land')
def land(address: str = '', bcode: str = '', jibun: str = ''):
    """주소 문자열(직접 입력·검색 결과 모두) 또는 법정동코드+지번으로 필지 토지특성 조회."""
    try:
        if address.strip():
            pnu, refined = landinfo.geocode_pnu(address)
            info = {**landinfo.land_info(pnu), 'refined_address': refined}
        else:
            info = landinfo.land_info(landinfo.make_pnu(bcode, jibun))
        try:
            info['uses'] = landinfo.land_use(info['pnu'])
        except (OSError, ValueError):
            info['uses'] = []
        return info
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    except (ValueError, LookupError) as exc: raise HTTPException(404, str(exc)) from exc
    except OSError as exc: raise HTTPException(502, f'브이월드 연결 실패: {exc}') from exc


# ── v4: 3차 지자체 도시계획 — 토지이음 고시 자동 검색 · 결정조서 용적률 추출 ──
from . import eum


@app.get('/api/v4/plans/search')
def plans_search(address: str, kind: str = 'district', municipality: str = '', registered: str = ''):
    try:
        return {'candidates': eum.find_candidates(address, kind, municipality, registered)}
    except OSError as exc:
        raise HTTPException(502, f'토지이음 연결 실패: {exc}') from exc


@app.get('/api/v4/plans/extract')
def plans_extract(seq: str, address: str = ''):
    try:
        return eum.extract(seq, address)
    except OSError as exc:
        raise HTTPException(502, f'토지이음 연결 실패: {exc}') from exc


@app.post('/api/v3/proforma/cashflow.xlsx')
def proforma_cashflow_xlsx(p: Proforma):
    """월별 현금흐름 Excel (요약: 백만원 표시·원 단위 값 / 상세: 원)."""
    from . import cfexcel
    try: r = analyze(p)
    except (ValueError, ArithmeticError) as exc: raise HTTPException(422, str(exc)) from exc
    if not r.get('cashflow'):
        raise HTTPException(422, '월별 현금흐름을 켜야 합니다 (일정·현금흐름 탭)')
    from urllib.parse import quote
    name = quote(f'월별현금흐름_{p.project_name}.xlsx')
    return Response(cfexcel.build(p, r), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{name}"})


# ── v4: 사업지별 사업수지 (자료함/<사업지>/사업수지.json) ──
def _summary_for_list(p: Proforma) -> dict:
    r = analyze(p)
    s, rd, v = r['summary'], r.get('redevelopment'), r['verdict']
    return {'project_mode': p.project_mode, 'land_area_sqm': float(p.land_area_sqm), 'units': r['area']['units'],
            'zones': [z['zone'] for z in r['compliance']['zones']], 'revenue_net': s['revenue_net'], 'total_cost': s['total_cost'],
            'pbt': s['pbt'], 'npat': s['npat'], 'margin_pct': s['margin_pct'], 'bep_sales_rate_pct': s['bep_sales_rate_pct'],
            'equity_irr_pct': s.get('equity_irr_pct'), 'proportional_rate_pct': rd['proportional_rate_pct'] if rd else None,
            'verdict': v['overall'], 'verdict_label': v['label'],
            'location': ' '.join(x for x in [p.site.province, p.site.municipality] if x)}


# ── 시나리오 비교 · 스트레스 테스트 ──
from . import scenarios as scnmod


@app.post('/api/v4/proforma/stress')
def proforma_stress(p: Proforma):
    try: return {'cases': scnmod.stress(p)}
    except (ValueError, ArithmeticError) as exc: raise HTTPException(422, str(exc)) from exc


@app.get('/api/v4/sites/{name}/scenarios/compare')
def scenarios_compare(name: str):
    cols = []
    cur = documents.load_proforma(name)
    if cur:
        try: cols.append({'name': '현재 작업본', 'current': True, **scnmod.metrics(Proforma.model_validate(cur))})
        except (ValueError, ArithmeticError) as exc: cols.append({'name': '현재 작업본', 'current': True, 'error': str(exc)})
    for s in documents.list_scenarios(name):
        try:
            pf = documents.load_proforma(name, s['name'])
            cols.append({**s, **scnmod.metrics(Proforma.model_validate(pf))})
        except (ValueError, ArithmeticError) as exc:
            cols.append({**s, 'error': str(exc)})
    return {'columns': cols}


@app.delete('/api/v4/sites/{name}/scenarios/{scenario}')
def scenario_delete(name: str, scenario: str):
    try: return documents.delete_scenario(name, scenario)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.get('/api/v4/sites/{name}/proforma')
def site_proforma_get(name: str, scenario: str | None = None):
    try: return {'proforma': documents.load_proforma(name, scenario), 'scenarios': documents.list_scenarios(name)}
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@app.put('/api/v4/sites/{name}/proforma')
def site_proforma_put(name: str, p: Proforma, scenario: str | None = None, memo: str = ''):
    try:
        summary = None if scenario else _summary_for_list(p)
        # Decimal 을 문자열이 아닌 숫자로 저장 (정수는 int, 소수는 float)
        payload = json.loads(json.dumps(p.model_dump(), default=lambda d: int(d) if d == d.to_integral_value() else float(d)))
        if scenario:
            from datetime import datetime
            payload['_scenario'] = {'memo': memo[:300], 'saved_at': datetime.now().isoformat(timespec='minutes')}
        return {**documents.save_proforma(name, payload, summary, scenario), 'summary': summary}
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except (ValueError, ArithmeticError) as exc: raise HTTPException(422, str(exc)) from exc
