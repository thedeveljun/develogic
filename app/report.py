"""사업수지분석표 Excel 작성.

시트 구성: ① 사업수지분석표(개요·판정·수지표·핵심지표) ② 분양수입 ③ 사업비 상세 ④ 월별 현금흐름
          ⑤ 금융·세금 ⑥ 법규 검토 ⑦ 민감도
"""
import io
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY, BLUE, SOFT, LINE = '111A2E', '1E88D6', 'F4F8FA', 'D5DEE4'
OK, WARN, BAD = ('E6F4EA', '1E7B3A'), ('FFF1E6', 'B4530B'), ('FFE9E7', 'B3261E')
WON = '#,##0;[Red]-#,##0'
EOK = '#,##0"억";[Red]-#,##0"억"'
PCT = '0.00"%"'
thin = Side(style='thin', color=LINE)
BORDER = Border(top=thin, bottom=thin, left=thin, right=thin)
STATUS = {'ok': ('적합', OK), 'warn': ('주의', WARN), 'bad': ('부적합', BAD)}
BASIS = {'fixed': '정액', 'per_land_py': '대지 평당', 'per_above_py': '지상연면적 평당', 'per_below_py': '지하연면적 평당',
         'per_gfa_py': '전체연면적 평당', 'per_supply_py': '공급면적 평당', 'per_unit': '주거 세대당', 'monthly': '월 × 기간',
         'pct_land': '토지비 대비 %', 'pct_construction': '공사비 대비 %', 'pct_sales': '분양대금 대비 %',
         'pct_apt_sales': '공동주택 분양대금 대비 %', 'pct_total': '사업비 합계 대비 %', 'derived': '산출'}
KINDS = {'apartment': '공동주택', 'officetel': '오피스텔', 'retail': '상가·근생', 'office': '업무시설', 'knowledge': '지식산업센터', 'datacenter': '데이터센터', 'other': '기타'}


class Sheet:
    def __init__(self, ws, widths):
        self.ws, self.r = ws, 1
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.sheet_view.showGridLines = False

    def title(self, text, sub=''):
        c = self.ws.cell(self.r, 1, text)
        c.font = Font(size=16, bold=True, color=NAVY)
        if sub:
            self.ws.cell(self.r + 1, 1, sub).font = Font(size=9, color='627887')
            self.r += 1
        self.r += 2

    def section(self, text, span=8):
        c = self.ws.cell(self.r, 1, text)
        c.font = Font(bold=True, color='FFFFFF')
        for i in range(1, span + 1):
            self.ws.cell(self.r, i).fill = PatternFill('solid', fgColor=NAVY)
        self.r += 1

    def header(self, cols):
        for i, h in enumerate(cols, 1):
            c = self.ws.cell(self.r, i, h)
            c.font = Font(bold=True, color='435768')
            c.fill = PatternFill('solid', fgColor=SOFT)
            c.border = BORDER
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        self.r += 1

    def row(self, vals, fmts=None, bold=False, fill=None, color=None, indent=0):
        for i, v in enumerate(vals, 1):
            c = self.ws.cell(self.r, i, v)
            c.border = BORDER
            if fmts and i - 1 < len(fmts) and fmts[i - 1]:
                c.number_format = fmts[i - 1]
            if bold or color:
                c.font = Font(bold=bold, color=color or '142638')
            if fill:
                c.fill = PatternFill('solid', fgColor=fill)
            if i == 1 and indent:
                c.alignment = Alignment(indent=indent)
            if isinstance(v, str) and len(v) > 40:
                c.alignment = Alignment(wrap_text=True, vertical='top', indent=indent if i == 1 else 0)
        self.r += 1

    def status(self, col, st):
        label, (bg, fg) = STATUS[st]
        c = self.ws.cell(self.r - 1, col, label)
        c.fill = PatternFill('solid', fgColor=bg)
        c.font = Font(bold=True, color=fg)
        c.alignment = Alignment(horizontal='center')

    def gap(self, n=1):
        self.r += n


