"""운영형 개발사업 사업수지 (호텔 + 운영·임대 상업시설: 개발 → 보유·운영 → 매각).

개발비(사업비 + 건설기간 금융비) → 준공 시 자본구조(자기자본·대출 유지 또는 담보대출 전환)
→ 연 단위 운영(호텔 USALI 손익 + 운영사업·임대 라인 → NOI·DSCR·법인세) → 보유기간 말 환원율 매각 순으로 계산한다.
연 단위 흐름의 0년차 = 개발 1년차, 운영 1년차 = dev_years 번째 해. 연차별 리스트 입력은 리스트보다 긴 연차에 마지막 값을 유지한다(램프업 후 안정화).
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from pydantic import BaseModel, Field

from .rental import _tax, eok

D = Decimal
ZERO = D(0)
YearList = list[Decimal]   # 연차별 값 (리스트보다 긴 연차는 마지막 값 유지)


def pick(lst, i: int) -> Decimal:
    return lst[min(i, len(lst) - 1)] if lst else ZERO


class UndistItem(BaseModel):
    name: str = Field(min_length=1)
    pct_by_year: YearList = Field(default_factory=lambda: [ZERO], description='총매출 대비 % (연차별)')


def _default_undist() -> list[UndistItem]:
    return [UndistItem(name='관리 (A&G)', pct_by_year=[D(8)]), UndistItem(name='영업 (S&M)', pct_by_year=[D(5)]),
            UndistItem(name='수선유지 (R&M)', pct_by_year=[D(4)]), UndistItem(name='수도광열 (Utility)', pct_by_year=[D(4)])]


class HotelPlan(BaseModel):
    """호텔 운영 손익 (USALI: 부서이익 → 비배분비용 → GOP → 운영수수료 → NOI)."""
    enabled: bool = Field(default=True, description='호텔 포함 여부')
    rooms: int = Field(default=0, ge=0, le=10000, description='객실 수')
    days: int = Field(default=365, ge=1, le=366, description='연 영업일')
    occupancy_pct_by_year: YearList = Field(default_factory=lambda: [D(65), D(70), D(75)], description='객실 점유율 % (연차별)')
    adr_year1: Decimal = Field(default=D(120000), ge=0, description='1년차 객실 평균 판매단가 ADR (원)')
    adr_growth_pct: Decimal = Field(default=D(2), ge=-20, le=30, description='ADR 연 상승률')
    round_sold_rooms: bool = Field(default=True, description='판매 객실수 정수 반올림')
    room_other_pct: Decimal = Field(default=D(3), ge=0, le=100, description='기타 객실매출 (객실매출 대비 %)')
    fnb_pct_of_room_by_year: YearList = Field(default_factory=lambda: [D(20)], description='식음(F&B) 매출 (객실매출 대비 %, 연차별)')
    other_revenue_pct_of_room: Decimal = Field(default=ZERO, ge=0, le=200, description='부대(기타) 매출 (객실매출 대비 %)')
    rooms_cost_pct_by_year: YearList = Field(default_factory=lambda: [D(25)], description='객실 부서비용 (객실매출 대비 %, 연차별)')
    room_other_cost_pct: Decimal = Field(default=D(30), ge=0, le=200, description='기타 객실 부서비용 (기타객실매출 대비 %)')
    fnb_cost_pct: Decimal = Field(default=D(75), ge=0, le=200, description='식음 부서비용 (F&B 매출 대비 %)')
    other_cost_pct: Decimal = Field(default=D(50), ge=0, le=200, description='부대 매출 부서비용 (부대매출 대비 %)')
    undistributed: list[UndistItem] = Field(default_factory=_default_undist, description='비배분비용 (총매출 대비 %)')
    base_fee_pct: Decimal = Field(default=D('2.5'), ge=0, le=20, description='기본 운영수수료 (총매출 대비 %)')
    incentive_fee_pct: Decimal = Field(default=D(6), ge=0, le=30, description='인센티브 수수료 (Adjusted GOP 대비 %)')
    insurance_pct: Decimal = Field(default=D(1), ge=0, le=10, description='보험료 (총매출 대비 %)')
    ffe_reserve_pct: Decimal = Field(default=D(3), ge=0, le=10, description='FF&E 적립금 (총매출 대비 %)')


class OperatingLine(BaseModel):
    """호텔 외 운영 라인 — business: 직영 운영사업(전시장·박물관 등), lease: 임대(상가·오피스)."""
    name: str = Field(min_length=1)
    kind: Literal['business', 'lease'] = 'business'
    revenue_year1: Decimal = Field(default=ZERO, ge=0, description='운영사업: 1년차 매출 (원)')
    cost_pct: Decimal = Field(default=D(60), ge=0, le=200, description='운영사업: 매출 대비 운영비 %')
    area_py: Decimal = Field(default=ZERO, ge=0, description='임대: 임대면적 (평)')
    rent_per_py_month: Decimal = Field(default=ZERO, ge=0, description='임대: 평당 월임대료 (원)')
    occupancy_pct: Decimal = Field(default=D(95), ge=0, le=100, description='임대: 임대율 %')
    opex_pct: Decimal = Field(default=D(10), ge=0, le=100, description='임대: 임대수입 대비 운영비 % (관리·공실·수선)')
    growth_pct: Decimal = Field(default=D(2), ge=-20, le=30, description='매출·비용 연 성장률')
    start_year: int = Field(default=1, ge=1, le=40, description='운영 개시 연차')


class OperatingPlan(BaseModel):
    hold_years: int = Field(default=10, ge=1, le=40, description='보유·운영 기간 (년)')
    dev_years: int = Field(default=3, ge=1, le=10, description='개발 기간 (년, 운영 전)')
    cost_split_pct_by_year: YearList = Field(default_factory=lambda: [D(20), D(40), D(40)],
                                             description='총사업비 연도별 집행 비율 % (개발 연차, 합계로 정규화 · 무차입 IRR)')
    equity_split_pct_by_year: YearList = Field(default_factory=lambda: [D(100)],
                                               description='자기자본 연도별 투입 비율 % (개발 연차, 합계로 정규화)')
    hotel: HotelPlan = Field(default_factory=HotelPlan)
    lines: list[OperatingLine] = Field(default_factory=list, description='운영사업·임대 라인')
    property_tax_year1: Decimal = Field(default=ZERO, ge=0, description='운영기 1년차 보유세 (재산세·종부세, 원)')
    property_tax_growth_pct: Decimal = Field(default=D(2), ge=-20, le=30, description='보유세 연 증가율')
    debt_mode: Literal['carry', 'refinance'] = Field(
        default='carry', description='carry: 건설 대출을 운영기간에도 각 금리로 이자만 상환 · 매각 시 원금 상환 / refinance: 준공 시 (총사업비 − 자기자본) 담보대출로 전환')
    refi_rate_pct: Decimal = Field(default=D('4.5'), ge=0, le=20, description='전환 담보대출 금리')
    refi_amort_years: int = Field(default=0, ge=0, le=40, description='담보대출 원금 균등분할 상환 연수 (0 = 만기일시)')
    exit_cap_pct: Decimal = Field(default=D(6), gt=0, le=30, description='매각 환원율 (Cap rate)')
    exit_noi_basis: Literal['trailing', 'forward'] = Field(default='trailing', description='매각 NOI: 보유 마지막 해(trailing) / 다음 해(forward)')
    sale_cost_pct: Decimal = Field(default=D(1), ge=0, le=10, description='매각 비용 (매각가 대비 %)')
    valuation_cap_pct: Decimal = Field(default=D(6), gt=0, le=30, description='준공 시점 가치평가 환원율 (1년차 NOI 기준)')
    building_ratio_pct: Decimal = Field(default=D(60), ge=0, le=100, description='총사업비 중 건물분 (감가상각)')
    depreciation_years: int = Field(default=40, ge=5, le=60)
    discount_rate_pct: Decimal = Field(default=D(7), ge=0, le=30, description='지분 NPV 할인율')
    yield_min_pct: Decimal = Field(default=D(6), description='판정: Yield on Cost 기준')
    dscr_min: Decimal = Field(default=D('1.2'), description='판정: 최저 DSCR 기준')
    irr_min_pct: Decimal = Field(default=D(8), description='판정: Equity IRR 기준')


def _split(lst: list, n: int) -> list[Decimal]:
    """개발 연차별 비율 → 합계 1 로 정규화 (개발기간보다 긴 값은 버림, 비어 있으면 균등)."""
    v = [D(x) for x in lst[:n]] + [ZERO] * max(0, n - len(lst))
    s = sum(v, ZERO)
    return [x / s for x in v] if s > 0 else [D(1) / n] * n


def _hotel_year(h: HotelPlan, i: int) -> dict:
    zero = {k: ZERO for k in ('avail', 'sold', 'adr', 'room_rev', 'room_other_rev', 'fnb_rev', 'other_rev', 'hotel_revenue', 'dept_cost',
                              'undistributed', 'gop', 'base_fee', 'agop', 'incentive_fee', 'insurance', 'ffe_reserve', 'hotel_noi')}
    occ = pick(h.occupancy_pct_by_year, i)
    zero['occupancy_pct'] = occ if h.enabled and h.rooms else ZERO
    if not h.enabled or not h.rooms:
        return zero
    avail = D(h.rooms * h.days)
    sold = avail * occ / 100
    if h.round_sold_rooms:
        sold = sold.quantize(D(1), rounding=ROUND_HALF_UP)   # 엑셀 ROUND(, 0)
    adr = h.adr_year1 * (1 + h.adr_growth_pct / 100) ** i
    room = sold * adr
    room_other = room * h.room_other_pct / 100
    fnb = room * pick(h.fnb_pct_of_room_by_year, i) / 100
    other = room * h.other_revenue_pct_of_room / 100
    revenue = room + room_other + fnb + other
    dept = (room * pick(h.rooms_cost_pct_by_year, i) + room_other * h.room_other_cost_pct + fnb * h.fnb_cost_pct + other * h.other_cost_pct) / 100
    undist = revenue * sum((pick(u.pct_by_year, i) for u in h.undistributed), ZERO) / 100
    gop = revenue - dept - undist
    base_fee = revenue * h.base_fee_pct / 100
    agop = gop - base_fee
    incentive = max(agop, ZERO) * h.incentive_fee_pct / 100
    insurance = revenue * h.insurance_pct / 100
    ffe = revenue * h.ffe_reserve_pct / 100
    return {'occupancy_pct': occ, 'avail': avail, 'sold': sold, 'adr': adr, 'room_rev': room, 'room_other_rev': room_other, 'fnb_rev': fnb,
            'other_rev': other, 'hotel_revenue': revenue, 'dept_cost': dept, 'undistributed': undist, 'gop': gop, 'base_fee': base_fee,
            'agop': agop, 'incentive_fee': incentive, 'insurance': insurance, 'ffe_reserve': ffe,
            'hotel_noi': agop - incentive - insurance - ffe}


def _line_year(l: OperatingLine, i: int) -> dict:
    y = i + 1
    if y < l.start_year:
        return {'name': l.name, 'kind': l.kind, 'revenue': ZERO, 'cost': ZERO, 'op': ZERO}
    gf = (1 + l.growth_pct / 100) ** (y - l.start_year)
    if l.kind == 'business':
        rev = l.revenue_year1 * gf
        cost = rev * l.cost_pct / 100
    else:
        rev = l.area_py * l.rent_per_py_month * 12 * l.occupancy_pct / 100 * gf
        cost = rev * l.opex_pct / 100
    return {'name': l.name, 'kind': l.kind, 'revenue': rev, 'cost': cost, 'op': rev - cost}


def _noi_year(o: OperatingPlan, i: int) -> tuple[dict, list[dict], Decimal, Decimal]:
    h = _hotel_year(o.hotel, i)
    lines = [_line_year(l, i) for l in o.lines]
    ptax = o.property_tax_year1 * (1 + o.property_tax_growth_pct / 100) ** i
    noi = h['hotel_noi'] + sum((x['op'] for x in lines), ZERO) - ptax
    return h, lines, ptax, noi


def run(p, items: list[dict], fin_rows: list[dict]) -> dict:
    """p: Proforma (project_mode='operating'), items: 사업비 항목(금액 산출 완료), fin_rows: 대출별 건설기간 이자·수수료 (_finance)."""
    from .schedule import _irr
    o = p.operating
    h = o.hotel
    warns, notes = [], []
    fin_input = sum((i['amount'] for i in items if i['category'] == 'finance'), ZERO)
    dev_cost = sum((i['amount'] for i in items), ZERO) - fin_input
    loan_fin = sum((r['interest'] + r['fee'] for r in fin_rows), ZERO)
    finance_cost = loan_fin + fin_input
    total_cost = dev_cost + finance_cost
    loans = [l for l in p.loans if l.amount > 0]
    loan_total = sum((l.amount for l in loans), ZERO)
    # 준공 시 자본구조
    if o.debt_mode == 'refinance':
        debt0 = max(total_cost - p.equity, ZERO)
        rate = o.refi_rate_pct
        notes.append(f'준공 시 담보대출 전환: {eok(debt0)}원, 연 {float(rate):g}%'
                     + (f', {o.refi_amort_years}년 원금 균등분할' if o.refi_amort_years else ', 만기일시'))
    else:
        debt0 = loan_total
        rate = (sum((l.amount * l.annual_rate_pct for l in loans), ZERO) / loan_total) if loan_total else ZERO
        if loans:
            notes.append(f'건설 대출 {eok(loan_total)}원을 운영기간에도 유지 (가중 금리 연 {float(rate):.2f}%, 이자만 상환 · 매각 시 원금 상환)')
    # 재원 부족분(자기자본 + 대출 < 총사업비)은 추가 자기자본으로 개발기간에 사업비 집행 비율대로 투입
    extra_eq = max(total_cost - p.equity - debt0, ZERO)
    if extra_eq:
        warns.append(f'재원 부족: 자기자본 {eok(p.equity)} + 대출 {eok(debt0)} < 총사업비 {eok(total_cost)}원 '
                     f'→ 부족분 {eok(extra_eq)}원을 추가 자기자본으로 반영했습니다.')
    if debt0 and o.exit_cap_pct < rate:
        warns.append(f'매각 환원율 {float(o.exit_cap_pct):g}%가 대출 금리 {float(rate):.2f}%보다 낮습니다 (부(-)의 레버리지).')
    if not o.property_tax_year1:
        notes.append('운영기 보유세(재산세·종부세) 미반영 — 운영 계획의 보유세 1년차 금액을 입력하세요.')
    if h.enabled and h.rooms:
        hi = max(h.occupancy_pct_by_year or [ZERO])
        if hi > 95:
            warns.append(f'호텔 점유율 {float(hi):g}%가 95%를 넘습니다 (과대 가정 여부 확인).')
    elif not o.lines:
        warns.append('운영 수입이 없습니다: 호텔 객실 수 또는 운영·임대 라인을 입력하세요.')
    # 연 단위 운영
    depr = total_cost * o.building_ratio_pct / 100 / o.depreciation_years
    tax_cfg = p.corporate_tax
    surtax = 1 + tax_cfg.local_surtax_pct / 100
    bal = debt0
    principal_amt = (debt0 / o.refi_amort_years) if o.debt_mode == 'refinance' and o.refi_amort_years else ZERO
    rows, nol, min_dscr, gop_hi = [], [], None, ZERO
    for i in range(o.hold_years):
        hy, lines, ptax, noi = _noi_year(o, i)
        if o.debt_mode == 'refinance':
            interest = bal * rate / 100
            principal = min(principal_amt, bal)
        else:
            interest = sum((l.amount * l.annual_rate_pct / 100 for l in loans), ZERO)
            principal = ZERO
        bal -= principal
        ds = interest + principal
        dscr = noi / ds if ds else None
        if dscr is not None:
            min_dscr = dscr if min_dscr is None else min(min_dscr, dscr)
        income = noi - interest - depr
        used = ZERO
        if income > 0:
            cap = income * D('0.8')   # 이월결손금 공제 한도 (일반법인 80%)
            for it in nol:
                u = min(it[1], cap - used); it[1] -= u; used += u
            nol = [x for x in nol if x[1] > 0]
        elif income < 0:
            nol.append([i + 1, -income])
        ct = _tax(max(income - used, ZERO), tax_cfg.brackets) * surtax if tax_cfg.enabled else ZERO
        line_rev = sum((x['revenue'] for x in lines), ZERO)
        total_rev = hy['hotel_revenue'] + line_rev
        gop_pct = hy['gop'] / hy['hotel_revenue'] * 100 if hy['hotel_revenue'] else None
        if gop_pct is not None:
            gop_hi = max(gop_hi, gop_pct)
        rows.append({'year': i + 1, 'calendar_year': o.dev_years + i + 1, **{k: v for k, v in hy.items() if k != 'avail'},
                     'sold_rooms': hy['sold'], 'revpar': hy['room_rev'] / hy['avail'] if hy['avail'] else ZERO,
                     'gop_pct': gop_pct, 'lines': lines, 'line_revenue': line_rev, 'line_op': sum((x['op'] for x in lines), ZERO),
                     'total_revenue': total_rev, 'property_tax': ptax, 'noi': noi, 'noi_pct': noi / total_rev * 100 if total_rev else None,
                     'interest': interest, 'principal': principal, 'debt_balance': bal, 'dscr': dscr, 'depreciation': depr,
                     'taxable': income, 'tax': ct, 'cash_flow': noi - interest - principal - ct})
    if gop_hi > 60:
        warns.append(f'호텔 GOP율 {float(gop_hi):.1f}%가 60%를 넘습니다 (비용 가정 확인).')
    # 매각 (보유 마지막 해 말)
    noi_last = rows[-1]['noi']
    exit_noi = noi_last if o.exit_noi_basis == 'trailing' else _noi_year(o, o.hold_years)[3]
    gross_exit = max(exit_noi, ZERO) / (o.exit_cap_pct / 100)
    sale_cost = gross_exit * o.sale_cost_pct / 100
    book = total_cost - depr * o.hold_years
    gain = gross_exit - sale_cost - book
    gain_tax = _tax(max(gain, ZERO), tax_cfg.brackets) * surtax if tax_cfg.enabled else ZERO
    exit_net = gross_exit - sale_cost - bal - gain_tax
    # 연 단위 현금흐름 (0 = 개발 1년차)
    eq_split, cost_split = _split(o.equity_split_pct_by_year, o.dev_years), _split(o.cost_split_pct_by_year, o.dev_years)
    equity_total = p.equity + extra_eq
    eq_flows = [-(p.equity * s + extra_eq * c) for s, c in zip(eq_split, cost_split)] + [r['cash_flow'] for r in rows]
    eq_flows[-1] += exit_net
    un_flows = [-total_cost * s for s in cost_split] + [r['noi'] for r in rows]
    un_flows[-1] += gross_exit - sale_cost
    irr_e, irr_u = _irr(eq_flows), _irr(un_flows)
    disc = 1 + o.discount_rate_pct / 100
    npv = sum((v / disc ** t for t, v in enumerate(eq_flows)), ZERO)
    inflow = sum((v for v in eq_flows if v > 0), ZERO)
    payback, cum = None, ZERO
    for t, v in enumerate(eq_flows):
        cum += v
        if t >= o.dev_years and cum >= 0 and equity_total > 0:
            payback = t - o.dev_years + 1
            break
    noi1 = rows[0]['noi']
    value0 = noi1 / (o.valuation_cap_pct / 100)
    stab = rows[min(3, o.hold_years) - 1]['noi']
    return {
        'dev_cost': dev_cost, 'finance_cost': finance_cost, 'finance_input': fin_input, 'total_cost': total_cost,
        'equity': p.equity, 'extra_equity': extra_eq, 'debt': debt0, 'debt_rate_pct': rate, 'ltc_pct': debt0 / total_cost * 100 if total_cost else None,
        'rooms': h.rooms if h.enabled else 0, 'hold_years': o.hold_years, 'dev_years': o.dev_years,
        'rows': rows, 'noi_year1': noi1, 'hotel_noi_year1': rows[0]['hotel_noi'], 'stabilized_noi': stab,
        'value_at_completion': value0, 'dev_margin': value0 - total_cost,
        'exit_noi': exit_noi, 'exit_value': gross_exit, 'exit_sale_cost': sale_cost, 'exit_gain_tax': gain_tax,
        'exit_debt_repaid': bal, 'exit_net_to_equity': exit_net, 'book_value': book,
        'yield_on_cost_pct': noi1 / total_cost * 100 if total_cost else None, 'min_dscr': min_dscr,
        'equity_irr_pct': irr_e * 100 if irr_e is not None else None, 'unlevered_irr_pct': irr_u * 100 if irr_u is not None else None,
        'equity_npv': npv, 'equity_multiple': inflow / equity_total if equity_total else None, 'payback_year': payback,
        'equity_flows': eq_flows, 'unlevered_flows': un_flows, 'warnings': warns, 'notes': notes,
    }
