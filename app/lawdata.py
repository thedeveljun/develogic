"""국가법령정보센터(law.go.kr) 기반 법규 데이터.

1) 국가 기준: 「국토의 계획 및 이용에 관한 법률 시행령」 제84조①(건폐율)·제85조①(용적률),
   「주택건설기준 등에 관한 규정」 제27조①(주차) — 원문 확인값을 내장한다.
2) 지자체 기준: 각 시·군·구 「도시계획 조례」 본문을 law.go.kr 에서 받아
   '용도지역에서의 건폐율/용적률' 조문의 호별 수치를 읽어 캐시한다.
   (API 키 없이 공개 페이지 사용. 자동 판독값이므로 검토자 확인 전에는 '자동수집'으로 표시)
"""
import html as htmllib
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import DB
LAW_BASE = 'https://www.law.go.kr'
PARSER_VERSION = 5   # 5: 원문 오기 허용(제1전용·보존·센트)·줄 안에 이어진 항목, 4: 자치법규 검색 보조·관리계획 조례·별표 묶음(이름 없음·별지서식·1~19)·100분의 표기·주거부분 용적률 합계(대구)
UA = {'User-Agent': 'Mozilla/5.0 (DeveLogic feasibility prototype)'}

# ── 국가 기준 (국토계획법 시행령 [시행 2026.9.18.] 대통령령 제36587호) ──
NATIONAL_SOURCE = {
    'title': '국토의 계획 및 이용에 관한 법률 시행령 제84조①·제85조①',
    'effective': '2026-09-18',
    'url': 'https://www.law.go.kr/법령/국토의계획및이용에관한법률시행령',
}
# 용도지역: (건폐율 상한, 용적률 하한, 용적률 상한)
NATIONAL = {
    '제1종전용주거지역': (50, 50, 100), '제2종전용주거지역': (50, 50, 150),
    '제1종일반주거지역': (60, 100, 200), '제2종일반주거지역': (60, 100, 250), '제3종일반주거지역': (50, 100, 300),
    '준주거지역': (70, 200, 500),
    '중심상업지역': (90, 200, 1500), '일반상업지역': (80, 200, 1300), '근린상업지역': (70, 200, 900), '유통상업지역': (80, 200, 1100),
    '전용공업지역': (70, 150, 300), '일반공업지역': (70, 150, 350), '준공업지역': (70, 150, 400),
    '보전녹지지역': (20, 50, 80), '생산녹지지역': (20, 50, 100), '자연녹지지역': (20, 50, 100),
    '보전관리지역': (20, 50, 80), '생산관리지역': (20, 50, 80), '계획관리지역': (40, 50, 100),
    '농림지역': (20, 50, 80), '자연환경보전지역': (20, 50, 80),
}
ZONES = list(NATIONAL)

# ── 주차 기준 (주택건설기준 등에 관한 규정 제27조① [시행 2026.11.7.]) ──
PARKING_SOURCE = {'title': '주택건설기준 등에 관한 규정 제27조①', 'effective': '2026-11-07',
                  'url': 'https://www.law.go.kr/법령/주택건설기준등에관한규정'}
# 지역 구분 → (전용 85㎡ 이하 ㎡당 1대, 85㎡ 초과 ㎡당 1대)
PARKING_RATIO = {
    'special': (75, 65),     # 특별시
    'metro': (85, 70),       # 광역시·특별자치시 및 수도권 내의 시지역
    'city': (95, 75),        # 그 밖의 시지역과 수도권 내의 군지역
    'other': (110, 85),      # 그 밖의 지역
}
PARKING_REGION_NAMES = {'special': '특별시', 'metro': '광역시·특별자치시·수도권 시', 'city': '시지역·수도권 군', 'other': '그 밖의 지역'}
CAPITAL = ('서울특별시', '인천광역시', '경기도')


def parking_region(province: str | None, municipality: str | None) -> str:
    p, m = province or '', municipality or ''
    if p.endswith('특별시'):
        return 'special'
    if p.endswith(('광역시', '특별자치시')):
        return 'metro'
    if p in CAPITAL:
        return 'metro' if m.endswith('시') else 'city'
    return 'city' if m.endswith('시') else 'other'


# ── 캐시 DB ──
def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS ordinance_cache (
      province TEXT NOT NULL, municipality TEXT NOT NULL, ordin_seq TEXT, title TEXT, effective TEXT,
      promulgation TEXT, url TEXT, limits_json TEXT NOT NULL, articles_json TEXT, fetched_at TEXT NOT NULL,
      reviewed_by TEXT, reviewed_on TEXT,
      PRIMARY KEY (province, municipality))''')
    c.commit()
    return c


def cached(province: str, municipality: str) -> dict | None:
    c = _conn()
    try:
        r = c.execute('SELECT * FROM ordinance_cache WHERE province=? AND municipality=?', (province, municipality)).fetchone()
        return _row(r) if r else None
    finally:
        c.close()


def list_cached() -> list[dict]:
    c = _conn()
    try:
        return [_row(r) for r in c.execute('SELECT * FROM ordinance_cache ORDER BY province, municipality')]
    finally:
        c.close()


def _row(r) -> dict:
    d = dict(r)
    d['limits'] = json.loads(d.pop('limits_json'))
    d['articles'] = json.loads(d.pop('articles_json') or '{}')
    return d


def mark_reviewed(province: str, municipality: str, reviewer: str, on: str) -> None:
    c = _conn()
    try:
        n = c.execute('UPDATE ordinance_cache SET reviewed_by=?, reviewed_on=? WHERE province=? AND municipality=?',
                      (reviewer, on, province, municipality)).rowcount
        c.commit()
        if not n:
            raise ValueError('수집된 조례가 없습니다')
    finally:
        c.close()


def save_cache(province: str, municipality: str, data: dict) -> dict:
    c = _conn()
    try:
        c.execute('''INSERT OR REPLACE INTO ordinance_cache
          (province, municipality, ordin_seq, title, effective, promulgation, url, limits_json, articles_json, fetched_at, reviewed_by, reviewed_on)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (province, municipality, data.get('ordin_seq'), data.get('title'), data.get('effective'), data.get('promulgation'),
                   data.get('url'), json.dumps(data['limits'], ensure_ascii=False), json.dumps(data.get('articles', {}), ensure_ascii=False),
                   datetime.now().isoformat(timespec='seconds'), data.get('reviewed_by'), data.get('reviewed_on')))
        c.commit()
    finally:
        c.close()
    return cached(province, municipality)


