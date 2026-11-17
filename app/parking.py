"""비주거(오피스텔·상가·업무·지식산업센터·데이터센터) 부설주차장 — 주차장법 시행령 별표1 + 지자체 주차장 조례 별표.

- 국가 기준: 주차장법 시행령 [별표 1] (시행 2026. 8. 28., 원문 대조 2026-11-17)
- 지자체: 「○○ 주차장 설치 및 관리 조례」(또는 주차장 조례)의 '부설주차장 설치기준' 별표. 시설면적 ○㎡당 1대 를 용도별로 판독.
  특별시·광역시 자치구는 구 조례에 설치기준이 없으면 시 조례를 쓴다(서울·부산 등).
- 복합 건축물: 별표1 비고 4·6 — 용도별 대수를 소수 첫째 자리까지 합산, 소수점 이하 0.5 이상은 1대. 공동주택·오피스텔(제5호)은 따로 산정해 더한다.
"""
import json
from html import unescape as htmllib_unescape
import re
import sqlite3
import urllib.parse
from datetime import datetime

from . import lawdata as L

NATIONAL_SOURCE = {'title': '주차장법 시행령 [별표 1] 부설주차장의 설치대상 시설물 종류 및 설치기준', 'effective': '2026-08-28',
                   'url': 'https://www.law.go.kr/법령/주차장법시행령'}
# 시설면적 ㎡당 1대 (별표1 제2호 업무·판매 150, 제3호 근생 200, 제10호 데이터센터 400, 제11호 그 밖 300 — 지식산업센터는 '아파트형 공장'으로 제7호 제외 → 그 밖)
NATIONAL = {'retail': 200.0, 'office': 150.0, 'sales': 150.0, 'knowledge': 300.0, 'datacenter': 400.0, 'other': 300.0}
KIND_LABEL = {'retail': '근린생활시설(상가)', 'office': '업무시설', 'knowledge': '지식산업센터', 'datacenter': '데이터센터', 'other': '그 밖의 건축물'}

_AREA = r'([\d,]+(?:\.\d+)?)\s*(?:㎡|제곱미터|m2|㎡)\s*(?:당|마다)\s*1\s*대'   # 평택: '150㎡마다 1대'


def _conn():
    c = L._conn()
    c.execute('''CREATE TABLE IF NOT EXISTS parking_cache (province TEXT NOT NULL, municipality TEXT NOT NULL, data_json TEXT NOT NULL,
                 fetched_at TEXT NOT NULL, PRIMARY KEY (province, municipality))''')
    return c


def cached(province: str, municipality: str) -> dict | None:
    c = _conn()
    try:
        r = c.execute('SELECT data_json FROM parking_cache WHERE province=? AND municipality=?', (province, municipality)).fetchone()
        return json.loads(r[0]) if r else None
    finally:
        c.close()


def _save(province: str, municipality: str, data: dict) -> dict:
    c = _conn()
    try:
        # HWP에서 나온 깨진 글자(서로게이트)는 저장 전에 바꾼다 (담양)
        js = json.dumps(data, ensure_ascii=False).encode('utf-8', 'replace').decode('utf-8')
        c.execute('INSERT OR REPLACE INTO parking_cache VALUES (?,?,?,?)', (province, municipality, js, datetime.now().isoformat(timespec='seconds')))
        c.commit()
    finally:
        c.close()
    return data


# ── 조례 찾기 ──
def candidates(province: str, municipality: str) -> list[tuple[str, str]]:
    """(검색어 이름, 적용 범위) 목록. 자치구는 구 조례 다음에 시 조례."""
    p, m = province.strip(), (municipality or '').strip()
    names = []
    if m and m != p and p not in ('세종특별자치시', '제주특별자치도'):
        if p.endswith(('특별시', '광역시')):
            names += [(p + m + '주차장설치및관리조례', m), (p + m + '주차장조례', m)]
        else:
            names += [(m + '주차장설치및관리조례', m), (m + '주차장조례', m), (m + '주차장설치및운영조례', m)]
    names += [(p + '주차장설치및관리조례', p), (p + '주차장조례', p)]
    return names


