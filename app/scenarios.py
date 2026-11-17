"""시나리오 비교 · 스트레스 테스트 (디벨로퍼 투자심사용).

- compare: 현재 작업본 + 저장된 시나리오를 같은 지표로 나란히 비교 (기준안 대비 증감)
- stress : 현재 작업본에 표준 위험 요인(분양가 하락·분양률·공사비·금리·공기 지연·복합)을 적용해 즉시 재계산
  PF 대주단·투자심의에서 통상 요구하는 하방 시나리오를 한 번에 본다.
"""
from copy import deepcopy
from decimal import Decimal

from .proforma import Proforma, analyze

D = Decimal


def _f(x):
    return None if x is None else float(x)


def metrics(p: Proforma) -> dict:
    r = analyze(p)
    s, v, a = r['summary'], r['verdict'], r['area']
    cons = next((c['amount'] for c in r['costs'] if c['key'] == 'construction'), None)
    land = next((c['amount'] for c in r['costs'] if c['key'] == 'land'), None)
    supply_py = a.get('supply_py') or 0
    loans = [l for l in p.loans if l.amount > 0]
    debt = sum((l.amount for l in loans), D(0))
    rate = (sum((l.amount * l.annual_rate_pct for l in loans), D(0)) / debt) if debt else None
    sale_units = [u for u in p.units if u.buyer != 'rental' and u.price_per_py > 0]
    sp = sum((u.supply_sqm * u.count for u in sale_units), D(0))
    avg_price = (sum((u.price_per_py * u.supply_sqm * u.count for u in sale_units), D(0)) / sp) * (1 + p.price_adjust_pct / 100) if sp else None
    return {
        'kpi': {
            'revenue_net': _f(s['revenue_net']), 'total_cost': _f(s['total_cost']), 'land_cost': _f(land), 'construction_cost': _f(cons),
            'finance_cost': _f(s['finance_cost']), 'pbt': _f(s['pbt']), 'npat': _f(s['npat']), 'margin_pct': _f(s['margin_pct']),
            'roe_pct': _f(s.get('roe_pct')), 'bep_sales_rate_pct': _f(s['bep_sales_rate_pct']), 'price_drop_tolerance_pct': _f(s['price_drop_tolerance_pct']),
            'equity_irr_pct': _f(s.get('equity_irr_pct')), 'equity_multiple': _f(s.get('equity_multiple')), 'ltc_pct': _f(s.get('ltc_pct')),
            'peak_loan': _f(s.get('peak_loan')), 'extra_equity': _f(s.get('extra_equity')), 'cost_per_supply_py': _f(s.get('cost_per_supply_py')),
            'rent_yield_pct': next((_f(x['value']) for x in v['financial'] if x['name'].startswith('임대수익률')), None),
            'min_dscr': next((_f(x['value']) for x in v['financial'] if 'DSCR' in x['name']), None),
        },
        'assume': {
            'sales_rate_pct': _f(p.sales_rate_pct), 'price_adjust_pct': _f(p.price_adjust_pct), 'avg_price_per_py': _f(avg_price),
            'supply_py': _f(supply_py), 'units': a.get('units'), 'duration_months': p.duration_months,
            'construction_months': p.schedule.construction_months if p.schedule else None,
            'equity': _f(p.equity), 'debt': _f(debt), 'avg_rate_pct': _f(rate),
        },
        'verdict': v['overall'], 'verdict_label': v['label'],
        'reasons': [x['text'] for x in v.get('reasons', []) if x['status'] == 'bad'][:3],
    }


# ── 표준 스트레스 ──
def _cost_up(p: Proforma, pct: float):
    k = D(1) + D(str(pct)) / 100
    for c in p.costs:
        # 공사비 항목 중 정액·면적 단가 기준만 증액 (비율 기준 항목은 공사비에 연동되어 자동 증가)
        if c.category == 'construction' and not c.basis.startswith('pct_') and c.basis != 'derived':
            c.value = (c.value * k).quantize(D('1'))


def _rate_up(p: Proforma, pp: float):
    for l in p.loans:
        l.annual_rate_pct = min(D(50), l.annual_rate_pct + D(str(pp)))


def _delay(p: Proforma, m: int):
    p.duration_months = min(240, p.duration_months + m)
    if p.schedule:
        p.schedule.construction_months = min(120, p.schedule.construction_months + m)
    for l in p.loans:
        l.months = min(D(240), l.months + m)
        if l.maturity_month is not None:
            l.maturity_month = min(300, l.maturity_month + m)