def build(p, r: dict) -> bytes:
    wb = Workbook()
    s, rev, a, cf = r['summary'], r['revenue'], r['area'], r.get('cashflow')
    v, comp = r['verdict'], r['compliance']
    eok = lambda x: None if x is None else x / 1e8
    tn = rev['total_net'] or 1
    sp = a['supply_py'] or 1

    # ① 사업수지분석표 ─────────────────────────
    sh = Sheet(wb.active, [30, 18, 12, 12, 14, 16, 16, 14])
    sh.ws.title = '사업수지분석표'
    sh.title(f"사업수지분석표 — {p.project_name}", f'작성일 {date.today().isoformat()} · 디벨로직 · 입력 가정 기반 추정 (확정 수지 아님)')
    sh.section('1. 사업 개요')
    loc = ' '.join(x for x in [p.site.province, p.site.municipality] if x) or '미입력'
    zones = ', '.join(f"{z['zone']} {z['area_sqm']:,.0f}㎡" for z in comp['zones']) or '미입력'
    sched = p.schedule
    for k, val, f in [
        ('사업 위치', loc, None), ('용도지역', zones, None),
        ('대지면적', f"{a['land_sqm']:,.1f}㎡ ({a['land_py']:,.1f}평)", None),
        ('지상 / 지하 연면적', f"{a['above_gfa_sqm']:,.1f}㎡ / {a['below_gfa_sqm']:,.1f}㎡ (계 {a['gfa_py']:,.1f}평)", None),
        ('용적률 (계획 / 허용)', f"{a['far_pct']:.2f}% / " + (f"{comp['allowed_gfa_sqm'] / a['land_sqm'] * 100:.2f}%" if comp['zones'] else '미확인'), None),
        ('세대·호수 (주거)', f"{a['units']:,} ({a['residential_units']:,})", None),
        ('분양(공급)면적', f"{a['supply_py']:,.1f}평", None),
        ('사업기간', f"{p.duration_months}개월" + (f" · 개시 {sched.start_month} · 준공 {cf['completion_month']} · 입주 {cf['move_in_month']}" if cf else ''), None),
        ('분양률 / 분양가 조정', f"{float(p.sales_rate_pct):g}% / {float(p.price_adjust_pct):+g}%", None),
    ]:
        sh.row([k, val], [None, f])
        sh.ws.merge_cells(start_row=sh.r - 1, start_column=2, end_row=sh.r - 1, end_column=8)
    sh.gap()

    sh.section('2. 사업타당성·적합성 판정')
    label, (bg, fg) = STATUS[v['overall']]
    sh.row(['종합 판정', v['label']], bold=True)
    sh.ws.merge_cells(start_row=sh.r - 1, start_column=2, end_row=sh.r - 1, end_column=7)
    sh.ws.cell(sh.r - 1, 8, label)
    sh.status(8, v['overall'])
    sh.header(['사업성 항목', '결과', '판정 기준', '', '', '', '', '판정'])
    for x in v['financial']:
        sh.row([x['name'], x['display'], x['rule']])
        sh.ws.merge_cells(start_row=sh.r - 1, start_column=3, end_row=sh.r - 1, end_column=7)
        sh.status(8, x['status'])
    sh.header(['법규 적합성 항목', '내용', '', '', '', '', '', '판정'])
    for x in v['legal']:
        sh.row([x['name'], x['detail']])
        sh.ws.merge_cells(start_row=sh.r - 1, start_column=2, end_row=sh.r - 1, end_column=7)
        sh.ws.row_dimensions[sh.r - 1].height = 30 if len(x['detail']) > 60 else 16
        sh.status(8, x['status'])
    sh.row([v['note']], color='627887')
    sh.ws.merge_cells(start_row=sh.r - 1, start_column=1, end_row=sh.r - 1, end_column=8)
    sh.gap()

    sh.section('3. 사업수지표')
    sh.header(['구분', '금액 (원)', '억원', '구성비', '매출 대비', '공급평당 (원)', '산정 기준', '비고'])
    fm = [None, WON, EOK, PCT, PCT, WON, None, None]
    sh.row(['Ⅰ. 매출 (부가세 제외)'], bold=True, fill='FBFDFF')
    for name, amt in [('분양수입', rev['sales_net']), ('발코니 확장', rev['balcony_cash'] - rev['balcony_vat']), ('기타 수입', rev['other_income'])]:
        if amt:
            sh.row([name, amt, eok(amt), None, amt / tn * 100, amt / sp], fm, indent=2)
    sh.row(['총매출', rev['total_net'], eok(rev['total_net']), None, 100, rev['total_net'] / sp], fm, bold=True, fill=SOFT)
    sh.row(['Ⅱ. 사업비'], bold=True, fill='FBFDFF')
    tc = s['total_cost'] or 1
    for c in r['costs']:
        sh.row([c['name'], c['amount'], eok(c['amount']), c['amount'] / tc * 100, c['amount'] / tn * 100, c['amount'] / sp], fm, bold=True)
        for it in c['items']:
            sh.row([it['name'], it['amount'], eok(it['amount']), it['amount'] / tc * 100, it['amount'] / tn * 100, it['amount'] / sp,
                    BASIS.get(it.get('basis'), '')], fm, indent=2)
    sh.row(['총사업비', s['total_cost'], eok(s['total_cost']), 100, s['total_cost'] / tn * 100, s['total_cost'] / sp], fm, bold=True, fill=SOFT)
    sh.row(['Ⅲ. 세전이익', s['pbt'], eok(s['pbt']), None, s['margin_pct'], s['pbt'] / sp], fm, bold=True, fill='DCEBF8')
    sh.row(['법인세·지방소득세', -s['corporate_tax'], eok(-s['corporate_tax']), None, -s['corporate_tax'] / tn * 100, None, s.get('tax_method', '')], fm, indent=2)
    sh.row(['Ⅳ. 세후이익', s['npat'], eok(s['npat']), None, s['npat'] / tn * 100, s['npat'] / sp], fm, bold=True, fill='DCEBF8')
    sh.gap()

    sh.section('4. 핵심 지표')
    kp = [('매출이익률 (세전)', s['margin_pct'], PCT), ('원가율', s['cost_to_revenue_pct'], PCT),
          ('BEP 분양률', s['bep_sales_rate_pct'], PCT),
          ('분양가 하락 허용폭', -s['price_drop_tolerance_pct'] if s.get('price_drop_tolerance_pct') is not None else None, PCT),
          ('Equity IRR (세후, 연)', s.get('equity_irr_pct'), PCT), ('사업 IRR (무차입, 세후, 연)', s.get('project_irr_pct'), PCT),
          ('Equity Multiple', s.get('equity_multiple'), '0.00"배"'), ('ROE (세후이익/자기자본)', s['roe_pct'], PCT),
          ('LTC (대출/총사업비)', s['ltc_pct'], PCT), ('최대 대출잔액', s.get('peak_loan'), WON),
          ('추가 자기자본 필요', s.get('extra_equity'), WON), ('평균 분양가 (공급평당)', rev['sales_cash'] / sp, WON),
          ('총사업비 (공급평당)', s['cost_per_supply_py'], WON), ('토지비 (대지평당)', s['land_per_py'], WON),
          ('공사비 (연면적평당)', s['construction_per_gfa_py'], WON)]
    for i in range(0, len(kp), 2):
        vals, fmts = [], []
        for k, val, f in kp[i:i + 2]:
            vals += [k, val, '', '']
            fmts += [None, f, None, None]
        sh.row(vals, fmts)
    sh.row([r['notice']], color='627887')
    sh.ws.merge_cells(start_row=sh.r - 1, start_column=1, end_row=sh.r - 1, end_column=8)

    # ② 분양수입 ─────────────────────────
    sh = Sheet(wb.create_sheet('분양수입'), [14, 12, 10, 10, 9, 12, 16, 18, 16, 18])
    sh.title('타입별 분양수입', f"분양률 {float(p.sales_rate_pct):g}% · 분양가 조정 {float(p.price_adjust_pct):+g}% · 분양가 부가세 {'포함' if p.price_includes_vat else '별도'} · 과세분 건물가 비율 {float(p.building_ratio_pct):g}%")
    sh.header(['타입', '구분', '전용㎡', '공급㎡', '세대', '공급평 합계', '세대당 분양가', '분양대금 (VAT 포함)', '부가세', '공급가액'])
    for x in rev['rows']:
        sh.row([x['name'], KINDS[x['kind']] + (' (과세)' if x['taxable'] else ' (면세)'), x['exclusive_sqm'], x['supply_sqm'], x['count'],
                x['supply_py_total'], x['unit_price'], x['cash'], x['vat'], x['net']],
               [None, None, '0.00', '0.00', '#,##0', '#,##0.0', WON, WON, WON, WON])
    if rev['balcony_cash']:
        sh.row(['발코니 확장', '공동주택', None, None, None, None, None, rev['balcony_cash'], rev['balcony_vat'], rev['balcony_cash'] - rev['balcony_vat']],
               [None] * 7 + [WON] * 3)
    sh.row(['합계', '', None, None, a['units'], a['supply_py'], None, rev['total_cash'] - rev['other_income'], rev['total_vat'],
            rev['total_net'] - rev['other_income']], [None, None, None, None, '#,##0', '#,##0.0', None, WON, WON, WON], bold=True, fill=SOFT)

    # ③ 사업비 상세 ─────────────────────────
    sh = Sheet(wb.create_sheet('사업비 상세'), [16, 26, 22, 16, 18, 10, 30])
    sh.title('사업비 상세', '산정 기준 · 입력값 · 산출액')
    sh.header(['분류', '항목', '산정 기준', '입력값', '산출 금액', '구성비', '비고'])
    inputs = {(c.category, c.name): c for c in p.costs}
    for c in r['costs']:
        for it in c['items']:
            src = inputs.get((it['category'], it['name']))
            sh.row([c['name'], it['name'], BASIS.get(it.get('basis'), ''), it.get('value'), it['amount'], it['amount'] / tc * 100,
                    src.note if src else ''],
                   [None, None, None, '#,##0.##', WON, PCT])
    sh.row(['', '총사업비', '', None, s['total_cost'], 100], [None, None, None, None, WON, PCT], bold=True, fill=SOFT)

    # ④ 월별 현금흐름 ─────────────────────────
    if cf:
        cols = [('month', '연월'), ('phase', '단계'), ('progress_cum', '누적 공정률'), ('deposit', '계약금'), ('midpay', '중도금'),
                ('balance_pay', '잔금'), ('other_income', '기타수입'), ('cost_land', '토지비'), ('cost_construction', '공사비'),
                ('cost_indirect', '설계·감리'), ('cost_charges', '부담금'), ('cost_sales', '분양·판매'), ('cost_taxes', '제세공과'),
                ('cost_admin', '일반관리'), ('cost_contingency', '예비비'), ('vat_input', '매입세액'), ('vat_paid', '부가세 납부(환급)'),
                ('corporate_tax', '법인세'), ('local_tax', '지방소득세'), ('midpay_interest', '중도금이자'), ('midpay_recovery', '중도금이자 회수'),
                ('interest', 'PF·브릿지 이자'),
                ('fees', '취급수수료'), ('equity_in', '자기자본'), ('extra_equity', '추가 자기자본'), ('draw', '대출 인출'),
                ('repay', '대출 상환'), ('loan_balance', '대출 잔액'), ('cash', '월말 현금')]
        sh = Sheet(wb.create_sheet('월별 현금흐름'), [9, 10, 9] + [14] * (len(cols) - 3))
        sh.title('월별 현금흐름', f"금액 단위: 원 · 공정률 {p.schedule.curve} · 계약금 {float(p.schedule.deposit_pct):g}% / 중도금 {float(p.schedule.midpay_pct):g}% ({p.schedule.midpay_installments}회: {', '.join(cf['installment_months'])}) / 잔금")
        sh.header([c[1] for c in cols])
        fmts = [None, None, '0.0%'] + [WON] * (len(cols) - 3)
        for row in cf['rows']:
            sh.row([row[k] for k, _ in cols], fmts, fill='FFF1E6' if row['extra_equity'] else None)
        tot = ['합계', '', None] + [sum(x[k] for x in cf['rows']) if k not in ('loan_balance', 'cash') else None for k, _ in cols[3:]]
        sh.row(tot, fmts, bold=True, fill=SOFT)
        sh.ws.freeze_panes = 'D5'

        # ⑤ 금융·세금
        sh = Sheet(wb.create_sheet('금융·세금'), [22, 18, 18, 18, 18, 16, 12, 12, 12])
        sh.title('금융비용 · 세금', '월 이자 = 월초 잔액 × 연 금리/12 · 취급수수료 = 한도 × 수수료율 (개시월)')
        sh.section('대출별 금융비용', 9)
        sh.header(['대출', '약정 한도', '인출 누계', '최대 잔액', '이자', '수수료', '인출률', '개시', '만기'])
        for l in cf['loans']:
            sh.row([l['name'], l['limit'], l['drawn'], l['peak'], l['interest'], l['fees'], (l['utilization'] or 0), l['start'], l['end']],
                   [None, WON, WON, WON, WON, WON, '0.0%'])
        sh.row(['중도금 대출이자 (시행사 부담)', None, None, None, cf['midpay_interest_total']], [None, None, None, None, WON])
        sh.row(['금융비용 합계', None, None, None, cf['finance_total']], [None, None, None, None, WON], bold=True, fill=SOFT)
        sh.gap()
        sh.section('법인세 (진행기준 · 법인세법 시행령 제69조 예약매출)', 9)
        sh.header(['사업연도', '작업진행률', '계약 누계', '익금(분양수익)', '분양원가 손금', '판관비·금융비용', '과세표준', '법인세', '납부월'])
        for t in cf['tax_years']:
            sh.row([t['year'], t['progress'], t['contracted'], t['revenue_recognized'], t['cost_recognized'], t['period_cost'] + t['finance_cost'],
                    t['tax_base'], t['corporate_tax'], t['pay_month']], [None, '0.0%', '0.0%', WON, WON, WON, WON, WON])
        sh.row(['합계 (지방소득세 포함)', None, None, None, None, None, None, cf['corporate_tax_total'] + cf['local_tax_total']],
               [None] * 7 + [WON], bold=True, fill=SOFT)
        if cf.get('unused_nol'):
            sh.row([f"미사용 이월결손금 {cf['unused_nol']:,}원 (사업 종료로 공제 불가)"], color='B4530B')
        sh.row(['부가세: 매출세액·매입세액(과세분 공사·용역비) 분기 신고 정산, 국민주택 건설용역 면세(조특법 제106조)'], color='627887')

    # ⑥ 법규 검토 — 셀 너비에 맞춰 줄바꿈 · 행 높이 자동 계산
    W = [18, 11, 9, 9, 30, 12, 62]
    sh = Sheet(wb.create_sheet('법규 검토'), W)
    sh.title('법규 검토', '국가법령정보센터 기준 · 국토계획법 시행령 → 지자체 조례 → 검토자 등록 순으로 우선 적용')
    ws = sh.ws

    def lines(text, width):
        """셀 너비(문자 단위)에 들어가는 줄 수 — 한글은 약 1.9칸, 영문·숫자 1칸."""
        n = 0
        for part in str(text or '').split('\n'):
            w = sum(1.9 if ord(ch) > 0x2E80 else 1.0 for ch in part)
            n += max(1, -(-int(w * 1.08) // max(1, int(width - 1))))
        return n

    def put(vals, fmts=(), color='142638', merge=None, center=(), link=None):
        r = sh.r
        widths = list(W)
        if merge:
            a, b = merge
            widths[a - 1] = sum(W[a - 1:b])
        h = 1
        for i, v in enumerate(vals, 1):
            c = ws.cell(r, i, v)
            c.border = BORDER
            c.font = Font(size=10, color=color)
            if i - 1 < len(fmts) and fmts[i - 1]:
                c.number_format = fmts[i - 1]
            num = isinstance(v, (int, float)) and not isinstance(v, bool)
            c.alignment = Alignment(horizontal='center' if i in center else 'right' if num else 'left',
                                    vertical='center', wrap_text=not num, indent=0 if num or i in center else 1)
            if isinstance(v, str) and v:
                h = max(h, lines(v, widths[i - 1]))
        if merge:
            for i in range(merge[0] + 1, merge[1] + 1):
                ws.cell(r, i).border = BORDER
            ws.merge_cells(start_row=r, start_column=merge[0], end_row=r, end_column=merge[1])
        if link:
            col, url = link
            c = ws.cell(r, col)
            c.hyperlink = url
            c.font = Font(size=10, color=BLUE, underline='single')
        ws.row_dimensions[r].height = max(20, 15 * h + 6)
        sh.r += 1

    def head(cols, merge=None):
        r = sh.r
        for i, t in enumerate(cols, 1):
            c = ws.cell(r, i, t)
            c.font = Font(bold=True, size=10, color='435768')
            c.fill = PatternFill('solid', fgColor=SOFT)
            c.border = BORDER
            c.alignment = Alignment(horizontal='center', vertical='center')
        if merge:
            ws.merge_cells(start_row=r, start_column=merge[0], end_row=r, end_column=merge[1])
        ws.row_dimensions[r].height = 22
        sh.r += 1

    head(['용도지역', '면적 ㎡', '건폐율', '용적률', '근거', '시행일', '참고'])
    LV = {'registered': '검토자 등록', 'ordinance': '조례(원문 대조)', 'auto': '조례(자동 판독)', 'national': '시행령 상한(조례 미확인)', 'none': '근거 없음'}
    for z in comp['zones']:
        src = z['source'] or {}
        basis = LV[z['level']] + (f"\n{src.get('title')}" if src.get('title') else '')
        put([z['zone'], z['area_sqm'], z['bcr'], z['far'], basis, src.get('effective') or '',
             '\n'.join(z['notes']) if z['notes'] else ''], [None, '#,##0.0', '0"%"', '0"%"'], center=(6,))
        if src.get('url'):
            put(['', '', '', '', '원문 보기 ↗', '', src['url']], color='627887', link=(5, src['url']), center=(6,))
        if z.get('far_text'):
            put(['', '', '', '', '조문 (용적률)', '', z['far_text']], color='627887', center=(6,))
    if comp['parking']:
        pk = comp['parking']
        sh.gap()
        head(['주차', '대수', '', '', '산정 기준', '시행일', '참고'])
        put(['법정 주차대수', pk['required'], '', '', f"{pk['region']}\n{pk['ratio']}", pk['source']['effective'] or '', pk['note']], [None, '#,##0'], center=(6,))
        for prow in pk.get('rows', []):   # 용도별 산정 내역 (r 은 분석 결과라 다른 이름을 쓴다)
            put(['  ' + prow['use'], prow['spaces'], '', '', f"{prow['basis']}\n{prow['rule']}".strip(), '', prow.get('detail') or ''], [None, '#,##0.0'], center=(6,))
    sh.gap()
    head(['검토 항목', '내용', '', '', '', '', '판정'], merge=(2, 6))
    for x in comp['items']:
        put([x['name'], x['detail'], '', '', '', '', ''], merge=(2, 6))
        label, (bg, fg) = STATUS[x['status']]
        c = ws.cell(sh.r - 1, 7, label)
        c.fill = PatternFill('solid', fgColor=bg)
        c.font = Font(bold=True, size=10, color=fg)
        c.alignment = Alignment(horizontal='center', vertical='center')
    ws.freeze_panes = 'A4'

    # ⑦ 민감도
    sv = r['sensitivity']
    sh = Sheet(wb.create_sheet('민감도'), [18] + [14] * len(sv['sales_rates']))
    sh.title('민감도 분석', '분양가 조정 × 분양률 → 매출이익률 / 세전이익(억원)')
    for label, key, f in [('매출이익률', 'margin', '0.0%'), ('세전이익 (억원)', 'pbt', '#,##0;[Red]-#,##0')]:
        sh.section(label, len(sv['sales_rates']) + 1)
        sh.header(['분양가 \\ 분양률'] + [f'{x:g}%' for x in sv['sales_rates']])
        for i, rowc in enumerate(sv['cells']):
            vals = [f"{sv['price_adjusts'][i]:+g}%"] + [(c['margin'] if key == 'margin' else c['pbt'] / 1e8) for c in rowc]
            sh.row(vals, [None] + [f] * len(rowc))
            for j, c in enumerate(rowc, 2):
                m = c['margin']
                bg = 'FFD8D3' if m is None or m < 0 else 'FFF1D6' if m < .05 else 'E3F0FB' if m < .10 else 'B9DCF5'
                sh.ws.cell(sh.r - 1, j).fill = PatternFill('solid', fgColor=bg)
        sh.gap()
    if s['bep_sales_rate_pct'] is not None:
        sh.row([f"BEP 분양률 {s['bep_sales_rate_pct']:.1f}%", '', '', f"분양가 하락 허용폭 {(-s['price_drop_tolerance_pct'] if s.get('price_drop_tolerance_pct') is not None else 0):.1f}%"], bold=True)

    R = r.get('rental')
    if R:
        sh = Sheet(wb.create_sheet('임대 운영', 1), [14] + [15] * 10)
        sh.title('공공지원민간임대 운영 · 매각', ' / '.join(R.get('notes', [])))
        sh.section('자본 구조 (준공 시)', 11)
        for k, v in [('총사업비 (건설이자 포함)', R['total_cost']), ('임대보증금', R['deposit_total']), ('주택도시기금 융자', R['fund_loan']),
                     ('준공 후 담보대출', R['mortgage']), ('자기자본', R['equity'])]:
            sh.row([k, v], [None, WON])
        sh.gap()
        sh.section('연도별 현금흐름 (원)', 11)
        cols = [('year', '연차'), ('rent', '임대수입'), ('deposit_increase', '보증금 증액'), ('opex', '운영비'), ('property_tax', '보유세'),
                ('guarantee_fee', '보증료'), ('noi', 'NOI'), ('interest', '이자'), ('dscr', 'DSCR'), ('tax', '법인세'), ('cash_flow', '자기자본 CF')]
        sh.header([c[1] for c in cols])
        for x in R['rows']:
            sh.row([x[k] for k, _ in cols], [None] + [WON] * 7 + ['0.00'] + [WON, WON])
        sh.row(['매각', R['exit_value'], None, None, None, None, None, None, None, R['exit_gain_tax'], R['exit_net_to_equity']],
               [None, WON] + [None] * 7 + [WON, WON], bold=True, fill=SOFT)
        sh.gap()
        for k, v, f in [('임대수익률 (1년차)', R['yield_on_cost_pct'], PCT), ('최저 DSCR', R['min_dscr'], '0.00"배"'),
                        ('Equity IRR', R['equity_irr_pct'], PCT), ('Equity Multiple', R['equity_multiple'], '0.00"배"')]:
            sh.row([k, v], [None, f])
        sh.row([' / '.join(R.get('sources', []))], color='627887')

    for ws in wb.worksheets:
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