def _search(province: str, name: str) -> tuple[str, str] | None:
    h = L._get(f"{L.LAW_BASE}/LSW/ordinSc.do?menuId=3&subMenuId=27&tabMenuId=139&query={urllib.parse.quote(name + ' 주차장')}")
    for seq, title in re.findall(r"ordinInfPop\('(\d{5,})'[^>]*>(.*?)</a>", h, flags=re.S):
        t = re.sub(r'\s+', '', re.sub(r'<[^>]+>', ' ', title))
        t = re.sub(r'\[[^\]]*\]$', '', t)
        # 성남: '주차장 설치 및 관리 운영에 관한 조례' — 시행규칙·특별회계·융자 등은 제외
        for pre in (name, province + name):
            pre = pre.replace(' ', '')
            if t.startswith(pre) and re.fullmatch(r'주차장(?:의)?(?:설치[^조]*)?조례', t[len(pre):]):
                return seq, t
    return None


def _byl_by_title(html: str) -> str | None:
    """별표 목록에서 제목이 '부설주차장 … 설치기준/설치대상'인 별표 번호 (인천·평택·제천처럼 조문 제목이 제각각인 경우)."""
    for t in re.findall(r'class="blu"[^>]*>\s*<img[^>]*>\s*([^<]{0,120}?)\s*</a>', html):
        t = htmllib_unescape(t)
        if re.search(r'부설\s*주차장', t) and re.search(r'설치\s*기준|설치\s*대상', t) and not re.search(r'기계식|구조|비용|완화', t):
            m = re.search(r'별표\s*(\d+(?:\s*의\s*\d+)?)', t)
            if m:
                return re.sub(r'\s', '', m.group(1))
    return None


def _byl_file_by_title(html: str) -> tuple[str, str] | None:
    """번호 없이 제목만 있는 별표(이천: '부설주차장의 설치대상시설물 종류 및 설치기준')의 파일을 바로 받는다 → (제목, 본문)."""
    for m in re.finditer(r'class="blu"[^>]*>\s*<img[^>]*>\s*([^<]{0,120}?)\s*</a>.{0,900}?flDownload\.do\?([^"\']+)', html, flags=re.S):
        t = htmllib_unescape(m.group(1))
        if re.search(r'부설\s*주차장', t) and re.search(r'설치\s*기준|설치\s*대상', t) and not re.search(r'기계식|구조|비용|완화', t):
            body = L._download_text(m.group(2))
            if body:
                return re.sub(r'\s+', ' ', t).strip(), body
    return None


_TABLE_HEAD = re.compile(r'부설\s*주차장[^\n]{0,40}?설치\s*(?:기준|대상)|설치대상\s*시설물[^\n]{0,20}설치\s*기준')


def _scan_files(html: str, limit: int = 10) -> tuple[str, dict] | None:
    """조례 화면의 별표·서식 파일을 차례로 받아 '부설주차장 설치기준' 표를 찾는다 → (제목, 판독 결과)."""
    i = html.find('name="byl"')
    links = list(dict.fromkeys(re.findall(r'flDownload\.do\?([^"\']+)', html[i if i >= 0 else 0:])))[:limit]
    for q in links:
        try:
            body = L._download_text(q)
        except Exception:
            continue
        if not body or not re.search(_AREA, body):
            continue
        starts = [m for m in _TABLE_HEAD.finditer(body)]
        cands = [body[m.start():] for m in starts] or [body]
        for seg in cands:
            nxt = re.search(r'\n\s*[\[〔【「]?\s*별표\s*\d+(?:\s*의\s*\d+)?\s*[\]〕】」]', seg[20:])
            seg = seg[:nxt.start() + 20] if nxt else seg
            d = parse(seg)
            if d['rates'].get('retail') or d['rates'].get('office'):
                return _appendix_head(seg), d
    return None


def _appendix_head(seg: str) -> str:
    m = _TABLE_HEAD.search(seg)
    line = seg[m.start():].split('\n')[0] if m else seg.strip().split('\n')[0]
    return re.sub(r'\s+', ' ', line).strip()[:80]