# ── law.go.kr 수집 · 판독 ──
def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode('utf-8', 'replace')


def _text(h: str) -> str:
    h = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', h, flags=re.S | re.I)
    h = re.sub(r'<br\s*/?>|</p>|</div>|</li>', '\n', h, flags=re.I)
    t = htmllib.unescape(re.sub(r'<[^>]+>', ' ', h))
    t = re.sub(r'[ \t ]+', ' ', t)
    return re.sub(r'\n\s*\n+', '\n', t)


def ordinance_name(municipality: str) -> str:
    return f'{municipality} 도시계획 조례'


def ordinance_candidates(province: str, municipality: str) -> list[str]:
    """적용 조례 후보 (law.go.kr/자치법규/<이름> 형식).
    - 특별시·광역시의 자치구, 제주·세종: 광역 조례가 적용된다 (자치구는 도시계획 조례가 없음)
    - 광역시의 군: 군계획 조례가 있으면 그것, 없으면 광역 조례
    - 도의 시·군: 시는 '도시계획 조례', 군은 '군계획 조례'"""
    p, m = province.strip(), (municipality or '').strip()
    metro = p + '도시계획조례'
    if not m or m == p or p in ('세종특별자치시', '제주특별자치도'):
        return [metro]
    if p.endswith(('특별시', '광역시')):
        return [m + '군계획조례', metro] if m.endswith('군') else [metro]
    if m.endswith('군'):
        return [m + '군계획조례', m + '계획조례', m + '관리계획조례', m + '도시군계획조례', m + '도시ㆍ군계획조례', m + '도시계획조례']   # 장흥·무안: '관리계획 조례'
    return [m + '도시계획조례', m + '도시군계획조례', m + '도시ㆍ군계획조례']


def find_ordin_seq(province: str, municipality: str) -> tuple[str, str]:
    for n in ordinance_candidates(province, municipality):
        h = _get(LAW_BASE + '/' + urllib.parse.quote('자치법규/' + n))
        seqs = re.findall(r'ordinSeq[=\'":\s]+(\d{5,})', h)
        if seqs:
            return seqs[0], n
    found = search_ordinance(municipality or province)   # 한글주소가 등록되지 않은 조례(청도군 등)
    if found:
        return found
    raise LookupError(f'국가법령정보센터에서 {municipality or province}의 도시·군계획 조례를 찾지 못했습니다')


_PLAN_TITLE = re.compile(r'^(?:도시\s*[ㆍ·]?\s*)?(?:군\s*)?(?:관리\s*)?계획\s*조례$')


def search_ordinance(name: str) -> tuple[str, str] | None:
    """국가법령정보센터 자치법규 검색 결과에서 '<지자체> (도시·군|관리)계획 조례'를 찾는다."""
    h = _get(f"{LAW_BASE}/LSW/ordinSc.do?menuId=3&subMenuId=27&tabMenuId=139&query={urllib.parse.quote(name + ' 계획')}")
    for seq, title in re.findall(r"ordinInfPop\('(\d{5,})'[^>]*>(.*?)</a>", h, flags=re.S):
        t = re.sub(r'\s+', ' ', htmllib.unescape(re.sub(r'<[^>]+>', ' ', title))).strip()
        t = re.sub(r'\s*\[[^\]]*\]\s*$', '', t)   # '[제명개정 2020. 10. 5.]'
        if t.replace(' ', '').startswith(name) and _PLAN_TITLE.match(t.replace(' ', '')[len(name):]):
            return seq, t
    return None


_ZONE_KEYS = {z.replace('지역', ''): z for z in ZONES}
_ITEM_SPLIT = re.compile(r'(?:^|\n)\s*(\d{1,2})\.\s*')
_PCT = r'([\d,]+(?:\.\d+)?)\s*(?:퍼센트|%)'
_APT = re.compile(r'(?:공동주택|아파트)')


