"""지구단위계획 결정조서 — 획지(블록·가구·택지)별 건폐율·용적률·높이·허용용도 판독.

HWP·PDF에서 뽑은 글자는 표의 칸이 한 줄씩 나온다. 결정조서 표는 크게 두 형식이다.
  ① 세로 나열형: 획지 → 용도 / 건폐율 / 용적률 / 높이 … (인천 용현·학익, 은평 대조1, 강서 발산)
  ② 가로 표형:   머리(필지번호 · 대지면적 · … · 건폐율 · 용적률) → 획지마다 한 행 (아산 탕정 택지)
기정·변경 조서가 함께 실리면 변경(최종) 값을 쓴다. 자동 판독이므로 화면에서 근거 글과 함께 보여주고 원문 대조를 요구한다.
"""
import re

_BULLET = '∙⋅‧ㆍ•·◦○●▪■□∎-–ㅇ '
_PHASE = re.compile(r'^[○ㅇ∎■●▪◦m\s]*(?:<\s*)?(기\s*정|변\s*경(?:\s*후)?|신\s*설)(?:\s*>)?$')
_PHASE_IN = re.compile(r'[(（]\s*(기정|변경|신설)\s*[)）]')
_LABEL = re.compile(r'^(?:[A-Z]{1,3}\s?\d{1,3}(?:-\d{1,3})?|\d{1,2}-[A-Z]{1,2}\d{1,2}|(?:획지|택지|가구|블록|BL)\s*\d{1,3}(?:-\d{1,3})?'
                    r'|[가-힣]{1,4}\d{1,2}(?:-\d{1,2})?)[,，]?$')
_NOT_LABEL = re.compile(r'^(?:제\d|시보|별표|호\d|층\d|소계|합계|계\d)')
_NUMCELL = re.compile(r'^[(（]?\s*([\d,]+(?:\.\d+)?)\s*(?:%|㎡|m|층|호|인|세대)?\s*(?:이하|이상|이내)?\s*(?:[(（].*[)）])?$')
_PCT_ANY = re.compile(r'([\d,]+(?:\.\d+)?)\s*%')
_KEYS = (('bcr', re.compile(r'^건\s*폐\s*율')), ('far', re.compile(r'^(?:전체\s*)?용\s*적\s*률')),
         ('height', re.compile(r'^(?:최고\s*)?(?:높\s*이|층\s*수)')), ('uses', re.compile(r'^(?:용\s*도|허용\s*용도|지정\s*용도|권장\s*용도)')))
_STOP_KEY = re.compile(r'^(?:배\s*치|형\s*태|색\s*채|건축선|건축한계선|기\s*타|주\s*\))')   # '비고'는 표 머리에 흔해서 제외


def _num(s: str) -> float:
    return float(s.replace(',', ''))


def _clean(c: str) -> str:
    c = re.sub(r'\s+', ' ', c).strip()
    if c in ('-', '–', '—', '－'):   # 표의 빈 칸 표시는 열 맞춤에 필요
        return '-'
    return c.lstrip(_BULLET).strip()


def _is_label(c: str) -> bool:
    c = c.strip()
    return bool(_LABEL.match(c)) and not _NOT_LABEL.match(c)


def section(text: str) -> str:
    """'건축물에 관한(대한) … 결정조서' 부분. 없으면 전체."""
    m = re.search(r'건축물(?:의|에)?\s*(?:대한|관한)?[^\n]{0,60}(?:용도|건폐율|용적률|개발밀도)[^\n]{0,80}', text)
    if not m:
        return text
    end = re.search(r'\n\s*(?:Ⅲ|Ⅳ)\s*\.|관계\s*도(?:면|서)\s*[:：]|관련\s*도면\s*[:：]|기타\s*사항에\s*관한[^\n]{0,30}결정', text[m.end():])
    return text[m.start(): m.end() + (end.start() if end else len(text))]


def _far_values(txt: str) -> dict:
    """'기준용적률: 220% 이하 허용용적률: 250% 이하' / '275 (주거 : 220)' / '300% 이하' → dict."""
    out = {}
    for key, pat in (('base_far', r'기준\s*용적률'), ('allowed_far', r'허용\s*용적률'), ('max_far', r'(?<!법적)상한\s*용적률'),
                     ('legal_max_far', r'법적\s*상한\s*용적률')):
        m = re.search(pat + r'[^\d%]{0,12}?([\d,]+(?:\.\d+)?)\s*%?', txt)
        if m:
            out[key] = _num(m.group(1))
    res = re.search(r'주거\s*(?:부문)?\s*(?:용적률)?\s*[:：]?\s*([\d,]+(?:\.\d+)?)', txt)
    if res and re.search(r'[(（]\s*주거', txt):
        out['far_res'] = _num(res.group(1))
    if not out.get('base_far') and not out.get('allowed_far'):
        m = _PCT_ANY.search(txt) or re.match(r'^\s*([\d,]+(?:\.\d+)?)\s*(?:이하|$|[(（])', txt)
        if m and 10 <= _num(m.group(1)) <= 2000:
            out['far'] = _num(m.group(1))
    return out