def _follows_national(text: str) -> dict | None:
    """'부설주차장의 설치기준' 조문이 시행령 별표 1을 그대로 적용하는 경우 → 국가 기준 + 본문의 공동주택 세대당 기준."""
    a = re.search(r'제\d+조(?:의\d+)?\s*\(\s*(?:건축물\s*)?부설\s*주차장(?:의)?\s*설치\s*기준\s*\)', text)
    if not a:
        return None
    body = text[a.end():a.end() + 1500]
    nxt = re.search(r'\n\s*제\d+조(?:의\d+)?\s*\(', body)
    body = body[:nxt.start()] if nxt else body
    if not re.search(r'영\s*\)?\s*제6조\s*제1항[^.]{0,30}별표\s*1|영\s*별표\s*1', body):
        return None
    # 제천: ① 공동주택 세대당 1.2대 … ② 의료시설: 시설면적 ○㎡당 1대 … (본문 각 호)
    rates = {}
    for line in re.split(r'(?<=[.\s])(?=\d{1,2}\.\s*[가-힣])', re.sub(r'\s+', ' ', body)):
        r = _rate(line)
        if not r:
            continue
        if re.search(r'제\s*[12]\s*종\s*근린생활시설', line):
            rates.setdefault('retail', r)
        elif re.search(r'업무시설', line) and '오피스텔' not in line:
            rates.setdefault('office', r)
        elif '지식산업센터' in line:
            rates.setdefault('knowledge', r)
    flat = re.sub(r'\s+', ' ', body)
    apt = re.search(r'공동주택\s*[:：].*?(?=\s\d{1,2}\.\s*[가-힣]|②|$)', flat)   # 제천: '2. 공동주택 : 세대당 1.2대(…60㎡ 이하 1대)'
    res_part = apt.group(0) if apt else flat   # 나주: '② 공동주택 … 1. 세대당 1대(60㎡ 이하 0.7대)'
    return {'rates': rates, 'texts': {'residential': re.sub(r'\s+', ' ', res_part)[:400]}, 'residential': _residential(res_part), 'follows_national': True}


def _article_appendix(text: str) -> str | None:
    """'부설주차장의 설치기준' 조문이 가리키는 별표 번호."""
    for a in re.finditer(r'제\d+조(?:의\d+)?\s*\(\s*(?:건축물\s*)?부설\s*주차장(?:의)?\s*(?:설치|시설)[^)]{0,30}\)', text):   # 청도: '(부설주차장의 설치)'
        if re.search(r'비용|인근|구조|기계식', a.group(0)):
            continue
        body = text[a.end():a.end() + 500]
        m = re.search(r'별표\s*(\d+(?:\s*의\s*\d+)?)', body)
        if m and re.search(r'설치\s*기준|종류', body[:m.end() + 40]):
            return re.sub(r'\s', '', m.group(1))
    return None


def fetch(province: str, municipality: str) -> dict:
    """주차장 조례를 찾아 판독·저장. 후보 조례 하나에서 내려받기·판독이 실패해도 다음 후보(자치구 → 시)로 넘어간다."""
    tried, last_err = [], None
    for name, scope in candidates(province, municipality):
        try:
            data = _try_one(province, municipality, name, scope, tried)
        except Exception as exc:   # 네트워크·HWP 판독 오류
            last_err = exc
            continue
        if data:
            return _save(province, municipality, data)
    if last_err and not tried:
        raise OSError(f'국가법령정보센터 연결 실패: {last_err}')
    # 못 찾은 결과도 저장해 화면을 열 때마다 다시 내려받지 않게 한다 (판독기 버전이 오르면 다시 시도)
    _save(province, municipality, {'missing': True, 'rates': {}, 'residential': None, 'texts': {}, 'title': '', 'parser': PARSER_VERSION,
                                   'checked': datetime.now().date().isoformat()})
    raise LookupError(f'{municipality or province}의 주차장 조례에서 부설주차장 설치기준 별표를 찾지 못했습니다')


