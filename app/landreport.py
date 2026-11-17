"""토지이용계획 열람본(참고용) 자동 작성 — 브이월드(국토교통부) 토지특성·토지이용계획 속성으로 필지별 정리 후 PDF 저장.

정식 「토지이용계획확인서」 발급은 정부24(본인 인증·수수료)에서만 가능하다. 이 문서는 같은 항목 구성의 참고용 열람본이며,
사업지 자료함에 저장되면 documents.parse_land_use_plan 이 그대로 읽어 필지·용도지역·규제를 정리한다.
"""
import html
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import landinfo

FONT_DIRS = [Path('C:/Windows/Fonts'), Path('/usr/share/fonts/truetype/nanum'), Path('/Library/Fonts')]


def _national(u: dict) -> bool:
    """국토계획법에 따른 지역·지구(브이월드 코드 UQ*, 단 토지거래허가구역 UQQ는 부동산거래신고법)."""
    c = str(u.get('code') or '')
    return c.startswith('UQ') and not c.startswith('UQQ')


ACT_RULES = ('토지거래', '상대보호구역', '절대보호구역', '가축사육제한', '대기관리권역', '과밀억제권역', '성장관리권역', '자연보전권역')


def collect(items: list[dict]) -> list[dict]:
    """[{address, pnu}] → 필지별 토지특성 + 토지이용계획. 실패한 필지는 error."""
    def one(it):
        try:
            pnu = it.get('pnu') if len(str(it.get('pnu') or '')) == 19 else landinfo.geocode_pnu(it.get('address') or '')[0]
            info = landinfo.land_info(pnu)
            try:
                uses = landinfo.land_use(pnu)
            except Exception:
                uses = []
            return {**info, 'uses': uses, 'input_address': it.get('address')}
        except PermissionError:
            raise
        except Exception as exc:
            return {'input_address': it.get('address'), 'error': str(exc)[:160]}
    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(one, items))


def _join(us: list[dict]) -> str:
    return ', '.join(f"{u['name']}{'(' + u['relation'] + ')' if u.get('relation') and u['relation'] != '포함' else ''}" for u in us) or '해당 없음'


def build_pdf(site: str, rows: list[dict], out: Path) -> Path:
    import pymupdf
    font_dir = next((d for d in FONT_DIRS if (d / 'malgun.ttf').exists() or any(d.glob('Nanum*.ttf'))), None)
    font = 'malgun.ttf' if font_dir and (font_dir / 'malgun.ttf').exists() else (next(font_dir.glob('Nanum*.ttf')).name if font_dir else None)
    css = (f"@font-face {{font-family: kr; src: url({font});}} * {{font-family: kr;}}" if font else '') + """
      body {font-size: 9.5pt; color: #142638;} h1 {font-size: 15pt; margin: 0 0 4pt 0;} .sub {color: #627887; font-size: 8.5pt;}
      .item {border: 0.6pt solid #9aa9b5; margin-top: 8pt;} .k {background: #eef3f7; font-weight: bold; padding: 4pt 6pt;}
      .v {padding: 3pt 6pt;} .small {font-size: 8.5pt; color: #4a5d6c;} .warn {color: #a35a00; font-size: 8.5pt; margin-top: 10pt;}"""
    archive = pymupdf.Archive(str(font_dir)) if font_dir else None
    doc = pymupdf.open()
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    for r in rows:
        page = doc.new_page(width=595, height=842)   # A4
        if r.get('error'):
            body = f"<h1>토지이용계획 열람본 (참고용)</h1><p>입력 주소: {html.escape(str(r.get('input_address') or ''))}</p><p class='warn'>조회 실패: {html.escape(r['error'])}</p>"
        else:
            uses = r.get('uses') or []
            nat = [u for u in uses if _national(u)]
            act = [u for u in uses if not _national(u) and any(k in u['name'] for k in ACT_RULES)]
            oth = [u for u in uses if not _national(u) and u not in act]
            addr = f"{r.get('address', '')} {r.get('jibun', '')}".strip()
            body = f"""<h1>토지이용계획 열람본 (참고용)</h1>
<div class="sub">사업지: {html.escape(site)} · 작성 {now} · 자료: 국토교통부 브이월드 토지특성정보·토지이용계획속성 (기준연도 {html.escape(str(r.get('year') or ''))})</div>
<div class="item"><div class="k">토지 기본정보 (지목·면적·개별공시지가)</div>
<div class="v">소재지 {html.escape(addr)}</div><div class="v">지목 {html.escape(str(r.get('jimok') or ''))}</div>
<div class="v">면적 {r.get('area_sqm') or 0:,.1f} ㎡</div>
<div class="v">개별공시지가 {r.get('price_per_sqm') or 0:,.0f}원 (㎡당, {html.escape(str(r.get('year') or ''))}년 기준)</div></div>
<div class="item"><div class="k">지역ㆍ지구등 지정여부</div>
<div class="v">「국토의 계획 및 이용에 관한 법률」에 따른 지역ㆍ지구등 {html.escape(_join(nat))}</div>
<div class="v">다른 법령 등에 따른 지역ㆍ지구등 {html.escape(_join(oth + act))}</div></div>
<div class="item"><div class="k">「토지이용규제 기본법 시행령」 제9조제4항 각 호에 해당되는 사항</div>
<div class="v">{html.escape(_join([u for u in uses if '토지거래' in u['name']]))}</div></div>
<div class="item"><div class="k">지정일</div><div class="v small">{html.escape(', '.join(f"{u['name']} {u['registered']}" for u in uses if u.get('registered'))[:700])}</div></div>
<p class="warn">※ 이 문서는 공개 자료로 자동 작성한 <b>참고용 열람본</b>으로 법적 효력이 있는 「토지이용계획확인서」가 아닙니다. 인허가·계약에는 정부24에서 발급받은 확인서를 사용하세요.
확인도면·행위제한 내용은 토지이음(www.eum.go.kr)에서 확인하세요.</p>"""
        page.insert_htmlbox(pymupdf.Rect(40, 40, 555, 802), body, css=css, archive=archive)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    doc.close()
    return out


def make_report(site: str, site_dir: Path, items: list[dict]) -> dict:
    rows = collect(items)
    name = f"토지이용계획_열람본_{datetime.now().strftime('%Y%m%d')}.pdf"
    path = build_pdf(site, rows, site_dir / name)
    ok = [r for r in rows if not r.get('error')]
    return {'file': path.name, 'parcels': ok, 'failed': [{'address': r.get('input_address'), 'error': r['error']} for r in rows if r.get('error')],
            'notice': '참고용 열람본입니다 (정식 토지이용계획확인서는 정부24에서 발급).'}