def _article(text: str, kind: str) -> tuple[str, str] | None:
    """kind='건폐율'|'용적률' → (조문번호, ①항 본문)."""
    m = (re.search(r'(제\d+조(?:의\d+)?)\s*\(\s*용도(?:구역\s*[·ㆍ]\s*)?지역\s*(?:[·ㆍ]\s*지구)?\s*(?:에서|안에서|안|의)의?\s*' + kind
                   + r'\s*(?:및\s*완화)?\s*(?:<[^)]*)?\)', text)   # 고성: '(용도지역 안에서의 건폐율 <개정 2014.5.30>)', 여수: '(용도구역·지역·지구안에서의 건폐율)'
         or re.search(r'(제\d+조(?:의\d+)?)\s*\(\s*용도지역\s*[ㆍ·]?\s*(?:지구\s*등)?\s*(?:에서|안에서|안|의)의?\s*' + kind + r'\s*\)', text)
         or re.search(r'(제\d+조(?:의\d+)?)\s*\(\s*용도지역\s*(?:에서|안에서|안|의)의?\s*건폐율\s*[‧·ㆍ및,]\s*용적률\s*\)', text))
    if not m:
        return None
    body = text[m.end():m.end() + 9000]
    nxt = re.search(r'\n\s*제\d+조(?:의\d+)?\s*\(', body)
    body = body[:nxt.start()] if nxt else body
    parts = re.split(r'\n\s*(?=②)', body, maxsplit=1)
    return m.group(1), parts[0], (parts[1] if len(parts) > 1 else '')


def _korean_numbers(s: str) -> str:
    """'1천퍼센트'·'1천3백퍼센트'·'1천 500퍼센트' 같은 한글 단위 숫자, '100분의 230' 같은 분수 표기를 'N퍼센트'로 바꾼다."""
    s = re.sub(r'100\s*분\s*의\s*([\d,]+(?:\.\d+)?)', r'\1퍼센트', s)
    s = re.sub(r'(\d)\s*센트', r'\1퍼센트', s)   # 옥천: 원문 오기 '200센트'
    def conv(m):
        return str(int(m.group(1)) * 1000 + int(m.group(2) or 0) * 100 + int(m.group(3) or 0))
    return re.sub(r'(\d+)\s*천\s*(?:(\d+)\s*백)?\s*(\d+)?(?=\s*(?:퍼센트|%))', conv, s)


def _apartment_value(item: str, general: float) -> float | None:
    """항목 본문에서 공동주택(아파트) 별도 기준을 찾는다. 없으면 None."""
    for am in _APT.finditer(item):
        seg = item[am.start():am.start() + 160]
        seg = re.split(r'[,，]\s*(?:법\s*제\d+조|「)', seg)[0]  # 지구단위·정비사업 등 다른 조건 앞에서 끊기
        v = re.search(_PCT, seg)
        if v:
            val = float(v.group(1).replace(',', ''))
            return val if val != general else None
        # '각 목의 어느 하나에 해당하는 경우 500퍼센트' 형식 (목 안에는 수치 없음)
        lead = re.search(r'각\s*목의?\s*어느\s*하나에\s*해당하는\s*경우\s*' + _PCT, item)
        if lead:
            val = float(lead.group(1).replace(',', ''))
            return val if val != general else None
    return None


def parse_items(body: str, key: str, limits: dict) -> int:
    '''「1. 제1종전용주거지역 : 100퍼센트 이하 …」 목록 → limits[용도지역][key …]. 판독한 항목 수를 돌려준다.'''
    n = 0
    # 성주: '… 125퍼센트 이하. 20. 농림지역 : …' 처럼 줄바꿈 없이 이어진 항목을 나눈다
    body = re.sub(r'(?<=[.)\s])\s*(\d{1,2})\.\s*(?=(?:제\s*[123]|준주거|중심상업|일반상업|근린상업|유통상업|전용공업|일반공업|준공업|보전녹지|생산녹지|자연녹지|보전관리|생산관리|계획관리|농림지역|자연환경))',
                  r'\n\1. ', body)
    parts = _ITEM_SPLIT.split('\n' + body)
    for i in range(1, len(parts) - 1, 2):
        item = _korean_numbers(re.sub(r'\s+', ' ', parts[i + 1]).strip())
        head = re.sub(r'\s', '', item.split(':')[0].split('：')[0])[:14]
        head = re.sub(r'^제([123])(전용|일반)', r'제\1종\2', head).replace('자연환경보존', '자연환경보전')   # 원문 오기: 정선 '제1전용', 고양 '보존'
        if head.startswith('삭제'):
            continue
        zone = next((z for k, z in _ZONE_KEYS.items() if head.startswith(k)), None)
        v = re.search(_PCT, item)
        if not zone or not v:
            continue
        general = float(v.group(1).replace(',', ''))
        rec = limits.setdefault(zone, {})
        rec[key] = general
        n += 1
        apt = _apartment_value(item, general)
        if apt is None and re.search(r'주택법\s*시행령.{0,40}?사업계획의?\s*승인', item):   # 창원: 주택법 사업계획승인 대상은 별도
            am = re.search(r'사업계획의?\s*승인.{0,90}?' + _PCT, item)
            apt = float(am.group(1).replace(',', '')) if am and float(am.group(1).replace(',', '')) != general else None
        if apt is not None:
            rec[key + '_apt'] = apt
        part = re.search(r'부분의\s*용적률은\s*' + _PCT, item)
        if part and key == 'far' and re.search(r'주거용|공동주택|준주택', item):
            rec['far_res_part'] = float(part.group(1).replace(',', ''))
        ot = re.search(r'오피스텔[^:：]{0,40}[:：]\s*' + _PCT, item)
        if ot:
            rec[key + '_officetel'] = float(ot.group(1).replace(',', ''))
        if len(item) > 40:
            rec[key + '_text'] = item[:600]
    return n


