"""월별 사업 현금흐름(공정률·분양대금·PF 자금조달) 엔진.

사업수지(proforma)의 매출·사업비 산출값을 '언제' 들어오고 나가는지 월 단위로 배분하고,
부족 자금을 Equity → 대출(약정 순서) 로 조달하며 대출 잔액 기준 월 이자를 계산한다.

주요 가정 (모두 입력값으로 조정 가능)
- 월 이자 = 월초 대출잔액 × 연 금리 / 12. 이자는 해당 월 현금에서 지급하며, 현금이 부족하면 대출 인출로 충당(사실상 자본화)
- 취급수수료는 대출 개시월에 약정한도 × 수수료율로 지급
- 분양대금은 부가세 포함 금액이 들어오고, 부가세 해당분은 같은 달 납부로 처리(매입세액 환급은 반영하지 않음)
- 중도금 대출이자(시행사 부담분)는 수분양자가 낸 중도금 누적액 × 금리/12 를 입주 전까지 매월 지급
"""
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field

D = Decimal
ZERO = D(0)

Timing = Literal['auto', 'land', 'contract', 'land_balance', 'pre_construction', 'construction_start', 'construction_curve',
                 'construction_even', 'sales_start', 'sales_linked', 'completion', 'move_in', 'even', 'property_tax']
TIMING_NAMES = {
    'auto': '자동(분류 기본값)', 'land': '토지 계약금·잔금 분할', 'contract': '사업 개시월', 'land_balance': '토지 잔금월',
    'pre_construction': '착공 전 균등', 'construction_start': '착공월', 'construction_curve': '공정률 연동',
    'construction_even': '공사기간 균등', 'sales_start': '분양 개시월', 'sales_linked': '분양대금 수납 연동',
    'completion': '준공월', 'move_in': '입주(잔금)월', 'even': '전 기간 균등', 'property_tax': '재산세 (매년 7·9월)',
}
PERIOD_CATS = ('sales', 'admin', 'finance')          # 판매비·관리비: 발생 연도 손금
INVENTORY_CATS = ('land', 'construction', 'indirect', 'charges', 'taxes', 'contingency')  # 분양원가: 진행률로 손금


class Schedule(BaseModel):
    enabled: bool = True
    start_month: str = Field(default='2027-01', pattern=r'^\d{4}-\d{2}$', description='사업 개시(토지 계약) 연월')
    land_contract_pct: Decimal = Field(default=D(10), ge=0, le=100)
    land_balance_month: int = Field(default=3, ge=0, le=120)
    construction_start_month: int = Field(default=8, ge=0, le=180)
    construction_months: int = Field(default=30, ge=1, le=120)
    curve: Literal['s_curve', 'linear', 'custom'] = 's_curve'
    custom_curve: list[Decimal] = []
    payment_lag_months: int = Field(default=1, ge=0, le=6, description='기성 청구 → 지급 지연')
    retention_pct: Decimal = Field(default=ZERO, ge=0, le=20, description='공사 유보금 (준공 후 지급)')
    sales_start_month: int = Field(default=9, ge=0, le=180)
    initial_sales_share_pct: Decimal = Field(default=D(60), ge=0, le=100, description='분양 개시월 계약 비중 (분양분 대비)')
    sales_period_months: int = Field(default=12, ge=1, le=120, description='잔여 분양 소진 기간')
    deposit_pct: Decimal = Field(default=D(10), ge=0, le=100)
    midpay_pct: Decimal = Field(default=D(60), ge=0, le=100)
    midpay_installments: int = Field(default=6, ge=0, le=24)
    move_in_lag_months: int = Field(default=1, ge=0, le=12, description='준공 → 입주(잔금) 시점')
    sweep_pct: Decimal = Field(default=ZERO, ge=0, le=100, description='여유 현금 중 대출 조기상환 비율')
    minimum_cash: Decimal = Field(default=ZERO, ge=0)
    discount_rate_pct: Decimal = Field(default=D(8), ge=0, le=50)
    vat_settlement: bool = Field(default=True, description='부가세를 분기 신고월(1·4·7·10월)에 정산')
    corporate_tax_by_progress: bool = Field(default=True, description='법인세 진행기준(작업진행률) 연도별 계산·다음해 3월 납부')
    sme: bool = Field(default=False, description='중소기업: 이월결손금 공제한도 100% (일반 80%)')


