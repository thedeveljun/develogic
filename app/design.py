"""설계도서(설계사무소 작성 PDF) 자동 인식.

대상: 설계개요(건축개요) · 층별개요 · 용도별 분양면적표 · 근린생활시설/업무시설/오피스텔 층별 분양면적표 ·
오피스텔(공동주택) 타입별 분양면적표.

방식: PDF 글자 좌표로 행을 만들고, 표 머리(전용·공용·분양·계약·세대·호수·층 …)의 위치에 숫자를 대응시킨다.
머리가 여러 줄(예: '분양면적' 아래 '전용/공용/계', 그 아래 '㎡/평')이어도 위에서 아래로 이어 붙여 열 이름을 만든다.
설계사무소마다 양식이 달라 결과는 '제안값'이며, 화면에서 원문 행과 함께 보여 주고 되돌릴 수 있게 한다.
"""
import re
from pathlib import Path

import pymupdf

NUM = re.compile(r'^\(?-?[\d,]*\d(?:\.\d+)?\)?$')
DESIGN_HINT = re.compile(r'설계\s*개요|건축\s*개요|층별\s*개요|분양\s*면적|공급\s*면적|면적\s*표|타입별|층별\s*면적|전용\s*면적')
HEAD_KW = re.compile(r'전용|공용|분양|공급|계약|세대|호수|호실|실수|수량|개소|면적|타입|TYPE|type|Type|층|용도|구분|비고|합계|소계|계$|㎡|m2|m²|평')
TOTAL_ROW = re.compile(r'^(합\s*계|총\s*계|소\s*계|계|TOTAL|Total|총합계)$')


def _num(s: str):
    s = s.strip().strip('()').replace(',', '')
    try:
        return float(s)
    except ValueError:
        return None


def floor_of(label: str):
    """'B2', '지하2층', 'B2F' → -2 · '1F', '지상1층', '1층' → 1 · 'PH', '옥탑' → None."""
    t = re.sub(r'\s', '', label or '')
    m = re.match(r'^(?:B|지하|지)(\d+)(?:F|층)?', t, flags=re.I)
    if m:
        return -int(m.group(1))
    m = re.match(r'^(?:지상)?(\d+)(?:F|층)$', t, flags=re.I) or re.match(r'^(?:지상)(\d+)', t)
    return int(m.group(1)) if m else None


# ───────────── PDF → 행(셀) ─────────────
def _words(page) -> list[tuple]:
    """글자 좌표로 낱말을 직접 나눈다: 공백 또는 글자 간격이 글자 크기의 35%를 넘으면 다른 칸.
    (PDF 라이브러리의 낱말 묶음은 가까운 숫자 칸을 '18.625.63'처럼 붙이는 경우가 있다)"""
    out = []
    for b in page.get_text('rawdict')['blocks']:
        for ln in b.get('lines', []):
            for sp in ln['spans']:
                gap = sp['size'] * 0.35
                cur = None
                for ch in sp['chars']:
                    c, (x0, y0, x1, y1) = ch['c'], ch['bbox']
                    if c.isspace():
                        if cur: out.append(tuple(cur)); cur = None
                        continue
                    if cur and x0 - cur[2] <= gap:
                        cur[2] = x1; cur[4] += c
                    else:
                        if cur: out.append(tuple(cur))
                        cur = [x0, y0, x1, y1, c]
                if cur: out.append(tuple(cur))
    return out


def _rows(page) -> list[list[dict]]:
    words = _words(page)
    rows: list[list] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - yc) <= 3.5:
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    out = []
    for yc, ws in rows:
        ws.sort(key=lambda w: w[0])
        cells: list[dict] = []
        for w in ws:
            txt = w[4]
            # 숫자 셀은 옆 글자와 붙이지 않는다 (열 경계 보존)
            if cells and w[0] - cells[-1]['x1'] < 4 and not NUM.match(txt) and not NUM.match(cells[-1]['t']):
                c = cells[-1]
                c['t'] += txt; c['x1'] = w[2]
            else:
                cells.append({'t': txt, 'x0': w[0], 'x1': w[2], 'y': yc})
        out.append(cells)
    return out


def _is_data(row) -> bool:
    nums = [c for c in row if NUM.match(c['t'])]
    if len(nums) == 1 and len(row) >= 2 and floor_of(row[0]['t']) is not None:   # 층별개요: 층 + 면적 하나
        return True
    return len(nums) >= 2 and bool(re.search(r'[\dA-Za-z가-힣]', row[0]['t']))