def parse_ordinance(text: str) -> dict:
    limits: dict[str, dict] = {}
    articles, warnings = {}, []
    for kind, key in (('건폐율', 'bcr'), ('용적률', 'far')):
        a = _article(text, kind)
        if not a:
            warnings.append(f'「용도지역에서의 {kind}」 조문을 찾지 못했습니다')
            continue
        articles[key] = a[0]
        if a[2]:
            articles[key + '_more'] = [re.sub(r'\s+', ' ', x).strip()[:400] for x in re.split(r'\n\s*(?=[②③④⑤⑥⑦⑧⑨⑩])', a[2]) if x.strip()][:8]
        parse_items(a[1], key, limits)
    # 국가 기준 범위 검증 (판독 오류 방지)
    for zone, rec in limits.items():
        b, lo, hi = NATIONAL[zone]
        for k in ('bcr', 'bcr_apt'):
            if rec.get(k) is not None and rec[k] > b:
                warnings.append(f'{zone} 건폐율 {rec[k]:g}%가 시행령 상한 {b}%를 넘습니다 — 원문 확인 필요')
        for k in ('far', 'far_apt'):
            if rec.get(k) is not None and not (lo <= rec[k] <= hi):
                warnings.append(f'{zone} 용적률 {rec[k]:g}%가 시행령 범위 {lo}~{hi}%를 벗어납니다 — 원문 확인 필요')
    far_art = _article(text, '용적률')
    mix = _mixed_ref(far_art[1] + chr(10) + far_art[2]) if far_art else None   # 용적률 조문 안에서만 찾음 (허용용도 별표 오인 방지)
    if mix:
        articles['mixed_ref'] = mix
    return {'limits': limits, 'articles': articles, 'parse_warnings': warnings}


# ── 용도용적제: 상업(·준주거)지역 주거복합 건축물의 주거비율별 용적률 ──
_RATIO_TOKEN = re.compile(r'(\d{1,3})\s*%?\s*이상\s*[∼~\-–]\s*(\d{1,3})\s*%?\s*미만|(\d{1,3})\s*%?\s*미만|(\d{1,3})\s*%?\s*이상|^-$|^[\d,]+\s*(?:%|퍼센트)\s*이하$')


def _mixed_ref(text: str) -> dict | None:
    """조례 본문에서 상업지역 주거복합(주상복합) 건축물의 주거비율별 용적률 근거(별표 N 또는 본문 표)를 찾는다."""
    pat = r'(주거(?:용)?\s*(?:부분의\s*)?비율|주거면적\s*비율|공동주택\s*비율|주상복합|복합된\s*건축물|함께\s*건축)[^。]{0,220}?별표\s*(\d+(?:\s*의\s*\d+)?)'
    for m in re.finditer(pat, text):
        ctx = text[max(0, m.start() - 200):m.end() + 40]
        if not re.search(r'상업지역|준주거', ctx) or re.search(r'건축할\s*수\s*(?:있|없)는\s*건축물', text[m.end() - 60:m.end() + 40]):
            continue
        before = text[max(0, m.start(2) - 25):m.start(2)]
        if re.search(r'(시행령|시행규칙|법률|법」|령」|규칙」)\s*별표\s*$', before):
            continue
        no = re.sub(r'\s', '', m.group(2))
        return {'appendix': no, 'text': re.sub(r'\s+', ' ', ctx).strip()}
    m = re.search(r'주거(?:용)?\s*(?:부분의\s*)?비율[^\n]{0,40}(?:이상|미만)', text)
    return {'appendix': None, 'text': re.sub(r'\s+', ' ', text[max(0, m.start() - 200):m.end() + 600]).strip()} if m else None


_ZONE_COL = re.compile(r'((?:중심|일반|근린|유통)(?:[·⋅ㆍ,、/](?:중심|일반|근린|유통))*)상업(?:지역)?|준주거(?:지역)?')
_RANGE = re.compile(
    r'^(?:(\d{1,3})\s*(?:%|퍼센트)?\s*이상\s*[∼~～〜\-–]?\s*(\d{1,3})\s*(?:%|퍼센트)?\s*(?:미만|이하)'      # 80이상 ～ 90미만 (이하 오기 포함)
    r'|(\d{1,3})\s*(?:%|퍼센트)?\s*미만\s*[∼~～〜\-–]?\s*(\d{1,3})\s*(?:%|퍼센트)?\s*이상'           # 90미만 ~ 80이상 (역순)
    r'|(\d{1,3})\s*(?:%|퍼센트)?\s*미만|(\d{1,3})\s*(?:%|퍼센트)?\s*이상)\s*$')
_VAL = re.compile(r'^([\d,]+(?:\.\d+)?)\s*(?:(?:%|퍼센트)\s*)?(?:[∼~～〜\-–]\s*([\d,]+(?:\.\d+)?)\s*(?:%|퍼센트)?\s*)?(?:이하)?$')


def _cols(head: str) -> list[list[str]]:
    """머리 글(공백 제거) → 열마다 해당 용도지역 목록. '중심·일반상업지역' 은 한 열에 두 지역."""
    cols = []
    for m in _ZONE_COL.finditer(head):
        if m.group(0).startswith('준주거'):
            cols.append(['준주거지역'])
            continue
        cols.append([f'{k}상업지역' for k in re.split(r'[·⋅ㆍ,、/]', m.group(1))])
    return cols