def _try_one(province: str, municipality: str, name: str, scope: str, tried: list) -> dict | None:
    found = None
    h = L._get(L.LAW_BASE + '/' + urllib.parse.quote('자치법규/' + name))
    seqs = re.findall(r'ordinSeq[=\'":\s]+(\d{5,})', h)
    if seqs:
        found = (seqs[0], name)
    else:
        found = _search(province if scope != province else '', scope)
    if not found or found[0] in tried:
        return None
    tried.append(found[0])
    seq = found[0]
    html = L._get(f'{L.LAW_BASE}/ordinInfoR.do?ordinSeq={seq}')
    text = L._text(html)
    no = _byl_by_title(html) or _article_appendix(text)
    got = L.fetch_appendix(seq, html, no) if no else None
    label = f'[별표 {no}] ' if got else ''
    if not got:
        got = _byl_file_by_title(html)
    data = parse(got[1]) if got else None
    if not data or not data['rates']:
        scanned = _scan_files(html)   # 여주·화순·진도·김제 등: 별표가 한 파일로 묶였거나 제목·번호가 제각각
        if scanned:
            got, data, label = (scanned[0], ''), scanned[1], ''
    if not data or (not data['rates'] and not data.get('residential')):
        nat = _follows_national(text)   # 나주: '영 별표 1의 기준을 적용' + 공동주택 세대당 기준만 본문에
        if not nat:
            return None   # 자치구 조례에 설치기준이 없으면 시 조례로
        data, got, label = nat, ('시행령 별표 1 준용', ''), ''
    head = text[:3000]
    eff = re.search(r'시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})', head)
    title = re.search(r'([가-힣]+\s*주차장\s*(?:설치\s*및\s*(?:관리|운영)\s*)?조례)', head)
    data.update({'ordin_seq': seq, 'title': (title.group(1) if title else found[1]), 'appendix': (label + got[0]).strip(),
                 'effective': f'{eff.group(1)}-{int(eff.group(2)):02d}-{int(eff.group(3)):02d}' if eff else None,
                 'url': f'{L.LAW_BASE}/ordinInfoR.do?ordinSeq={seq}', 'scope': scope, 'parser': PARSER_VERSION})
    return data


PARSER_VERSION = 14


# ── 별표 판독 ──
def _items(t: str) -> list[tuple[str, str]]:
    """'1. 위락시설 ○시설면적 67㎡당 1대 2. …' → [(시설물, 설치기준)]. 비고 이후는 버린다."""
    t = re.sub(r'[ \t　]{3,}', '\n', t)    # 공주: 칸 사이가 줄바꿈 없이 긴 공백
    t = re.sub(r'[ \t　]+', ' ', t)
    # 표 아래 '비고'(서울: '<비고>')부터는 버린다. 단 표 머리의 '시설물 | 설치기준 | 비고' 열 제목(서산)은 첫 항목보다 앞이므로 남긴다
    first = re.search(r'(?:^|\n)\s*1\s*\.\s*[가-힣「]', t)
    note = re.search(r'\n\s*[<〈(]?\s*비\s*고\s*[>〉)]?\s*\n', t[first.end():]) if first else None
    if note:
        t = t[:first.end() + note.start()]
    parts = re.split(r'(?:^|\n)\s*(\d{1,2})\s*\.\s*(?=[가-힣「])', '\n' + t)
    out = []
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1].strip()
        cut = re.search(r'[○◦ㅇ●]|시설\s*면적|전용\s*면적', body)
        head = body[:cut.start()] if cut else body[:120]
        out.append((re.sub(r'\s+', ' ', head).strip(), re.sub(r'\s+', ' ', body[len(head):]).strip()))
    return out


def _rate(rule: str) -> float | None:
    m = re.search(_AREA, rule)
    return float(m.group(1).replace(',', '')) if m else None