def _height_values(txt: str) -> dict:
    out = {}
    f = re.findall(r'(\d{1,3})\s*층\s*(?:이하|이내)', txt) or re.findall(r'(\d{1,3})\s*층', txt)
    if f:
        out['floors'] = int(f[0])
    mm = re.search(r'(\d{1,3}(?:\.\d+)?)\s*m\s*(?:이하|이내)', txt)
    if mm:
        out['height_m'] = float(mm.group(1))
    return out


class _Rec(dict):
    pass


def parse_blocks(text: str) -> list[dict]:
    """결정조서 글자 → [{block, phase, bcr, far|base_far|allowed_far|max_far|legal_max_far, far_res, floors, height_m, height, uses, area_sqm, evidence}]."""
    cells = [c for c in (_clean(x) for x in section(text).split('\n')) if c]
    recs: dict[tuple, dict] = {}
    order: list[tuple] = []
    phase, labels, fresh, key, buf = None, [], False, None, ''

    def rec(lbl):
        k = (phase or '', lbl)
        if k not in recs:
            recs[k] = {'block': lbl, 'phase': phase or ''}
            order.append(k)
        return recs[k]

    def put(field, value, evidence=''):
        for l in (labels or ['전체']):
            r = rec(l)
            if isinstance(value, dict):
                for kk, vv in value.items():
                    r.setdefault(kk, vv)
            else:
                r.setdefault(field, value)
            if evidence:
                r.setdefault('evidence', [])
                if len(r['evidence']) < 6:
                    r['evidence'].append(evidence[:160])

    i = 0
    while i < len(cells):
        c = cells[i]
        if c.startswith(('서울시보', '시보', '인 천 광 역 시 보')) or re.match(r'^-\s*\d+\s*-$', c) or re.match(r'^\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.', c):
            i += 1
            continue
        if '변경없음' in c.replace(' ', ''):
            i += 1
            continue
        pm = _PHASE.match(c)
        if pm:
            phase = '기정' if '기' in pm.group(1) else '변경'
            labels, fresh = [], False
            i += 1
            continue
        pin = _PHASE_IN.search(c)
        if pin and len(c) < 120 and not _PCT_ANY.search(c):
            phase = '기정' if pin.group(1) == '기정' else '변경'
        # ② 가로 표형: 머리에 건폐율·용적률이 칸으로 있고 바로 뒤가 값이 아닌 경우
        if re.match(r'^건\s*폐\s*율\s*(?:[(（]%[)）])?$', c) and i + 1 < len(cells) and not re.search(r'\d', cells[i + 1]):
            got = _grid(cells, i, phase)
            if got:
                rows, i = got
                for lbl, vals, ev in rows:
                    r = rec(lbl)
                    r.update(vals)
                    r.setdefault('evidence', []).append(ev)
                labels, fresh, key = [], False, None
                continue
        if _is_label(c):
            new = c.strip(' ,，')
            labels = (labels + [new]) if (not fresh and i > 0 and _is_label(cells[i - 1])) else [new]
            fresh, key = False, None
            i += 1
            continue
        kc = re.sub(r'^(?:[가-하]|\d{1,2})\)\s*', '', c)   # '다) 높이 계획' 같은 소제목도 항목 시작
        km = next(((k, p.match(kc)) for k, p in _KEYS if p.match(kc)), None)
        if km:
            key = km[0]
            c = re.sub(r'^(?:계획|기준)\b', '', kc[km[1].end():].strip(' :：()%（）')).strip()
            if not c:
                # '용적률 | 기준 | 허용 | 상한 | 법적상한' 형식의 밀도 표
                if key == 'far':
                    got = _density_table(cells, i + 1)
                    if got:
                        rows, i = got
                        put('far', rows[-1], ' / '.join(f"{k} {v:g}" for k, v in rows[-1].items()))
                        fresh, key = True, None
                        continue
                i += 1
                continue
        elif _STOP_KEY.match(c):
            key = None
            i += 1
            continue
        if key and '→' in c:
            c = c.split('→')[-1].strip()
        if key:
            # '공공2 : 200% 이하, 공공3 : 150% 이하' 처럼 획지별 값이 한 칸에 있는 경우
            pairs = re.findall(r'([가-힣A-Z]{1,4}\d{1,2}(?:-\d{1,2})?)\s*[:：]\s*([^,，]+)', c)
            if pairs and len(pairs) >= 2:
                for lbl, v in pairs:
                    r = rec(lbl)
                    if key == 'far':
                        r.update(_far_values(v))
                    elif key == 'bcr' and _PCT_ANY.search(v):
                        r['bcr'] = _num(_PCT_ANY.search(v).group(1))
                    elif key == 'height':
                        r.update(_height_values(v)); r['height'] = v.strip()[:60]
                    r.setdefault('evidence', []).append(c[:160])
                fresh = True
                i += 1
                continue
            if key == 'bcr':
                m = _PCT_ANY.search(c) or re.match(r'^([\d.]+)\s*(?:이하|$)', c)
                if m and 1 <= _num(m.group(1)) <= 100:
                    put('bcr', _num(m.group(1)), '건폐율 ' + c)
                    fresh = True
            elif key == 'far':
                v = _far_values(c)
                if v:
                    put('far', v, '용적률 ' + c)
                    fresh = True
            elif key == 'height':
                v = _height_values(c)
                if v:
                    first = not any(rec(l).get('height') for l in (labels or ['전체']))
                    put('h', v, '높이 ' + c)
                    if first:
                        put('height', c[:60])
                    fresh = True
            elif key == 'uses':
                for l in (labels or ['전체']):
                    r = rec(l)
                    if len(r.get('uses', '')) < 300:
                        r['uses'] = (r.get('uses', '') + ' ' + c).strip()[:300]
        i += 1
    rows = _finalize(recs, order)
    renew = _renewal_row(text)
    if renew and len(rows) <= 1 and not any(r.get('legal_max_far') for r in rows):
        if rows and rows[0]['block'] != '전체':
            renew['block'] = rows[0]['block']   # 정비계획 표의 획지명(획지1) 유지
        rows = [renew]   # 단일 정비구역: 정비계획 표(건폐율·정비계획·법적상한·높이 한 행)가 더 확실
    return rows