def parse_mixed_table(t: str) -> dict:
    """별표(또는 본문) 표 텍스트 → {용도지역: [{'min', 'max', 'far', 'far_lo'?}]}.
    HWP 표는 칸마다 한 줄: 머리(지역명) → 행(주거비율 구간 다음에 열 수만큼 값). 머리가 여러 번 나오면(구리 등) 열을 다시 정한다."""
    t = re.sub(r'100\s*분\s*의\s*([\d,]+(?:\.\d+)?)', r'\1%', t)   # 가평: '100분의 80 이상 ～', '100분의 500 이하'
    t = re.sub(r'[ \t　]{2,}', '\n', t.replace('|', '\n'))
    lines = [re.sub(r'\s+', ' ', x).strip() for x in t.split('\n') if x.strip()]
    # '80이상' / '90미만' 처럼 두 줄로 나뉜 구간을 합친다 ('80% 이상 ～' 처럼 물결이 윗줄 끝에 붙은 경우 포함)
    merged = []
    for x in lines:
        if merged and re.match(r'^\d{1,3}\s*(%|퍼센트)?\s*이상\s*[∼~～〜\-–]?$', merged[-1]) and re.match(r'^[∼~～〜\-–]?\s*\d{1,3}\s*(%|퍼센트)?\s*미만$', x):
            merged[-1] = merged[-1].rstrip('∼~～〜-– ') + ' ~ ' + x.lstrip('∼~～〜-– ')
        else:
            merged.append(x)
    out: dict[str, list] = {}
    cols, head = [], ''
    i = 0
    while i < len(merged):
        x = merged[i]
        m = _RANGE.match(x)
        if not m:
            compact = re.sub(r'\s', '', x)
            is_title = re.search(r'주상복합|용적률|관련|비고|건축물|※|별표', compact) or re.match(r'^\d+[.)]', compact)   # '1. 중심·근린상업지역' 같은 소제목
            if not is_title and len(compact) <= 16 and (re.search(r'상업|준주거', compact) or compact in ('중심', '일반', '근린', '유통')):
                if not head.endswith('§'):
                    head = head + compact
                else:
                    head = compact
            i += 1
            continue
        if head:
            cols, head = _cols(head) or cols, '§'
        if not cols:
            i += 1
            continue
        g = m.groups()
        if g[0]:
            lo, hi = float(g[0]), float(g[1])
        elif g[2]:
            hi, lo = float(g[2]), float(g[3])
        elif g[4]:
            lo, hi = 0.0, float(g[4])
        else:
            lo, hi = float(g[5]), 100.0
        vals, j = [], i + 1
        while j < len(merged) and len(vals) < len(cols):
            v = merged[j]
            if v in ('-', '–', '—', '－'):
                vals.append(None)
            elif _RANGE.match(v):
                break
            else:
                vm = _VAL.match(v.replace(' ', ''))
                if vm:
                    a1 = float(vm.group(1).replace(',', ''))
                    a2 = float(vm.group(2).replace(',', '')) if vm.group(2) else None
                    vals.append((min(a1, a2), max(a1, a2)) if a2 else (None, a1))
                else:
                    break
            j += 1
        for zs, v in zip(cols, vals):
            if v is None:
                continue
            for z in zs:
                row = {'min': lo, 'max': hi, 'far': v[1]}
                if v[0] is not None:
                    row['far_lo'] = v[0]   # 범위 값: 주거비율에 비례해 적용
                out.setdefault(z, []).append(row)
        i = j
    return {z: sorted(r, key=lambda x: x['min']) for z, r in out.items() if r}


def parse_zone_table(t: str, kind: str | None = None) -> dict:
    """별표의 용도지역별 표 → {용도지역: {'bcr':, 'far':}}. 머리에 건폐율·용적률이 함께 있으면 그 순서대로 값 배정."""
    t = re.sub(r'[ \t　]{2,}', '\n', t.replace('|', '\n'))
    lines = [re.sub(r'\s+', ' ', x).strip() for x in t.split('\n') if x.strip()]
    first = next((i for i, x in enumerate(lines) if any(re.sub(r'\s', '', x).startswith(k) for k in _ZONE_KEYS)), None)
    if first is None:
        return {}
    head = ''.join(lines[:first])
    order = sorted([(head.find(k), key) for k, key in (('건폐율', 'bcr'), ('용적률', 'far')) if k in head])
    keys = [k for _, k in order] or ([{'건폐율': 'bcr', '용적률': 'far'}[kind]] if kind else ['far'])
    out, zone, vals = {}, None, []

    def flush():
        if zone and vals:
            for k, v in zip(keys, vals):
                out.setdefault(zone, {})[k] = v
    for x in lines[first:]:
        c = re.sub(r'\s', '', x)
        z = next((zz for k, zz in sorted(_ZONE_KEYS.items(), key=lambda kv: -len(kv[0])) if c.startswith(k)), None)
        if z:
            flush()
            zone, vals = z, []
            rest = c[len(next(k for k in _ZONE_KEYS if c.startswith(k))):].lstrip('지역')
            for v in re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:%|퍼센트)?\s*이하', _korean_numbers(rest)) or re.findall(r'^([\d,]+(?:\.\d+)?)$', rest):
                vals.append(float(v.replace(',', '')))
            continue
        v = re.match(r'^([\d,]+(?:\.\d+)?)\s*(?:%|퍼센트)?\s*(?:이하)?(?:\(.*\))?$', _korean_numbers(x).replace(' ', ''))
        if v and zone and len(vals) < len(keys):
            vals.append(float(v.group(1).replace(',', '')))
    flush()
    return out


def _download_text(q: str) -> str | None:
    from . import eum
    req = urllib.request.Request(f'{LAW_BASE}/LSW/flDownload.do?{q.replace("&amp;", "&")}', headers={**UA, 'Referer': f'{LAW_BASE}/'})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    if data[:4] == b'\xd0\xcf\x11\xe0':
        return eum.hwp_text(data)
    if data[:2] == b'PK':
        return eum.hwpx_text(data)
    if data[:4] == b'%PDF':
        return eum.pdf_text(data)
    return None


