"""월별 현금흐름 Excel (보기 좋은 형식).

① 월별 현금흐름: 2단 머리글(유입·유출·결과), 백만원 표시(셀 값은 원 단위 그대로), 단계별 색, 합계 행, 틀 고정
② 상세 (원 단위): 항목별 전체 열
월말 현금 = 전월 월말 현금 + 유입 합계 − 유출 합계 (원 단위 반올림 값으로 누적 → 행마다 정확히 일치)
"""
import io
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY, SOFT = '111A2E', 'F4F8FA'
thin = Side(style='thin', color='D5DEE4')
BORDER = Border(top=thin, bottom=thin, left=thin, right=thin)
MIL = '#,##0,,;[Red]-#,##0,,;"-"'      # 백만원 표시 (값은 원)
WON = '#,##0;[Red]-#,##0;"-"'
PHASE_FILL = {'토지·인허가': 'F4F8FA', '공사': 'FFFFFF', '준공': 'EEF6FD', '입주·잔금': 'E6F4EA', '정산·세금': 'FBF7EF'}


def _n(v):
    return int(round(v or 0))


def _month(m):
    return f'{m[:4]}년 {m[5:]}월'


GROUPS = [
    ('유입', 'E3F0FB', [
        ('계약금', lambda x: _n(x['deposit'])),
        ('중도금', lambda x: _n(x['midpay'])),
        ('잔금', lambda x: _n(x['balance_pay'])),
        ('기타 수입', lambda x: _n(x['other_income']) + _n(x.get('midpay_recovery'))),
        ('자기자본', lambda x: _n(x['equity_in']) + _n(x['extra_equity'])),
        ('대출 인출', lambda x: _n(x['draw'])),
    ]),
    ('유출', 'FFF1E6', [
        ('토지비', lambda x: _n(x['cost_land'])),
        ('공사비', lambda x: _n(x['cost_construction'])),
        ('기타 사업비', lambda x: sum(_n(x['cost_' + k]) for k in ('indirect', 'charges', 'sales', 'taxes', 'admin', 'contingency'))),
        ('부가세', lambda x: _n(x['vat_input']) + _n(x['vat_paid'])),
        ('법인세 등', lambda x: _n(x['corporate_tax']) + _n(x['local_tax'])),
        ('금융비용', lambda x: _n(x['midpay_interest']) + _n(x['interest']) + _n(x['fees']) + _n(x.get('cost_finance', 0))),
        ('대출 상환', lambda x: _n(x['repay'])),
    ]),
]

DETAIL = [('계약금', 'deposit'), ('중도금', 'midpay'), ('잔금', 'balance_pay'), ('기타 수입', 'other_income'), ('중도금이자 회수', 'midpay_recovery'),
          ('자기자본 투입', 'equity_in'), ('추가 자기자본', 'extra_equity'), ('대출 인출', 'draw'),
          ('토지비', 'cost_land'), ('공사비', 'cost_construction'), ('설계·감리·용역비', 'cost_indirect'), ('부담금·인입비', 'cost_charges'),
          ('분양·판매비', 'cost_sales'), ('제세공과금', 'cost_taxes'), ('일반관리비', 'cost_admin'), ('예비비', 'cost_contingency'), ('금융비(수수료·신탁 등)', 'cost_finance'),
          ('매입세액', 'vat_input'), ('부가세 납부(−환급)', 'vat_paid'), ('법인세', 'corporate_tax'), ('지방소득세', 'local_tax'),
          ('중도금 대출이자', 'midpay_interest'), ('PF·브릿지 이자', 'interest'), ('취급수수료', 'fees'), ('대출 상환', 'repay'),
          ('대출 잔액', 'loan_balance'), ('(참고) 매출세액 발생', 'vat_out')]


def _width(text, minimum=8):
    """한글은 2칸, 나머지 1칸으로 계산한 열 너비."""
    w = sum(2 if '가' <= ch <= '힣' or ch in '【】·−' else 1 for ch in str(text))
    return max(minimum, w + 2)


