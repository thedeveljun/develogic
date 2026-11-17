"""Date-based development cashflow engine. Amounts in KRW, Decimal precision."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict

D=lambda x: Decimal(str(x))
ZERO=D(0)

def month_key(day): return day.strftime('%Y-%m')
def amount(x): return D(x).quantize(D('1'),rounding=ROUND_HALF_UP)

def run_model(payload):
    """Daily event model. Explicit financing draws/repayments, no implicit funding.
    Loan interest accrues on daily opening balance; draw/repay events affect next day.
    Payment of accrued interest occurs on specified monthly interest payment day
    (or on last day of month if payment_day=0). No interest capitalization.
    """
    start=date.fromisoformat(payload['start']); end=date.fromisoformat(payload['end'])
    if end<start: raise ValueError('end must be >= start')
    if (end-start).days>365*30: raise ValueError('maximum 30 years')
    loans={x['id']:x for x in payload.get('loans',[])}
    if len(loans)!=len(payload.get('loans',[])): raise ValueError('duplicate loan ids')
    balances={k:ZERO for k in loans}; accrued={k:ZERO for k in loans}
    daily=defaultdict(list)
    for e in payload.get('events',[]):
        day=date.fromisoformat(e['date']); kind=e['type']; val=D(e['amount'])
        if not start<=day<=end: raise ValueError('event outside project period')
        if val<0: raise ValueError('negative amounts are not allowed')
        if kind not in ('receipt','cost','equity_in','equity_out','draw','repay'):
            raise ValueError('unknown event type: '+kind)
        if kind in ('draw','repay') and e.get('loan_id') not in loans:
            raise ValueError('loan_id required for financing event')
        daily[day].append((kind,val,e.get('loan_id')))
    rows=defaultdict(lambda:defaultdict(lambda:ZERO))
    cash=D(payload.get('opening_cash',0)); minimum=D(payload.get('minimum_cash',0))
    if minimum<0: raise ValueError('minimum_cash cannot be negative')
    day=start
    while day<=end:
        m=month_key(day)
        # Interest accrued before today's principal movements (opening daily balance).
        for lid,loan in loans.items():
            rate=D(loan['annual_rate']); basis=int(loan.get('day_basis',365))
            if rate<0 or basis not in (360,365,366): raise ValueError('invalid rate/day basis')
            accrued[lid]+=balances[lid]*rate/D(basis)
        for kind,val,lid in daily.get(day,[]):
            if kind=='draw':
                if balances[lid]+val>D(loans[lid]['limit']): raise ValueError(f'loan limit exceeded: {lid}')
                balances[lid]+=val; cash+=val
            elif kind=='repay':
                if val>balances[lid]: raise ValueError(f'principal repayment exceeds balance: {lid}')
                balances[lid]-=val; cash-=val
            elif kind in ('receipt','equity_in'): cash+=val
            else: cash-=val
            rows[m][kind]+=val
        tomorrow=day+timedelta(days=1)
        for lid,loan in loans.items():
            pay_day=int(loan.get('payment_day',0))
            if pay_day<0 or pay_day>31: raise ValueError('invalid payment day')
            last=tomorrow.month!=day.month
            # A payment day greater than month length settles on month end.
            due=last if pay_day==0 else (day.day==pay_day or (last and day.day<pay_day))
            if due:
                interest=amount(accrued[lid]); cash-=interest
                rows[m]['interest']+=interest; accrued[lid]=ZERO
        rows[m]['closing_cash']=cash
        rows[m]['loan_balance']=sum(balances.values(),ZERO)
        rows[m]['funding_gap']=max(ZERO,minimum-cash)
        day=tomorrow
    result=[]
    for m in sorted(rows):
        r=rows[m]
        result.append({'month':m,**{k:str(amount(r[k])) for k in ('receipt','cost','equity_in','equity_out','draw','repay','interest','closing_cash','loan_balance','funding_gap')}})
    return {'project_type':payload['project_type'],'months':result,
            'unpaid_accrued_interest':{k:str(amount(v)) for k,v in accrued.items()},
            'warning':'Unpaid interest at project end is disclosed separately; ensure loan maturity settlement.'}