def _cut_appendix(body: str, num: str) -> tuple[str, str] | None:
    """여러 별표가 든 파일 본문에서 [별표 num] 부분만 잘라낸다 (목차가 아닌 본문 쪽, 즉 마지막 일치)."""
    start = None
    for sm in re.finditer(r'[\[〔【「]\s*별표\s*' + num + r'\s*[\]〕】」]', body):
        start = sm
    if not start:
        return None
    rest = body[start.end():]
    nxt = re.search(r'[\[〔【「]\s*별표\s*\d+(?:\s*의\s*\d+)?\s*[\]〕】」]', rest)
    seg = rest[:nxt.start()] if nxt else rest
    return (_appendix_title(seg), seg)


def _appendix_title(seg: str) -> str:
    """별표 본문 첫머리에서 '〈개정 …〉' 같은 연혁 표시를 건너뛴 제목 줄."""
    for line in seg.split('\n'):
        x = re.split(r'\s*\(\s*%\s*\)', re.sub(r'\s+', ' ', re.sub(r'[<〈][^>〉]*[>〉]', '', line)))[0].strip()   # 용인: '… 용적률 (%) 연면적의…'
        if len(x) >= 4:
            return x[:80]
    return ''


def _safe_download(q: str) -> str | None:
    """별표 파일 하나를 받지 못하거나 HWP·PDF를 읽지 못해도 조례 판독 전체가 멈추지 않게 None."""
    try:
        return _download_text(q)
    except Exception:
        return None


def fetch_appendix(seq: str, html: str, no) -> tuple[str, str] | None:
    """조례 화면 HTML에서 [별표 no] 파일(HWP·HWPX·PDF)을 내려받아 (제목, 본문)을 돌려준다.
    별표가 하나의 파일로 묶여 있으면('별표 1 ~ 별표 25', '별표 1~19', 이름 없는 '별표', 별표가 든 '별지서식') 묶음에서 해당 별표 부분만 잘라낸다."""
    num = str(no).replace('의', r'\s*의\s*')
    # '[별표 17] 제목' · '별표_2_제목'(대구) · '별표 2 제목'·'별표2'(수원·청도, 괄호 없음)
    m = re.search(r'(?:[\[〔【「]\s*별표\s*' + num + r'\s*[\]〕】」]|>\s*별표_' + num + r'_|<img[^>]*>\s*별표\s*' + num + r'(?=[\s<(（]))\s*([^<]{0,160}?)\s*(?:<a|</a>).{0,900}?flDownload\.do\?([^"\']+)', html, flags=re.S)
    if m:
        body = _safe_download(m.group(2))
        return (re.sub(r'\s+', ' ', htmllib.unescape(m.group(1))).strip(), body) if body else None
    nm = re.match(r'\d+', str(no))
    if not nm:
        return None
    n = int(nm.group(0))
    for bm in re.finditer(r'별표\s*(\d+)\s*[~∼～〜\-–]\s*(?:별표\s*)?(\d+).{0,900}?flDownload\.do\?([^"\']+)', html, flags=re.S):
        if int(bm.group(1)) <= n <= int(bm.group(2)):
            body = _safe_download(bm.group(3))
            return _cut_appendix(body, num) if body else None
    # 번호 없는 묶음 파일: '별표'(용인), '별지서식'(목포 — 별표가 서식 파일 안에 있음)
    for gm in re.finditer(r'class="blu"[^>]*>\s*<img[^>]*>\s*(별표|별지\s*서식|별표\s*[및ㆍ·]\s*별지\s*서식)\s*</a>.{0,400}?flDownload\.do\?([^"\']+)', html, flags=re.S):
        body = _safe_download(gm.group(2))
        got = _cut_appendix(body, num) if body else None
        if got:
            return got
    return None


def parse_res_part(t: str) -> dict:
    """주거비율 표 대신 '주거용 용도의 용적률 합계는 중심상업지역 450퍼센트 이하 …'로 정한 방식(대구) →
    {용도지역: {'far_res_part': 450, 'res_max': 90}} (res_max: 비주거 최소비율에서 나온 주거비율 상한)."""
    t = _korean_numbers(re.sub(r'\s+', ' ', t))
    m = re.search(r'주거(?:용)?\s*(?:용도|부분)[^.。]{0,120}?용적률\s*(?:의\s*)?합계', t)
    if not m:
        return {}
    seg = t[m.end():m.end() + 600]
    out = {}
    for zm in re.finditer(r'((?:중심|일반|근린|유통)상업지역|준주거지역)\s*[:：]?\s*' + _PCT, seg):
        out[zm.group(1)] = {'far_res_part': float(zm.group(2).replace(',', ''))}
    nonres = re.search(r'주거(?:용)?[^.。]{0,40}?외의\s*용도[^.。]{0,120}?연면적의\s*' + _PCT + r'\s*이상', t)
    if nonres and out:
        for v in out.values():
            v['res_max'] = 100 - float(nonres.group(1).replace(',', ''))
    return out