def month_label(start: str, i: int) -> str:
    y, m = map(int, start.split('-'))
    m += i
    return f'{y + (m - 1) // 12}-{(m - 1) % 12 + 1:02d}'


def curve_weights(s: Schedule) -> list[Decimal]:
    n = s.construction_months
    if s.curve == 'custom' and s.custom_curve:
        w = [max(D(x), ZERO) for x in s.custom_curve[:n]] + [ZERO] * max(0, n - len(s.custom_curve))
    elif s.curve == 'linear':
        w = [D(1)] * n
    else:  # S커브: 누적 = 3t² − 2t³
        cum = [D(3) * (D(i) / n) ** 2 - D(2) * (D(i) / n) ** 3 for i in range(n + 1)]
        w = [cum[i + 1] - cum[i] for i in range(n)]
    tot = sum(w) or D(1)
    return [x / tot for x in w]


def default_timing(item: dict) -> str:
    cat, basis, name = item['category'], item.get('basis', ''), item.get('name', '')
    if cat == 'land':
        return 'land' if ('매입' in name or basis in ('per_land_py', 'fixed')) and not basis.startswith('pct') else 'land_balance'
    if cat == 'construction':
        return 'construction_curve'
    if cat == 'indirect':
        return 'construction_even'
    if cat == 'charges':
        return 'sales_linked' if basis in ('pct_sales', 'pct_sales_net', 'pct_apt_sales') else 'construction_start'
    if cat == 'sales':
        return 'sales_linked' if basis in ('pct_sales', 'pct_sales_net', 'pct_apt_sales', 'pct_general_sales', 'per_unit') else 'sales_start'
    if cat == 'taxes':
        return 'completion' if basis == 'pct_construction' else 'property_tax'
    if cat == 'admin':
        return 'sales_linked' if basis in ('pct_sales', 'pct_sales_net', 'pct_apt_sales') else 'even'
    if cat == 'finance':   # PF 취급·주관 수수료 등은 착공(PF 실행)월, 매출 연동 신탁보수는 수납 연동
        return 'sales_linked' if basis.startswith('pct_sales') else 'land_balance' if basis == 'pct_land' else 'construction_start'
    return 'construction_even'


