"""공공지원민간임대주택 사업수지 (민간임대주택에 관한 특별법).

개발(사업비) → 준공 시 자본구조(자기자본·임대보증금·주택도시기금·담보대출) → 의무임대기간 연 단위 운영(NOI·DSCR·법인세)
→ 의무기간 종료 후 매각(환원율 또는 평당 분양전환가) 순으로 계산한다. 법정 기준값은 RENTAL_LAW 에 근거와 함께 둔다.
"""
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field

D = Decimal
ZERO = D(0)

# 법령 기준값 (출처·확인일은 RENTAL_LAW_SOURCES 참조). 확인되지 않은 값은 None → 입력값 사용
RENTAL_LAW = {
    'hold_years': 10,                         # 법 제2조제4호·제43조①: 10년 이상
    'general_rent_cap_pct': D(95),            # 시행규칙 별표2: 일반공급 계수 0.95 이하
    'special_rent_cap_pct_20': D(70),         # 별표2: 특별공급 비율 20~30% 미만 → 0.7 이하
    'special_rent_cap_pct_30': D(75),         # 별표2: 특별공급 비율 30% 이상 → 0.75 이하
    'special_share_min_pct': D(20),           # 시행규칙 별표1: 특별공급 20% 이상
    'rent_increase_cap_pct': D(5),            # 법 제44조②③: 5% 범위, 1년 이내 재증액 금지
    'guarantee_landlord_share_pct': D(75),    # 시행령 제40조: 보증수수료 임대사업자 75%·임차인 25%
}
# 지방세특례제한법 제31조의3 (민간임대, 일몰 2027.12.31): 전용면적 상한 → 감면율 %
PROPERTY_TAX_RELIEF = [(D(40), D(100)), (D(60), D(75)), (D(85), D(50))]
ACQUISITION_TAX_RELIEF = [(D(60), D(100)), (D(85), D(50))]       # 건설 취득, 60~85㎡는 20호 이상
# 주택도시기금 민간임대주택건설자금 (공공지원, 호당 한도·연 금리, 14년 만기일시) — nhuf.molit.go.kr 표 기준
FUND_LOAN_TABLE = [(D(45), D(70_000_000), D('2.6')), (D(60), D(100_000_000), D('2.9')), (D(85), D(120_000_000), D('3.4'))]
RENTAL_LAW_SOURCES = [
    '민간임대주택에 관한 특별법 [시행 2026.1.2] 제2조제4호·제43조·제44조·제49조, 시행령 [2026.10.27] 제34조의2·제40조, 시행규칙 [2026.10.27] 별표1·별표2',
    '지방세특례제한법 제31조의3 (민간임대 취득세·재산세 감면, 일몰 2027.12.31, 가액 상한 별도 확인)',
    '종합부동산세법 시행령 제3조①7호 합산배제 (전용 149㎡ 이하, 공시가 9억(2~29호)/12억(30호 이상), 10년 이상 임대, 증액 5% 이하)',
    '주택도시기금 민간임대주택건설자금 (nhuf.molit.go.kr, 2026-11-16 열람 — 페이지 내 구 수치 병기, 기금 확인 필요)',
]


def eok(n) -> str:
    """금액 표기 (소수점 없음): 13억 9,412만."""
    man = round(abs(float(n)) / 1e4)
    sign = '-' if float(n) < 0 else ''
    if man >= 10000:
        e, r = divmod(man, 10000)
        return f'{sign}{e:,}억' + (f' {r:,}만' if r else '')
    return f'{sign}{man:,}만' if man else f'{sign}{round(abs(float(n))):,}'


def relief_pct(table, sqm) -> Decimal:
    for cap, pct in table:
        if sqm <= cap:
            return pct
    return ZERO


