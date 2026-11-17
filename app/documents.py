"""사업지 자료함: 폴더에 넣은 기본 자료를 읽어 필지·용도지역·규제 현황을 정리한다.

자료함 구조:  자료함/<사업지명>/
  - 토지이용계획확인서 PDF (토지이음·정부24 출력본, 텍스트 PDF)  → 자동 추출
  - 필지목록.xlsx / .csv (양식: 자료함/_양식)                     → 표로 읽기
  - 그 밖의 파일(지적도, 사진, 조례 원문 등)                       → 첨부 목록

추출값은 원문과 대조가 필요한 '1차 정리'이며, 인식하지 못한 값은 비워 두고 경고한다.
"""
import csv
import io
import re
import shutil
from pathlib import Path

from . import config

ROOT = Path(__file__).parent.parent


def _inbox() -> Path:          # 내 PC: 자료함/ · 클라우드: 업체별 자료함 (config.inbox)
    return config.inbox()


def _tpl_dir() -> Path:
    return _inbox() / '_양식'


def _trash() -> Path:
    return _inbox() / '_삭제된 사업지'


def __getattr__(name):         # 예전 이름 호환 (documents.INBOX 등)
    if name == 'INBOX': return _inbox()
    if name == 'TEMPLATE_DIR': return _tpl_dir()
    if name == 'TRASH': return _trash()
    raise AttributeError(name)


TABLE_COLUMNS = ['소재지', '지번', '지목', '면적(㎡)', '용도지역', '개별공시지가(원/㎡)', '비고']

ZONES = [
    '제1종전용주거지역', '제2종전용주거지역', '제1종일반주거지역', '제2종일반주거지역', '제3종일반주거지역', '준주거지역',
    '중심상업지역', '일반상업지역', '근린상업지역', '유통상업지역', '전용공업지역', '일반공업지역', '준공업지역',
    '보전녹지지역', '생산녹지지역', '자연녹지지역', '보전관리지역', '생산관리지역', '계획관리지역', '농림지역', '자연환경보전지역',
]
JIMOK = ['전', '답', '과수원', '목장용지', '임야', '광천지', '염전', '대', '공장용지', '학교용지', '주차장', '주유소용지', '창고용지',
         '도로', '철도용지', '제방', '하천', '구거', '유지', '양어장', '수도용지', '공원', '체육용지', '유원지', '종교용지', '사적지', '묘지', '잡종지']

# 토지이용계획확인서에 자주 나오는 규제 → 사업 검토 시 확인 사항
FLAGS = {
    '지구단위계획구역': '지구단위계획 결정도서의 용적률(기준·허용·상한)·건축한계선·용도 제한이 조례보다 우선합니다.',
    '정비구역': '정비계획(도시정비법)에 따른 용적률·기반시설 부담이 적용됩니다.',
    '재정비촉진지구': '재정비촉진계획에 따른 별도 용적률·기반시설 기준을 확인하세요.',
    '개발제한구역': '원칙적으로 개발행위가 제한됩니다(개발제한구역법).',
    '도시계획시설': '도시계획시설(도로·공원 등) 저촉 부분은 건축 불가·보상 대상일 수 있습니다. 저촉 면적을 확인하세요.',
    '도로': '도시계획도로 저촉 여부(소로·중로·대로, 접함/저촉)를 확인하세요. 저촉 면적은 대지면적에서 제외될 수 있습니다.',
    '공원': '공원 저촉 면적은 건축이 제한됩니다.',
    '군사기지 및 군사시설 보호구역': '관할 부대 협의(높이 제한 등)가 필요합니다.',
    '비행안전구역': '건축물 높이 제한을 확인하세요.',
    '대공방어협조구역': '높이 기준 초과 시 군 협의가 필요합니다.',
    '고도지구': '건축물 높이 최고한도가 적용됩니다.',
    '경관지구': '경관 관련 높이·형태 제한을 확인하세요.',
    '문화유산': '문화유산(국가유산) 보존지역 내 현상변경 허가 검토가 필요합니다.',
    '문화재': '문화재 보존지역 내 현상변경 허가 검토가 필요합니다.',
    '역사문화환경 보존지역': '현상변경 허가 기준(높이·형태)을 확인하세요.',
    '교육환경보호구역': '교육환경평가·금지시설(유해업종) 제한을 확인하세요.',
    '상대보호구역': '교육환경보호구역 내 금지시설 제한을 확인하세요.',
    '절대보호구역': '교육환경보호구역 내 금지시설 제한을 확인하세요.',
    '과밀억제권역': '수도권정비계획법상 과밀부담금·학교용지 등 부담 기준에 영향이 있습니다.',
    '토지거래계약에 관한 허가구역': '토지 매매 시 토지거래허가가 필요합니다.',
    '가축사육제한구역': '주거 개발에는 통상 영향이 적으나 원문을 확인하세요.',
    '상수원보호구역': '건축·개발행위 제한이 큽니다.',
    '수질보전특별대책지역': '오수 처리·건축 연면적 제한을 확인하세요.',
    '하천구역': '하천 점용·건축 제한을 확인하세요.',
    '소하천': '소하천 구역 저촉 여부를 확인하세요.',
    '전략환경영향평가': '환경영향평가 대상 여부를 확인하세요.',
}


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', '', (name or '').strip())
    if not name or name.startswith('.') or name.startswith('_'):
        raise ValueError('사업지 이름이 올바르지 않습니다')
    return name[:60]