def run(s: Schedule, horizon: int, rev: dict, items: list[dict], loans: list, equity: Decimal, midpay, tax=None,
        taxable_share: Decimal = ZERO) -> dict:
    cs, cm = s.construction_start_month, s.construction_months
    completion = cs + cm - 1
    move_in = completion + s.move_in_lag_months
    base_n = max(horizon, move_in + 1, s.sales_start_month + s.sales_period_months + 1)
    n = base_n
    taxing = tax is not None and tax.enabled and s.corporate_tax_by_progress
    if taxing:
        y0, m0 = map(int, s.start_month.split('-'))
        last_year = y0 + (m0 - 1 + base_n - 1) // 12
        n = max(n, (last_year + 1 - y0) * 12 + 4 - m0 + 1)   # 마지막 사업연도 다음해 4월(지방소득세)까지
    warnings = []
    if base_n > horizon:
        warnings.append(f'일정상 사업기간이 {base_n}개월로 늘어났습니다 (입력 {horizon}개월). 총 사업기간을 확인하세요.')
    if s.sales_start_month > completion:
        warnings.append('분양 개시가 준공 이후입니다 (후분양). 중도금 회차 없이 계약 즉시 잔금 처리됩니다.')
    Z = lambda: [ZERO] * n

    # ── 1. 분양 계약 · 수납 일정 ──
    sold = Z()
    rem_months = s.sales_period_months
    init = s.initial_sales_share_pct / 100
    if s.sales_start_month < n:
        sold[s.sales_start_month] += init
        for k in range(1, rem_months + 1):
            if s.sales_start_month + k < n:
                sold[s.sales_start_month + k] += (1 - init) / rem_months
            else:
                sold[n - 1] += (1 - init) / rem_months
    k_inst = s.midpay_installments
    first_mid, last_mid = s.sales_start_month + 2, completion - 1
    inst_months = []
    if k_inst and last_mid >= first_mid:
        span = last_mid - first_mid
        inst_months = [first_mid + round(span * j / max(k_inst - 1, 1)) for j in range(k_inst)] if k_inst > 1 else [first_mid]
    elif k_inst:
        inst_months = [min(first_mid, n - 1)]
    dep, mid_p = s.deposit_pct / 100, s.midpay_pct / 100
    bal_p = 1 - dep - mid_p
    if bal_p < 0:
        raise ValueError('계약금 + 중도금 비율이 100%를 넘습니다')
    w_dep, w_mid, w_bal = Z(), Z(), Z()   # 분양대금 수납 비중 (전체 분양대금 = 1)
    for m, f in enumerate(sold):
        if not f:
            continue
        w_dep[m] += f * dep
        if inst_months:
            for im in inst_months:
                w_mid[max(im, m)] += f * mid_p / len(inst_months)
        else:
            w_bal[max(move_in, m)] += f * mid_p
        w_bal[min(max(move_in, m), n - 1)] += f * bal_p
    w_all = [a + b + c for a, b, c in zip(w_dep, w_mid, w_bal)]
    sales_cash = rev['sales_cash'] + rev['balcony_cash']   # 이미 분양률 반영된 금액
    sales_vat = rev['sales_vat'] + rev['balcony_vat']
    recv_dep = [sales_cash * w for w in w_dep]
    recv_mid = [sales_cash * w for w in w_mid]
    recv_bal = [sales_cash * w for w in w_bal]
    vat_out = [sales_vat * w for w in w_all]
    other_in = Z()
    other_in[min(move_in, n - 1)] = rev['other_income']

    # ── 2. 사업비 지급 일정 ──
    cw = curve_weights(s)
    progress = Z()
    for i, w in enumerate(cw):
        if cs + i < n:
            progress[cs + i] = w
    def spread(amount: Decimal, timing: str) -> list[Decimal]:
        out = Z()
        if timing == 'land':
            out[0] += amount * s.land_contract_pct / 100
            out[min(s.land_balance_month, n - 1)] += amount * (1 - s.land_contract_pct / 100)
        elif timing == 'contract':
            out[0] += amount
        elif timing == 'land_balance':
            out[min(s.land_balance_month, n - 1)] += amount
        elif timing == 'pre_construction':
            k = max(cs, 1)
            for i in range(k):
                out[i] += amount / k
        elif timing == 'construction_start':
            out[min(cs, n - 1)] += amount
        elif timing == 'construction_curve':
            ret = s.retention_pct / 100
            for i, w in enumerate(cw):
                out[min(cs + i + s.payment_lag_months, n - 1)] += amount * w * (1 - ret)
            out[min(completion + s.payment_lag_months + 1, n - 1)] += amount * ret
        elif timing == 'construction_even':
            for i in range(cm):
                out[min(cs + i, n - 1)] += amount / cm
        elif timing == 'sales_start':
            out[min(s.sales_start_month, n - 1)] += amount
        elif timing == 'sales_linked':
            for i, w in enumerate(w_all):
                out[i] += amount * w
        elif timing == 'completion':
            out[min(completion, n - 1)] += amount
        elif timing == 'move_in':
            out[min(move_in, n - 1)] += amount
        elif timing == 'property_tax':
            # 과세기준일 6월 1일 보유분: 매년 7월·9월 납부 (사업기간 중 해당 월에 균등 배분)
            months = [i for i in range(base_n) if int(month_label(s.start_month, i)[5:]) in (7, 9)] or [0]
            for i in months:
                out[i] += amount / len(months)
        else:  # even
            for i in range(base_n):
                out[i] += amount / base_n
        return out
    cats = ['land', 'construction', 'indirect', 'charges', 'sales', 'taxes', 'admin', 'contingency', 'finance']
    cost_by_cat = {c: Z() for c in cats}
    for it in items:
        t = it.get('timing') or 'auto'
        if t == 'auto':
            t = default_timing(it)
        for i, v in enumerate(spread(it['amount'], t)):
            cost_by_cat[it['category']][i] += v

    # ── 3. 자금 조달 (Equity → 대출 순서) ──
    L = [{'name': l.name, 'limit': l.amount, 'rate': l.annual_rate_pct / 100, 'fee': l.fee_pct / 100,
          'start': l.start_month, 'end': min(l.maturity_month if l.maturity_month is not None else move_in, base_n - 1),
          'bal': ZERO, 'drawn': ZERO, 'interest': ZERO, 'fees': ZERO, 'peak': ZERO, 'bal_series': Z()} for l in loans]
    cash = ZERO
    eq_in, extra_eq, mid_int, rows = Z(), Z(), Z(), []
    mid_balance = ZERO
    mp_mode = midpay.effective_mode()
    # 무이자: 시행사 부담 비율만큼 매월 지급 / 이자후불제: 전액 대납 후 입주(잔금) 시 회수 / 유이자: 수분양자 부담
    mp_rate = {'interest_free': midpay.annual_rate_pct / 100 * midpay.developer_share_pct / 100,
               'deferred': midpay.annual_rate_pct / 100, 'with_interest': ZERO}[mp_mode]
    mid_recover = Z()
    eq_in[0] = equity
    # 부가세: 과세분 공사·용역비 매입세액(10%) 지급 → 분기 신고 시 매출세액과 정산(음수=환급)
    in_vat = [(cost_by_cat['construction'][m] + cost_by_cat['indirect'][m]) * D('0.1') * taxable_share for m in range(n)]
    vat_pay, vat_acc = Z(), ZERO
    # 법인세 진행기준
    cons_total = sum(cost_by_cat['construction']) or D(1)
    inv_total = sum(sum(cost_by_cat[c]) for c in INVENTORY_CATS)
    net_sales = rev['sales_net'] + rev['balcony_net']
    corp_pay, local_pay, tax_years = Z(), Z(), []
    cum_cons = cum_sold = prev_rev = prev_inv = ZERO
    year_period = year_fin = year_other = ZERO
    nol = []  # 이월결손금 [연도, 잔액]
    for m in range(n):
        draws = {l['name']: ZERO for l in L}
        repays = {l['name']: ZERO for l in L}
        ints = {l['name']: ZERO for l in L}
        fees = ZERO
        cal = int(month_label(s.start_month, m)[5:])
        inflow = recv_dep[m] + recv_mid[m] + recv_bal[m] + other_in[m] + eq_in[m]
        outflow = sum(cost_by_cat[c][m] for c in cats)
        if s.vat_settlement:
            outflow += in_vat[m]
            vat_acc += vat_out[m] - in_vat[m]
            if (cal in (1, 4, 7, 10) and m > 0) or m == base_n - 1:
                vat_pay[m] = vat_acc
                vat_acc = ZERO
            outflow += vat_pay[m]
        else:
            outflow += vat_out[m]
        outflow += corp_pay[m] + local_pay[m]
        # 중도금 대출이자 (입주 전까지, 누적 중도금 잔액 기준)
        if m < move_in:
            mid_int[m] = mid_balance * mp_rate / 12
        if m == move_in:
            mid_balance = ZERO
        mid_balance += recv_mid[m] if m < move_in else ZERO
        outflow += mid_int[m]
        if mp_mode == 'deferred' and m == min(move_in, n - 1):
            mid_recover[m] = sum(mid_int[:m])     # 이자후불제: 잔금 때 수분양자에게서 회수
            inflow += mid_recover[m]
        for l in L:
            ints[l['name']] = l['bal'] * l['rate'] / 12
            l['interest'] += ints[l['name']]
            if m == l['start'] and l['limit']:
                f = l['limit'] * l['fee']
                l['fees'] += f
                fees += f
        outflow += sum(ints.values()) + fees
        if taxing:
            cum_cons += cost_by_cat['construction'][m]
            cum_sold += sold[m]
            year_period += sum(cost_by_cat[c][m] for c in PERIOD_CATS)
            year_fin += sum(ints.values()) + fees + mid_int[m]
            year_other += other_in[m] + mid_recover[m]
            if m < base_n and (cal == 12 or m == base_n - 1):
                prog = D(1) if m >= completion else min(cum_cons / cons_total, D(1))
                rec_rev = net_sales * cum_sold * prog                       # 익금: 계약금액 × 작업진행률
                rec_inv = inv_total * rev['sales_rate'] * cum_sold * prog   # 손금: 분양분 원가 × 작업진행률
                income = (rec_rev - prev_rev) + year_other - (rec_inv - prev_inv) - year_period - year_fin
                year = int(month_label(s.start_month, m)[:4])
                used = ZERO
                if income > 0:
                    cap = income if s.sme else income * D('0.8')
                    for item in nol:
                        if year - item[0] > 15:
                            continue
                        u = min(item[1], cap - used)
                        item[1] -= u
                        used += u
                    nol = [x for x in nol if x[1] > 0]
                elif income < 0:
                    nol.append([year, -income])
                base_amt = max(income - used, ZERO)
                ct = _bracket_tax(base_amt, tax.brackets)
                lt = ct * tax.local_surtax_pct / 100
                pay_m = (year + 1 - int(s.start_month[:4])) * 12 + 3 - int(s.start_month[5:])
                if ct:
                    corp_pay[min(pay_m, n - 1)] += ct
                    local_pay[min(pay_m + 1, n - 1)] += lt
                tax_years.append({'year': year, 'progress': prog, 'contracted': cum_sold, 'revenue_recognized': rec_rev - prev_rev,
                                  'cost_recognized': rec_inv - prev_inv, 'period_cost': year_period, 'finance_cost': year_fin,
                                  'income': income, 'nol_used': used, 'tax_base': base_amt, 'corporate_tax': ct, 'local_tax': lt,
                                  'pay_month': month_label(s.start_month, pay_m)})
                prev_rev, prev_inv = rec_rev, rec_inv
                year_period = year_fin = year_other = ZERO
        cash += inflow - outflow
        # 만기 상환
        for l in L:
            if m == l['end'] and l['bal'] > 0:
                pay = l['bal']
                repays[l['name']] += pay
                l['bal'] -= pay
                cash -= pay
        # 부족 자금 인출
        need = s.minimum_cash - cash
        if need > 0:
            for l in L:
                if need <= 0:
                    break
                if l['start'] <= m < l['end'] or (l['start'] <= m and m == l['end'] == n - 1):
                    room = l['limit'] - l['drawn']
                    take = min(room, need)
                    if take > 0:
                        l['bal'] += take
                        l['drawn'] += take
                        draws[l['name']] += take
                        cash += take
                        need -= take
            if need > 0:
                extra_eq[m] = need
                cash += need
        # 여유 자금 조기상환 (sweep)
        surplus = cash - s.minimum_cash
        if s.sweep_pct > 0 and surplus > 0 and m >= s.sales_start_month:
            pool = surplus * s.sweep_pct / 100
            for l in L:
                if pool <= 0:
                    break
                pay = min(pool, l['bal'])
                if pay > 0:
                    l['bal'] -= pay
                    repays[l['name']] += pay
                    pool -= pay
                    cash -= pay
        # 마지막 달: 잔여 대출 전액 상환
        if m == n - 1:
            for l in L:
                if l['bal'] > 0:
                    repays[l['name']] += l['bal']
                    cash -= l['bal']
                    l['bal'] = ZERO
            if cash < 0:
                extra_eq[m] += -cash
                cash = ZERO
        for l in L:
            l['peak'] = max(l['peak'], l['bal'])
            l['bal_series'][m] = l['bal']
        cum_prog = sum(progress[:m + 1])
        rows.append({
            'month': month_label(s.start_month, m), 'idx': m,
            'phase': _phase(m, s, completion, move_in),
            'progress': float(progress[m]), 'progress_cum': float(cum_prog),
            'sold': float(sold[m]),
            'deposit': recv_dep[m], 'midpay': recv_mid[m], 'balance_pay': recv_bal[m], 'other_income': other_in[m],
            'vat_out': vat_out[m], 'vat_input': in_vat[m] if s.vat_settlement else ZERO,
            'vat_paid': vat_pay[m] if s.vat_settlement else vat_out[m],
            'corporate_tax': corp_pay[m], 'local_tax': local_pay[m],
            **{f'cost_{c}': cost_by_cat[c][m] for c in cats},
            'midpay_interest': mid_int[m], 'midpay_recovery': mid_recover[m], 'interest': sum(ints.values()), 'fees': fees,
            'equity_in': eq_in[m], 'extra_equity': extra_eq[m],
            'draw': sum(draws.values()), 'repay': sum(repays.values()),
            'draws': draws, 'repays': repays, 'interests': ints,
            'loan_balance': sum(l['bal'] for l in L), 'cash': cash,
        })

    # ── 4. 요약 · 수익률 ──
    residual = cash
    eq_flows = [-(eq_in[m] + extra_eq[m]) for m in range(n)]
    eq_flows[-1] += residual
    total_int = sum(l['interest'] for l in L)
    total_fee = sum(l['fees'] for l in L)
    total_mid = sum(mid_int) - sum(mid_recover)   # 시행사 순부담 (후불제는 회수분 차감)
    for l in L:
        if l['drawn'] == 0 and l['limit'] > 0:
            warnings.append(f"{l['name']}: 인출이 발생하지 않았습니다 (개시월·만기 또는 자금 순서를 확인하세요). 취급수수료는 반영됩니다.")
    if sum(extra_eq) > 0:
        first = next(r['month'] for r in rows if r['extra_equity'] > 0)
        warnings.append(f'대출 한도·기간으로 부족 자금을 충당하지 못해 추가 자기자본 {sum(extra_eq):,.0f}원이 필요합니다 (최초 {first}).')
    irr_m = _irr(eq_flows)
    vat_cash = [(in_vat[m] + vat_pay[m]) if s.vat_settlement else vat_out[m] for m in range(n)]
    unlev = [recv_dep[m] + recv_mid[m] + recv_bal[m] + other_in[m] - vat_cash[m] - sum(cost_by_cat[c][m] for c in cats)
             - mid_int[m] - corp_pay[m] - local_pay[m] for m in range(n)]
    irr_u = _irr(unlev)
    disc = (1 + s.discount_rate_pct / 100) ** (D(1) / 12) - 1
    npv = sum(v / (1 + disc) ** i for i, v in enumerate(eq_flows))
    eq_total = sum(eq_in) + sum(extra_eq)
    return {
        'months': n, 'completion_month': month_label(s.start_month, completion), 'move_in_month': month_label(s.start_month, move_in),
        'installment_months': [month_label(s.start_month, i) for i in inst_months],
        'rows': rows,
        'loans': [{'name': l['name'], 'limit': l['limit'], 'drawn': l['drawn'], 'peak': l['peak'], 'interest': l['interest'],
                   'fees': l['fees'], 'start': month_label(s.start_month, l['start']), 'end': month_label(s.start_month, l['end']),
                   'utilization': (l['drawn'] / l['limit']) if l['limit'] else None} for l in L],
        'interest_total': total_int, 'fee_total': total_fee, 'midpay_interest_total': total_mid,
        'finance_total': total_int + total_fee + total_mid,
        'peak_loan': max((r['loan_balance'] for r in rows), default=ZERO),
        'equity_total': eq_total, 'extra_equity': sum(extra_eq), 'residual_cash': residual,
        'equity_irr_annual': _annual(irr_m), 'project_irr_annual': _annual(irr_u),
        'equity_multiple': (residual / eq_total) if eq_total else None,
        'equity_npv': npv,
        'min_cash': min((r['cash'] for r in rows), default=ZERO),
        'tax_years': tax_years, 'corporate_tax_total': sum(corp_pay), 'local_tax_total': sum(local_pay),
        'vat_net_total': sum(vat_cash), 'unused_nol': sum((x[1] for x in nol), ZERO),
        'base_months': base_n,
        'warnings': warnings,
    }