class RentalPlan(BaseModel):
    hold_years: int = Field(default=10, ge=1, le=30, description='임대 운영기간 (의무임대기간 이상)')
    general_rent_ratio_pct: Decimal = Field(default=D(95), ge=0, le=100, description='일반공급 임대료 (시세 대비)')
    special_share_pct: Decimal = Field(default=D(20), ge=0, le=100, description='특별공급 세대 비율')
    special_rent_ratio_pct: Decimal = Field(default=D(70), ge=0, le=100, description='특별공급 임대료 (시세 대비, 별표2 계수)')
    auto_relief: bool = Field(default=True, description='전용면적별 재산세·취득세 감면 자동 적용 (지특법 제31조의3)')
    auto_fund: bool = Field(default=True, description='주택도시기금 융자 한도·금리 자동 산정 (호당·면적별)')
    occupancy_pct: Decimal = Field(default=D(97), ge=0, le=100)
    rent_growth_pct: Decimal = Field(default=D(2), ge=0, le=10, description='연 임대료 증액률')
    opex_pct: Decimal = Field(default=D(12), ge=0, le=60, description='운영비 (관리·수선·보험·마케팅, 임대료 수입 대비)')
    property_tax_annual: Decimal = Field(default=ZERO, ge=0, description='재산세·종부세 등 연간 보유세 (감면 전)')
    property_tax_relief_pct: Decimal = Field(default=ZERO, ge=0, le=100, description='재산세 감면율')
    guarantee_rate_pct: Decimal = Field(default=D('0.2'), ge=0, le=2, description='HUG 임대보증금 보증료율 (연 0.073~1.590%, 신용·부채비율)')
    fund_loan: Decimal = Field(default=ZERO, ge=0, description='주택도시기금 융자')
    fund_rate_pct: Decimal = Field(default=D(2), ge=0, le=15)
    mortgage_rate_pct: Decimal = Field(default=D('4.5'), ge=0, le=20, description='준공 후 담보대출(리파이낸싱) 금리')
    construction_months: int = Field(default=30, ge=1, le=120, description='착공~준공 (건설이자 산정)')
    construction_rate_pct: Decimal = Field(default=D('6.5'), ge=0, le=20, description='건설기간 PF 금리')
    construction_draw_pct: Decimal = Field(default=D(55), ge=0, le=100, description='건설기간 평균 인출률')
    exit_mode: Literal['cap', 'price'] = 'cap'
    exit_cap_pct: Decimal = Field(default=D('4.5'), gt=0, le=20, description='매각 환원율 (다음 해 NOI 기준)')
    exit_price_per_py: Decimal = Field(default=ZERO, ge=0, description='매각(분양전환) 공급평당 가격')
    sale_cost_pct: Decimal = Field(default=D('1.5'), ge=0, le=10)
    building_ratio_pct: Decimal = Field(default=D(60), ge=0, le=100, description='총사업비 중 건물분 (감가상각)')
    depreciation_years: int = Field(default=40, ge=10, le=60)
    discount_rate_pct: Decimal = Field(default=D(7), ge=0, le=30)
    yield_min_pct: Decimal = D('4.5')
    dscr_min: Decimal = D('1.2')
    irr_min_pct: Decimal = D(7)


def _tax(base, brackets):
    t, lower = ZERO, ZERO
    for b in brackets:
        upper = b.up_to if b.up_to is not None else base
        if base > lower:
            t += (min(base, upper) - lower) * b.rate_pct / 100
        if b.up_to is None or base <= upper:
            break
        lower = upper
    return t


