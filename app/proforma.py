"""시행사 사업수지(Pro-forma) 계산 엔진.

설계 원칙
- 모든 금액은 Decimal 로 계산하고 출력 시 원 단위로 반올림한다.
- 사업비 항목은 '산정 기준(basis)'을 선택해 입력한다. 같은 항목도 사업지마다
  평당·비율·정액 등 산정 방식이 다르기 때문이다.
- 분양률·분양가 변동에 비례하는 항목(분양대행·광고·보증·신탁·학교용지부담금·
  중도금 이자 등)이 있으므로, 세전이익은 분양률에 대해 1차식이다. 이를 이용해
  BEP 분양률을 정확히 계산한다.
- 부가세·법인세는 단순화된 추정이다. 실제 안분·세율은 세무 검토로 확정해야 한다.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
import math
from pydantic import BaseModel, Field, field_validator, model_validator
from . import schedule as sched
from . import lawdata
from . import rental as rentalmod

D = Decimal
ZERO = D(0)
NATIONAL_HOUSING_SQM = D(85)    # 국민주택규모(전용 85㎡) — 초과분은 건물분 부가세 과세

UnitKind = Literal['apartment', 'officetel', 'retail', 'office', 'knowledge', 'datacenter', 'other']   # 공동주택·오피스텔·상가근생·업무·지식산업센터·데이터센터·기타
Category = Literal['land', 'construction', 'indirect', 'charges', 'sales', 'taxes', 'admin', 'contingency']
Basis = Literal[
    'fixed',             # 정액 (원)
    'per_land_py',       # 대지 평당 (원/평)
    'per_above_py',      # 지상 연면적 평당
    'per_below_py',      # 지하 연면적 평당
    'per_gfa_py',        # 전체 연면적 평당
    'per_supply_py',     # 분양(공급)면적 평당
    'per_unit',          # 세대(호)당 — 주거(아파트·오피스텔) 세대수
    'monthly',           # 월 금액 × 사업기간
    'pct_land',          # 토지비(정액·평당 항목 합계) 대비 %
    'pct_construction',  # 공사비(정액·평당 항목 합계) 대비 %
    'pct_sales',         # 분양대금(VAT 포함, 분양률 반영, 발코니 포함) 대비 %
    'pct_apt_sales',     # 공동주택 분양대금 대비 % (학교용지부담금 등)
    'pct_total',         # 위 항목 전체 합계 대비 % (예비비)
    'pct_direct',        # 직접공사비(연면적 평당 공사비 항목) 대비 %
    'pct_construction_total',  # 공사비 분류 전체(비율 항목 포함) 대비 %
    'pct_general_sales', # 일반분양대금 대비 % (분양대행 등, 조합원분 제외)
    'auto_school', 'auto_metro', 'auto_sewer', 'auto_water',          # 법정 자동: 부담금 (app/levies.py)
    'auto_preservation', 'auto_land_tax', 'auto_holding',            # 법정 자동: 제세공과금
]
PCT_BASES = {'pct_land', 'pct_construction', 'pct_sales', 'pct_apt_sales', 'pct_total', 'pct_direct', 'pct_construction_total',
             'pct_general_sales'}
DIRECT_BASES = {'per_above_py', 'per_below_py', 'per_gfa_py'}

CATEGORY_NAMES = {
    'land': '토지비', 'construction': '공사비', 'indirect': '설계·감리·용역비', 'charges': '부담금·인입비',
    'sales': '분양·판매비', 'taxes': '제세공과금', 'admin': '일반관리비', 'contingency': '예비비',
}


class UnitType(BaseModel):
    name: str = ''

    @field_validator('name')
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip() or '미지정 타입'   # 타입 추가 직후 이름을 입력하는 중에도 계산되도록
    kind: UnitKind = 'apartment'
    exclusive_sqm: Decimal = Field(ge=0, description='전용면적 ㎡ (부가세 과세 판정)')
    supply_sqm: Decimal = Field(gt=0, description='세대(호)당 분양·공급면적 ㎡')
    count: int = Field(ge=0)
    price_per_py: Decimal = Field(ge=0, description='공급면적 평당 분양가 (원)')
    buyer: Literal['general', 'member', 'rental'] = Field(default='general', description='일반분양 / 조합원분양 / 임대(매각)')
    market_deposit: Decimal = Field(default=ZERO, ge=0, description='임대: 세대당 시세 보증금')
    market_rent: Decimal = Field(default=ZERO, ge=0, description='임대: 세대당 시세 월임대료')


class CostItem(BaseModel):
    category: Category
    name: str = Field(min_length=1)
    basis: Basis = 'fixed'
    value: Decimal = Field(ge=0, description='금액(원) 또는 비율(%)')
    note: str = ''
    timing: sched.Timing = 'auto'


class LoanTranche(BaseModel):
    name: str = Field(min_length=1)
    amount: Decimal = Field(ge=0)
    annual_rate_pct: Decimal = Field(ge=0, le=50)
    months: Decimal = Field(ge=0, le=240)
    utilization_pct: Decimal = Field(default=D(100), ge=0, le=100, description='기간 평균 인출률')
    fee_pct: Decimal = Field(default=ZERO, ge=0, le=20, description='취급·주관·자문 수수료')
    start_month: int = Field(default=0, ge=0, le=240, description='인출 개시월 (사업 개시 = 0)')
    maturity_month: int | None = Field(default=None, ge=0, le=300, description='만기월 (비우면 입주·잔금월에 상환)')


class MidpayLoan(BaseModel):
    enabled: bool = True   # 이전 저장분 호환: False 이면 유이자로 처리
    mode: Literal['interest_free', 'deferred', 'with_interest'] = Field(
        default='interest_free', description='무이자(시행사 부담) / 이자후불제(시행사 대납 → 입주 시 회수) / 유이자(수분양자 부담)')
    ratio_pct: Decimal = Field(default=D(60), ge=0, le=100, description='분양대금 중 중도금 비율')
    annual_rate_pct: Decimal = Field(default=D('4.5'), ge=0, le=30)
    avg_months: Decimal = Field(default=D(18), ge=0, le=120, description='평균 대출기간(개월)')
    developer_share_pct: Decimal = Field(default=D(100), ge=0, le=100, description='무이자: 시행사 부담 비율')

    def effective_mode(self) -> str:
        return self.mode if self.enabled else 'with_interest'


class TaxBracket(BaseModel):
    up_to: Decimal | None = None  # None = 초과 전 구간
    rate_pct: Decimal = Field(ge=0, le=100)


class CorporateTax(BaseModel):
    enabled: bool = True
    brackets: list[TaxBracket] = Field(default_factory=lambda: [
        TaxBracket(up_to=D(200_000_000), rate_pct=D(10)),
        TaxBracket(up_to=D(20_000_000_000), rate_pct=D(20)),
        TaxBracket(up_to=D(300_000_000_000), rate_pct=D(22)),
        TaxBracket(up_to=None, rate_pct=D(25)),
    ])
    local_surtax_pct: Decimal = Field(default=D(10), ge=0, le=100, description='지방소득세 (법인세액 대비)')


class ZoneArea(BaseModel):
    zone: str
    area_sqm: Decimal = Field(gt=0)


PLAN_KINDS = {'none': '해당 없음', 'district': '지구단위계획', 'redevelopment': '재개발사업 (도시정비법)',
              'reconstruction': '재건축사업 (도시정비법)', 'small': '소규모주택정비 (빈집법: 가로주택·소규모재건축 등)'}


class UrbanPlan(BaseModel):
    """3차: 지자체 도시계획 결정고시(지구단위계획·정비계획)의 용적률. 있으면 조례보다 우선 적용."""
    kind: Literal['none', 'district', 'redevelopment', 'reconstruction', 'small'] = 'none'
    title: str = ''
    notice_no: str = ''
    notice_date: str = ''
    url: str = ''
    base_far: Decimal | None = Field(default=None, ge=0, le=2000, description='기준용적률 / 정비계획 용적률')
    allowed_far: Decimal | None = Field(default=None, ge=0, le=2000, description='허용용적률 (인센티브 달성분 반영)')
    max_far: Decimal | None = Field(default=None, ge=0, le=2000, description='상한용적률 / 법적상한용적률')
    plan_bcr: Decimal | None = Field(default=None, ge=0, le=100, description='계획 건폐율 상한')
    public_land_sqm: Decimal = Field(default=ZERO, ge=0, description='공공시설 등 부지 제공(기부채납) 면적')
    use_max: bool = Field(default=False, description='상한·법적상한 용적률 적용 (임대주택·공공기여 요건 충족 전제)')
    housing_ratio_pct: Decimal = Field(default=ZERO, ge=0, le=100, description='초과 용적률 중 국민주택규모·공공임대 건설 비율')
    block: str = Field(default='', description='결정조서의 획지·블록·가구 (예: 1-C1, 택지1, BL 20)')
    max_floors: int | None = Field(default=None, description='결정고시 최고층수')
    height_limit_m: Decimal | None = Field(default=None, description='결정고시 최고높이(m)')
    allowed_uses: str = Field(default='', description='결정고시 허용(지정·권장)용도 요약')
    res_far: Decimal | None = Field(default=None, description='결정고시 주거부문 용적률 상한 (예: 전체 275% 중 주거 220%)')

    @field_validator('res_far', mode='before')
    @classmethod
    def _res_far(cls, v):
        try:
            x = Decimal(str(v)) if v not in (None, '') else None
        except Exception:
            return None
        return x if x is not None and 0 < x <= 2000 else None

    # 참고용 항목이라 범위를 벗어난 값(판독 오류·오타)은 분석 전체를 막지 않고 비우거나 자른다
    @field_validator('block', 'allowed_uses', mode='before')
    @classmethod
    def _text(cls, v, info):
        v = '' if v is None else str(v).strip()
        return v[:40] if info.field_name == 'block' else v[:400]

    @field_validator('max_floors', mode='before')
    @classmethod
    def _floors(cls, v):
        try:
            n = round(float(v)) if v not in (None, '') else None
        except (TypeError, ValueError):
            return None
        return n if n is not None and 1 <= n <= 200 else None

    @field_validator('height_limit_m', mode='before')
    @classmethod
    def _height(cls, v):
        try:
            x = Decimal(str(v)) if v not in (None, '') else None
        except Exception:
            return None
        return x if x is not None and 0 < x <= 1000 else None


class Parcel(BaseModel):
    address: str = ''
    area_sqm: Decimal = Field(default=ZERO, ge=0)
    zone: str = ''
    jimok: str = ''
    price_per_sqm: Decimal | None = None
    pnu: str = ''
    uses: list[dict] = []
    auto: dict = {}          # 주소 조회로 자동 입력된 값 (화면 구분 표시용)
    manual: bool = False     # 지번 미확정 토지(도시개발·택지 블록 등) — 면적·용도지역 직접 입력, 필지 조회 안 함


class Site(BaseModel):
    address: str | None = None
    parcels: list[Parcel] = []
    province: str | None = None
    municipality: str | None = None
    zones: list[ZoneArea] = []
    incentive_far_pct: Decimal = Field(default=ZERO, ge=0, le=500)
    building_area_sqm: Decimal | None = Field(default=None, ge=0, description='계획 건축면적')
    plan_parking: int | None = Field(default=None, ge=0, description='계획 주차대수')
    parking_area_per_space: Decimal = Field(default=D(33), gt=0, le=80, description='지하주차장 대당 소요면적(램프·통로 포함)')
    auto_far: bool = Field(default=True, description='조례 허용 연면적을 지상 연면적에 자동 대입')
    plan: UrbanPlan = Field(default_factory=UrbanPlan)
    flags: list[str] = []


HUG_PF_RATES = [D('0.563'), D('0.697'), D('0.848'), D('0.982'), D('1.104')]   # 심사등급 1~5, 연 %
HUG_SOURCE = 'HUG 상품안내 (khug.or.kr, 2026-11-16 열람): 주택사업금융보증·신축매입약정 사업비 대출보증·주택분양보증'


class HugGuarantee(BaseModel):
    """HUG(주택도시보증공사) 보증을 통한 사업비 조달."""
    enabled: bool = False
    product: Literal['pf', 'purchase'] = Field(default='pf', description='주택사업금융보증(PF·표준PF) / 신축매입약정 사업비 대출보증')
    business: Literal['sale', 'urban', 'rental'] = Field(default='sale', description='분양 / 도시형생활주택·오피스텔 / 임대')
    temp_relief: bool = Field(default=True, description='2027.6.30까지 한시 특례 (한도 70%·80%, 자기자금 완화)')
    top_contractor: bool = Field(default=False, description='시공능력평가 100위(도생·오피 200위) 이내')
    grade: int = Field(default=3, ge=1, le=5, description='HUG 사업 심사등급')
    loan_name: str = Field(default='', description='보증 대상 대출명 (비우면 이름에 PF가 들어간 대출, 없으면 마지막 대출)')
    capital_region: bool = Field(default=True, description='수도권·광역시 여부 (연면적 요건·매입약정 한도)')
    land_trust: bool = Field(default=False, description='신축매입약정: 관리형 토지신탁 (요율 0.261%)')
    sale_guarantee: bool = Field(default=True, description='주택분양보증 (일반분양 30세대 이상 선분양 시 필수)')
    sale_build_rate_pct: Decimal = Field(default=D('0.25'), ge=D('0.144'), le=D('0.342'), description='분양보증 건축비 부분 연 요율 (신용·심사등급표 0.144~0.342%)')
    sale_discount_pct: Decimal = Field(default=ZERO, ge=0, le=60, description='분양보증료 한시 할인 (보도 기준 30%, 2027.5.31까지)')
    confirm_approval: bool = Field(default=False, description='사업계획승인 또는 건축허가 완료')
    confirm_land_trust: bool = Field(default=False, description='사업부지 확보 및 HUG(지정 신탁사) 신탁')
    confirm_contractor: bool = Field(default=False, description='시공사 HUG 신용등급 요건(PF BB+, 매입약정 C 이상)·책임준공')
    confirm_purchase_agreement: bool = Field(default=False, description='LH·SH·GH 신축매입약정 체결')


class Criteria(BaseModel):
    proportional_ok_pct: Decimal = D(100)
    proportional_risk_pct: Decimal = D(80)
    margin_min_pct: Decimal = D(10)
    margin_warn_pct: Decimal = D(5)
    bep_max_pct: Decimal = D(80)
    bep_warn_pct: Decimal = D(90)
    price_drop_min_pct: Decimal = D(10)
    equity_irr_min_pct: Decimal = D(15)
    ltc_max_pct: Decimal = D(85)


class MemberCase(BaseModel):
    name: str = Field(min_length=1)
    share_py: Decimal = Field(ge=0, description='대지지분(평)')
    appraisal: Decimal | None = Field(default=None, ge=0, description='종전평가액 (비우면 지분 × 평당 감정가)')
    apply_price: Decimal = Field(default=ZERO, ge=0, description='신청 평형 조합원 분양가액 (미신청 0)')


class PriorAssets(BaseModel):
    land_py: Decimal = Field(default=ZERO, ge=0, description='종전 토지 총면적(평)')
    appraisal_per_py: Decimal = Field(default=ZERO, ge=0, description='감정평가 평당가')
    appraisal_total: Decimal | None = Field(default=None, ge=0, description='종전자산 총액 (입력 시 우선)')
    members: int = Field(default=0, ge=0)
    cases: list[MemberCase] = []

    def total(self) -> Decimal:
        return self.appraisal_total if self.appraisal_total is not None else self.land_py * self.appraisal_per_py


class Proforma(BaseModel):
    project_name: str = '신규 사업'
    template_key: str = Field(default='', max_length=40, description='시작한 용도 템플릿 (법정 기준 초기화에 사용)')
    project_mode: Literal['developer', 'redevelopment', 'rental'] = 'developer'
    prior_assets: PriorAssets = Field(default_factory=PriorAssets)
    duration_months: int = Field(default=48, ge=1, le=240)
    land_area_sqm: Decimal = Field(gt=0)
    above_gfa_sqm: Decimal = Field(ge=0)
    below_gfa_sqm: Decimal = Field(default=ZERO, ge=0)
    units: list[UnitType] = Field(min_length=1)
    sales_rate_pct: Decimal = Field(default=D(100), ge=0, le=100)
    price_adjust_pct: Decimal = Field(default=ZERO, ge=-90, le=200)
    price_includes_vat: bool = True
    building_ratio_pct: Decimal = Field(default=D(60), ge=0, le=100, description='과세 분양가 중 건물분 비율')
    balcony_per_unit: Decimal = Field(default=ZERO, ge=0, description='공동주택 세대당 발코니 확장비(부가세 포함)')
    balcony_taxable: bool = True
    other_income: Decimal = Field(default=ZERO, ge=0)
    costs: list[CostItem] = []
    nondeductible_vat_pct: Decimal = Field(default=ZERO, ge=0, le=100, description='공사비 중 매입세액 불공제 부가세 비용 반영 비율')
    equity: Decimal = Field(default=ZERO, ge=0)
    loans: list[LoanTranche] = []
    midpay: MidpayLoan = Field(default_factory=MidpayLoan)
    corporate_tax: CorporateTax = Field(default_factory=CorporateTax)
    schedule: sched.Schedule | None = None
    site: Site = Field(default_factory=Site)
    criteria: Criteria = Field(default_factory=Criteria)
    hug: HugGuarantee = Field(default_factory=HugGuarantee)
    rental: rentalmod.RentalPlan = Field(default_factory=rentalmod.RentalPlan)

    @model_validator(mode='after')
    def _check(self):
        for u in self.units:
            if u.exclusive_sqm > u.supply_sqm:
                raise ValueError(f'{u.name}: 전용면적이 공급면적보다 큽니다')
        return self


def py(sqm: Decimal) -> Decimal:
    return sqm * 121 / 400  # 1평 = 400/121 ㎡ (정확값)


def won(x: Decimal) -> int:
    return int(x.quantize(D(1), rounding=ROUND_HALF_UP))


def _ratio(a: Decimal, b: Decimal) -> float | None:
    return float(a / b) if b else None


def _is_taxable(u: UnitType) -> bool:
    """건물분 부가세 과세 여부: 국민주택규모 초과 주택, 오피스텔·상가 등 비주택."""
    if u.kind == 'apartment':
        return u.exclusive_sqm > NATIONAL_HOUSING_SQM
    return True


def _revenue(p: Proforma, sales_rate: Decimal, price_adj: Decimal):
    sold = sales_rate / 100
    adj = 1 + price_adj / 100
    br = p.building_ratio_pct / 100
    rows = []
    cash = net = vat = apt_cash = ZERO
    gen_cash = ZERO
    for u in p.units:
        sold_u = sold if u.buyer == 'general' else D(1)   # 조합원·임대분은 분양률과 무관
        list_amt = py(u.supply_sqm) * u.price_per_py * u.count * adj * sold_u
        taxable = _is_taxable(u)
        if taxable:
            if p.price_includes_vat:
                u_vat = list_amt * br / 11
                u_cash, u_net = list_amt, list_amt - u_vat
            else:
                u_vat = list_amt * br / 10
                u_cash, u_net = list_amt + u_vat, list_amt
        else:
            u_vat, u_cash, u_net = ZERO, list_amt, list_amt
        if u.buyer == 'general':
            gen_cash += u_cash
        rows.append({'name': u.name, 'kind': u.kind, 'buyer': u.buyer, 'count': u.count, 'taxable': taxable,
                     'exclusive_sqm': float(u.exclusive_sqm), 'supply_sqm': float(u.supply_sqm),
                     'supply_py_total': float(py(u.supply_sqm) * u.count),
                     'unit_price': won(py(u.supply_sqm) * u.price_per_py * adj),
                     'cash': won(u_cash), 'vat': won(u_vat), 'net': won(u_net)})
        cash += u_cash; net += u_net; vat += u_vat
        if u.kind == 'apartment':
            apt_cash += u_cash
    apt_units = sum(u.count for u in p.units if u.kind == 'apartment')
    bal_cash = p.balcony_per_unit * apt_units * sold
    bal_vat = bal_cash / 11 if p.balcony_taxable else ZERO
    total_cash = cash + bal_cash
    return {
        'rows': rows,
        'sales_cash': cash, 'sales_vat': vat, 'sales_net': net,
        'apt_cash': apt_cash,
        'balcony_cash': bal_cash, 'balcony_vat': bal_vat, 'balcony_net': bal_cash - bal_vat,
        'other_income': p.other_income,
        'total_cash': total_cash + p.other_income,
        'total_vat': vat + bal_vat,
        'total_net': net + bal_cash - bal_vat + p.other_income,
        'pct_sales_base': total_cash,
        'general_cash': gen_cash,
        'sales_rate': sold,
    }


def _costs(p: Proforma, rev: dict):
    land_py = py(p.land_area_sqm)
    above_py, below_py = py(p.above_gfa_sqm), py(p.below_gfa_sqm)
    supply_py = sum((py(u.supply_sqm) * u.count for u in p.units), ZERO)
    res_units = sum(u.count for u in p.units if u.kind in ('apartment', 'officetel'))
    first = {
        'fixed': D(1), 'per_land_py': land_py, 'per_above_py': above_py, 'per_below_py': below_py,
        'per_gfa_py': above_py + below_py, 'per_supply_py': supply_py, 'per_unit': D(res_units),
        'monthly': D(p.duration_months),
    }
    amounts: list[Decimal | None] = [None] * len(p.costs)
    for i, c in enumerate(p.costs):
        if c.basis in first:
            amounts[i] = c.value * first[c.basis]
    land_base = sum((a for a, c in zip(amounts, p.costs) if a is not None and c.category == 'land'), ZERO)
    cons_base = sum((a for a, c in zip(amounts, p.costs) if a is not None and c.category == 'construction'), ZERO)
    direct = sum((a for a, c in zip(amounts, p.costs) if a is not None and c.category == 'construction' and c.basis in DIRECT_BASES), ZERO)
    second = {'pct_land': land_base, 'pct_construction': cons_base, 'pct_direct': direct,
              'pct_sales': rev['pct_sales_base'], 'pct_apt_sales': rev['apt_cash'], 'pct_general_sales': rev['general_cash']}
    for i, c in enumerate(p.costs):
        if c.basis in second:
            amounts[i] = c.value / 100 * second[c.basis]
    cons_all = sum((a for a, c in zip(amounts, p.costs) if a is not None and c.category == 'construction'), ZERO)
    for i, c in enumerate(p.costs):
        if c.basis == 'pct_construction_total':
            amounts[i] = c.value / 100 * cons_all
    # 법정 자동 산정 (부담금·제세공과금) — 근거·산식은 details 로 화면에 표시
    details: dict[int, str] = {}
    if any(c.basis.startswith('auto_') for c in p.costs):
        from . import levies
        indirect_all = sum((a for a, c in zip(amounts, p.costs) if a is not None and c.category == 'indirect'), ZERO)
        adj = 1 + p.price_adjust_pct / 100
        for i, c in enumerate(p.costs):
            if not c.basis.startswith('auto_'):
                continue
            if c.basis == 'auto_school':
                a, d = levies.school_levy(p, adj)
            elif c.basis == 'auto_metro':
                a, d = levies.metro_levy(p)
            elif c.basis in ('auto_sewer', 'auto_water'):
                a, d = levies.utility_levy(p, c.basis, c.value)
            elif c.basis == 'auto_preservation':
                a, d = levies.preservation_tax(p, cons_all + indirect_all)
            elif c.basis == 'auto_land_tax':   # 과세표준 = 토지 매입대금(이름에 매입·토지대금 등), 없으면 토지비 합계
                import re as _re
                purchase = sum((x for x, cc in zip(amounts, p.costs) if x is not None and cc.category == 'land' and not cc.basis.startswith(('pct_', 'auto_'))
                                and _re.search(r'매입|토지\s*대금|토지비|대지', cc.name)), ZERO)
                a, d = levies.land_tax(p, purchase or land_base)
            else:
                a, d = levies.holding_tax(p)
            amounts[i], details[i] = a, d
    vat_cost = cons_base * D('0.1') * p.nondeductible_vat_pct / 100
    subtotal = sum((a for a in amounts if a is not None), ZERO) + vat_cost
    for i, c in enumerate(p.costs):
        if c.basis == 'pct_total':
            amounts[i] = c.value / 100 * subtotal
    items = [{'category': c.category, 'name': c.name, 'basis': c.basis, 'value': float(c.value), 'amount': a, 'timing': c.timing,
              **({'detail': details[i]} if i in details else {})}
             for i, (c, a) in enumerate(zip(p.costs, amounts))]
    if p.hug.enabled:
        dev_total = sum((a for a in amounts if a is not None), ZERO) + vat_cost
        if hug_eligibility(p, land_base, dev_total)['eligible']:
            items += hug_items(p, rev, land_base, dev_total)
    if vat_cost:
        items.append({'category': 'construction', 'name': '공사비 불공제 부가세', 'basis': 'derived',
                      'value': float(p.nondeductible_vat_pct), 'amount': vat_cost, 'timing': 'construction_curve'})
    return items, {'land': land_base, 'construction': cons_base}


def _finance(p: Proforma, rev: dict):
    rows = []
    for l in p.loans:
        interest = l.amount * l.annual_rate_pct / 100 * l.months / 12 * l.utilization_pct / 100
        fee = l.amount * l.fee_pct / 100
        rows.append({'name': l.name, 'amount': l.amount, 'interest': interest, 'fee': fee})
    m = p.midpay
    mid = ZERO
    if m.effective_mode() == 'interest_free':   # 후불제는 입주 시 회수, 유이자는 수분양자 부담 → 사업비 0
        mid = (rev['sales_cash'] + rev['balcony_cash']) * m.ratio_pct / 100 * m.annual_rate_pct / 100 \
            * m.avg_months / 12 * m.developer_share_pct / 100
    return rows, mid


def _tax(p: Proforma, pbt: Decimal) -> Decimal:
    t = p.corporate_tax
    if not t.enabled or pbt <= 0:
        return ZERO
    tax, lower = ZERO, ZERO
    for b in t.brackets:
        upper = b.up_to if b.up_to is not None else pbt
        if pbt > lower:
            tax += (min(pbt, upper) - lower) * b.rate_pct / 100
        if b.up_to is None or pbt <= upper:
            break
        lower = upper
    return tax * (1 + t.local_surtax_pct / 100)


def hug_loan(p: Proforma):
    if not p.loans:
        return None
    if p.hug.loan_name:
        return next((l for l in p.loans if l.name == p.hug.loan_name), None)
    return next((l for l in p.loans if 'PF' in l.name.upper()), p.loans[-1])


def hug_terms(p: Proforma, land: Decimal, dev_total: Decimal) -> dict:
    """보증한도·자기자금 선투입 요건·보증료율 (HUG 상품안내 기준)."""
    h = p.hug
    if h.product == 'purchase':
        ratio = D(90) if h.capital_region else D(80)
        equity_req = land * D('0.10')
        rate = D('0.261') if h.land_trust else D('0.441')
        rate_note = '신축매입약정 사업비 대출보증 연 ' + str(rate) + '%'
    else:
        if h.business == 'rental':
            ratio, equity_req = D(70), dev_total * D('0.05')
        else:
            ratio = (D(70) if h.business == 'sale' else D(80)) if h.temp_relief else D(50)
            if h.temp_relief and h.top_contractor:
                equity_req = max(land * D('0.05'), dev_total * D('0.01'))
            else:
                equity_req = max(land * D('0.10'), dev_total * D('0.02'))
        rate = HUG_PF_RATES[h.grade - 1]
        inv = p.equity / dev_total * 100 if dev_total else ZERO
        disc = D(20) if inv > 20 else D(10) if inv > 15 else D(5) if inv > 10 else ZERO
        rate = rate * (1 - disc / 100)
        rate_note = f'주택사업금융보증 {h.grade}등급 연 {float(HUG_PF_RATES[h.grade - 1]):g}%' + (f' − 투자금 비율 할인 {disc:g}%' if disc else '')
    return {'limit_ratio': ratio, 'limit': dev_total * ratio / 100, 'equity_required': equity_req, 'rate': rate, 'rate_note': rate_note}


def hug_eligibility(p: Proforma, land: Decimal, dev_total: Decimal) -> dict:
    """HUG 보증 이용 가능 여부 (khug.or.kr 상품안내 기준). 자동 판정 + 사용자 확인 항목."""
    h = p.hug
    gfa = p.above_gfa_sqm + p.below_gfa_sqm
    res_units = sum(u.count for u in p.units if u.kind in ('apartment', 'officetel'))
    general_units = sum(u.count for u in p.units if u.buyer == 'general' and u.kind in ('apartment', 'officetel'))
    t = hug_terms(p, land, dev_total)
    checks = []
    def add(name, ok, detail, kind='auto'):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail, 'kind': kind})
    if h.product == 'pf':
        need = D(5000) if (h.business == 'rental' or h.capital_region) else D(10000)
        add('보증 대상 연면적', gfa >= need, f"연면적 {float(gfa):,.0f}㎡ / 최소 {float(need):,.0f}㎡ "
            f"({'임대사업' if h.business == 'rental' else '분양 · 수도권·광역시' if h.capital_region else '분양 · 그 밖의 지역'})")
        redev = p.project_mode == 'redevelopment' and p.site.plan.kind == 'redevelopment'
        add('사업 유형', not redev, '주택재개발사업은 주택사업금융보증 대상에서 제외' if redev else '보증 대상 사업 유형')
    else:
        add('사업 규모', res_units >= 30, f'주거 {res_units}세대 / 최소 30세대 (신축매입약정)')
        add('신축매입약정 체결', h.confirm_purchase_agreement, 'LH·SH·GH와 매입약정 체결', 'confirm')
    add('자기자금 선투입', p.equity >= t['equity_required'],
        f"자기자본 {rentalmod.eok(p.equity)} / 요건 {rentalmod.eok(t['equity_required'])}")
    add('사업계획승인·건축허가', h.confirm_approval, '사업계획승인 또는 건축허가를 받은 사업', 'confirm')
    add('사업부지 확보·신탁', h.confirm_land_trust, '부지 확보 후 HUG 또는 지정 신탁사에 신탁', 'confirm')
    add('시공사 요건', h.confirm_contractor,
        ('HUG 신용등급 BB+ 이상 · 책임준공' if h.product == 'pf' else 'HUG 신용등급 C 이상 · 책임준공'), 'confirm')
    sale_ok = general_units >= 30 and h.business != 'rental' and h.product == 'pf'
    return {'eligible': all(c['ok'] for c in checks), 'checks': checks,
            'sale_guarantee_allowed': sale_ok, 'general_units': general_units,
            'source': 'HUG 상품안내 (khug.or.kr, 2026-11-16 열람)'}


def hug_items(p: Proforma, rev: dict, land: Decimal, dev_total: Decimal) -> list[dict]:
    t = hug_terms(p, land, dev_total)
    out = []
    loan = hug_loan(p)
    if loan:
        guaranteed = min(loan.amount, t['limit'])
        months = (D(loan.maturity_month - loan.start_month) if loan.maturity_month is not None else loan.months)
        fee = guaranteed * t['rate'] / 100 * months / 12
        out.append({'category': 'admin', 'name': 'HUG PF보증료', 'basis': 'derived', 'value': float(t['rate']), 'amount': fee,
                    'timing': 'construction_start'})
    general_units = sum(u.count for u in p.units if u.buyer == 'general' and u.kind in ('apartment', 'officetel'))
    if p.hug.sale_guarantee and p.hug.product == 'pf' and p.hug.business != 'rental' and general_units >= 30:
        sc = p.schedule
        dep_mid = (sc.deposit_pct + sc.midpay_pct) / 100 if sc else D('0.7')
        period = D((sc.construction_start_month + sc.construction_months + sc.move_in_lag_months) - sc.sales_start_month) if sc else D(30)
        amt = rev['general_cash'] * dep_mid
        land_share = land / dev_total if dev_total else ZERO
        rate = (land_share * D('0.133') + (1 - land_share) * p.hug.sale_build_rate_pct) * (1 - p.hug.sale_discount_pct / 100)
        out.append({'category': 'sales', 'name': 'HUG 주택분양보증료', 'basis': 'derived', 'value': float(rate),
                    'amount': amt * rate / 100 * max(period, D(1)) / 12, 'timing': 'sales_start'})
    return out


def hug_check(p: Proforma, items: list[dict], gfa_total: Decimal) -> list[dict]:
    """HUG 보증 요건 점검 (판정 항목)."""
    if not p.hug.enabled:
        return []
    h = p.hug
    land = sum((i['amount'] for i in items if i['category'] == 'land'), ZERO)
    dev = sum((i['amount'] for i in items if not i['name'].startswith('HUG')), ZERO)
    el = hug_eligibility(p, land, dev)
    if not el['eligible']:
        miss = [c['name'] for c in el['checks'] if not c['ok']]
        return [{'name': 'HUG 보증 이용 요건', 'status': 'bad',
                 'detail': '요건 미충족으로 HUG 보증을 적용하지 않았습니다: ' + ', '.join(miss)}]
    t = hug_terms(p, land, dev)
    loan = hug_loan(p)
    res = []
    if loan:
        ok = loan.amount <= t['limit']
        res.append({'name': 'HUG 보증한도', 'status': 'ok' if ok else 'bad',
                    'detail': f"{loan.name} {rentalmod.eok(loan.amount)} / 한도 {rentalmod.eok(t['limit'])} (총사업비 {float(t['limit_ratio']):g}%)"
                              + ('' if ok else ' — 한도 초과분은 보증되지 않습니다')})
    else:
        res.append({'name': 'HUG 보증한도', 'status': 'bad', 'detail': '보증 대상 대출이 없습니다'})
    res.append({'name': 'HUG 자기자금 선투입', 'status': 'ok' if p.equity >= t['equity_required'] else 'bad',
                'detail': f"자기자본 {rentalmod.eok(p.equity)} / 요건 {rentalmod.eok(t['equity_required'])}"})
    if h.product == 'pf':
        need = D(5000) if (h.business == 'rental' or h.capital_region) else D(10000)
        res.append({'name': 'HUG 보증 대상 연면적', 'status': 'ok' if gfa_total >= need else 'bad',
                    'detail': f"연면적 {float(gfa_total):,.0f}㎡ / 최소 {float(need):,.0f}㎡ ({'임대사업' if h.business == 'rental' else '수도권·광역시' if h.capital_region else '그 밖의 지역'}) · "
                              '시공사 HUG 신용등급 BB+ 이상·책임준공, 부지 신탁 필요'})
    if h.sale_guarantee and any('분양보증' in c.name for c in p.costs):
        res.append({'name': 'HUG 분양보증료 중복', 'status': 'warn', 'detail': '사업비에 별도 "분양보증" 항목이 있습니다. HUG 분양보증료가 자동 계산되므로 중복 여부를 확인하세요.'})
    res.append({'name': 'HUG 보증 조건 출처', 'status': 'ok', 'detail': HUG_SOURCE + ' · ' + t['rate_note'] + ' · 한시 특례 종료일과 최신 요율 확인 필요'})
    return res


def taxable_share(p: Proforma) -> Decimal:
    tot = sum((u.supply_sqm * u.count for u in p.units), ZERO)
    tx = sum((u.supply_sqm * u.count for u in p.units if _is_taxable(u)), ZERO)
    return tx / tot if tot else ZERO


def _core(p: Proforma, sales_rate: Decimal, price_adj: Decimal, with_cf: bool = True):
    rev = _revenue(p, sales_rate, price_adj)
    items, bases = _costs(p, rev)
    dev_cost = sum((i['amount'] for i in items), ZERO)
    cf = None
    if with_cf and p.schedule and p.schedule.enabled:
        cf = sched.run(p.schedule, p.duration_months, rev, items, p.loans, p.equity, p.midpay, p.corporate_tax, taxable_share(p))
        loans = [{'name': l['name'], 'amount': l['limit'], 'interest': l['interest'], 'fee': l['fees']} for l in cf['loans']]
        mid = cf['midpay_interest_total']
    else:
        loans, mid = _finance(p, rev)
    fin_cost = sum((l['interest'] + l['fee'] for l in loans), ZERO) + mid
    pbt = rev['total_net'] - dev_cost - fin_cost
    return rev, items, bases, loans, mid, dev_cost, fin_cost, pbt, cf


def _solve(f, lo: Decimal, hi: Decimal, iters: int = 40) -> float | None:
    """f(x)=0 인 x (f 단조 증가 가정)를 이분법으로 찾는다."""
    flo, fhi = f(lo), f(hi)
    if flo > 0 or fhi < 0:
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return float((lo + hi) / 2)


def analyze(p: Proforma) -> dict:
    if p.project_mode == 'rental':
        return analyze_rental(p)
    return analyze_sale(p)


def analyze_rental(p: Proforma) -> dict:
    """공공지원민간임대: 사업비 → 준공 자본구조 → 연 단위 운영 → 매각."""
    rev = _revenue(p, ZERO, ZERO)          # 분양 없음: 분양 연동 비용 기준 0
    items, bases = _costs(p, rev)
    if p.rental.auto_relief:               # 취득세(보존등기) 면적별 감면
        res = [u for u in p.units if u.kind in ('apartment', 'officetel') and u.count]
        tot = sum((u.supply_sqm * u.count for u in res), ZERO)
        rel = (sum((rentalmod.relief_pct(rentalmod.ACQUISITION_TAX_RELIEF, u.exclusive_sqm) * u.supply_sqm * u.count for u in res), ZERO) / tot) if tot else ZERO
        for it in items:
            if it['category'] == 'taxes' and ('보존' in it['name'] or '취득' in it['name']):
                it['amount'] = it['amount'] * (1 - rel / 100)
                it['name'] += f' (감면 {float(rel):.0f}% 반영)'
    rr = rentalmod.run(p, items)
    a = {'land_sqm': float(p.land_area_sqm), 'land_py': float(py(p.land_area_sqm)), 'above_gfa_sqm': float(p.above_gfa_sqm),
         'below_gfa_sqm': float(p.below_gfa_sqm), 'gfa_py': float(py(p.above_gfa_sqm + p.below_gfa_sqm)),
         'supply_py': float(sum((py(u.supply_sqm) * u.count for u in p.units), ZERO)),
         'far_pct': float(p.above_gfa_sqm / p.land_area_sqm * 100), 'units': sum(u.count for u in p.units),
         'residential_units': sum(u.count for u in p.units if u.kind in ('apartment', 'officetel'))}
    by_cat = []
    for key, label in CATEGORY_NAMES.items():
        rows = [i for i in items if i['category'] == key]
        if rows:
            amt = sum((r['amount'] for r in rows), ZERO)
            by_cat.append({'key': key, 'name': label, 'amount': won(amt), 'share': _ratio(amt, rr['total_cost']),
                           'items': [{**r, 'amount': won(r['amount'])} for r in rows]})
    by_cat.append({'key': 'finance', 'name': '금융비용 (건설기간)', 'amount': won(rr['construction_interest']),
                   'share': _ratio(rr['construction_interest'], rr['total_cost']),
                   'items': [{'category': 'finance', 'name': '건설기간 PF 이자', 'basis': 'derived', 'amount': won(rr['construction_interest'])}]})
    rows = rr['rows']
    life_rev = sum((x['rent'] for x in rows), ZERO) + rr['exit_value'] - rr['exit_sale_cost']
    life_cost = rr['total_cost'] + sum((x['opex'] + x['property_tax'] + x['guarantee_fee'] + x['interest'] for x in rows), ZERO)
    pbt = life_rev - life_cost
    tax = sum((x['tax'] for x in rows), ZERO) + rr['exit_gain_tax']
    c = p.rental
    def st(ok, warn=False): return 'ok' if ok else ('warn' if warn else 'bad')
    yoc, dscr, irr = rr['yield_on_cost_pct'], rr['min_dscr'], rr['equity_irr_pct']
    fin = [
        {'name': '임대수익률 (1년차 NOI ÷ 총사업비)', 'value': float(yoc) if yoc is not None else None,
         'display': f'{float(yoc):.2f}%' if yoc is not None else '–', 'status': st(yoc is not None and yoc >= c.yield_min_pct, yoc is not None and yoc >= c.yield_min_pct - 1),
         'rule': f'적합 ≥ {c.yield_min_pct}%'},
        {'name': '최저 DSCR', 'value': float(dscr) if dscr is not None else None, 'display': f'{float(dscr):.2f}배' if dscr is not None else '차입 없음',
         'status': st(dscr is None or dscr >= c.dscr_min, dscr is not None and dscr >= 1), 'rule': f'적합 ≥ {c.dscr_min}배'},
        {'name': f'Equity IRR ({c.hold_years}년 운영 후 매각, 세후)', 'value': irr, 'display': f'{irr:.1f}%' if irr is not None else '–',
         'status': st(irr is not None and irr >= c.irr_min_pct, irr is not None and irr >= 0), 'rule': f'적합 ≥ {c.irr_min_pct}%'},
    ]
    legal = [{'name': '민간임대 기준', 'status': 'bad' if rr['warnings'] else 'ok',
              'detail': ' / '.join(rr['warnings']) or f"의무임대 {c.hold_years}년 · 일반 {float(c.general_rent_ratio_pct):g}% · 특별공급 {float(c.special_share_pct):g}%·{float(c.special_rent_ratio_pct):g}% · 증액 {float(c.rent_growth_pct):g}%"}]
    comp = _compliance(p)
    comp['items'] += hug_check(p, items, p.above_gfa_sqm + p.below_gfa_sqm)
    legal += comp['items']
    stat = [x['status'] for x in fin + legal]
    overall = 'bad' if 'bad' in stat else 'warn' if 'warn' in stat else 'ok'
    conv = lambda v: won(v) if isinstance(v, Decimal) else v
    rental_out = {k: (conv(v) if not isinstance(v, (list, dict)) else v) for k, v in rr.items() if k not in ('rows', 'equity_flows')}
    for k in ('yield_on_cost_pct', 'min_dscr', 'rent_ratio_pct', 'fund_rate_pct', 'property_tax_relief_pct', 'special_rent_cap_pct', 'equity_multiple'):
        rental_out[k] = float(rr[k]) if rr[k] is not None else None
    rental_out['rows'] = [{k: (float(v) if k == 'dscr' and v is not None else conv(v)) for k, v in x.items()} for x in rows]
    rental_out['equity_flows'] = [won(v) for v in rr['equity_flows']]
    total_cost = rr['total_cost']
    return {
        'project_name': p.project_name, 'area': a,
        'revenue': {'rows': [], 'sales_cash': 0, 'sales_vat': 0, 'sales_net': 0, 'balcony_cash': 0, 'balcony_vat': 0, 'other_income': 0,
                    'total_cash': won(life_rev), 'total_vat': 0, 'total_net': won(life_rev)},
        'costs': by_cat,
        'summary': {'revenue_net': won(life_rev), 'development_cost': won(rr['dev_cost']), 'finance_cost': won(rr['construction_interest']),
                    'total_cost': won(total_cost), 'pbt': won(pbt), 'corporate_tax': won(tax), 'npat': won(pbt - tax),
                    'margin_pct': _pct(pbt, life_rev), 'cost_to_revenue_pct': _pct(life_cost, life_rev), 'roe_pct': _pct(pbt - tax, p.equity),
                    'cost_per_supply_py': won(total_cost / D(str(a['supply_py']))) if a['supply_py'] else None,
                    'cost_per_gfa_py': won(total_cost / D(str(a['gfa_py']))) if a['gfa_py'] else None,
                    'land_per_py': won(bases['land'] / py(p.land_area_sqm)), 'construction_per_gfa_py': won(bases['construction'] / D(str(a['gfa_py']))) if a['gfa_py'] else None,
                    'bep_sales_rate_pct': None, 'price_drop_tolerance_pct': None, 'equity_irr_pct': irr, 'project_irr_pct': None,
                    'equity_multiple': rental_out['equity_multiple'], 'peak_loan': None, 'extra_equity': None,
                    'equity': won(p.equity), 'debt': won(rr['mortgage'] + rr['fund_loan']), 'ltc_pct': _pct(rr['mortgage'] + rr['fund_loan'], total_cost),
                    'tax_method': f'연도별 (NOI−이자−감가상각) + 매각 양도차익'},
        'sensitivity': {'sales_rates': [], 'price_adjusts': [], 'cells': []},
        'redevelopment': None, 'cashflow': None, 'compliance': comp, 'rental': rental_out,
        'hug_eligibility': hug_eligibility(p, bases['land'], rr['dev_cost']),
        'verdict': {**_label_reasons(overall, fin, legal), 'financial': fin, 'legal': legal, 'note': '판정 기준값(임대수익률·DSCR·IRR)은 사내 기준에 맞게 조정하세요. ' + ' / '.join(rr['sources'])},
        'warnings': rr['warnings'],
        'notice': '공공지원민간임대 사업수지는 입력한 시세·운영비·매각 가정에 따른 추정입니다. 표준임대료(시장전환율)·감면 가액 상한·기금 조건은 신청 시점 기준으로 확인하세요.',
    }


def analyze_sale(p: Proforma) -> dict:
    rev, items, bases, loans, mid, dev_cost, fin_cost, pbt, cf = _core(p, p.sales_rate_pct, p.price_adjust_pct)
    total_cost = dev_cost + fin_cost
    if cf and p.schedule.corporate_tax_by_progress and p.corporate_tax.enabled:
        tax = cf['corporate_tax_total'] + cf['local_tax_total']
    else:
        tax = _tax(p, pbt)
    npat = pbt - tax

    # BEP 분양률 · 분양가 하락 허용폭
    if cf:
        bep = _solve(lambda r: _core(p, r, p.price_adjust_pct)[7], ZERO, D(100))
        if bep is None and _core(p, D(100), p.price_adjust_pct)[7] < 0:
            bep = 999.0
        drop = _solve(lambda a: _core(p, D(100), p.price_adjust_pct + a)[7], D(-90), D(50))
    else:
        pbt0 = _core(p, ZERO, p.price_adjust_pct)[7]
        pbt100 = _core(p, D(100), p.price_adjust_pct)[7]
        slope = pbt100 - pbt0
        bep = float(-pbt0 / slope * 100) if slope > 0 else None
        pm = _core(p, D(100), p.price_adjust_pct - 10)[7]
        sl = (pbt100 - pm) / 10
        drop = float(-pbt100 / sl) if sl > 0 else None

    by_cat = []
    for key, label in CATEGORY_NAMES.items():
        rows = [i for i in items if i['category'] == key]
        if rows:
            amt = sum((r['amount'] for r in rows), ZERO)
            by_cat.append({'key': key, 'name': label, 'amount': won(amt), 'share': _ratio(amt, total_cost),
                           'items': [{**r, 'amount': won(r['amount'])} for r in rows]})
    fin_items = [{'category': 'finance', 'name': f"{l['name']} 이자", 'basis': 'derived', 'amount': won(l['interest'])} for l in loans] \
        + [{'category': 'finance', 'name': f"{l['name']} 수수료", 'basis': 'derived', 'amount': won(l['fee'])} for l in loans if l['fee']]
    if p.midpay.effective_mode() == 'interest_free':
        fin_items.append({'category': 'finance', 'name': '중도금 대출이자 (무이자 · 시행사 부담)', 'basis': 'derived', 'amount': won(mid)})
    by_cat.append({'key': 'finance', 'name': '금융비용', 'amount': won(fin_cost), 'share': _ratio(fin_cost, total_cost), 'items': fin_items})

    sens_rates = [D(60), D(70), D(80), D(90), D(100)]
    sens_prices = [D(-10), D(-5), D(0), D(5), D(10)]
    sensitivity = {'sales_rates': [float(r) for r in sens_rates], 'price_adjusts': [float(a) for a in sens_prices], 'cells': []}
    for a in sens_prices:
        row = []
        for r in sens_rates:
            c = _core(p, r, p.price_adjust_pct + a)
            row.append({'pbt': won(c[7]), 'margin': _ratio(c[7], c[0]['total_net'])})
        sensitivity['cells'].append(row)

    supply_py = sum((py(u.supply_sqm) * u.count for u in p.units), ZERO)
    gfa_py = py(p.above_gfa_sqm + p.below_gfa_sqm)
    debt = sum((l.amount for l in p.loans), ZERO)
    warnings = []
    if p.above_gfa_sqm and supply_py * 400 / 121 > p.above_gfa_sqm:
        warnings.append('분양(공급)면적 합계가 지상 연면적보다 큽니다. 면적 입력을 확인하세요.')
    if p.equity + debt < bases['land']:
        warnings.append('자기자본+대출이 토지비보다 작습니다. 토지 잔금 조달 계획을 확인하세요.')
    if bep is not None and bep > 100:
        warnings.append('100% 분양해도 손실입니다 (BEP 분양률 100% 초과).')
    if cf:
        warnings += cf['warnings']
    compliance = _compliance(p)
    compliance['items'] += hug_check(p, items, p.above_gfa_sqm + p.below_gfa_sqm)
    summary_tmp = {'margin_pct': _pct(pbt, rev['total_net']), 'bep': bep, 'drop': drop, 'ltc': _pct(debt, total_cost),
                   'proportional': _pct(pbt, p.prior_assets.total()) if p.project_mode == 'redevelopment' else None}
    verdict = _verdict(p, summary_tmp, cf, compliance)

    return {
        'project_name': p.project_name,
        'area': {
            'land_sqm': float(p.land_area_sqm), 'land_py': float(py(p.land_area_sqm)),
            'above_gfa_sqm': float(p.above_gfa_sqm), 'below_gfa_sqm': float(p.below_gfa_sqm),
            'gfa_py': float(gfa_py), 'supply_py': float(supply_py),
            'far_pct': float(p.above_gfa_sqm / p.land_area_sqm * 100),
            'units': sum(u.count for u in p.units),
            'residential_units': sum(u.count for u in p.units if u.kind in ('apartment', 'officetel')),
        },
        'revenue': {
            'rows': rev['rows'],
            'sales_cash': won(rev['sales_cash']), 'sales_vat': won(rev['sales_vat']), 'sales_net': won(rev['sales_net']),
            'balcony_cash': won(rev['balcony_cash']), 'balcony_vat': won(rev['balcony_vat']),
            'other_income': won(rev['other_income']),
            'total_cash': won(rev['total_cash']), 'total_vat': won(rev['total_vat']), 'total_net': won(rev['total_net']),
        },
        'costs': by_cat,
        'summary': {
            'revenue_net': won(rev['total_net']),
            'development_cost': won(dev_cost),
            'finance_cost': won(fin_cost),
            'total_cost': won(total_cost),
            'pbt': won(pbt),
            'corporate_tax': won(tax),
            'npat': won(npat),
            'margin_pct': _pct(pbt, rev['total_net']),
            'cost_to_revenue_pct': _pct(total_cost, rev['total_net']),
            'roe_pct': _pct(npat, p.equity),
            'cost_per_supply_py': won(total_cost / supply_py) if supply_py else None,
            'cost_per_gfa_py': won(total_cost / gfa_py) if gfa_py else None,
            'land_per_py': won(bases['land'] / py(p.land_area_sqm)),
            'construction_per_gfa_py': won(bases['construction'] / gfa_py) if gfa_py else None,
            'bep_sales_rate_pct': bep,
            'price_drop_tolerance_pct': drop,
            'equity_irr_pct': cf['equity_irr_annual'] if cf else None,
            'project_irr_pct': cf['project_irr_annual'] if cf else None,
            'equity_multiple': float(cf['equity_multiple']) if cf and cf['equity_multiple'] is not None else None,
            'peak_loan': won(cf['peak_loan']) if cf else None,
            'extra_equity': won(cf['extra_equity']) if cf else None,
            'tax_method': '진행기준 연도별 (다음해 3·4월 납부)' if cf and p.schedule.corporate_tax_by_progress else '세전이익 일괄 추정',
            'equity': won(p.equity), 'debt': won(debt),
            'ltc_pct': _pct(debt, total_cost),
        },
        'sensitivity': sensitivity,
        'redevelopment': _redev(p, rev, pbt) if p.project_mode == 'redevelopment' else None,
        'hug_eligibility': hug_eligibility(p, bases['land'], dev_cost),
        'cashflow': _cf_out(cf) if cf else None,
        'compliance': compliance,
        'verdict': verdict,
        'warnings': warnings,
        'notice': '입력 가정에 따른 산술 추정입니다. 부가세 안분·법인세·부담금은 세무·인허가 검토로 확정해야 하며 투자·대출 의사결정용 확정 수지가 아닙니다.',
    }


def _pct(a: Decimal, b: Decimal) -> float | None:
    return float(a / b * 100) if b else None


def _cf_out(cf: dict) -> dict:
    """현금흐름 결과를 응답용으로 정리 (원 단위 정수)."""
    def conv(v):
        if isinstance(v, Decimal):
            return won(v)
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    out = conv({k: v for k, v in cf.items() if k not in ('rows', 'tax_years', 'loans')})
    out['loans'] = [{**conv(l), 'utilization': float(l['utilization']) if l['utilization'] is not None else None} for l in cf['loans']]
    out['tax_years'] = [{**conv(t), 'progress': float(t['progress']), 'contracted': float(t['contracted'])} for t in cf['tax_years']]
    out['rows'] = [{**conv({k: v for k, v in r.items() if k not in ('progress', 'progress_cum', 'sold')}),
                    'progress': r['progress'], 'progress_cum': r['progress_cum'], 'sold': r['sold']} for r in cf['rows']]
    return out


def required_parking(p: Proforma) -> dict | None:
    """법정 주차대수.
    - 공동주택·오피스텔: 주택건설기준 등에 관한 규정 제27조①(주차장법 시행령 별표1 제5호) — 전용면적 합계 기준과 세대(호실)당 최소 중 큰 값.
      지자체 주차장 조례가 비율·세대당 최소를 따로 정하면 그 기준.
    - 비주거(상가·업무·지식산업센터·데이터센터·기타): 시설면적 ÷ 조례(없으면 시행령 별표1) ㎡당 1대.
      별표1 비고 4·6: 용도별 대수를 소수 첫째 자리까지 합산하고 소수점 이하 0.5 이상은 1대, 합계 1대 미만은 0대.
    시설면적은 타입별 분양(공급)면적 × 호수로 근사한다(공용 포함·주차장 제외 바닥면적)."""
    from . import parking
    res_units = [u for u in p.units if u.kind in ('apartment', 'officetel') and u.count]
    non = [u for u in p.units if u.kind not in ('apartment', 'officetel') and u.count]
    if not res_units and not non:
        return None
    rule = parking.resolve(p.site.province, p.site.municipality)
    region = lawdata.parking_region(p.site.province, p.site.municipality)
    rows, required, notes = [], 0, []
    ratio_txt = ''
    if res_units:
        rr = rule.get('residential') or {}
        if rr.get('complex'):   # 면적대별 세대당 대수 등 자동 적용하지 않는 형식
            notes.append('지자체 조례가 공동주택·오피스텔 주차를 면적대별 세대당 대수 등으로 따로 정하고 있어 자동 적용하지 않았습니다(국가 기준으로 계산). '
                         '조례 원문으로 확인하세요: ' + ((rule.get('texts') or {}).get('residential') or '')[:200])
            rr = {}
        bands = rr.get('bands')
        if bands:   # 면적대별 세대당 기준 (춘천·강릉·아산·이천·논산·양양 등)
            ex = rr.get('apt_min')
            total_b, miss = ZERO, []
            for u in res_units:
                v = parking.per_unit_spaces(rr, float(u.exclusive_sqm), u.kind == 'apartment')
                if v is None:   # 조례 면적대에 없는 큰 평형 → 국가 기준(전용 85㎡ 초과 ㎡당 1대, 세대당 1대 이상)
                    v = max(float(u.exclusive_sqm) / lawdata.PARKING_RATIO[region][1], 1.0)
                    miss.append(u.name)
                total_b += D(str(v)) * u.count
            res_req = math.ceil(total_b)
            required += res_req
            band_txt = ' / '.join(
                (f"전용 {b[0]:g}㎡ 이하 " if b[0] else '그 초과 ') +
                (f"{b[1]:g}대+(전용−{b[3]:g}㎡)÷{b[2]:g}㎡" if b[4] == 'extra' else
                 ' · '.join(x for x in [f'세대당 {b[1]:g}대' if b[1] else '', f'{b[2]:g}㎡당 1대' if b[2] else ''] if x))
                for b in bands) + (f' · 아파트 세대당 최소 {ex:g}대' if ex else '')
            kinds = '공동주택' + ('·오피스텔' if any(u.kind == 'officetel' for u in res_units) else '')
            rows.append({'use': kinds, 'basis': f'{sum(u.count for u in res_units):,}세대(호실)', 'rule': '조례 면적대별 기준: ' + band_txt,
                         'spaces': res_req, 'detail': f'세대(호실)별 대수 합계 {float(total_b):.1f}대'
                                                     + (f" · 면적대 밖({', '.join(miss)})은 국가 기준" if miss else '')})
            ratio_txt = '조례 면적대별 기준'
        else:
            r_small, r_large = lawdata.PARKING_RATIO[region]
            r_small, r_large = rr.get('small') or r_small, rr.get('large') or r_large
            tiers = rr.get('per_unit')
            def per_unit(e):
                if tiers:
                    return next((D(str(v)) for cap, v in tiers if cap is None or e <= D(str(cap))), D(1))
                return D('0.7') if e <= 60 else D(1)
            by_area = sum((u.exclusive_sqm * u.count / D(str(r_small if u.exclusive_sqm <= 85 else r_large)) for u in res_units), ZERO)
            by_unit = sum((u.count * per_unit(u.exclusive_sqm) for u in res_units), ZERO)
            res_req = max(math.ceil(by_area), math.ceil(by_unit))
            if rr.get('multiplier'):
                res_req = math.ceil(res_req * D(str(rr['multiplier'])))   # float 곱셈 오차로 1대 더 올라가지 않게 (100×1.1)
            required += res_req
            ratio_txt = f'85㎡ 이하 {r_small:g}㎡당 1대 / 85㎡ 초과 {r_large:g}㎡당 1대'
            tier_txt = (' · 세대당 최소 ' + ', '.join(f"{'전용 ' + format(c, 'g') + '㎡ 이하 ' if c else ''}{v:g}대" for c, v in tiers)) if tiers else ' · 세대당 최소 1대(60㎡ 이하 0.7대)'
            kinds = '공동주택' + ('·오피스텔' if any(u.kind == 'officetel' for u in res_units) else '')
            rows.append({'use': kinds, 'basis': f'전용면적 합계 {float(sum((u.exclusive_sqm * u.count for u in res_units), ZERO)):,.1f}㎡',
                         'rule': ratio_txt + tier_txt + (f" × {rr['multiplier']:g}배" if rr.get('multiplier') else ''),
                         'spaces': res_req, 'detail': f'면적 기준 {float(by_area):.1f}대 / 세대 기준 {float(by_unit):.1f}대 중 큰 값'})
    if non:
        total = ZERO
        for kind in ('retail', 'office', 'knowledge', 'datacenter', 'other'):
            us = [u for u in non if u.kind == kind]
            if not us:
                continue
            area = sum((u.supply_sqm * u.count for u in us), ZERO)
            per = D(str(rule['rates'].get(kind) or parking.NATIONAL[kind]))
            n = (area / per).quantize(D('0.1'), rounding='ROUND_DOWN')
            total += n
            rows.append({'use': parking.KIND_LABEL[kind], 'basis': f'시설면적 {float(area):,.1f}㎡', 'rule': f'시설면적 {float(per):g}㎡당 1대',
                         'spaces': float(n), 'detail': (rule.get('texts') or {}).get(kind, '')[:160]})
        non_req = 0 if total < 1 else int(total) + (1 if total - int(total) >= D('0.5') else 0)
        required += non_req
        rows.append({'use': '비주거 합계', 'basis': '', 'rule': '용도별 합산(소수 첫째 자리) → 0.5 이상 올림', 'spaces': non_req, 'detail': ''})
        if any(u.kind == 'retail' for u in non):
            notes.append('상가는 근린생활시설 기준입니다. 판매시설(대규모 점포 등)이면 업무·판매 기준으로 바뀝니다.')
        notes.append('비주거 시설면적은 분양(공급)면적 × 호수로 근사했습니다. 설계 바닥면적(주차장 제외)으로 확인하세요.')
    src = rule['source']
    lvl = '조례' if rule['level'] == 'ordinance' else '시행령(조례 미확인)'
    if rule['level'] != 'ordinance':
        notes.append('지자체 주차장 조례를 아직 불러오지 않아 국가 기준으로 계산했습니다. 조례는 대부분 더 엄격합니다(예: 상가 134㎡·업무 100㎡당 1대).')
    return {'region': lawdata.PARKING_REGION_NAMES[region] + f' · {lvl}', 'required': required, 'rows': rows,
            'review': bool((rule.get('residential') or {}).get('complex')) and bool(res_units),
            'ratio': ratio_txt or ' · '.join(f"{r['use']} {r['rule']}" for r in rows if r['use'] != '비주거 합계'),
            'source': {'title': src.get('title'), 'effective': src.get('effective'), 'url': src.get('url')}, 'level': rule['level'],
            'note': ' '.join(notes) or '지자체 주차장 조례 기준입니다. 원문과 대조하세요.'}


def residential_share(p: Proforma, include_officetel: bool = True) -> float | None:
    """연면적(분양면적 기준) 중 주거용 비율 %. 오피스텔은 준주택으로 포함(조례가 '공동주택 비율'이면 제외)."""
    kinds = ('apartment', 'officetel') if include_officetel else ('apartment',)
    tot = sum((u.supply_sqm * u.count for u in p.units), ZERO)
    if not tot:
        return None
    return float(sum((u.supply_sqm * u.count for u in p.units if u.kind in kinds), ZERO) / tot * 100)


def _compliance(p: Proforma) -> dict:
    st = p.site
    residential = any(u.kind == 'apartment' for u in p.units)
    has_ot = any(u.kind == 'officetel' for u in p.units)
    zones = st.zones or []
    items, allowed_gfa, allowed_fp, zrows, far_area = [], ZERO, ZERO, [], ZERO
    for z in zones:
        r = lawdata.resolve(st.province, st.municipality, z.zone)
        far, bcr = r['far'], r['bcr']
        o = lawdata.cached(st.province or '', st.municipality or '') if r['level'] in ('auto', 'ordinance') else None
        lim = (o or {}).get('limits', {}).get(z.zone, {})
        if residential and lim.get('far_apt') is not None:
            far = lim['far_apt']
            r['notes'].append(f"공동주택 별도 기준 {lim['far_apt']:g}% 적용 (일반 {lim.get('far'):g}%)")
        elif has_ot and lim.get('far_officetel') is not None and far is not None and lim['far_officetel'] < far:
            far = lim['far_officetel']
            r['notes'].append(f"오피스텔 복합 건축물 기준 {lim['far_officetel']:g}% 적용 (일반 {lim.get('far'):g}%)")
        if residential and lim.get('bcr_apt') is not None:
            bcr = lim['bcr_apt']
        # 용도용적제: 상업지역 등 주거복합 건축물은 주거비율에 따라 용적률 제한
        if far is not None and (lim.get('mixed') or lim.get('far_res_part')) and (residential or has_ot):
            basis_apt = lim.get('mixed_basis') == 'apt'
            share = residential_share(p, include_officetel=not basis_apt)
            if share:
                if lim.get('mixed'):
                    mf = lawdata.mixed_far(lim['mixed'], share)
                    ceil = lawdata.mixed_ceiling(lim['mixed'])
                    label = f"주거비율 {share:.1f}%{' (공동주택만)' if basis_apt else ' (오피스텔 등 준주택 포함)'}"
                    if ceil is not None and share >= ceil:
                        items.append({'name': f'용도용적제 ({z.zone})', 'status': 'bad',
                                      'detail': f"{label} — 조례 {lim.get('mixed_src') or '별표'}는 주거비율 {ceil:g}% 미만까지만 정합니다. 비주거 비율을 늘리거나 원문을 확인하세요."})
                        mf = min(x['far'] for x in lim['mixed'])
                    if mf is not None and mf < far:
                        r['notes'].append(f"용도용적제: {label} → {mf:g}% ({lim.get('mixed_src') or '조례 별표'}; 일반 {far:g}%)")
                        items.append({'name': f'용도용적제 ({z.zone})', 'status': 'warn',
                                      'detail': f"{label} → 허용 용적률 {far:g}% → {mf:g}% 로 낮아짐 · 근거 {lim.get('mixed_src') or '조례 별표'} ({'원문 대조 완료' if (o or {}).get('reviewed_by') else '자동 판독 — 원문 확인'})"})
                        far = mf
                elif lim.get('far_res_part'):
                    share = residential_share(p, include_officetel=True)
                    if lim.get('res_max') is not None and share > lim['res_max']:
                        items.append({'name': f'주거복합 비주거 비율 ({z.zone})', 'status': 'bad',
                                      'detail': f"주거비율 {share:.1f}% — 조례 {lim.get('mixed_src') or ''}는 주거 외 용도를 연면적의 {100 - lim['res_max']:g}% 이상 두도록 정합니다 (주거비율 {lim['res_max']:g}% 이하)."})
                    cap = lim['far_res_part'] * 100 / share
                    if cap < far:
                        r['notes'].append(f"주거·준주택 부분 용적률 {lim['far_res_part']:g}% 이하 → 주거비율 {share:.1f}%면 전체 {cap:.0f}%")
                        items.append({'name': f'주거 부분 용적률 ({z.zone})', 'status': 'warn',
                                      'detail': f"조례: 주거·준주택 부분 용적률 {lim['far_res_part']:g}% 이하 · 주거비율 {share:.1f}% → 전체 허용 {far:g}% → {cap:.0f}%"})
                        far = round(cap, 2)
        zrows.append({'zone': z.zone, 'area_sqm': float(z.area_sqm), 'far': far, 'bcr': bcr, 'level': r['level'],
                      'source': r['source'], 'national': r['national'], 'notes': r['notes'],
                      'far_text': lim.get('far_text'), 'bcr_text': lim.get('bcr_text')})
        if far is not None:
            allowed_gfa += z.area_sqm * (D(str(far)) + st.incentive_far_pct) / 100
            far_area += z.area_sqm
        if bcr is not None:
            allowed_fp += z.area_sqm * D(str(bcr)) / 100
    zone_area = sum((z.area_sqm for z in zones), ZERO)
    # 용적률을 모르는 용도지역은 평균에서 빼고, 하나도 모르면 None (0%로 보면 지구단위 완화 한도가 0이 되어 계획 용적률이 0으로 잘림)
    plan_res = plan_far(p, allowed_gfa / far_area * 100 if far_area else None)
    LV = {'registered': '검토자 등록 근거', 'ordinance': '조례 (원문 대조 완료)', 'auto': '조례 (자동 판독 — 확인 필요)',
          'national': '시행령 상한 (조례 미확인)', 'none': '근거 없음'}
    if zones:
        levels = {z['level'] for z in zrows}
        if abs(zone_area - p.land_area_sqm) > D('0.5'):
            items.append({'name': '용도지역 면적 합계', 'status': 'warn',
                          'detail': f'용도지역별 면적 합계 {float(zone_area):,.1f}㎡ ≠ 대지면적 {float(p.land_area_sqm):,.1f}㎡'})
        plan_far_v = p.above_gfa_sqm / p.land_area_sqm * 100
        if plan_res and plan_res['gfa'] is not None:
            # 3차 도시계획: 순 대지(공공시설 제공 후) × 계획 용적률
            allowed_gfa = plan_res['gfa']
            allow_far = allowed_gfa / p.land_area_sqm * 100
            status = 'ok' if p.above_gfa_sqm <= allowed_gfa + D('0.01') else 'bad'
            if status == 'ok' and not (st.plan.notice_no or st.plan.title):
                status = 'warn'
            basis = f"도시계획 ({PLAN_KINDS[st.plan.kind]}{' ' + st.plan.notice_no if st.plan.notice_no else ''})"
        else:
            allow_far = allowed_gfa / zone_area * 100 if zone_area else ZERO
            status = 'ok' if plan_far_v <= allow_far + D('0.01') else 'bad'
            if status == 'ok' and levels & {'national', 'none', 'auto'}:
                status = 'warn'
            basis = ', '.join(sorted({LV[z["level"]] for z in zrows}))
        items.append({'name': '용적률', 'status': status, 'plan': float(plan_far_v), 'limit': float(allow_far),
                      'detail': f'계획 {float(plan_far_v):.2f}% / 허용 {float(allow_far):.2f}% (지상 연면적 {float(p.above_gfa_sqm):,.1f}㎡, 허용 {float(allowed_gfa):,.1f}㎡) · 근거: ' + basis})
        if plan_res:
            items += plan_res['items']
        if st.building_area_sqm is not None:
            plan_bcr = st.building_area_sqm / p.land_area_sqm * 100
            allow_bcr = allowed_fp / zone_area * 100 if zone_area else ZERO
            if plan_res and plan_res.get('bcr') is not None:
                allow_bcr = plan_res['bcr']
            items.append({'name': '건폐율', 'status': 'ok' if plan_bcr <= allow_bcr + D('0.01') else 'bad', 'plan': float(plan_bcr),
                          'limit': float(allow_bcr), 'detail': f'계획 {float(plan_bcr):.2f}% / 허용 {float(allow_bcr):.2f}%'})
        else:
            items.append({'name': '건폐율', 'status': 'warn', 'detail': f'계획 건축면적 미입력 (허용 건축면적 {float(allowed_fp):,.1f}㎡)'})
    else:
        items.append({'name': '용적률·건폐율', 'status': 'warn', 'detail': '용도지역이 입력되지 않아 법규 적합성을 판단하지 못했습니다'})
    pk = required_parking(p)
    if pk:
        est_area = pk['required'] * p.site.parking_area_per_space
        if st.plan_parking is not None:
            items.append({'name': '주차대수', 'status': 'ok' if st.plan_parking >= pk['required'] else 'bad', 'plan': st.plan_parking,
                          'limit': pk['required'], 'detail': f"계획 {st.plan_parking}대 / 법정 {pk['required']}대 ({pk['region']}: {pk['ratio']})"})
        else:
            items.append({'name': '주차대수', 'status': 'warn', 'limit': pk['required'],
                          'detail': f"계획 주차대수 미입력 · 법정 최소 {pk['required']}대 ({pk['region']})"})
        brk = ' / '.join(f"{r['use']} {r['spaces']:g}대 ({r['basis']}, {r['rule']})" if r['basis'] else f"{r['use']} {r['spaces']:g}대"
                         for r in pk['rows'])
        src_t = (pk['source'] or {}).get('title') or ''
        items.append({'name': '주차 산정 내역', 'status': 'ok' if pk['level'] == 'ordinance' and not pk.get('review') else 'warn',
                      'detail': f"{brk} · 근거: {src_t}" + (f" — {pk['note']}" if pk.get('note') else '')})
        items.append({'name': '지하 연면적 (주차)', 'status': 'ok' if p.below_gfa_sqm >= est_area else 'warn',
                      'detail': f"법정 주차 {pk['required']}대 × {float(p.site.parking_area_per_space):g}㎡ ≈ {float(est_area):,.0f}㎡ 필요 / 계획 지하 {float(p.below_gfa_sqm):,.0f}㎡"})
    gate = {'지구단위계획구역': 'district', '정비구역': 'redevelopment', '재정비촉진지구': 'redevelopment'}
    for f, k in gate.items():
        if f in st.flags and st.plan.kind == 'none':
            items.append({'name': f'3차 도시계획: {f}', 'status': 'bad',
                          'detail': f'토지이용계획상 {f}입니다. 조례보다 결정고시({PLAN_KINDS[k]})의 용적률이 우선하므로 고시 내용을 입력해야 합니다.'})
    for f in st.flags:
        from .documents import FLAGS
        items.append({'name': f'규제: {f}', 'status': 'warn', 'detail': FLAGS.get(f, '토지이용계획 규제 — 원문 확인 필요')})
    return {'zones': zrows, 'items': items, 'parking': pk, 'allowed_gfa_sqm': float(allowed_gfa),
            'allowed_footprint_sqm': float(allowed_fp), 'plan': plan_res and {k: (float(v) if isinstance(v, Decimal) else v)
                                                                             for k, v in plan_res.items() if k != 'items'},
            'tiers': ['1차 국가법령 (국토계획법 시행령 등)', '2차 지자체 조례', '3차 지자체 도시계획 (지구단위계획·정비계획)']}


def plan_far(p: Proforma, ordinance_far):
    """3차 지자체 도시계획 용적률 (법령 원문 확인 2026-11-16).
    - 지구단위계획: 국토계획법 시행령 제46조①1호 — 용적률 + 1.5×(제공면적×제공부지 용적률)÷제공 후 대지면적,
      건폐율 × (1 + 제공면적÷원래 대지면적), 제46조⑩ 완화 한도: 용적률 200%·건폐율 150%
    - 재개발·재건축: 도시정비법 제54조 — 법적상한용적률, 초과용적률 중 국민주택규모 주택 건설비율(④), 인수가격 표준건축비(제55조②)
    - 소규모주택정비: 빈집법 제49조① — 공공임대 20% 이상(조례 비율 이상) 시 법적상한, 10~20% 미만은 조례 산식
    """
    pl = p.site.plan
    if pl.kind == 'none':
        return None
    items, notes = [], []
    net = p.land_area_sqm - pl.public_land_sqm
    if net <= 0:
        return {'far': None, 'gfa': None, 'net_site_sqm': net, 'items': [{'name': '공공시설 제공 면적', 'status': 'bad', 'detail': '제공 면적이 대지면적 이상입니다'}]}
    zone_far = D(str(ordinance_far)) if ordinance_far is not None else None
    base = pl.base_far if pl.base_far is not None else zone_far
    if base is None:
        return {'far': None, 'gfa': None, 'net_site_sqm': net,
                'items': [{'name': '3차 도시계획 용적률', 'status': 'bad', 'detail': '결정고시의 기준(정비계획) 용적률을 입력하세요'}]}
    far, obligation, bcr = base, ZERO, pl.plan_bcr
    capital = '과밀억제권역' in p.site.flags
    if pl.kind == 'district':
        far = pl.allowed_far if pl.allowed_far is not None else base
        if pl.public_land_sqm:
            bonus = D('1.5') * pl.public_land_sqm * base / net
            far += bonus
            notes.append(f'시행령 제46조①1호나목: 공공시설 부지 제공 +{float(bonus):.2f}%p')
            if bcr is not None:
                bcr = bcr * (1 + pl.public_land_sqm / p.land_area_sqm)
                notes.append(f'시행령 제46조①1호가목: 건폐율 {float(pl.plan_bcr):g}% → {float(bcr):.2f}%')
        cap_base = zone_far if zone_far is not None else base
        if far > cap_base * 2:
            notes.append(f'시행령 제46조⑩: 완화 한도(용적률의 200% = {float(cap_base * 2):g}%) 적용')
            far = cap_base * 2
        if pl.max_far is not None and far > pl.max_far:
            notes.append(f'결정고시 상한용적률 {float(pl.max_far):g}%로 제한')
            far = pl.max_far
        if pl.res_far:   # 주거부문 용적률 상한: 주거 연면적 ≤ 대지 × 주거부문 용적률 → 전체 용적률 ≤ 주거부문 ÷ 주거비율
            share = residential_share(p, include_officetel=True)
            if share:
                cap = pl.res_far * 100 / D(str(share))
                if cap < far:
                    notes.append(f'결정고시 주거부문 용적률 {float(pl.res_far):g}% · 주거비율 {share:.1f}% → 전체 {float(cap):.2f}%로 제한')
                    far = cap
    elif pl.use_max and pl.max_far is not None:
        far = pl.max_far
        if pl.kind in ('redevelopment', 'reconstruction'):
            lo, hi = ((30, 50) if pl.kind == 'reconstruction' else (50, 75)) if capital else ((0, 50) if pl.kind == 'reconstruction' else (0, 75))
            excess = max(pl.max_far - base, ZERO)
            obligation = excess / 100 * net * pl.housing_ratio_pct / 100
            rng = f"{'과밀억제권역 ' if capital else ''}{lo}~{hi}%" if lo else f'{hi}% 이하'
            ok = lo <= pl.housing_ratio_pct <= hi
            items.append({'name': '국민주택규모 주택 건설 의무', 'status': 'warn' if ok else 'bad',
                          'detail': f'도시정비법 제54조④: 초과용적률 {float(excess):g}%p × {float(pl.housing_ratio_pct):g}% (법정 범위 {rng}, 시·도 조례 비율) '
                                    f'= 연면적 약 {float(obligation):,.1f}㎡ → 인수자 공급, 인수가격 표준건축비·부속토지 기부채납(제55조②). 분양계획에 임대·매각 타입으로 반영하세요.'})
        else:  # 소규모주택정비 (빈집법 제49조①)
            gfa_total = net * far / 100
            obligation = gfa_total * pl.housing_ratio_pct / 100
            if pl.housing_ratio_pct >= 20:
                st, msg = 'warn', '20% 이상(시·도 조례 비율 이상) → 법적상한용적률 적용 가능'
            elif pl.housing_ratio_pct >= 10:
                st, msg = 'bad', '10~20% 미만: 법적상한이 아닌 시·도 조례 산식에 따른 용적률만 적용 — 상한 대신 조례 산정값을 입력하세요'
            else:
                st, msg = 'bad', '공공임대 10% 미만: 빈집법 제49조① 특례 대상 아님'
            items.append({'name': '공공임대주택 비율 (빈집법 제49조①)', 'status': st,
                          'detail': f'전체 연면적 대비 {float(pl.housing_ratio_pct):g}% = 약 {float(obligation):,.1f}㎡ · {msg} · 인수가격은 건축비+부속토지 가격 기초(제49조④)'})
    zone = p.site.zones[0].zone if p.site.zones else None
    if zone in lawdata.NATIONAL and far > lawdata.NATIONAL[zone][2] and pl.kind == 'district':
        items.append({'name': '1차 국가법령 범위', 'status': 'warn',
                      'detail': f'계획 용적률 {float(far):.1f}%가 시행령 제85조① {zone} 상한 {lawdata.NATIONAL[zone][2]}%를 넘습니다 — 제46조 완화 근거 확인'})
    gfa = net * far / 100
    src = ' · '.join(x for x in [pl.title, pl.notice_no, pl.notice_date, f'획지 {pl.block}' if pl.block else ''] if x) or '결정고시 정보 미입력'
    if pl.kind == 'district' and (pl.max_floors or pl.height_limit_m or pl.allowed_uses):
        lim = ' · '.join(x for x in [f'최고 {pl.max_floors}층' if pl.max_floors else '', f'{float(pl.height_limit_m):g}m' if pl.height_limit_m else ''] if x)
        items.append({'name': f"높이·용도 (결정고시{' ' + pl.block if pl.block else ''})", 'status': 'warn',
                      'detail': ' / '.join(x for x in [f'높이 {lim} 이하' if lim else '', f'허용용도: {pl.allowed_uses[:160]}' if pl.allowed_uses else ''] if x)
                                + ' — 설계안의 층수·높이·용도와 대조하세요'})
    items.insert(0, {'name': '3차 도시계획 적용', 'status': 'ok' if (pl.title or pl.notice_no) else 'warn',
                     'detail': f'{PLAN_KINDS[pl.kind]} · 적용 용적률 {float(far):.2f}% × 순대지 {float(net):,.1f}㎡ = {float(gfa):,.1f}㎡ · {src}'
                               + ('' if (pl.title or pl.notice_no) else ' — 고시명·고시번호를 입력해 근거를 남기세요')})
    return {'far': far, 'gfa': gfa, 'bcr': bcr, 'net_site_sqm': net, 'base_far': base, 'obligation_sqm': obligation, 'notes': notes,
            'kind': pl.kind, 'kind_name': PLAN_KINDS[pl.kind], 'items': items}


def _verdict(p: Proforma, s: dict, cf, compliance: dict) -> dict:
    c = p.criteria
    rows = []
    def add(name, value, status, rule, fmt='{:.1f}%'):
        rows.append({'name': name, 'value': value, 'display': '–' if value is None else fmt.format(value), 'status': status, 'rule': rule})
    if p.project_mode == 'redevelopment':
        pr = s['proportional']
        add('비례율', pr, 'bad' if pr is None or pr < c.proportional_risk_pct else 'warn' if pr < c.proportional_ok_pct else 'ok',
            f'양호 ≥ {c.proportional_ok_pct}% · 위험 < {c.proportional_risk_pct}%')
    m = s['margin_pct']
    add('매출이익률 (세전)', m, 'bad' if m is None or m < c.margin_warn_pct else 'warn' if m < c.margin_min_pct else 'ok',
        f'적합 ≥ {c.margin_min_pct}% · 주의 ≥ {c.margin_warn_pct}%')
    b = s['bep']
    add('BEP 분양률' + (' (일반분양)' if p.project_mode == 'redevelopment' else ''), b, 'bad' if b is None or b > c.bep_warn_pct else 'warn' if b > c.bep_max_pct else 'ok',
        f'적합 ≤ {c.bep_max_pct}% · 주의 ≤ {c.bep_warn_pct}%')
    d = s['drop']
    tol = -d if d is not None else None
    add('분양가 하락 허용폭 (분양률 100%)', tol, 'bad' if tol is None or tol <= 0 else 'warn' if tol < c.price_drop_min_pct else 'ok',
        f'적합 ≥ {c.price_drop_min_pct}% 하락 감내')
    add('LTC (대출/총사업비)', s['ltc'], 'ok' if s['ltc'] is not None and s['ltc'] <= c.ltc_max_pct else 'warn', f'적합 ≤ {c.ltc_max_pct}%')
    if cf:
        irr = cf['equity_irr_annual']
        add('Equity IRR (세후, 연)', irr, 'bad' if irr is None or irr < 0 else 'warn' if irr < c.equity_irr_min_pct else 'ok',
            f'적합 ≥ {c.equity_irr_min_pct}%')
        ex = cf['extra_equity']
        rows.append({'name': '추가 자기자본 필요', 'value': float(ex), 'display': f'{rentalmod.eok(ex)}원' if ex else '없음',
                     'status': 'bad' if ex > 0 else 'ok', 'rule': '대출 한도·기간 내 자금 충당'})
    legal = compliance['items']
    stat = [r['status'] for r in rows] + [i['status'] for i in legal]
    overall = 'bad' if 'bad' in stat else 'warn' if 'warn' in stat else 'ok'
    return {**_label_reasons(overall, rows, legal), 'financial': rows, 'legal': legal,
            'note': '판정 기준값은 사내 투자심사 기준에 맞게 조정하세요. 법규 항목은 조례·지구단위계획 원문 확인 후 확정됩니다.'}


def _label_reasons(overall: str, rows: list, legal: list) -> dict:
    """판정 문구(원인별) + 사유 목록(부적합 → 주의 순)."""
    fin_bad = [r for r in rows if r['status'] == 'bad']
    leg_bad = [i for i in legal if i['status'] == 'bad']
    if overall == 'bad':
        label = ('부적합 — 사업구조 재검토 필요' if fin_bad and not leg_bad else
                 '부적합 — 법규 조건 미충족 (계획 수정·입력 필요)' if leg_bad and not fin_bad else
                 '부적합 — 사업성·법규 모두 재검토 필요')
    else:
        label = {'ok': '사업 추진 적합', 'warn': '조건부 적합 (확인 사항 해소 필요)'}[overall]
    fin = lambda r: f"{r['name']} {r['display']} (기준 {r['rule']})"
    leg = lambda i: f"{i['name']}: {i['detail']}"
    reasons = ([{'status': 'bad', 'area': '사업성', 'text': fin(r)} for r in fin_bad] +
               [{'status': 'bad', 'area': '법규', 'text': leg(i)} for i in leg_bad] +
               [{'status': 'warn', 'area': '사업성', 'text': fin(r)} for r in rows if r['status'] == 'warn'] +
               [{'status': 'warn', 'area': '법규', 'text': leg(i)} for i in legal if i['status'] == 'warn'])
    return {'overall': overall, 'label': label, 'reasons': reasons}


def _redev(p: Proforma, rev: dict, pbt: Decimal) -> dict:
    """정비사업 지표: 비례율 = (총수입 − 총지출) ÷ 종전자산 × 100, 권리가액 = 종전평가액 × 비례율, 분담금 = 분양가액 − 권리가액."""
    pa = p.prior_assets
    total = pa.total()
    ratio = pbt / total if total else None
    per_py = pbt / pa.land_py if pa.land_py else None
    member_cash = sum((r['cash'] for r in rev['rows'] if r['buyer'] == 'member'), ZERO)
    cases = []
    for c in pa.cases:
        appraisal = c.appraisal if c.appraisal is not None else c.share_py * pa.appraisal_per_py
        right = appraisal * ratio if ratio is not None else None
        contrib = (c.apply_price - right) if (right is not None and c.apply_price) else None
        cases.append({'name': c.name, 'share_py': float(c.share_py), 'appraisal': won(appraisal),
                      'right_value': won(right) if right is not None else None, 'apply_price': won(c.apply_price),
                      'contribution': won(contrib) if contrib is not None else None,
                      'settlement': won(-right) if (right is not None and not c.apply_price) else None})
    avg_share = pa.land_py / pa.members if pa.members else None
    return {
        'prior_assets_total': won(total), 'land_py': float(pa.land_py), 'members': pa.members,
        'proportional_rate_pct': float(ratio * 100) if ratio is not None else None,
        'value_per_py': won(per_py) if per_py is not None else None,
        'avg_share_py': float(avg_share) if avg_share else None,
        'avg_right_value': won(per_py * avg_share) if per_py is not None and avg_share else None,
        'member_sales': won(member_cash), 'general_sales': won(rev['general_cash']),
        'cases': cases,
        'note': '비례율은 총수입(부가세 제외)에서 총지출(금융비용 포함)을 뺀 사업이익을 종전자산 총액으로 나눈 값입니다. '
                '최종 권리가액·분담금은 관리처분계획 인가 시 확정됩니다. 현금흐름에서 조합원 분양대금은 총액 기준으로 배분되며 '
                '분담금·청산금의 실제 수납·지급 일정은 별도 검토가 필요합니다.',
    }