def _renewal_row(text: str) -> dict | None:
    """정비계획 '건축시설계획' 표(대흥 재건축): '… 50% 이하 270% 이하 299.7% 이하 132.5m이하 (45층이하)' →
    건폐율 · 정비계획 용적률 · 법적상한 용적률 · 높이. 기정·변경이 함께 있으면 뒤(변경) 행."""
    if not re.search(r'정비\s*계획', text) or not re.search(r'법적\s*상한', text):
        return None
    t = '\n'.join(c for c in (_clean(x) for x in text.split('\n')) if c)
    pat = re.compile(r'(\d{1,2}(?:\.\d+)?)\s*%\s*\n?\s*이하\s*\n\s*(\d{2,4}(?:\.\d+)?)\s*%\s*\n?\s*이하\s*\n\s*(\d{2,4}(?:\.\d+)?)\s*%\s*\n?\s*이하'
                     r'(?:\s*\n\s*(\d{1,3}(?:\.\d+)?)\s*m\s*이하)?(?:\s*\n?\s*[(（]\s*(\d{1,3})\s*층)?')
    ms = list(pat.finditer(t))
    if not ms:
        return None
    m = ms[-1]
    bcr, base, legal = float(m.group(1)), float(m.group(2)), float(m.group(3))
    if not (1 <= bcr <= 100 and 10 <= base <= legal <= 2000):
        return None
    out = {'block': '전체', 'phase': '변경' if len(ms) > 1 else '', 'bcr': bcr, 'base_far': base, 'far': base, 'legal_max_far': legal,
           'evidence': [re.sub(r'\s+', ' ', m.group(0))[:160]]}
    if m.group(4):
        out['height_m'] = float(m.group(4))
    if m.group(5):
        out['floors'] = int(m.group(5))
        out['height'] = ' / '.join(x for x in [f"{m.group(4)}m" if m.group(4) else '', f'{m.group(5)}층'] if x) + ' 이하'
    return out