def _price(p: Proforma, pct: float):
    p.price_adjust_pct = max(D(-90), p.price_adjust_pct + D(str(pct)))


def _sales(p: Proforma, pp: float):
    p.sales_rate_pct = max(D(0), min(D(100), p.sales_rate_pct + D(str(pp))))


STRESS = [
    ('price10', '분양가 −10%', '분양가 조정 −10%p', [(_price, -10)]),
    ('sales80', '분양률 −20%p', '최종 분양률 20%p 하락 (미분양)', [(_sales, -20)]),
    ('cost10', '공사비 +10%', '공사비(정액·단가) 10% 상승 · 연동 비용 자동 반영', [(_cost_up, 10)]),
    ('rate2', '금리 +2%p', '모든 대출 금리 2%p 상승', [(_rate_up, 2)]),
    ('delay6', '공기 6개월 지연', '사업·공사·대출 기간 6개월 연장', [(_delay, 6)]),
    ('combo', '복합 하방', '분양가 −5% · 공사비 +5% · 금리 +1%p · 6개월 지연', [(_price, -5), (_cost_up, 5), (_rate_up, 1), (_delay, 6)]),
]


# 공공지원민간임대: 분양가·분양률 대신 임대료·입주율·매각가·건설/담보 금리
def _rent(p: Proforma, pct: float):
    k = D(1) + D(str(pct)) / 100
    for u in p.units:
        u.market_rent = (u.market_rent * k).quantize(D('1')); u.market_deposit = (u.market_deposit * k).quantize(D('1'))


def _occ(p: Proforma, pp: float):
    p.rental.occupancy_pct = max(D(0), p.rental.occupancy_pct + D(str(pp)))


def _exit(p: Proforma, pct: float):
    r = p.rental
    if r.exit_mode == 'price':
        r.exit_price_per_py = (r.exit_price_per_py * (D(1) + D(str(pct)) / 100)).quantize(D('1'))
    else:   # 환원율 상승 = 매각가 하락 (가격 −10% ≈ Cap ÷ 0.9)
        r.exit_cap_pct = min(D(20), r.exit_cap_pct / (D(1) + D(str(pct)) / 100))


def _rrate(p: Proforma, pp: float):
    r = p.rental
    r.construction_rate_pct = min(D(20), r.construction_rate_pct + D(str(pp)))
    r.mortgage_rate_pct = min(D(20), r.mortgage_rate_pct + D(str(pp)))
    _rate_up(p, pp)


def _rdelay(p: Proforma, m: int):
    p.rental.construction_months = min(120, p.rental.construction_months + m)
    _delay(p, m)


STRESS_RENTAL = [
    ('rent10', '임대료 −10%', '시세(보증금·월임대료) 10% 하락', [(_rent, -10)]),
    ('occ10', '입주율 −10%p', '공실 증가로 입주율 10%p 하락', [(_occ, -10)]),
    ('exit10', '매각가 −10%', '의무기간 후 매각가(분양전환가) 10% 하락', [(_exit, -10)]),
    ('cost10', '공사비 +10%', '공사비(정액·단가) 10% 상승 · 연동 비용 자동 반영', [(_cost_up, 10)]),
    ('rate2', '금리 +2%p', '건설 PF·준공 후 담보대출 금리 2%p 상승', [(_rrate, 2)]),
    ('delay6', '공기 6개월 지연', '공사·대출 기간 6개월 연장', [(_rdelay, 6)]),
    ('combo', '복합 하방', '임대료 −5% · 공사비 +5% · 금리 +1%p · 매각가 −5%', [(_rent, -5), (_cost_up, 5), (_rrate, 1), (_exit, -5)]),
]


def stress(p: Proforma) -> list[dict]:
    out = [{'key': 'base', 'label': '현재 작업본', 'desc': '기준', **metrics(p), 'proforma': None}]
    for key, label, desc, ops in (STRESS_RENTAL if p.project_mode == 'rental' else STRESS):
        q = deepcopy(p)
        for fn, arg in ops:
            fn(q, arg)
        try:
            m = metrics(Proforma.model_validate(q.model_dump()))
        except (ValueError, ArithmeticError) as exc:
            out.append({'key': key, 'label': label, 'desc': desc, 'error': str(exc)})
            continue
        out.append({'key': key, 'label': label, 'desc': desc, **m,
                    'proforma': q.model_dump(mode='json')})
    return out