def mixed_far(table: list[dict], residential_pct: float) -> float | None:
    """주거 비율(%)에 해당하는 행의 용적률. 범위 값(예: 500~549)은 구간 안에서 비례 적용(주거비율이 높을수록 낮게)."""
    for r in table:
        if r['min'] <= residential_pct < r['max'] or (r['max'] >= 100 and residential_pct >= r['min']):
            if r.get('far_lo') is not None and r['max'] > r['min']:
                k = (residential_pct - r['min']) / (r['max'] - r['min'])
                return round(r['far'] - k * (r['far'] - r['far_lo']), 1)
            return r['far']
    return None


def mixed_ceiling(table: list[dict]) -> float | None:
    """표에 있는 최대 주거비율(이 비율 이상이면 주상복합 용적률 표에 없음 → 상업지역 주거비율 상한)."""
    return max((r['max'] for r in table), default=None)


def fetch_ordinance(province: str, municipality: str) -> dict:
    seq, applied = find_ordin_seq(province, municipality)
    h = _get(f'{LAW_BASE}/ordinInfoR.do?ordinSeq={seq}')
    text = _text(h)
    parsed = parse_ordinance(text)
    for kind, key in (('건폐율', 'bcr'), ('용적률', 'far')):
        if any(key in v for v in parsed['limits'].values()):
            continue
        art = _article(text, kind)
        bm = re.search(r'별표\s*(\d+(?:\s*의\s*\d+)?)\s*(?:에|과|와|의|를)', art[1]) if art else None
        if not bm:
            continue
        try:
            got = fetch_appendix(seq, h, re.sub(r'\s', '', bm.group(1)))
        except Exception:
            got = None
        if got:
            if not parse_items(got[1], key, parsed['limits']):
                for z, vals in parse_zone_table(got[1], kind).items():
                    parsed['limits'].setdefault(z, {}).update(vals)
            parsed['articles'][key] = art[0] + f' (별표 {bm.group(1)})'
            parsed['parse_warnings'] = [w for w in parsed['parse_warnings'] if kind not in w]
    ref = parsed['articles'].get('mixed_ref')
    if ref:
        table, src, basis, part = {}, None, 'res', {}
        try:
            if ref.get('appendix'):
                got = fetch_appendix(seq, h, ref['appendix'])
                if got:
                    table, src = parse_mixed_table(got[1]), f"[별표 {ref['appendix']}] {got[0]}"
                    basis = 'apt' if re.search(r'공동주택\s*(?:의\s*)?(?:비율|면적)', got[1]) and not re.search(r'준주택|오피스텔', got[1]) else 'res'
                    if not table:
                        part = parse_res_part(got[1])
                        for z, v in part.items():
                            parsed['limits'].setdefault(z, {}).update(v, mixed_src=src)
            if not table and not part:   # 본문에 표가 있는 경우
                body = re.sub(r'(이하|미만|이상)\s*[:：]?\s*', r'\1\n', ref['text'])
                table, src, basis = parse_mixed_table(body), '본문', 'res'
        except Exception as exc:    # 별표 내려받기 실패해도 본 조례 판독은 유지
            parsed['parse_warnings'].append(f'용도용적제 별표를 읽지 못했습니다 ({exc.__class__.__name__}) — 원문 확인 필요')
        for z, rows in table.items():
            parsed['limits'].setdefault(z, {})['mixed'] = rows
            parsed['limits'][z]['mixed_src'] = src
            parsed['limits'][z]['mixed_basis'] = basis
        if not table and not part:
            parsed['parse_warnings'].append('용도용적제(주거비율별 용적률) 조항이 있으나 표를 판독하지 못했습니다 — 원문 확인 필요')
    if not parsed['limits']:
        raise LookupError('조례 본문에서 「용도지역에서의 건폐율·용적률」 조문을 판독하지 못했습니다. 조례 근거 등록 화면에서 직접 입력하세요.')
    head = text[:3000]
    eff = re.search(r'시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})', head)
    prom = re.search(r'([가-힣]+조례\s*제\s*\d+\s*호)', head)
    title = re.search(r'([가-힣]+[시군도]\s*(?:도시\s*[ㆍ·]?\s*)?(?:군\s*)?(?:관리\s*)?계획\s*조례)', head)
    data = {
        'ordin_seq': seq, 'title': title.group(1) if title else ordinance_name(municipality),
        'effective': f'{eff.group(1)}-{int(eff.group(2)):02d}-{int(eff.group(3)):02d}' if eff else None,
        'promulgation': prom.group(1).replace(' ', '') if prom else None,
        'url': f'{LAW_BASE}/ordinInfoR.do?ordinSeq={seq}', **parsed,
    }
    data['articles']['applied'] = applied
    data['articles']['parser'] = PARSER_VERSION
    data['articles']['warnings'] = parsed.pop('parse_warnings')
    return save_cache(province, municipality, data)