def _bracket_tax(base: Decimal, brackets) -> Decimal:
    tax, lower = ZERO, ZERO
    for b in brackets:
        upper = b.up_to if b.up_to is not None else base
        if base > lower:
            tax += (min(base, upper) - lower) * b.rate_pct / 100
        if b.up_to is None or base <= upper:
            break
        lower = upper
    return tax


def _phase(m, s, completion, move_in):
    if m < s.construction_start_month:
        return '토지·인허가'
    if m <= completion:
        return '공사'
    if m < move_in:
        return '준공'
    if m == move_in:
        return '입주·잔금'
    return '정산·세금'


def _irr(flows: list[Decimal]) -> float | None:
    f = [float(x) for x in flows]
    if not (any(x < 0 for x in f) and any(x > 0 for x in f)):
        return None
    npv = lambda r: sum(v / (1 + r) ** i for i, v in enumerate(f))
    # 부호가 여러 번 바뀌는 현금흐름도 있으므로 0%에서 바깥쪽으로 첫 부호 변화 구간을 찾는다 (월 −30% ~ +100%)
    base = npv(0.0)
    if base == 0:
        return 0.0
    step = 0.0025 if base > 0 else -0.0025
    lo, r = 0.0, step
    while -0.3 <= r <= 1.0 and npv(r) * base > 0:
        lo, r = r, r + step
    if not -0.3 <= r <= 1.0:
        return None
    lo, hi = (lo, r) if lo < r else (r, lo)
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _annual(r: float | None) -> float | None:
    return None if r is None else ((1 + r) ** 12 - 1) * 100