def build(p, r: dict) -> bytes:
    cf = r['cashflow']
    rows = cf['rows']
    wb = Workbook()
    ws = wb.active
    ws.title = '월별 현금흐름'
    ws.sheet_view.showGridLines = False
    ws['A1'] = f'월별 현금흐름 — {p.project_name}'
    ws['A1'].font = Font(size=15, bold=True, color=NAVY)
    ws['A2'] = ('표시 단위: 백만원 (셀 값은 원 단위 — 셀을 누르면 정확한 금액) · 월말 현금 = 전월 월말 현금 + 유입 합계 − 유출 합계 · '
                f"준공 {cf['completion_month']} · 입주 {cf['move_in_month']}")
    ws['A2'].font = Font(size=9, color='627887')
    h1, h2 = 4, 5
    heads = ['연월', '단계', '누적 공정률']
    spans, col = [], 4
    for gname, color, items in GROUPS:
        start = col
        heads += [name for name, _ in items] + [f'{gname} 합계']
        col += len(items) + 1
        spans.append((f'【{gname}】', start, col - 1, color))
    heads += ['순현금흐름', '월말 현금', '대출 잔액']
    spans.append(('【결과】', col, col + 2, 'DCEBF8'))
    last = len(heads)
    for c, name in enumerate(heads, 1):
        ws.cell(h2, c, name)
    for c in (1, 2, 3):
        ws.cell(h1, c, heads[c - 1])
        ws.merge_cells(start_row=h1, start_column=c, end_row=h2, end_column=c)
    for title, a, b, color in spans:
        ws.cell(h1, a, title)
        ws.merge_cells(start_row=h1, start_column=a, end_row=h1, end_column=b)
        for c in range(a, b + 1):
            ws.cell(h1, c).fill = PatternFill('solid', fgColor=color)
    for rr in (h1, h2):
        for c in range(1, last + 1):
            cell = ws.cell(rr, c)
            cell.font = Font(bold=True, color=NAVY)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = BORDER
            if rr == h2 or c <= 3:
                cell.fill = PatternFill('solid', fgColor=SOFT)
    ws.row_dimensions[h2].height = 22
    sum_cols = {b for _, a, b, _ in spans[:2]}
    run, totals, rr = 0, [0] * (last + 1), h2 + 1
    for x in rows:
        vals = [_month(x['month']), x['phase'], x['progress_cum']]
        flows = {}
        for gname, _, items in GROUPS:
            part = [fn(x) for _, fn in items]
            flows[gname] = sum(part)
            vals += part + [flows[gname]]
        net = flows['유입'] - flows['유출']
        run += net
        vals += [net, run, _n(x['loan_balance'])]
        fill = PatternFill('solid', fgColor=PHASE_FILL.get(x['phase'], 'FFFFFF'))
        for c, v in enumerate(vals, 1):
            cell = ws.cell(rr, c, v)
            cell.border = BORDER
            cell.fill = fill
            if c == 3:
                cell.number_format = '0.0%'
                cell.alignment = Alignment(horizontal='right')
            elif c > 3:
                cell.number_format = MIL
                if c < last - 1:
                    totals[c] += v
            if c in sum_cols or c == last - 1:
                cell.font = Font(bold=True)
        rr += 1
    ws.cell(rr, 1, '합계')
    for c in range(4, last + 1):
        ws.cell(rr, c, totals[c] if c < last - 1 else (run if c == last - 1 else _n(rows[-1]['loan_balance']))).number_format = MIL
    for c in range(1, last + 1):
        cell = ws.cell(rr, c)
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='DCEBF8')
        cell.border = BORDER
    # 글자가 잘리지 않도록 열 너비: 머리글·값 중 가장 긴 것 기준
    for c in range(1, last + 1):
        longest = max([_width(heads[c - 1])] + [_width(f'{int(ws.cell(k, c).value) // 1_000_000:,}', 6)
                                                for k in range(h2 + 1, rr + 1) if c > 3 and isinstance(ws.cell(k, c).value, (int, float))])
        ws.column_dimensions[get_column_letter(c)].width = max(longest, {1: 13, 2: 13, 3: 11}.get(c, 10))
    ws.freeze_panes = ws.cell(h2 + 1, 4)
    ws.page_setup.orientation = 'landscape'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0

    # ② 상세 (원 단위)
    ds = wb.create_sheet('상세 (원 단위)')
    ds.sheet_view.showGridLines = False
    ds['A1'] = '월별 현금흐름 상세 (원)'
    ds['A1'].font = Font(size=15, bold=True, color=NAVY)
    ds['A2'] = '유입 8개 − 유출 16개 항목 = 순현금흐름 · 매출세액은 분기 신고 때 「부가세 납부」로 나가므로 현금 유출이 아님 (참고용)'
    ds['A2'].font = Font(size=9, color='627887')
    dh = ['연월', '단계', '누적 공정률'] + [d[0] for d in DETAIL]
    for c, name in enumerate(dh, 1):
        cell = ds.cell(4, c, name)
        cell.font = Font(bold=True, color=NAVY)
        cell.fill = PatternFill('solid', fgColor=SOFT)
        cell.border = BORDER
        cell.alignment = Alignment(horizontal='center', vertical='center')
    for i, x in enumerate(rows, 5):
        vals = [_month(x['month']), x['phase'], x['progress_cum']] + [_n(x.get(k)) for _, k in DETAIL]
        for c, v in enumerate(vals, 1):
            cell = ds.cell(i, c, v)
            cell.border = BORDER
            cell.number_format = '0.0%' if c == 3 else WON if c > 3 else 'General'
    for c, name in enumerate(dh, 1):
        vals = [ds.cell(k, c).value for k in range(5, 5 + len(rows))]
        longest = max([_width(name)] + [_width(f'{v:,}' if isinstance(v, int) else v, 6) for v in vals if v is not None and c != 3])
        ds.column_dimensions[get_column_letter(c)].width = longest
    ds.freeze_panes = 'D5'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