def site_dir(name: str) -> Path:
    p = (_inbox() / safe_name(name)).resolve()
    if p.parent != _inbox().resolve():
        raise ValueError('잘못된 경로입니다')
    return p


def ensure_inbox():
    _inbox().mkdir(parents=True, exist_ok=True)
    _tpl_dir().mkdir(exist_ok=True)
    tpl = _tpl_dir() / '필지목록_양식.xlsx'
    if not tpl.exists():
        write_template(tpl)
    readme = _inbox() / '자료함_사용법.txt'
    if not readme.exists():
        readme.write_text(
            '자료함 사용법\n\n'
            '1. 사업지마다 폴더를 하나 만듭니다. 예) 자료함\\서울시_서초구\n'
            '2. 토지이용계획확인서 PDF(토지이음 eum.go.kr 또는 정부24 출력본)를 넣으면 자동으로 읽습니다.\n'
            '   스캔(이미지) PDF는 글자를 읽을 수 없으니 필지목록 양식에 직접 입력하세요.\n'
            '3. 필지가 많으면 _양식\\필지목록_양식.xlsx 를 복사해 채워 넣으세요.\n'
            '4. 지적도·사진·조례 원문 등 다른 파일도 함께 넣어 두면 첨부 목록으로 보입니다.\n'
            '5. 웹 화면 [사업지 자료] 메뉴에서 분석 결과를 보고, 법규 검토·사업수지로 보낼 수 있습니다.\n',
            encoding='utf-8')