def _is_title(row) -> bool:
    return bool(re.search(r'(표|개요|현황)$', ''.join(c['t'] for c in row)))


def _is_head(row) -> bool:
    if _is_title(row):
        return False
    hits = sum(1 for c in row if HEAD_KW.search(c['t']) and not NUM.match(c['t']))
    return hits >= 2 or (hits >= 1 and len(row) <= 3 and any(c['t'] in ('㎡', '평', 'm2', 'm²') for c in row))


def _classify(label: str) -> str | None:
    L = label.replace(' ', '')
    if L.endswith('평') or L.endswith('(평)'):
        return 'py'
    if '%' in L or '비율' in L or '대지지분' in L or '지분' in L:
        return None
    if '계약' in L:
        return 'contract'
    if '전용' in L:
        return 'excl'
    if re.search(r'세대|호수|호실|실수|수량|개소|^실$|^호$|개수', L) and '면적' not in L:
        return 'count'
    if '공용' in L and not re.search(r'(분양|공급).*계$', L):
        return 'common'
    if re.search(r'분양|공급', L):
        return 'supply'
    if re.search(r'^층|층별|층수|^구분층', L) and '면적' not in L:
        return 'floor'
    if re.search(r'타입|TYPE|type|Type|형별|평형', L):
        return 'type'
    if '용도' in L:
        return 'use'
    if '면적' in L or L in ('계', '합계', '소계', '㎡', 'm2', 'm²'):
        return 'area'
    return None


def _columns(head_rows) -> list[dict]:
    """머리 행들 → 맨 아래 머리 칸마다 위쪽 머리를 이어 붙인 열 이름."""
    cells = [c for r in head_rows for c in r if not NUM.match(c['t'])]
    if not cells:
        return []
    bottom_y = max(c['y'] for c in cells)
    cols = []
    # 각 칸을 '맨 아래쪽' 기준으로: 자기 아래에 겹치는 칸이 없는 칸이 실제 열
    for c in cells:
        below = [d for d in cells if d['y'] > c['y'] + 1 and d['x0'] < c['x1'] - 1 and d['x1'] > c['x0'] + 1]
        if below:
            continue
        xc = (c['x0'] + c['x1']) / 2
        above = sorted([d for d in cells if d['y'] < c['y'] - 1 and d['x0'] - 6 <= xc <= d['x1'] + 6], key=lambda d: d['y'])
        label = ''.join(d['t'] for d in above) + c['t']
        cols.append({'x': xc, 'x0': c['x0'], 'x1': c['x1'], 'label': label, 'key': _classify(label), 'leaf': c['t']})
    # '㎡' 같은 단위 칸은 위 열 이름의 단위로
    for col in cols:
        if col['leaf'] in ('㎡', 'm2', 'm²') and col['key'] in (None, 'area'):
            col['key'] = _classify(col['label'][:-len(col['leaf'])]) or 'area'
    return sorted(cols, key=lambda c: c['x'])


def _assign(row, cols):
    rec, label_parts = {}, []
    for c in row:
        if NUM.match(c['t']):
            xc = (c['x0'] + c['x1']) / 2
            col = min(cols, key=lambda k: abs(k['x'] - xc)) if cols else None
            if col and col['key'] and col['key'] not in ('py', 'type', 'floor', 'use') and col['key'] not in rec:
                rec[col['key']] = _num(c['t'])
            elif col and col['key'] in ('type', 'floor', 'use'):
                label_parts.append(c['t'])
        else:
            label_parts.append(c['t'])
    rec['label'] = ' '.join(label_parts).strip()
    return rec