def parse(t: str) -> dict:
    rates, texts, sub = {}, {}, {}
    residential = None
    for head, rule in _items(t):
        h = re.sub(r'\s', '', head)
        r = _rate(rule)
        if '공동주택' in h:   # 제5호. '업무시설(오피스텔은 제외)'만 있는 제2호(인천)와 혼동하지 않게 공동주택으로만 판별
            residential = _residential(head + ' ' + rule)
            texts['residential'] = rule[:400]
            continue
        if '근린생활시설' in h and '제2종' in h:
            rates['retail'], texts['retail'] = r, rule[:300]
        if '업무시설' in h and 'office' not in rates:   # 제5호(오피스텔)는 위에서 걸러짐
            rates['office'], texts['office'] = r, rule[:300]
            if '판매시설' in h:
                rates['sales'] = r
        if '데이터센터' in h:
            rates['datacenter'], texts['datacenter'] = r, rule[:300]
        if re.match(r'^(?:그\s*밖의|기타)\s*(?:건축물|시설)', head):   # 평택: '기타 건축물'
            # 서울: '○ 학생용기숙사 400 ○ 학교시설 250 ○ …을 제외한 그 밖의 건축물 200' → '제외한 그 밖의' 항목
            segs = [x for x in re.split(r'[○◦ㅇ●]', rule) if re.search(_AREA, x)]
            pick = next((x for x in segs if re.search(r'그\s*밖의|제외한', x)), segs[0] if segs else rule)
            rates['other'], texts['other'] = _rate(pick), pick.strip()[:300]
        # 하위 목: '가. 지식산업센터 … 150㎡당 1대' (그 밖의 건축물 아래 등 어디든)
        for sm in re.finditer(r'지식산업센터[^○]{0,80}?' + _AREA, head + ' ' + rule):
            sub['knowledge'] = float(sm.group(1).replace(',', ''))
            texts['knowledge'] = sm.group(0)[:200]
    if 'knowledge' not in sub:
        km = re.search(r'(?:지식산업센터|아파트형\s*공장)[^\n]{0,120}?' + _AREA, t)
        if km and not re.search(r'아파트형[은는]?\s*제외', km.group(0)):
            sub['knowledge'] = float(km.group(1).replace(',', ''))
            texts['knowledge'] = km.group(0)[:200]
    rates.update(sub)
    if rates.get('knowledge') is None and rates.get('other'):
        rates['knowledge'] = rates['other']
        texts.setdefault('knowledge', '지식산업센터 별도 규정 없음 → 그 밖의 건축물 기준')
    if rates.get('datacenter') is None and rates.get('other'):
        rates['datacenter'] = rates['other']
    return {'rates': {k: v for k, v in rates.items() if v}, 'texts': texts, 'residential': residential}


_SPECIAL = r'도시형\s*생활\s*주택|원룸형|소형\s*주택|주택법\s*시행령」?\s*제10조|공공주택\s*특별법|다가구\s*주택\s*[:：]|세대구분형'


_BAND_HEAD = re.compile(r'(?:전용\s*면적\s*(?:이|은|을)?\s*)?(\d{2,3})\s*㎡\s*(?:를|을)?\s*(?:초과\s*[∼~\-–]?\s*(\d{2,3})\s*㎡\s*)?(이하|미만|초과)(?!하는\s*\d)')   # 양양 '85㎡를 초과하는 85㎡당'은 경계 아님, 강릉 '85㎡를 초과하는 경우'는 경계
_PER_UNIT = re.compile(r'(?:세대|호실|가구|실)[^.㎡\d]{0,15}?(?:당|별|마다)\s*[)）]?\s*(\d(?:\.\d+)?)\s*대')