# ── 내장 확인값: 안양시 (원문 대조 완료, 2026-11-16) ──
SEED = {
    ('경기도', '안양시'): {
        'ordin_seq': '2117933', 'title': '안양시 도시계획 조례', 'effective': '2026-03-31', 'promulgation': '경기도안양시조례제3846호',
        'url': 'https://www.law.go.kr/ordinInfoR.do?ordinSeq=2117933', 'articles': {'bcr': '제49조', 'far': '제50조'},
        'limits': {
            '제1종전용주거지역': {'bcr': 50, 'far': 100}, '제2종전용주거지역': {'bcr': 50, 'far': 100},
            '제1종일반주거지역': {'bcr': 60, 'far': 200}, '제2종일반주거지역': {'bcr': 60, 'far': 250},
            '제3종일반주거지역': {'bcr': 50, 'far': 280}, '준주거지역': {'bcr': 60, 'far': 450},
            '중심상업지역': {'bcr': 80, 'far': 1000, 'mixed_basis': 'apt', 'mixed_src': '[별표 17] 상업지역내 주상복합건축물의 용적률',
                         'mixed': [{'min': 40, 'max': 50, 'far': 700}, {'min': 30, 'max': 40, 'far': 800}, {'min': 20, 'max': 30, 'far': 900}, {'min': 0, 'max': 20, 'far': 1000}]},
            '일반상업지역': {'bcr': 80, 'far': 800, 'mixed_basis': 'apt', 'mixed_src': '[별표 17] 상업지역내 주상복합건축물의 용적률',
                         'mixed': [{'min': 80, 'max': 90, 'far': 450}, {'min': 70, 'max': 80, 'far': 500}, {'min': 60, 'max': 70, 'far': 550}, {'min': 50, 'max': 60, 'far': 600},
                                                 {'min': 40, 'max': 50, 'far': 650}, {'min': 30, 'max': 40, 'far': 700}, {'min': 20, 'max': 30, 'far': 750}, {'min': 0, 'max': 20, 'far': 800}]},
            '일반공업지역': {'bcr': 70, 'far': 300}, '준공업지역': {'bcr': 70, 'far': 300},
            '보전녹지지역': {'bcr': 20, 'far': 50}, '자연녹지지역': {'bcr': 20, 'far': 80},
        },
        'reviewed_by': '국가법령정보센터 원문 대조', 'reviewed_on': '2026-11-17',
        'notes': ['제50조① 단서: 지구단위계획 수립 대상은 「안양시 지구단위계획수립지침」 용적률 적용',
                  '제50조②: 상업지역 주상복합 공동주택은 별표 17 적용',
                  '제50조⑤: 정비구역·상업지역 공공시설 부지 제공 시 용적률 ×(1+1.5α)',
                  '준공업지역 아파트 용적률 250%'],
    },
}


def seed_builtin():
    for (prov, muni), d in SEED.items():
        cur = cached(prov, muni)
        if not cur or not cur.get('reviewed_by') or (cur.get('effective') or '') < d['effective'] \
                or (cur.get('articles') or {}).get('parser', 0) < PARSER_VERSION:
            save_cache(prov, muni, {**d, 'articles': {**d['articles'], 'parser': PARSER_VERSION}})


def refresh_stale() -> list[str]:
    """이전 판독기로 저장된 자동 수집 조례를 새 판독기로 다시 읽는다 (서버 시작 시 백그라운드)."""
    done = []
    for r in list_cached():
        if r.get('reviewed_by') or (r.get('articles') or {}).get('parser', 0) >= PARSER_VERSION:
            continue
        try:
            fetch_ordinance(r['province'], r['municipality'])
            done.append(f"{r['province']} {r['municipality']}")
        except Exception:   # 네트워크·판독 실패 시 기존 값 유지
            continue
    return done


def resolve(province: str | None, municipality: str | None, zone: str, as_of: str | None = None, fetch: bool = False) -> dict:
    """용도지역 수치 결정: ①검토자 등록 규칙 → ②조례(내장·자동수집) → ③시행령 상한."""
    from .nationwide import connection
    out = {'zone': zone, 'national': None, 'bcr': None, 'far': None, 'level': 'none', 'source': None, 'notes': []}
    if zone in NATIONAL:
        b, lo, hi = NATIONAL[zone]
        out['national'] = {'bcr': b, 'far_min': lo, 'far_max': hi, **NATIONAL_SOURCE}
    if province and municipality:
        c = connection()
        try:
            day = as_of or datetime.now().date().isoformat()
            rows = c.execute('''SELECT * FROM rules WHERE province=? AND municipality=? AND zone=? AND valid_from<=?
              AND (valid_to IS NULL OR valid_to>=?) ORDER BY valid_from DESC''', (province, municipality, zone, day, day)).fetchall()
        finally:
            c.close()
        if rows:
            r = dict(rows[0])
            out.update(bcr=float(r['bcr_pct']), far=float(r['far_pct']), level='registered',
                       source={'title': f"{r['legal_title']} {r['article']}", 'effective': r['valid_from'], 'url': r['source_url'],
                               'reviewed_by': r['reviewed_by']})
            return out
        o = cached(province, municipality)
        if not o and fetch:
            try:
                o = fetch_ordinance(province, municipality)
            except Exception as exc:
                out['notes'].append(f'조례 자동수집 실패: {exc}')
        if o and zone in o['limits'] and o['limits'][zone].get('far') is not None:
            lim = o['limits'][zone]
            out.update(bcr=lim.get('bcr'), far=lim.get('far'), level='ordinance' if o.get('reviewed_by') else 'auto',
                       source={'title': f"{o['title']} {o['articles'].get('bcr', '')}·{o['articles'].get('far', '')}".strip(),
                               'effective': o['effective'], 'url': o['url'], 'reviewed_by': o.get('reviewed_by')})
            if (province, municipality) in SEED:
                out['notes'] += SEED[(province, municipality)]['notes']
            return out
        if o:
            out['notes'].append(f"「{o['title']}」에 {zone} 수치가 없습니다(삭제 또는 미규정).")
    if out['national']:
        out.update(bcr=out['national']['bcr'], far=out['national']['far_max'], level='national', source=NATIONAL_SOURCE)
        out['notes'].append('조례 미확인: 시행령 상한을 임시 적용했습니다. 실제 조례 수치는 이보다 낮을 수 있습니다.')
    return out