def _tables(page) -> list[dict]:
    """페이지 → [{title, columns, rows:[{label, excl, supply, …}], total}]"""
    rows = _rows(page)
    tables, i = [], 0
    while i < len(rows):
        if _is_head(rows[i]) and not _is_data(rows[i]):
            j = i
            heads = []
            while j < len(rows) and not _is_data(rows[j]) and (_is_head(rows[j]) or (heads and len(rows[j]) <= 8)):
                heads.append(rows[j]); j += 1
                if len(heads) > 4:
                    break
            cols = _columns(heads)
            keys = {c['key'] for c in cols}
            if len(keys - {None}) >= 2 and j < len(rows):
                title = ' '.join(c['t'] for r in rows[max(0, i - 3):i] for c in r)[-80:]
                data, total = [], None
                last_label = ''
                while j < len(rows) and (_is_data(rows[j]) or (len(rows[j]) == 1 and not _is_head(rows[j]))):
                    if len(rows[j]) == 1:   # 층·용도 구분 띠 행
                        last_label = rows[j][0]['t']; j += 1; continue
                    rec = _assign(rows[j], cols)
                    first = re.sub(r'\s', '', rows[j][0]['t'])
                    if TOTAL_ROW.match(first) or TOTAL_ROW.match(re.sub(r'\s', '', rec['label'])):
                        if re.sub(r'\s', '', rec['label']) in ('합계', '총계', 'TOTAL', 'Total', '총합계'):
                            total = rec
                        j += 1; continue
                    rec['group'] = last_label
                    data.append(rec)
                    j += 1
                if data:
                    tables.append({'title': title, 'columns': [c['label'] for c in cols], 'keys': sorted(k for k in keys if k), 'rows': data, 'total': total})
                i = j
                continue
        i += 1
    return tables


# ───────────── 설계개요 (항목: 값) ─────────────
def _area_after(t: str, label: str):
    m = re.search(label + r'[^\d\n]{0,20}?([\d,]+\.?\d*)\s*(?:㎡|m2|m²|M2)', t)
    return _num(m.group(1)) if m else None


def parse_overview(text: str) -> dict:
    t = re.sub(r'[ \t]+', ' ', text)
    out = {
        'land_area_sqm': _area_after(t, r'대지\s*면적'),
        'building_area_sqm': _area_after(t, r'건축\s*면적'),
        'total_gfa_sqm': _area_after(t, r'(?<!용적률\s산정용\s)(?<!용적률산정용)연\s*면\s*적(?!\s*\()') or _area_after(t, r'연\s*면\s*적'),
        'far_gfa_sqm': _area_after(t, r'용적률\s*산정용\s*(?:연\s*)?면적'),
        'above_gfa_sqm': _area_after(t, r'지상\s*(?:층\s*)?(?:연\s*)?면적') or _area_after(t, r'지상층'),
        'below_gfa_sqm': _area_after(t, r'지하\s*(?:층\s*)?(?:연\s*)?면적') or _area_after(t, r'지하층'),
    }
    m = re.search(r'건\s*폐\s*율[^\d\n]{0,12}?(\d{1,3}(?:\.\d+)?)\s*%', t)
    out['bcr_pct'] = float(m.group(1)) if m else None
    m = re.search(r'용\s*적\s*률(?!\s*산정)[^\d\n]{0,12}?(\d{2,4}(?:\.\d+)?)\s*%', t)
    out['far_pct'] = float(m.group(1)) if m else None
    m = re.search(r'지하\s*(\d+)\s*층\s*[,~/·]?\s*지상\s*(\d+)\s*층', t)
    out['floors_below'], out['floors_above'] = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    m = re.search(r'계획\s*(?:주차)?\s*(?:대수)?\s*[:：]?\s*([\d,]+)\s*대', t) or re.search(r'주차\s*대수[^\n]{0,40}?([\d,]+)\s*대(?![^\n]{0,30}계획)', t)
    out['parking'] = int(_num(m.group(1))) if m else None
    m = re.search(r'법정\s*(?:주차)?\s*(?:대수)?\s*[:：]?\s*([\d,]+(?:\.\d+)?)\s*대', t)
    out['parking_legal'] = _num(m.group(1)) if m else None
    m = re.search(r'(?:공동주택|아파트)[^\n\d]{0,15}([\d,]+)\s*세대', t) or re.search(r'([\d,]+)\s*세대', t)
    out['households'] = int(_num(m.group(1))) if m else None
    m = re.search(r'오피스텔[^\n\d]{0,15}([\d,]+)\s*(?:실|호|세대)', t)
    out['officetels'] = int(_num(m.group(1))) if m else None
    if out['below_gfa_sqm'] is None and out['total_gfa_sqm'] and out['above_gfa_sqm']:
        out['below_gfa_sqm'] = round(out['total_gfa_sqm'] - out['above_gfa_sqm'], 2)
    return {k: v for k, v in out.items() if v is not None}


# ───────────── 표 종류 판별 · 분양 타입 만들기 ─────────────
USE_RE = [('officetel', r'오피스텔'), ('knowledge', r'지식산업|아파트형\s*공장'), ('datacenter', r'데이터\s*센터|IDC'), ('retail', r'근린|근생|상가|판매'), ('office', r'업무|사무소'), ('apartment', r'공동주택|아파트|주택')]