def _density_table(cells: list[str], j: int):
    """'기준 | 허용 | 상한 | 법적상한(예정)' 머리 다음 숫자 행들 → ([{base_far,…}, …], 다음 위치). 뒤 행이 최종(변경)."""
    names = {'기준': 'base_far', '허용': 'allowed_far', '상한': 'max_far', '법적상한': 'legal_max_far', '계획': 'far'}
    head = []
    k = j
    while k < len(cells) and k < j + 12:
        c = re.sub(r'\s|용적률|[(（].*?[)）]|%', '', cells[k])
        if c in names:
            head.append(names[c])
            k += 1
            continue
        if c in ('구분', '비고', ''):
            k += 1
            continue
        break
    if len(head) < 2:
        return None
    rows, cur = [], []
    while k < len(cells) and k < j + 60:
        c = cells[k]
        m = _NUMCELL.match(c.replace(' ', ''))
        if m:
            cur.append(_num(m.group(1)))
            if len(cur) == len(head):
                rows.append(dict(zip(head, cur)))
                cur = []
        elif _PHASE.match(c) or c in ('-', '–', '구분', '비고'):
            pass
        elif rows:
            break
        k += 1
    return (rows, k) if rows else None


_HEAD_PREFIX = ('최고', '최저', '평균', '전체', '기준', '허용', '상한')
_NUM_COL = re.compile(r'면적|세대|인구|층|높이|건폐율|용적률|호수')


def _grid(cells: list[str], i: int, phase):
    """가로 표형: 머리 칸을 모아 숫자 열 순서를 정하고, 획지 행의 숫자 칸을 뒤에서부터 맞춘다."""
    a = i
    while a > 0 and i - a < 25:
        p = cells[a - 1]
        if (re.search(r'\d', p) or '(' in p or '（' in p) and not re.match(r'^[(（]', p) or len(p) > 20 or _PHASE.match(p) or _is_label(p):
            break
        a -= 1
    h_end = i
    while h_end < len(cells) and h_end - i < 12 and not (re.search(r'\d', cells[h_end]) and not re.match(r'^[(（]', cells[h_end])) and not _is_label(cells[h_end]):
        h_end += 1
    b = h_end
    while b < len(cells) and b - h_end < 30 and not _is_label(cells[b]):
        b += 1
    if b >= len(cells) or b - h_end >= 30:
        return None
    head = []
    for c in cells[a:h_end]:
        if re.match(r'^[(（]', c):
            continue
        if head and head[-1] in _HEAD_PREFIX:
            head[-1] += c
            continue
        head.append(re.sub(r'\s', '', c))
    if not any('건폐율' in h for h in head) or not any('용적률' in h for h in head):
        return None
    num_cols = [h for h in head if _NUM_COL.search(h)]
    width = len(head)
    rows, k = [], b
    while k < len(cells):
        c = cells[k]
        if not _is_label(c):
            if re.match(r'^(?:주\s*\)|※|<|\d+\)|[가-하]\))', c) or _PHASE.match(c) or (_PHASE_IN.search(c) and len(c) < 120):
                break
            k += 1
            continue
        row = cells[k + 1: k + width]
        slots = [x for x in row if _NUMCELL.match(x.replace(' ', '')) or x.strip() in ('-', '–')]
        vals = {}
        for col, x in zip(reversed(num_cols), reversed(slots)):
            m = _NUMCELL.match(x.replace(' ', ''))
            if not m:
                continue
            v = _num(m.group(1))
            if '건폐율' in col and 1 <= v <= 100:
                vals['bcr'] = v
            elif '용적률' in col and 10 <= v <= 2000:
                vals.update(_far_values(x) or {'far': v})
            elif '층' in col:
                vals['floors'] = int(v)
            elif '높이' in col:
                vals['height_m'] = v
            elif '면적' in col and '대지' in col or col in ('면적', '면적(㎡)'):
                vals['area_sqm'] = v
        if vals:
            vals['phase'] = phase or ''
            rows.append((c.strip(' ,，'), vals, ' | '.join([c] + row)[:160]))
        k += 1
    return (rows, k) if rows else None