def _bands(t: str) -> dict | None:
    """면적대별 공동주택 주차 기준 → {'bands': [[상한㎡|None, 세대당 대수|None, ㎡당 1대|None, 기본대수|None, 초과기준㎡|None]], 'apt_min': 아파트 세대당 최소}.
    춘천·아산 '【전용 60㎡ 이하】 세대당 1대 【60~85㎡】 1.5대 【85㎡ 초과】 50㎡당 1대(다만 세대당 1.7대 이상)',
    강릉·동해 '60㎡ 이하는 세대당 1대, 85㎡ 이하는 1.3대, 85㎡를 초과하는 경우 60㎡당 1대',
    양양 '85㎡ 초과: 1.5대에 85㎡를 초과하는 85㎡당 1대를 더한 대수', 이천·포천 '아파트는 세대당 1.4대 이상'."""
    # 이천·포천: '아파트의 경우(에는) 세대당 1.4대 이상' — 강릉 '아파트 중 전용면적이 …'은 해당 없음
    apt = re.search(r'아파트(?:의\s*경우(?:에는)?|는|은)\s*[^.]{0,20}?세대\s*당\s*(\d(?:\.\d+)?)\s*대', t)
    if apt:
        t = t[:apt.start()] + t[apt.end():]   # 아파트 최소 기준은 면적대 규칙(오피스텔에도 적용)과 분리
    heads = list(_BAND_HEAD.finditer(t))
    bands = []
    for i, m in enumerate(heads):
        seg = t[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(t)]
        if m.group(3) == '초과' and not m.group(2):
            upper = None
        else:
            upper = float(m.group(2) or m.group(1))
        extra = re.search(r'(\d(?:\.\d+)?)\s*대에\s*(\d+)\s*㎡\s*(?:를|을)?\s*초과하는\s*(\d+)\s*㎡\s*당\s*1\s*대', seg)
        area = re.search(_AREA.replace(r'1\s*대', r'1(?:\.0)?\s*대'), seg)
        per = _PER_UNIT.search(seg) or re.match(r'^\s*(?:인\s*경우)?\s*[:：)\]】〕]?\s*[-–]?\s*(\d(?:\.\d+)?)\s*대', seg)
        if extra:
            bands.append([upper, float(extra.group(1)), float(extra.group(3)), float(extra.group(2)), 'extra'])
        elif area or per:
            bands.append([upper, float(per.group(1)) if per else None, float(area.group(1).replace(',', '')) if area else None, None, None])
    # 같은 상한이 여러 번 나오면(괄호 속 예외 등) 처음 것만
    seen, uniq = set(), []
    for b in bands:
        if b[0] not in seen:
            seen.add(b[0])
            uniq.append(b)
    if len(uniq) < 2:
        return None
    uniq.sort(key=lambda b: (b[0] is None, b[0] or 0))
    return {'bands': uniq, 'apt_min': float(apt.group(1)) if apt else None}


def per_unit_spaces(res: dict, exclusive: float, is_apartment: bool) -> float | None:
    """면적대별 기준(_bands 결과)으로 한 세대(호실)의 주차대수. 해당 면적대가 없으면 None."""
    band = next((b for b in res['bands'] if b[0] is None or exclusive <= b[0]), None)
    if band is None:
        return None
    upper, per, area, base, kind = band
    if kind == 'extra':   # 1.5대 + (전용 − 85㎡) ÷ 85㎡
        v = per + max(exclusive - base, 0) / area
    else:
        v = max(per or 0, exclusive / area if area else 0)
    if is_apartment and res.get('apt_min'):
        v = max(v, res['apt_min'])
    return v