def run(p, items: list[dict]) -> dict:
    """p: Proforma (project_mode='rental'), items: 사업비 항목(금액 산출 완료)."""
    from .schedule import _irr, _annual
    r = p.rental
    py = lambda sqm: sqm * 121 / 400
    dev_cost = sum((i['amount'] for i in items), ZERO)
    cons_interest = dev_cost * r.construction_draw_pct / 100 * r.construction_rate_pct / 100 * D(r.construction_months) / 12
    total_cost = dev_cost + cons_interest
    # 연 임대수입·보증금 (세대별 시세 × 임대료율)
    units = [u for u in p.units if u.count]
    n_units = sum(u.count for u in units)
    sp = r.special_share_pct / 100
    ratio = (1 - sp) * r.general_rent_ratio_pct / 100 + sp * r.special_rent_ratio_pct / 100
    occ = r.occupancy_pct / 100
    rent0 = sum((u.market_rent * 12 * u.count for u in units), ZERO) * ratio * occ
    deposit0 = sum((u.market_deposit * u.count for u in units), ZERO) * ratio * occ
    warns, notes = [], []
    res_units = [u for u in units if u.kind in ('apartment', 'officetel')]
    n_res = sum(u.count for u in res_units) or 1
    fund_loan, fund_rate = r.fund_loan, r.fund_rate_pct
    if r.auto_fund:
        fl = [(next(((amt, rt) for cap, amt, rt in FUND_LOAN_TABLE if u.exclusive_sqm <= cap), (ZERO, ZERO)), u.count) for u in res_units]
        fund_loan = sum((a * c for (a, _), c in fl), ZERO)
        fund_rate = (sum((a * c * rt for (a, rt), c in fl), ZERO) / fund_loan) if fund_loan else ZERO
        notes.append(f'주택도시기금 융자 자동 산정: {eok(fund_loan)}원, 가중 금리 연 {float(fund_rate):.2f}% (85㎡ 초과는 대상 아님)')
    ptax_relief = r.property_tax_relief_pct
    if r.auto_relief:
        ptax_relief = sum((relief_pct(PROPERTY_TAX_RELIEF, u.exclusive_sqm) * u.count for u in res_units), ZERO) / n_res
        notes.append(f'재산세 감면 가중평균 {float(ptax_relief):.1f}% (지특법 제31조의3, 가액 상한·최소납부세제 별도 확인)')
    sp_cap = RENTAL_LAW['special_rent_cap_pct_30'] if r.special_share_pct >= 30 else RENTAL_LAW['special_rent_cap_pct_20']
    if r.special_share_pct < RENTAL_LAW['special_share_min_pct']:
        warns.append(f"특별공급 비율 {float(r.special_share_pct):g}%가 의무비율 20% 미만입니다 (시행규칙 별표1).")
    if r.hold_years < RENTAL_LAW['hold_years']:
        warns.append(f"운영기간 {r.hold_years}년이 임대의무기간 {RENTAL_LAW['hold_years']}년보다 짧습니다.")
    if r.general_rent_ratio_pct > RENTAL_LAW['general_rent_cap_pct']:
        warns.append(f"일반공급 임대료 {float(r.general_rent_ratio_pct):g}%가 상한 {float(RENTAL_LAW['general_rent_cap_pct']):g}%를 넘습니다.")
    if r.special_rent_ratio_pct > sp_cap:
        warns.append(f"특별공급 임대료 {float(r.special_rent_ratio_pct):g}%가 상한 {float(sp_cap):g}% (특별공급 {float(r.special_share_pct):g}% 기준, 별표2)를 넘습니다.")
    if r.rent_growth_pct > RENTAL_LAW['rent_increase_cap_pct']:
        warns.append(f"임대료 증액률 {float(r.rent_growth_pct):g}%가 법정 상한 {float(RENTAL_LAW['rent_increase_cap_pct']):g}%를 넘습니다.")
    if not rent0 and not deposit0:
        warns.append('분양 계획 표에 타입별 시세 보증금·월세를 입력하세요 (임대수입 0).')
    # 준공 시 자본구조
    mortgage = max(total_cost - p.equity - deposit0 - fund_loan, ZERO)
    equity_release = max(p.equity + deposit0 + fund_loan - total_cost, ZERO)
    g = 1 + r.rent_growth_pct / 100
    depr = total_cost * r.building_ratio_pct / 100 / r.depreciation_years
    tax_cfg = p.corporate_tax
    rows, eq_flows, nol = [], [-p.equity + equity_release], []
    min_dscr = None
    deposit_prev = deposit0
    for y in range(1, r.hold_years + 1):
        gf = g ** (y - 1)
        rent = rent0 * gf
        deposit = deposit0 * gf
        opex = rent * r.opex_pct / 100
        ptax = r.property_tax_annual * (1 - ptax_relief / 100)
        gfee = deposit * r.guarantee_rate_pct / 100 * RENTAL_LAW['guarantee_landlord_share_pct'] / 100
        noi = rent - opex - ptax - gfee
        interest = fund_loan * fund_rate / 100 + mortgage * r.mortgage_rate_pct / 100
        dscr = noi / interest if interest else None
        if dscr is not None:
            min_dscr = dscr if min_dscr is None else min(min_dscr, dscr)
        income = noi - interest - depr
        used = ZERO
        if income > 0:
            cap = income * D('0.8')
            for it in nol:
                u = min(it[1], cap - used); it[1] -= u; used += u
            nol = [x for x in nol if x[1] > 0]
        elif income < 0:
            nol.append([y, -income])
        ct = _tax(max(income - used, ZERO), tax_cfg.brackets) * (1 + tax_cfg.local_surtax_pct / 100) if tax_cfg.enabled else ZERO
        deposit_inc = deposit - deposit_prev
        deposit_prev = deposit
        cf = noi - interest - ct + deposit_inc
        rows.append({'year': y, 'rent': rent, 'deposit': deposit, 'deposit_increase': deposit_inc, 'opex': opex, 'property_tax': ptax,
                     'guarantee_fee': gfee, 'noi': noi, 'interest': interest, 'dscr': dscr, 'depreciation': depr, 'taxable': income,
                     'tax': ct, 'cash_flow': cf})
        eq_flows.append(cf)
    # 매각
    noi_next = rows[-1]['noi'] * g if rows else ZERO
    supply_py = sum((py(u.supply_sqm) * u.count for u in units), ZERO)
    gross_exit = noi_next / (r.exit_cap_pct / 100) if r.exit_mode == 'cap' else r.exit_price_per_py * supply_py
    sale_cost = gross_exit * r.sale_cost_pct / 100
    book = total_cost - depr * r.hold_years
    gain = gross_exit - sale_cost - book
    gain_tax = _tax(max(gain, ZERO), tax_cfg.brackets) * (1 + tax_cfg.local_surtax_pct / 100) if tax_cfg.enabled else ZERO
    deposit_end = rows[-1]['deposit'] if rows else deposit0
    exit_net = gross_exit - sale_cost - deposit_end - fund_loan - mortgage - gain_tax
    eq_flows[-1] += exit_net
    irr_a = _irr([D(str(x)) for x in eq_flows])
    irr = None if irr_a is None else ((1 + irr_a) ** 1 - 1) * 100  # 연 단위 흐름 → 연 IRR
    disc = r.discount_rate_pct / 100
    npv = sum(v / (1 + disc) ** i for i, v in enumerate(eq_flows))
    profit = sum(eq_flows[1:]) - (p.equity - equity_release)
    yoc = rows[0]['noi'] / total_cost * 100 if rows and total_cost else None
    return {
        'units': n_units, 'rent_ratio_pct': ratio * 100, 'dev_cost': dev_cost, 'construction_interest': cons_interest, 'total_cost': total_cost,
        'rent_year1': rent0, 'deposit_total': deposit0, 'fund_loan': fund_loan, 'fund_rate_pct': fund_rate, 'mortgage': mortgage, 'equity': p.equity,
        'property_tax_relief_pct': ptax_relief, 'special_rent_cap_pct': sp_cap, 'notes': notes,
        'equity_release': equity_release, 'noi_year1': rows[0]['noi'] if rows else ZERO, 'yield_on_cost_pct': yoc,
        'min_dscr': min_dscr, 'exit_value': gross_exit, 'exit_sale_cost': sale_cost, 'exit_gain_tax': gain_tax, 'exit_net_to_equity': exit_net,
        'book_value': book, 'equity_irr_pct': irr, 'equity_npv': npv, 'equity_profit': profit,
        'equity_multiple': (sum(eq_flows[1:]) / (p.equity - equity_release)) if p.equity > equity_release else None,
        'rows': rows, 'equity_flows': eq_flows, 'warnings': warns, 'law': {k: float(v) for k, v in RENTAL_LAW.items()},
        'sources': RENTAL_LAW_SOURCES,
    }