def _finalize(recs: dict, order: list) -> list[dict]:
    """같은 획지가 기정·변경에 모두 있으면 변경(없으면 나중에 나온 것)을 쓴다. 수치가 하나도 없는 획지는 버린다."""
    out: dict[str, dict] = {}
    for k in order:
        r = recs[k]
        h = r.pop('h', None)
        if h:
            r.update(h)
        f = r.pop('far', None)
        if isinstance(f, dict):
            r.update(f)
        elif f is not None:
            r['far'] = f
        # 판독 오류로 보이는 값은 버린다 (용적률 10~2000%, 건폐율 1~100%, 층수 1~200, 높이 0~1000m, 면적 > 0)
        for key, lo, hi in (('far', 10, 2000), ('base_far', 10, 2000), ('allowed_far', 10, 2000), ('max_far', 10, 2000), ('legal_max_far', 10, 2000),
                            ('far_res', 10, 2000), ('bcr', 1, 100), ('floors', 1, 200), ('height_m', 1, 1000), ('area_sqm', 1, 1e8)):
            if r.get(key) is not None and not (lo <= r[key] <= hi):
                r.pop(key)
        if not any(r.get(x) is not None for x in ('bcr', 'far', 'base_far', 'allowed_far', 'max_far', 'floors', 'height_m')):
            continue
        prev = out.get(r['block'])
        if prev is None or r['phase'] == '변경' or prev['phase'] != '변경':
            merged = {**(prev or {}), **r} if prev and prev['phase'] == r['phase'] else r
            out[r['block']] = merged
    rows = list(out.values())
    for r in rows:
        if r.get('allowed_far') or r.get('base_far'):   # 기준·허용이 있으면 그것이 계획 용적률 (단일 수치는 인센티브 % 등일 수 있음)
            r['far'] = r.get('allowed_far') or r.get('base_far')
        r['evidence'] = r.get('evidence', [])[:4]
        if r.get('uses'):
            r['uses'] = re.sub(r'\s+', ' ', r['uses'].lstrip('-–⋅∙·: ')).strip()
    if len(rows) > 1:   # 수치 없는 '전체'는 획지가 따로 있으면 버림
        rows = [r for r in rows if r['block'] != '전체' or r.get('far') is not None]
    return rows


def locate(text: str, blocks: list[dict]) -> None:
    """가구·획지 규모 표 등에서 획지 이름 바로 뒤에 나오는 위치(○○동 ○○번지)를 찾아 blocks[i]['location']에 넣는다."""
    cells = [re.sub(r'(\d)\s*-\s*(\d)', r'\1-\2', c) for c in (_clean(x) for x in text.split('\n')) if c]   # '88- 22' → '88-22'
    names = {b['block'] for b in blocks}
    found: dict[str, str] = {}
    for i, c in enumerate(cells):
        lbl = c.strip(' ,，')
        if lbl not in names or lbl in found:
            continue
        for x in cells[i + 1:i + 7]:
            if _is_label(x):
                break
            m = re.search(r'([가-힣]+[동리가])\s*((?:산\s*)?\d+(?:-\d+)?(?:\s*[∼~,-]\s*\d+)?)\s*(?:번지)?', x)
            if not m:
                m2 = re.match(r'^[(（]?\s*((?:산\s*)?\d+(?:-\d+)?(?:\s*[∼~]\s*\d+)?)\s*(?:번지)?', x)
                prev = next((p for p in reversed(cells[i + 1:cells.index(x, i + 1)]) if re.search(r'[가-힣]+[동리가]$', p)), '') if m2 else ''
                if m2 and prev:
                    found[lbl] = f"{re.search(r'[가-힣]+[동리가]$', prev).group(0)} {m2.group(1)}"
                    break
                continue
            found[lbl] = f'{m.group(1)} {m.group(2)}'
            break
    for b in blocks:
        if b['block'] in found:
            b['location'] = found[b['block']]


def match_address(blocks: list[dict], address: str) -> str | None:
    """사업지 주소(…동 123-4)와 위치가 맞는 획지 이름. 범위 표기(665-1∼18)·본번 일치도 인정."""
    m = re.search(r'([가-힣]+[동리가])\s+(?:산\s*)?(\d+)(?:-(\d+))?\s*$', (address or '').strip())
    if not m:
        return None
    dong, main, sub = m.group(1), m.group(2), m.group(3)
    hits = []
    for b in blocks:
        loc = b.get('location') or ''
        lm = re.search(r'([가-힣]+[동리가])\s*(?:산\s*)?(\d+)(?:-(\d+))?(?:\s*[∼~]\s*(\d+))?', loc)
        if not lm or lm.group(1) != dong or lm.group(2) != main:
            continue
        exact = sub is not None and lm.group(3) is not None and (
            lm.group(3) == sub or (lm.group(4) and int(lm.group(3)) <= int(sub) <= int(lm.group(4))))
        hits.append((bool(exact), b['block']))
    hits.sort(reverse=True)
    return hits[0][1] if hits and (hits[0][0] or len(hits) == 1) else None