def _use_of(text: str):
    for k, rx in USE_RE:
        if re.search(rx, text or ''):
            return k
    return None


def _unit_rows(tb):
    """면적표 행 → 전용·분양(공급) 확정. 분양 = 전용 + 공용 으로 보완·검증."""
    out = []
    for r in tb['rows']:
        excl, supply, common, count = r.get('excl'), r.get('supply'), r.get('common'), r.get('count')
        if supply is None and excl is not None and common is not None:
            supply = excl + common
        if supply is None and r.get('area') is not None and excl is not None and r['area'] >= excl:
            supply = r['area']
        if excl is None or supply is None or supply <= 0 or excl > supply * 1.001:
            continue
        out.append({**r, 'excl': excl, 'supply': supply, 'count': count})
    return out


def build_units(tables: list[dict], page_titles: dict) -> tuple[list[dict], list[str]]:
    by_use: dict[str, dict] = {}
    notes = []
    for tb in tables:
        ctx = tb['title'] + ' ' + page_titles.get(tb['page'], '')
        use = _use_of(tb['title']) or _use_of(page_titles.get(tb['page'], '')) or _use_of(' '.join(r.get('group', '') for r in tb['rows']))
        rows = _unit_rows(tb)
        if not use or not rows:
            continue
        mode = 'type' if ('타입' in ctx or 'TYPE' in ctx.upper() or 'type' in tb['keys']) and '층별' not in ctx else 'floor'
        prev = by_use.get(use)
        if prev and prev['mode'] == 'type' and mode == 'floor':
            continue                       # 타입별 표가 있으면 같은 용도의 층별 표는 중복이므로 제외
        by_use[use] = {'mode': mode, 'rows': rows, 'source': tb['source'], 'title': tb['title']}

    units = []
    NAMES = {'officetel': '오피스텔', 'retail': '근린생활시설', 'office': '업무시설', 'knowledge': '지식산업센터', 'datacenter': '데이터센터', 'apartment': '공동주택'}
    for use, g in by_use.items():
        kind = use
        buckets: dict[str, dict] = {}
        for r in g['rows']:
            lab = (r['label'] or r.get('group') or '').strip()
            if g['mode'] == 'floor':
                fl = floor_of(lab.split()[0] if lab else '') or floor_of(r.get('group', '')) or next((floor_of(x) for x in lab.split() if floor_of(x)), None)
                key = (f'지하{-fl}층' if fl and fl < 0 else f'{fl}층') if fl else (lab.split()[0] if lab else '기타')
            else:
                key = re.sub(r'\s+', '', lab.split()[0] if lab else '') or '타입'
            b = buckets.setdefault(key, {'n': 0, 'excl': 0.0, 'supply': 0.0, 'rows': 0})
            n = int(r['count']) if r.get('count') and float(r['count']).is_integer() and 0 < r['count'] < 5000 else 1
            # 층별 표에서 행이 '호실별'이면 전용·분양은 1호실 값, '층 합계'면 호수와 함께 합계 값
            b['n'] += n
            per_row_total = g['mode'] == 'floor' and n > 1 and r['excl'] > 400
            b['excl'] += r['excl'] if per_row_total else r['excl'] * n
            b['supply'] += r['supply'] if per_row_total else r['supply'] * n
            b['rows'] += 1
        for key, b in buckets.items():
            n = max(1, b['n'])
            units.append({'name': f"{NAMES[use]} {key}", 'kind': kind, 'use': use, 'count': n,
                          'exclusive_sqm': round(b['excl'] / n, 2), 'supply_sqm': round(b['supply'] / n, 2),
                          'source': g['source']})
        notes.append(f"{NAMES[use]}: {g['source']} — {'타입별' if g['mode'] == 'type' else '층별'} {len(buckets)}개 → {sum(b['n'] for b in buckets.values())}{'세대' if use == 'apartment' else '실·호'}")
    return units, notes


