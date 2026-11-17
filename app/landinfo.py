"""필지 정보 자동 조회: 브이월드(국토교통부 공간정보 오픈플랫폼) 토지특성정보 API.

필지고유번호(PNU, 19자리) = 법정동코드(10) + 대장구분(1: 일반, 2: 산) + 본번(4) + 부번(4)
API 인증키는 data/settings.json 에만 저장(서버 측)하고 화면에는 앞뒤 일부만 표시한다.
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .config import SETTINGS
NED_URL = 'https://api.vworld.kr/ned/data/getLandCharacteristics'


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_settings(**kw) -> dict:
    s = load_settings()
    s.update({k: v for k, v in kw.items() if v is not None})
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding='utf-8')
    return public_settings()


def public_settings() -> dict:
    s = load_settings()
    k = s.get('vworld_key') or ''
    return {'vworld_key_set': bool(k), 'vworld_key_masked': (k[:4] + '…' + k[-4:]) if len(k) > 8 else ('설정됨' if k else ''),
            'vworld_domain': s.get('vworld_domain') or 'http://127.0.0.1:8001'}


def make_pnu(bcode: str, jibun: str) -> str:
    """법정동코드 + 지번('1591', '1593-1', '산 12-3') → PNU."""
    bcode = re.sub(r'\D', '', bcode or '')
    if len(bcode) != 10:
        raise ValueError('법정동코드(10자리)가 없습니다')
    m = re.search(r'(산\s*)?(\d+)(?:\s*-\s*(\d+))?\s*$', (jibun or '').strip())
    if not m:
        raise ValueError(f'지번을 인식하지 못했습니다: {jibun}')
    return f"{bcode}{'2' if m.group(1) else '1'}{int(m.group(2)):04d}{int(m.group(3) or 0):04d}"


GEOCODER_URL = 'https://api.vworld.kr/req/address'


def geocode_pnu(address: str) -> tuple[str, str]:
    """지번 주소(약칭·일부 생략 가능) → (PNU 19자리, 정제된 주소). 브이월드 지오코더(parcel)."""
    s = load_settings()
    key = s.get('vworld_key')
    if not key:
        raise PermissionError('브이월드 API 인증키가 설정되지 않았습니다 (설정 › API 설정)')
    # 지번 없이 동까지만 입력하면 지오코더가 임의 필지(예: 1번지)를 돌려주므로 차단
    if not re.search(r'(산\s*)?\d+(\s*-\s*\d+)?\s*$', address.strip()):
        raise LookupError('지번까지 입력해야 필지를 찾을 수 있습니다 (예: 관양동 1591)')
    q = urllib.parse.urlencode({'service': 'address', 'request': 'getcoord', 'version': '2.0', 'crs': 'epsg:4326', 'address': address.strip(),
                                'refine': 'true', 'simple': 'false', 'format': 'json', 'type': 'parcel', 'key': key,
                                'domain': s.get('vworld_domain') or 'http://127.0.0.1:8001'})
    req = urllib.request.Request(f'{GEOCODER_URL}?{q}', headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode('utf-8'))
    res = body.get('response') or {}
    if res.get('status') != 'OK':
        err = (res.get('error') or {}).get('text') or res.get('status') or '주소를 찾지 못했습니다'
        raise LookupError(f'주소를 필지로 찾지 못했습니다 ({err}) — 「시·군·구 동 지번」 형식으로 입력하세요')
    st = (res.get('refined') or {}).get('structure') or {}
    pnu = re.sub(r'\D', '', st.get('level4LC') or '')
    if len(pnu) != 19:
        raise LookupError('지번까지 입력해야 필지를 찾을 수 있습니다 (예: 관양동 1591)')
    return pnu, (res.get('refined') or {}).get('text', address)


def land_use(pnu: str) -> list[dict]:
    """토지이용계획 지역·지구 (브이월드 토지이용계획속성): 지구단위계획구역·정비구역·도시계획시설 저촉 등."""
    s = load_settings()
    q = urllib.parse.urlencode({'key': s.get('vworld_key', ''), 'pnu': pnu, 'format': 'json', 'numOfRows': 100, 'pageNo': 1,
                                'domain': s.get('vworld_domain') or 'http://127.0.0.1:8001'})
    req = urllib.request.Request(f'https://api.vworld.kr/ned/data/getLandUseAttr?{q}', headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode('utf-8'))
    root = next(iter(body.values()), {}) if isinstance(body, dict) else {}
    fields = root.get('field') or [] if isinstance(root, dict) else []
    if isinstance(fields, dict):
        fields = [fields]
    seen, out = set(), []
    for f in fields:
        k = (f.get('prposAreaDstrcCodeNm'), f.get('cnflcAtNm'))
        if k in seen or not k[0]:
            continue
        seen.add(k)
        out.append({'name': f.get('prposAreaDstrcCodeNm'), 'code': f.get('prposAreaDstrcCode'), 'relation': f.get('cnflcAtNm'),
                    'registered': (f.get('registDt') or '')[:10]})
    return out


def land_info(pnu: str) -> dict:
    s = load_settings()
    key = s.get('vworld_key')
    if not key:
        raise PermissionError('브이월드 API 인증키가 설정되지 않았습니다 (설정 › API 설정)')
    q = urllib.parse.urlencode({'key': key, 'pnu': pnu, 'format': 'json', 'numOfRows': 50, 'pageNo': 1,
                                'domain': s.get('vworld_domain') or 'http://127.0.0.1:8001'})
    req = urllib.request.Request(f'{NED_URL}?{q}', headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode('utf-8'))
    root = body.get('landCharacteristicss') or {}
    fields = root.get('field') or []
    if isinstance(fields, dict):
        fields = [fields]
    if not fields:
        err = (body.get('response') or {}).get('error') or root.get('resultMsg') or '조회 결과가 없습니다'
        raise LookupError(f'토지특성정보 없음 (PNU {pnu}): {err}')
    f = max(fields, key=lambda x: (str(x.get('stdrYear', '')), str(x.get('stdrMt', ''))))   # 최신 기준연도

    def num(v):
        try:
            return float(str(v).replace(',', ''))
        except (TypeError, ValueError):
            return None
    zones = [z for z in (f.get('prposArea1Nm'), f.get('prposArea2Nm')) if z and z not in ('지정되지않음', '')]
    return {'pnu': pnu, 'address': f.get('ldCodeNm', ''), 'jibun': f.get('mnnmSlno', ''),
            'area_sqm': num(f.get('lndpclAr')), 'jimok': f.get('lndcgrCodeNm') or '',
            'zone': zones[0] if zones else '', 'zones': zones, 'price_per_sqm': num(f.get('pblntfPclnd')),
            'year': f.get('stdrYear'), 'land_use': f.get('ladUseSittnNm') or '', 'road_side': f.get('roadSideCodeNm') or '',
            'source': '브이월드 토지특성정보 (국토교통부)'}


# ── 필지 경계(연속지적도) · 지도 타일 — 필지 통합 지도 ──
_SHAPES: dict[str, dict] = {}
_TILES: dict[str, bytes] = {}
TILE_LAYERS = {'Base': 'png', 'Satellite': 'jpeg', 'Hybrid': 'png', 'white': 'png'}


def _vworld_get(url: str, timeout: int = 20) -> bytes:
    s = load_settings()
    dom = s.get('vworld_domain') or 'http://127.0.0.1:8001'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': dom})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parcel_shape(pnu: str) -> dict:
    """PNU → 필지 경계 GeoJSON Feature (브이월드 2D 데이터 LP_PA_CBND_BUBUN, EPSG:4326)."""
    pnu = re.sub(r'\D', '', pnu or '')
    if len(pnu) != 19:
        raise LookupError('PNU가 올바르지 않습니다')
    if pnu in _SHAPES:
        return _SHAPES[pnu]
    s = load_settings()
    key = s.get('vworld_key')
    if not key:
        raise PermissionError('브이월드 API 인증키가 설정되지 않았습니다 (설정 › API 설정)')
    q = urllib.parse.urlencode({'service': 'data', 'request': 'GetFeature', 'data': 'LP_PA_CBND_BUBUN', 'key': key,
                                'domain': s.get('vworld_domain') or 'http://127.0.0.1:8001', 'attrFilter': f'pnu:=:{pnu}',
                                'geometry': 'true', 'attribute': 'true', 'crs': 'EPSG:4326', 'format': 'json', 'size': 10})
    body = json.loads(_vworld_get(f'https://api.vworld.kr/req/data?{q}').decode('utf-8'))
    res = body.get('response') or {}
    feats = ((res.get('result') or {}).get('featureCollection') or {}).get('features') or []
    if res.get('status') != 'OK' or not feats:
        raise LookupError('연속지적도에서 필지 경계를 찾지 못했습니다')
    f = feats[0]
    out = {'type': 'Feature', 'geometry': f['geometry'], 'properties': {k: f['properties'].get(k) for k in ('pnu', 'jibun', 'addr', 'jiga')}}
    if len(_SHAPES) > 2000:
        _SHAPES.clear()
    _SHAPES[pnu] = out
    return out


def parcel_at(lat: float, lon: float) -> dict:
    """지도에서 누른 위치(위경도) → 그 자리의 필지 경계·지번 (연속지적도 LP_PA_CBND_BUBUN, 점 공간검색)."""
    if not (33 <= lat <= 39 and 124 <= lon <= 132):
        raise LookupError('국내 위치가 아닙니다')
    s = load_settings()
    key = s.get('vworld_key')
    if not key:
        raise PermissionError('브이월드 API 인증키가 설정되지 않았습니다 (설정 › API 설정)')
    q = urllib.parse.urlencode({'service': 'data', 'request': 'GetFeature', 'data': 'LP_PA_CBND_BUBUN', 'key': key,
                                'domain': s.get('vworld_domain') or 'http://127.0.0.1:8001', 'geomFilter': f'POINT({lon:.7f} {lat:.7f})',
                                'geometry': 'true', 'attribute': 'true', 'crs': 'EPSG:4326', 'format': 'json', 'size': 5})
    body = json.loads(_vworld_get(f'https://api.vworld.kr/req/data?{q}').decode('utf-8'))
    res = body.get('response') or {}
    feats = ((res.get('result') or {}).get('featureCollection') or {}).get('features') or []
    if res.get('status') != 'OK' or not feats:
        raise LookupError('이 위치에서 필지를 찾지 못했습니다 (도로·하천 경계 등) — 필지 안쪽을 눌러 보세요')
    f = feats[0]
    props = {k: f['properties'].get(k) for k in ('pnu', 'jibun', 'addr', 'jiga')}
    out = {'type': 'Feature', 'geometry': f['geometry'], 'properties': props}
    if props.get('pnu'):
        _SHAPES[re.sub(r'\D', '', props['pnu'])] = out
    return out


def area_center(query: str) -> tuple[float, float] | None:
    """시·군·구 이름 → 지도 시작 위치 (브이월드 검색 API 행정구역). 실패하면 None."""
    s = load_settings()
    key = s.get('vworld_key')
    if not key or not query.strip():
        return None
    for cat in ('L2', 'L1'):
        q = urllib.parse.urlencode({'service': 'search', 'request': 'search', 'version': '2.0', 'crs': 'EPSG:4326', 'size': 1,
                                    'query': query.strip(), 'type': 'district', 'category': cat, 'format': 'json', 'key': key,
                                    'domain': s.get('vworld_domain') or 'http://127.0.0.1:8001'})
        try:
            body = json.loads(_vworld_get(f'https://api.vworld.kr/req/search?{q}', timeout=10).decode('utf-8'))
            items = (((body.get('response') or {}).get('result') or {}).get('items') or [])
            if items:
                pt = items[0].get('point') or {}
                return float(pt['y']), float(pt['x'])
        except Exception:
            continue
    return None


def map_tile(layer: str, z: int, y: int, x: int) -> tuple[bytes, str]:
    """브이월드 WMTS 타일 중계 (인증키를 브라우저에 노출하지 않음)."""
    ext = TILE_LAYERS.get(layer)
    if not ext or not (5 <= z <= 19):
        raise LookupError('지원하지 않는 지도 종류입니다')
    k = f'{layer}/{z}/{y}/{x}'
    if k not in _TILES:
        key = load_settings().get('vworld_key')
        if not key:
            raise PermissionError('브이월드 API 인증키가 설정되지 않았습니다')
        data = _vworld_get(f'https://api.vworld.kr/req/wmts/1.0.0/{key}/{layer}/{z}/{y}/{x}.{ext}', timeout=15)
        if len(_TILES) > 3000:
            _TILES.clear()
        _TILES[k] = data
    return _TILES[k], 'image/png' if ext == 'png' else 'image/jpeg'