def _residential(rule: str) -> dict | None:
    """제5호(공동주택·오피스텔). 주택건설기준 그대로면 None(국가 산식).
    확실한 형식만 조례 값으로 읽는다:
      ① 전용 85㎡ 이하·초과 ○㎡당 1대 (안양·수원·의정부·김포·세종 등)
      ② 세대(호실)당 최소 N대 + 바로 뒤 괄호의 면적별 예외 (서울 '1대(30㎡ 이하 0.5대, 60㎡ 이하 0.8대)', 부산, 가평)
      ③ 주택건설기준 산정 대수의 ○배 (홍천)
    면적대별로 세대당 대수를 따로 정한 표(춘천·강릉·속초·아산·당진 등)는 {'complex': True}로 두고 국가 산식 + 원문 확인 경고."""
    t = re.sub(r'\s+', ' ', rule).replace('제곱미터', '㎡')
    # 도시형 생활주택·원룸형·공공매입 등 특례 기준은 일반 공동주택·오피스텔에 적용하지 않는다
    segs = [x for x in re.split(r'[○◦●ㆍ]|(?<=\s)-\s', t) if x.strip()]
    keep = [x for x in segs if not re.search(r'^[^.]{0,80}?(?:' + _SPECIAL + ')', x.strip())] or segs[:1]
    t = ' '.join(re.split(r'다만,?\s*[^.]{0,80}?(?:' + _SPECIAL + ')', x)[0] for x in keep)
    out = {}
    # 이천: '85㎡ 이하 : 세대당 1대 나. 85㎡ 초과 : 70㎡당' 를 85㎡ 이하 70㎡당으로 오인하지 않게 '초과' 구간을 넘지 않는다 (수원 '85㎡ 이하인 경우 : 85㎡당'은 인정)
    small = re.search(r'85\s*㎡\s*이하(?:(?!초과)[^○]){0,60}?' + _AREA, t)
    large = re.search(r'85\s*㎡\s*(?:를|을)?\s*초과[^○]{0,60}?' + _AREA, t)
    if small or large:
        out['small'] = float(small.group(1).replace(',', '')) if small else None
        out['large'] = float(large.group(1).replace(',', '')) if large else None
    bases = list(re.finditer(r'(?:세대|호실|가구)[^.。○]{0,20}?(?:당|마다)\s*[)）]?\s*(?:주차\s*대수가?\s*)?(\d(?:\.\d+)?)\s*대\s*(?:[(（]([^)）]*)[)）])?', t))   # 서울 '…호실당) 1대(…)', 수원 '세대 당 주차대수가 1대 이상'
    if not (small and large):   # 논산: 기호 없이 '60㎡이하 : 0.7대 - 60㎡초과 85㎡이하 : 1.2대 - 85㎡초과 : 세대당 1.5대'
        bd = _bands(t)
        if bd and bd['bands'][-1][0] is None and len(bd['bands']) >= 2:   # 열린 마지막 면적대(○㎡ 초과)가 있어야 면적대 표로 본다 (서울 괄호 예외는 제외)
            return bd
    if len({m.group(1) for m in bases}) > 1 or re.search(r'【\s*전용면적|〔\s*전용면적|㎡\s*초과\s*[∼~]\s*\d+\s*㎡\s*이하', t):
        return _bands(t) or {'complex': True}   # 면적대별 세대당 대수 — 띠 형식을 못 읽으면 자동 적용하지 않음
    if bases:
        m = next((x for x in bases if x.group(2) and '㎡' in x.group(2)), bases[0])   # 서울·김포: '…1대에 미달 … 1대(30㎡ 이하 0.5대 …)'
        tiers = [(float(x), float(v)) for x, v in re.findall(r'(\d+)\s*㎡\s*(?:이하|미만)[^0-9]{0,25}?(\d(?:\.\d+)?)\s*대', m.group(2) or '')]
        out['per_unit'] = sorted(set(tiers)) + [(None, float(m.group(1)))]
    if (small is None) != (large is None):
        return _bands(t) or {'complex': True}
    mult = re.search(r'주택건설기준[^.]{0,80}?(\d+(?:\.\d+)?)\s*배', t)   # 홍천: '산정된 주차대수의 1.5배'
    if mult:
        out['multiplier'] = float(mult.group(1))
    return out or None


def resolve(province: str | None, municipality: str | None, fetch_missing: bool = False) -> dict:
    """{'level': 'ordinance'|'national', 'rates': {kind: ㎡당 1대}, 'residential': …, 'source': …}"""
    base = {'level': 'national', 'rates': dict(NATIONAL), 'residential': None, 'source': NATIONAL_SOURCE, 'texts': {}}
    if not province:
        return base
    d = cached(province, municipality or '')
    if (not d or d.get('parser', 0) < PARSER_VERSION) and fetch_missing:
        try:
            d = fetch(province, municipality or '')
        except Exception as exc:   # 조례를 못 읽어도 국가 기준으로 계산은 계속
            base['note'] = f'주차장 조례 자동수집 실패: {exc}'
            return base
    if not d:
        return base
    if d.get('missing'):
        base['note'] = '지자체 주차장 조례의 부설주차장 설치기준을 찾지 못해 국가 기준으로 계산했습니다.'
        return base
    rates = {**NATIONAL, **{k: v for k, v in d['rates'].items() if v}}
    return {'level': 'ordinance', 'rates': rates, 'residential': d.get('residential'), 'texts': d.get('texts', {}),
            'source': {'title': f"{d['title']} {d.get('appendix', '')}".strip(), 'effective': d.get('effective'), 'url': d.get('url')},
            'scope': d.get('scope')}