def parse_pdfs(paths: list[Path]) -> dict:
    overview: dict = {}
    tables, titles, files, floors = [], {}, [], []
    for p in paths:
        doc = pymupdf.open(p)
        info = {'name': p.name, 'pages': doc.page_count, 'tables': 0, 'kinds': []}
        text_all = ''
        for pi, page in enumerate(doc):
            text = page.get_text()
            text_all += text + '\n'
            pid = f'{p.name}#{pi + 1}'
            titles[pid] = ' '.join(text.split('\n')[:4])
            for tb in _tables(page):
                tb['page'] = pid; tb['source'] = f'{p.name} {pi + 1}쪽'
                tables.append(tb); info['tables'] += 1
                if 'floor' in tb['keys'] or any(floor_of(r['label'].split()[0] if r['label'] else '') is not None for r in tb['rows'][:3]):
                    floors.append(tb)
        doc.close()
        if not text_all.strip():
            info['kinds'].append('스캔 이미지 (글자 없음 — 인식 불가)')
        ov = parse_overview(text_all)
        if re.search(r'설\s*계\s*개\s*요|건\s*축\s*개\s*요', text_all) or len(ov) >= 3:
            info['kinds'].append('설계개요')
            if re.search(r'공동주택|아파트', text_all):
                overview['has_apartment'] = True
            for k, v in ov.items():
                overview.setdefault(k, v)
        files.append(info)

    units, notes = build_units(tables, titles)
    alltext = ' '.join(titles.values()) + ' ' + ' '.join(t['title'] for t in tables)
    overview['has_apartment'] = overview.get('has_apartment') or bool(overview.get('households')) or bool(re.search(r'공동주택|아파트', alltext))
    for f in files:
        used = {u['source'].split(' ')[0] for u in units}
        if f['name'] in used:
            f['kinds'].append('분양면적표')

    # 층별개요: 지상/지하 바닥면적 합 (용도 표와 구분: 전용 열이 없는 층별 면적 표)
    checks = []
    above = below = 0.0
    for tb in floors:
        if 'excl' in tb['keys']:
            continue
        for r in tb['rows']:
            fl = floor_of(r['label'].split()[0] if r['label'] else '')
            a = r.get('area') or r.get('supply')
            if fl is None or not a:
                continue
            if fl < 0: below += a
            else: above += a
        src = next((f for f in files if tb['source'].startswith(f['name'])), None)
        if (above or below) and src and '층별개요' not in src['kinds']:
            src['kinds'].append('층별개요')
    if above and 'above_gfa_sqm' not in overview:
        overview['above_gfa_sqm'] = round(above, 2)
    if below and 'below_gfa_sqm' not in overview:
        overview['below_gfa_sqm'] = round(below, 2)
    if above and overview.get('above_gfa_sqm') and abs(above - overview['above_gfa_sqm']) > max(1, overview['above_gfa_sqm'] * 0.005):
        checks.append(f"층별개요 지상 합계 {above:,.2f}㎡ ≠ 설계개요 지상 {overview['above_gfa_sqm']:,.2f}㎡ — 원문 확인")

    # 검증: 면적표 분양면적 합 ≤ 연면적
    tot_supply = sum(u['supply_sqm'] * u['count'] for u in units)
    gfa = (overview.get('above_gfa_sqm') or 0) + (overview.get('below_gfa_sqm') or 0) or overview.get('total_gfa_sqm')
    if gfa and tot_supply > gfa * 1.02:
        checks.append(f'분양면적 합계 {tot_supply:,.0f}㎡가 연면적 {gfa:,.0f}㎡보다 큽니다 — 중복된 표(층별·타입별)가 있는지 확인하세요')
    if overview.get('households') and (n := sum(u['count'] for u in units if u['use'] == 'apartment')) and n != overview['households']:
        checks.append(f"공동주택 면적표 {n}세대 ≠ 설계개요 {overview['households']}세대")
    if overview.get('officetels') and (n := sum(u['count'] for u in units if u['use'] == 'officetel')) and n != overview['officetels']:
        checks.append(f"오피스텔 면적표 {n}실 ≠ 설계개요 {overview['officetels']}실")
    if not units and not overview:
        checks.append('설계개요·면적표를 인식하지 못했습니다. 글자를 선택할 수 있는 PDF(캐드·한글에서 PDF로 저장한 파일)인지 확인하세요.')
    return {'overview': overview, 'units': units, 'notes': notes, 'checks': checks, 'files': files,
            'tables': [{'source': t['source'], 'title': t['title'], 'columns': t['columns'], 'rows': len(t['rows'])} for t in tables]}


def is_design_pdf(text: str) -> bool:
    t = re.sub(r'\s+', '', text or '')   # '설 계 개 요'처럼 띄어 쓴 제목 대응
    return bool(DESIGN_HINT.search(t)) or ('대지면적' in t and '연면적' in t and ('건폐율' in t or '용적률' in t))