def write_template(path: Path, rows: list[list] | None = None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = '필지목록'
    ws.append(TABLE_COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='111A2E')
    for r in rows or [['경기도 안양시 동안구 예시동', '101', '대', 330.5, '제2종일반주거지역', 4500000, '예시 행 — 지우고 입력']]:
        ws.append(r)
    for col, w in zip('ABCDEFG', [34, 10, 8, 12, 20, 20, 30]):
        ws.column_dimensions[col].width = w
    wb.save(path)


def create_site(name: str) -> dict:
    ensure_inbox()
    d = site_dir(name)
    d.mkdir(exist_ok=True)
    tpl = d / '필지목록.xlsx'
    if not tpl.exists():
        shutil.copy(_tpl_dir() / '필지목록_양식.xlsx', tpl)
    return {'name': d.name}


def list_sites() -> list[dict]:
    ensure_inbox()
    out = []
    for d in sorted(_inbox().iterdir()):
        if d.is_dir() and not d.name.startswith(('_', '.')):
            files = [f for f in d.iterdir() if f.is_file() and not f.name.startswith(('~$', '.')) and f.name not in (PF_FILE, PF_RESULT)]
            out.append({'name': d.name, 'files': len(files),
                        'updated': max((f.stat().st_mtime for f in d.iterdir() if f.is_file()), default=d.stat().st_mtime),
                        'result': site_result(d.name), 'scenarios': len(list_scenarios(d.name))})
    return out


def design_pdf(text: str) -> bool:
    from .design import is_design_pdf
    return is_design_pdf(text) and not re.search(r'토지이용계획확인|결정\s*고시', text[:3000])


def design_files(name: str) -> list[Path]:
    d = site_dir(name)
    out = []
    for f in sorted(d.glob('*.pdf')):
        try:
            if design_pdf(pdf_text(f)):
                out.append(f)
        except Exception:   # 손상 파일
            continue
    return out


def delete_site(name: str) -> dict:
    """사업지 삭제 = 자료함/_삭제된 사업지/ 로 이동 (영구 삭제 아님 · 복원 가능)."""
    d = site_dir(name)
    if not d.is_dir():
        raise FileNotFoundError(f'사업지가 없습니다: {name}')
    _trash().mkdir(exist_ok=True)
    from datetime import datetime
    dest = _trash() / f"{d.name}__{datetime.now():%Y%m%d-%H%M%S}"
    shutil.move(str(d), str(dest))
    return {'name': d.name, 'trash': dest.name}


def list_trash() -> list[dict]:
    if not _trash().is_dir():
        return []
    out = []
    for d in sorted(_trash().iterdir(), key=lambda x: -x.stat().st_mtime):
        if d.is_dir():
            name, _, stamp = d.name.rpartition('__')
            out.append({'id': d.name, 'name': name or d.name, 'deleted': stamp, 'result': _read_json(d / PF_RESULT)})
    return out


def purge_site(trash_id: str) -> dict:
    """삭제된 사업지 폴더를 완전히 지운다 (복원 불가). 휴지통 안의 폴더만 허용."""
    src = (_trash() / trash_id).resolve()
    if src.parent != _trash().resolve() or not src.is_dir():
        raise FileNotFoundError('삭제된 사업지를 찾지 못했습니다')
    shutil.rmtree(src)
    return {'id': trash_id}


def restore_site(trash_id: str) -> dict:
    src = (_trash() / trash_id).resolve()
    if src.parent != _trash().resolve() or not src.is_dir():
        raise FileNotFoundError('삭제된 사업지를 찾지 못했습니다')
    name = trash_id.rpartition('__')[0] or trash_id
    dest = site_dir(name)
    if dest.exists():
        raise ValueError(f'같은 이름의 사업지가 이미 있습니다: {name}')
    shutil.move(str(src), str(dest))
    return {'name': name}


def _read_json(f: Path):
    try:
        return _json.loads(f.read_text(encoding='utf-8')) if f.exists() else None
    except ValueError:
        return None


# ───────────── 파싱 ─────────────
def _num(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r'-?[\d,]+(?:\.\d+)?', str(s))
    return float(m.group().replace(',', '')) if m else None


def _norm_header(h: str) -> str | None:
    h = re.sub(r'\s|\(.*?\)', '', str(h or ''))
    for key, alts in {'소재지': ['소재지', '주소', '위치'], '지번': ['지번', '번지'], '지목': ['지목'],
                      '면적': ['면적', '토지면적', '대지면적', '면적㎡'], '용도지역': ['용도지역', '지역'],
                      '공시지가': ['개별공시지가', '공시지가', '공시지가원/㎡'], '비고': ['비고', '메모']}.items():
        if any(h == a or h.startswith(a) for a in alts):
            return key
    return None


def _rows_to_parcels(rows: list[list], source: str) -> tuple[list[dict], list[str]]:
    rows = [r for r in rows if any(str(c or '').strip() for c in r)]
    if not rows:
        return [], [f'{source}: 내용이 없습니다']
    header = [_norm_header(h) for h in rows[0]]
    if '면적' not in header:
        return [], [f'{source}: "면적" 열을 찾지 못했습니다 (양식의 제목 행을 유지하세요)']
    parcels, warns = [], []
    for i, r in enumerate(rows[1:], start=2):
        rec = {k: r[j] if j < len(r) else None for j, k in enumerate(header) if k}
        if '예시 행' in str(rec.get('비고') or ''):
            continue
        area = _num(rec.get('면적'))
        if not area:
            warns.append(f'{source} {i}행: 면적이 없어 제외했습니다')
            continue
        addr = str(rec.get('소재지') or '').strip()
        jibun = str(rec.get('지번') or '').strip()
        if jibun.endswith('.0'):
            jibun = jibun[:-2]
        parcels.append({
            'address': (addr + ' ' + jibun).strip() if jibun and jibun not in addr else addr,
            'jimok': str(rec.get('지목') or '').strip() or None, 'area_sqm': area,
            'zones': [z for z in ZONES if z in str(rec.get('용도지역') or '')] or ([str(rec['용도지역']).strip()] if rec.get('용도지역') else []),
            'price_per_sqm': _num(rec.get('공시지가')), 'flags': [], 'note': str(rec.get('비고') or '').strip(),
            'source': source,
        })
    return parcels, warns


def read_table(path: Path):
    if path.suffix.lower() == '.csv':
        raw = path.read_bytes()
        for enc in ('utf-8-sig', 'cp949'):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return [], [f'{path.name}: 글자 인코딩을 읽을 수 없습니다']
        return _rows_to_parcels(list(csv.reader(io.StringIO(text))), path.name)
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return _rows_to_parcels(rows, path.name)


def pdf_text(path: Path) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return '\n'.join(page.get_text() for page in doc)


def parse_land_use_plan(text: str, source: str) -> tuple[list[dict], list[str]]:
    """토지이용계획확인서 텍스트 → 필지 정보. 한 PDF에 여러 필지가 있으면 '소재지' 단위로 나눈다."""
    t = re.sub(r'[ \t ]+', ' ', text)
    if len(t.strip()) < 30:
        return [], [f'{source}: 글자를 읽을 수 없는 PDF(스캔본)입니다. 필지목록에 직접 입력하세요.']
    if '토지이용' not in t and '지역' not in t:
        return [], [f'{source}: 토지이용계획확인서 형식이 아닙니다 (첨부로만 표시)']
    chunks = re.split(r'(?=소\s*재\s*지)', t)
    chunks = [c for c in chunks if re.match(r'소\s*재\s*지', c)] or [t]
    parcels, warns = [], []
    for c in chunks:
        flat = re.sub(r'\s+', ' ', c)
        m = re.search(r'소\s*재\s*지\s*:?\s*(.+?)\s*(?:지\s*번|지\s*목|면\s*적|$)', flat)
        addr = m.group(1).strip() if m else ''
        jb = re.search(r'지\s*번\s*:?\s*([산]?\s*\d+(?:-\d+)?)', flat)
        if jb and jb.group(1).replace(' ', '') not in addr:
            addr = (addr + ' ' + jb.group(1).replace(' ', '')).strip()
        jm = re.search(r'지\s*목\s*:?\s*(' + '|'.join(sorted(JIMOK, key=len, reverse=True)) + r')(?![가-힣])', flat)
        ar = re.search(r'면\s*적\s*:?\s*([\d,]+(?:\.\d+)?)\s*(?:㎡|m²|m2|제곱미터)', flat)
        pr = re.search(r'개별\s*공시\s*지가[^\d]{0,20}([\d,]{4,})\s*원', flat)
        sec_nat = re.search(r'국토의\s*계획\s*및\s*이용에\s*관한\s*법률.{0,10}?따른\s*지역\s*[ㆍ·.]?\s*지구\s*등(.+?)(?:다른\s*법령|「?토지이용규제|$)', flat)
        sec_oth = re.search(r'다른\s*법령\s*등에\s*따른\s*지역\s*[ㆍ·.]?\s*지구\s*등(.+?)(?:「?토지이용규제\s*기본법|확인\s*도면|$)', flat)
        scope = (sec_nat.group(1) if sec_nat else '') + ' ' + (sec_oth.group(1) if sec_oth else '')
        zones = [z for z in ZONES if z in (sec_nat.group(1) if sec_nat else flat)]
        target = scope if scope.strip() else flat
        flags = {k for k in FLAGS if k in target and k != '도로'}
        road = re.findall(r'((?:소로|중로|대로|광로)\s*\d\s*류[^,，]*?\((접함|저촉)\))', target)
        if road:
            flags.add('도로')
            if any(kind == '저촉' for _, kind in road):
                flags.add('도시계획시설')
        flags = sorted(flags)
        rec = {'address': addr or None, 'jimok': jm.group(1) if jm else None, 'area_sqm': _num(ar.group(1)) if ar else None,
               'zones': zones, 'price_per_sqm': _num(pr.group(1)) if pr else None, 'flags': flags,
               'note': '', 'source': source,
               'restrictions': (sec_nat.group(1).strip()[:300] if sec_nat else '') + (' / ' + sec_oth.group(1).strip()[:300] if sec_oth else '')}
        missing = [n for n, v in [('소재지', addr), ('면적', rec['area_sqm']), ('용도지역', zones)] if not v]
        if missing:
            warns.append(f'{source}: {", ".join(missing)}을(를) 인식하지 못했습니다. 원문을 확인해 필지목록에 보완하세요.')
        if rec['area_sqm'] or addr:
            parcels.append(rec)
    return parcels, warns


def parse_plan_notice(text: str, source: str) -> dict | None:
    """지구단위계획·정비계획 결정고시(텍스트 PDF)에서 용적률 수치를 찾는다. 확인용 제안값."""
    t = re.sub(r'\s+', ' ', text)
    if not re.search(r'지구단위계획|정비계획|정비구역|가로주택|소규모', t):
        return None
    def pct(label):
        m = re.search(label + r'[^0-9%]{0,25}?(\d{2,4}(?:\.\d+)?)\s*%', t)
        return float(m.group(1)) if m else None
    kind = 'district' if '지구단위계획' in t else 'reconstruction' if '재건축' in t else 'small' if re.search('가로주택|소규모', t) else 'redevelopment'
    out = {'source': source, 'kind': kind,
           'base_far': pct(r'기준\s*용적률') or pct(r'정비계획\s*용적률') or pct(r'계획\s*용적률'),
           'allowed_far': pct(r'허용\s*용적률'), 'max_far': pct(r'상한\s*용적률') or pct(r'법적\s*상한\s*용적률'),
           'plan_bcr': pct('건폐율')}
    no = re.search(r'([가-힣]+(?:특별시|광역시|도|시|군|구)\s*고시\s*제\s*[\d\-]+\s*호)', t)
    title = re.search(r'([가-힣0-9]+\s*(?:지구단위계획|정비계획|정비구역)[가-힣\s]{0,30}?(?:결정|변경)[가-힣\s]{0,10}?고시)', t)
    date = re.search(r'(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.', t)
    out.update(notice_no=no.group(1).replace(' ', '') if no else '', title=title.group(1).strip() if title else '',
               notice_date=f'{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}' if date else '')
    if not any(out[k] for k in ('base_far', 'allowed_far', 'max_far')):
        return None
    return out


# ───────────── 분석 ─────────────
def parse_address(addr: str) -> dict:
    """'경기도 안양시 동안구 관양동 …' → 광역 '경기도', 시군구 '안양시'(구가 있는 일반시는 시 단위)."""
    parts = (addr or '').split()
    prov = parts[0] if parts and re.search(r'(도|특별시|광역시|특별자치시|특별자치도)$', parts[0]) else None
    muni = None
    if prov and len(parts) > 1:
        if prov.endswith(('특별시', '광역시')):
            muni = parts[1] if parts[1].endswith(('구', '군')) else None
        elif prov == '세종특별자치시':
            muni = '세종특별자치시'
        else:
            muni = parts[1] if parts[1].endswith(('시', '군')) else None
    return {'province': prov, 'municipality': muni}


def analyze_site(name: str) -> dict:
    d = site_dir(name)
    if not d.is_dir():
        raise FileNotFoundError('사업지 폴더가 없습니다')
    files, parcels, warns, notices = [], [], [], []
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.name.startswith(('~$', '.')) or f.name in (PF_FILE, PF_RESULT):
            continue
        ext = f.suffix.lower()
        info = {'name': f.name, 'size': f.stat().st_size, 'kind': '첨부', 'parsed': 0}
        try:
            if ext in ('.xlsx', '.xlsm', '.csv'):
                ps, ws = read_table(f)
                info.update(kind='필지목록', parsed=len(ps))
            elif ext == '.pdf':
                text = pdf_text(f)
                ps, ws = parse_land_use_plan(text, f.name)
                info.update(kind='토지이용계획확인서' if ps else 'PDF', parsed=len(ps))
                if not ps and design_pdf(text):
                    info['kind'] = '설계도서'
                    ps, ws = [], []
                elif not ps:
                    ws = [] if (ws and '형식이 아닙니다' in ws[0]) else ws
                    pn = parse_plan_notice(text, f.name)
                    if pn:
                        notices.append(pn)
                        info['kind'] = '도시계획 결정고시'
                        ws = []
            else:
                ps, ws = [], []
        except Exception as exc:  # 손상된 파일 등
            ps, ws = [], [f'{f.name}: 읽기 실패 ({exc.__class__.__name__})']
            info['kind'] = '오류'
        parcels += ps
        warns += ws
        files.append(info)

    # 같은 필지(소재지 동일)는 하나로 합친다: 표 값 우선, 빈 값은 PDF로 보완
    merged: dict[str, dict] = {}
    for p in parcels:
        key = re.sub(r'\s+', '', p['address'] or '') or f"#{len(merged)}"
        if key in merged:
            q = merged[key]
            if q['area_sqm'] and p['area_sqm'] and abs(q['area_sqm'] - p['area_sqm']) > 0.5:
                warns.append(f"{p['address']}: 자료 간 면적이 다릅니다 ({q['area_sqm']:,}㎡ / {p['area_sqm']:,}㎡ — {q['source']} 값을 사용)")
            for k in ('jimok', 'area_sqm', 'price_per_sqm'):
                q[k] = q[k] or p[k]
            q['zones'] = q['zones'] or p['zones']
            q['flags'] = sorted(set(q['flags']) | set(p['flags']))
            q['restrictions'] = q.get('restrictions') or p.get('restrictions')
            q['source'] += ', ' + p['source']
        else:
            merged[key] = dict(p)
    plist = list(merged.values())

    total = sum(p['area_sqm'] or 0 for p in plist)
    by_zone: dict[str, float] = {}
    for p in plist:
        zs = p['zones'] or ['미확인']
        if len(zs) > 1:
            warns.append(f"{p['address']}: 용도지역이 둘 이상({', '.join(zs)})입니다. 면적 분할 여부를 확인하세요 (첫 번째 지역으로 집계).")
        by_zone[zs[0]] = by_zone.get(zs[0], 0) + (p['area_sqm'] or 0)
    by_jimok: dict[str, float] = {}
    for p in plist:
        by_jimok[p['jimok'] or '미확인'] = by_jimok.get(p['jimok'] or '미확인', 0) + (p['area_sqm'] or 0)
    priced = [p for p in plist if p['price_per_sqm'] and p['area_sqm']]
    price_total = sum(p['price_per_sqm'] * p['area_sqm'] for p in priced)
    flags = {}
    for p in plist:
        for f in p['flags']:
            flags.setdefault(f, {'name': f, 'note': FLAGS.get(f, ''), 'parcels': []})['parcels'].append(p['address'])
    for j in ('도로', '구거', '하천', '공원', '유지'):
        if by_jimok.get(j):
            warns.append(f'지목 "{j}" 필지 {by_jimok[j]:,.1f}㎡가 포함되어 있습니다. 매입·대지 산입 가능 여부를 확인하세요.')
    if by_zone.get('미확인'):
        warns.append(f"용도지역 미확인 면적 {by_zone['미확인']:,.1f}㎡가 있습니다.")
    loc = parse_address(next((p['address'] for p in plist if p['address']), ''))
    main_zone = max(((z, a) for z, a in by_zone.items() if z != '미확인'), key=lambda x: x[1], default=(None, 0))[0]
    return {
        'name': d.name, 'path': str(d), 'files': files, 'parcels': plist,
        'summary': {
            'parcel_count': len(plist), 'total_area_sqm': total, 'total_area_py': total * 121 / 400,
            'by_zone': [{'zone': z, 'area_sqm': a, 'share': a / total if total else None} for z, a in sorted(by_zone.items(), key=lambda x: -x[1])],
            'by_jimok': [{'jimok': j, 'area_sqm': a} for j, a in sorted(by_jimok.items(), key=lambda x: -x[1])],
            'main_zone': main_zone, 'province': loc['province'], 'municipality': loc['municipality'],
            'official_price_total': price_total,
            'official_price_avg_sqm': price_total / sum(p['area_sqm'] for p in priced) if priced else None,
            'price_coverage': sum(p['area_sqm'] for p in priced) / total if total else None,
        },
        'flags': list(flags.values()),
        'plan_notices': notices,
        'warnings': warns,
        'notice': '자료에서 자동으로 읽은 1차 정리입니다. 면적·용도지역·규제는 원문(토지이용계획확인서·지적도)과 대조하세요.',
    }


# ───────────── 사업지별 사업수지 저장 ─────────────
import json as _json
from datetime import datetime as _dt

PF_FILE, PF_RESULT, SCN_DIR = '사업수지.json', '사업수지_요약.json', '시나리오'


def _scn_name(n: str) -> str:
    n = re.sub(r'[\\/:*?"<>|]', '', (n or '').strip())[:60]   # \ 와 / 모두 제거 (경로 이탈 방지)
    if not n or n.startswith('.') or '..' in n:
        raise ValueError('시나리오 이름이 올바르지 않습니다')
    return n


def load_proforma(name: str, scenario: str | None = None) -> dict | None:
    d = site_dir(name)
    f = (d / SCN_DIR / (_scn_name(scenario) + '.json')) if scenario else d / PF_FILE
    return _json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def save_proforma(name: str, payload: dict, summary: dict | None, scenario: str | None = None) -> dict:
    d = site_dir(name)
    if not d.is_dir():
        raise FileNotFoundError('사업지 폴더가 없습니다')
    if scenario:
        (d / SCN_DIR).mkdir(exist_ok=True)
        f = d / SCN_DIR / (_scn_name(scenario) + '.json')
    else:
        f = d / PF_FILE
    f.write_text(_json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    if summary is not None and not scenario:
        (d / PF_RESULT).write_text(_json.dumps({**summary, 'saved_at': _dt.now().isoformat(timespec='seconds')}, ensure_ascii=False), encoding='utf-8')
    return {'saved': f.name}


def list_scenarios(name: str) -> list[dict]:
    d = site_dir(name) / SCN_DIR
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob('*.json'), key=lambda x: -x.stat().st_mtime):
        meta = {}
        try:
            meta = _json.loads(f.read_text(encoding='utf-8')).get('_scenario') or {}
        except ValueError:
            pass
        out.append({'name': f.stem, 'updated': f.stat().st_mtime, 'memo': meta.get('memo', ''), 'saved_at': meta.get('saved_at', '')})
    return out


def delete_scenario(name: str, scenario: str) -> dict:
    f = site_dir(name) / SCN_DIR / (_scn_name(scenario) + '.json')
    if not f.exists():
        raise FileNotFoundError('시나리오가 없습니다')
    f.unlink()
    return {'deleted': scenario}


def site_result(name: str) -> dict | None:
    f = site_dir(name) / PF_RESULT
    try:
        return _json.loads(f.read_text(encoding='utf-8')) if f.exists() else None
    except ValueError:
        return None
