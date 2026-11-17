"""건축물 용도별 사업수지 템플릿 생성기 → samples/tpl_*.json

용도마다 면적 구성·분양 타입·사업비 항목(메모에 근거)·공정·분양 일정·중도금·금융·판정 기준을 다르게 둔다.
분양가(예시)는 매출이익률이 목표치(통상 14%)가 되도록 일괄 보정한 값이므로 실제 사업에서는 반드시 시세로 바꿔야 한다.
실행: .venv/Scripts/python.exe tools/build_templates.py
"""
import json
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.proforma import Proforma, analyze  # noqa: E402

BASE = json.loads((ROOT / 'samples' / 'proforma.json').read_text(encoding='utf-8'))
PY = 400 / 121


def C(cat, name, basis, value, note=''):
    return {'category': cat, 'name': name, 'basis': basis, 'value': value, 'note': note}


def U(name, kind, excl, supply, count, price):
    return {'name': name, 'kind': kind, 'exclusive_sqm': excl, 'supply_sqm': supply, 'count': count, 'price_per_py': price}


def common_costs(land_py_price, land_note, cons_above, cons_below, cons_note, design_py=150000, supervise=2.5):
    return [
        C('land', '토지매입비', 'per_land_py', land_py_price, land_note),
        C('land', '취득세 등 (토지)', 'auto_land_tax', 0, '지방세법: 토지 매매 4.6% (농지 3.4%) 자동'),
        C('land', '중개·법무 수수료', 'pct_land', 0.5, ''),
        C('construction', '직접공사비 (지상)', 'per_above_py', cons_above, cons_note),
        C('construction', '직접공사비 (지하)', 'per_below_py', cons_below, '지하 굴착·흙막이·주차장'),
        C('indirect', '설계비', 'per_gfa_py', design_py, '건축·구조·설비·전기·조경'),
        C('indirect', '감리비', 'pct_construction', supervise, '건축물 규모·용도별 감리 대가 기준'),
        C('indirect', '인허가·영향평가 용역', 'fixed', 400_000_000, '교통·환경·경관 심의 등'),
        C('charges', '하수도 원인자부담금', 'auto_sewer', 0, '오수발생량 자동 × 지자체 공고 단위단가(입력값, 원/㎥)'),
        C('charges', '상수도 원인자부담금', 'auto_water', 0, '조례 구경별 부담액(안양 등 내장) 또는 세대당 부담액 입력'),
        C('taxes', '보존등기 (건물 취득세 등)', 'auto_preservation', 0, '지방세법: 원시취득 2.8% + 농특·교육세 자동'),
        C('taxes', '재산세·종부세 등', 'fixed', 200_000_000, '사업기간 토지 보유세'),
        C('admin', '시행사 운영비', 'monthly', 40_000_000, '인건비·사무실·법무·회계'),
        C('admin', '신탁 수수료', 'pct_sales', 0.5, '관리형 토지신탁 (대주 요구 시)'),
        C('contingency', '예비비', 'pct_total', 2.0, ''),
    ]


def sched(**kw):
    s = deepcopy(BASE['schedule'])
    s.update(kw)
    return s


T = []

# 1) 아파트 (공동주택)
T.append(dict(key='apartment', title='아파트 (공동주택)', zone='제3종일반주거지역', land=10000, above=25000, below=12000, months=48,
    desc='300세대 미만 일반분양 아파트 · 국민주택규모 이하 부가세 면세 · 학교용지·광역교통 부담금 · HUG 분양보증',
    units=[U('59A', 'apartment', 59.9, 80, 120, 1), U('84A', 'apartment', 84.9, 112, 100, 1), U('114A', 'apartment', 114.5, 150, 10, 1.04),
           U('단지 내 상가', 'retail', 300, 500, 1, 1.15)],
    base_price=26_000_000, land_price=12_000_000, land_note='제3종일반주거 — 인근 실거래·감정가로 교체',
    cons=(7_500_000, 6_000_000, '공동주택 표준 (철근콘크리트 벽식·라멘)'),
    extra=[C('construction', '철거·이주·부대공사', 'fixed', 1_000_000_000, ''),
           C('charges', '학교용지부담금', 'auto_school', 0, '학교용지법: 공동주택 분양가격의 0.4% (300세대 이상, 2024.12.20 개정)'),
           C('charges', '광역교통시설부담금', 'auto_metro', 0, '광역교통법: 표준건축비 × 부과율 × 주택 연면적 자동'),
           C('sales', '분양대행 수수료', 'per_unit', 5_000_000, '세대당'), C('sales', '광고·홍보비', 'pct_sales', 1.0, ''),
           C('sales', '모델하우스 (건립·운영)', 'fixed', 3_000_000_000, ''), C('sales', 'HUG 분양보증 수수료', 'pct_sales', 0.3, '주택법 30세대 이상 선분양')],
    schedule=sched(construction_months=30, sales_start_month=9, initial_sales_share_pct=60, sales_period_months=12, deposit_pct=10, midpay_pct=60, midpay_installments=6),
    midpay=dict(enabled=True, mode='interest_free', ratio_pct=60, annual_rate_pct=4.5, avg_months=18, developer_share_pct=100),
    balcony=15_000_000, building_ratio=60, criteria=dict(margin_min_pct=10, bep_max_pct=80, equity_irr_min_pct=15)))

# 2) 오피스텔 (단독형)
T.append(dict(key='officetel', title='오피스텔', zone='준주거지역', land=1500, above=6750, below=3000, months=36,
    desc='준주거지역 소형 오피스텔 + 1층 근생 · 전부 부가세 과세 · 학교용지·광역교통 부담금 없음 · 중도금 이자후불제',
    units=[U('오피스텔 A (원룸)', 'officetel', 26.4, 45, 100, 1), U('오피스텔 B (1.5룸)', 'officetel', 33.9, 58, 20, 1),
           U('1층 근생', 'retail', 50, 80, 4, 2.3)],
    base_price=20_000_000, land_price=25_000_000, land_note='준주거 — 인근 실거래·감정가로 교체',
    cons=(7_500_000, 6_000_000, '오피스텔 (철근콘크리트 라멘조)'),
    extra=[C('sales', '분양대행 수수료', 'pct_sales', 2.5, '오피스텔·상가 대행 수수료 (총매출 대비)'), C('sales', '광고·홍보비', 'pct_sales', 1.0, ''),
           C('sales', '홍보관 (임차·운영)', 'fixed', 800_000_000, ''),
           C('sales', '분양보증·대리사무 수수료', 'pct_sales', 0.3, '건축물분양법: 오피스텔 30실 이상 신탁·분양보증 후 분양')],
    schedule=sched(construction_months=24, sales_start_month=6, initial_sales_share_pct=50, sales_period_months=18, deposit_pct=10, midpay_pct=50, midpay_installments=5),
    midpay=dict(enabled=True, mode='deferred', ratio_pct=50, annual_rate_pct=5.0, avg_months=14, developer_share_pct=100),
    balcony=0, building_ratio=65, criteria=dict(margin_min_pct=12, bep_max_pct=75, equity_irr_min_pct=15)))

# 3) 주상복합아파트
T.append(dict(key='mixed_apt', title='주상복합아파트', zone='일반상업지역', land=4000, above=20000, below=10000, months=52,
    desc='일반상업지역 주상복합 · 저층 상가·업무 + 상층 공동주택 · 조례 용도용적제(주거비율별 용적률) 자동 적용 — 주거비율 약 75% · 학교용지·광역교통 부담금',
    units=[U('59A', 'apartment', 59.9, 80, 50, 1), U('84A', 'apartment', 84.9, 112, 80, 1), U('101A', 'apartment', 101.5, 135, 7, 1.05),
           U('근생 1층', 'retail', 55, 95, 12, 2.4), U('근생 2층', 'retail', 80, 135, 10, 1.2), U('업무 3~4층', 'office', 75, 130, 16, 0.75)],
    base_price=30_000_000, land_price=35_000_000, land_note='일반상업 — 인근 실거래·감정가로 교체',
    cons=(9_000_000, 7_000_000, '초고층·주상복합 (전이층·커튼월 포함)'),
    extra=[C('charges', '학교용지부담금', 'auto_school', 0, '학교용지법: 공동주택 분양가격의 0.4% (300세대 이상)'),
           C('charges', '광역교통시설부담금', 'auto_metro', 0, '광역교통법: 표준건축비 × 부과율 × 주택 연면적 자동'),
           C('sales', '분양대행 수수료', 'per_unit', 5_000_000, '세대당 (상가는 아래 별도)'), C('sales', '상가 분양대행', 'pct_sales', 0.3, '상가분 대행 (총매출 대비 환산)'),
           C('sales', '광고·홍보비', 'pct_sales', 1.0, ''), C('sales', '모델하우스 (건립·운영)', 'fixed', 3_500_000_000, ''),
           C('sales', 'HUG 분양보증 수수료', 'pct_sales', 0.3, '주택법 30세대 이상 선분양')],
    schedule=sched(construction_months=40, sales_start_month=10, initial_sales_share_pct=55, sales_period_months=15, deposit_pct=10, midpay_pct=60, midpay_installments=6),
    midpay=dict(enabled=True, mode='interest_free', ratio_pct=60, annual_rate_pct=4.5, avg_months=22, developer_share_pct=100),
    balcony=15_000_000, building_ratio=55, criteria=dict(margin_min_pct=10, bep_max_pct=80, equity_irr_min_pct=15)))

# 4) 주상복합오피스텔
T.append(dict(key='mixed_officetel', title='주상복합오피스텔', zone='일반상업지역', land=3000, above=24000, below=11000, months=48,
    desc='일반상업지역 오피스텔 + 저층 3개층 상가 · 전부 부가세 과세 · 건축물분양법 · 중도금 이자후불제',
    units=[U('오피스텔 A', 'officetel', 26.4, 45, 250, 1), U('오피스텔 B', 'officetel', 34.0, 58, 120, 1), U('오피스텔 C (투룸)', 'officetel', 59.0, 98, 20, 1.03),
           U('상가 1층', 'retail', 50, 90, 10, 2.6), U('상가 2층', 'retail', 70, 120, 8, 1.3), U('상가 3층', 'retail', 90, 150, 6, 1.0)],
    base_price=22_000_000, land_price=30_000_000, land_note='일반상업 — 인근 실거래·감정가로 교체',
    cons=(8_500_000, 6_500_000, '오피스텔 + 판매·근생 복합'),
    extra=[C('sales', '분양대행 수수료', 'pct_sales', 2.5, '오피스텔·상가 대행 (총매출 대비)'), C('sales', '광고·홍보비', 'pct_sales', 1.0, ''),
           C('sales', '홍보관 (임차·운영)', 'fixed', 1_500_000_000, ''), C('sales', '분양보증·대리사무 수수료', 'pct_sales', 0.3, '건축물분양법')],
    schedule=sched(construction_months=34, sales_start_month=8, initial_sales_share_pct=45, sales_period_months=18, deposit_pct=10, midpay_pct=50, midpay_installments=5),
    midpay=dict(enabled=True, mode='deferred', ratio_pct=50, annual_rate_pct=5.0, avg_months=18, developer_share_pct=100),
    balcony=0, building_ratio=60, criteria=dict(margin_min_pct=12, bep_max_pct=75, equity_irr_min_pct=15)))

# 5) 상업시설 (판매·근생 분양 상가)
T.append(dict(key='retail', title='상업시설 (분양 상가)', zone='일반상업지역', land=3000, above=12000, below=6000, months=40,
    desc='층별 구분분양 상가 · 1층 가격이 상층의 2~3배 · 분양기간 길고 미분양 위험 큼 → 판정 기준 강화 · MD 구성비',
    units=[U('1층 상가', 'retail', 40, 75, 30, 2.6), U('2층 상가', 'retail', 55, 100, 24, 1.3), U('3층 상가', 'retail', 65, 120, 20, 1.0),
           U('4층 상가', 'retail', 95, 170, 12, 0.85), U('5~6층 대형 (F&B·키즈)', 'retail', 520, 950, 2, 0.7)],
    base_price=23_000_000, land_price=30_000_000, land_note='일반상업 — 인근 실거래·감정가로 교체',
    cons=(7_000_000, 6_000_000, '판매·근생 (라멘조, 에스컬레이터 포함)'),
    extra=[C('sales', '분양대행 수수료', 'pct_sales', 4.0, '상가 대행 (총매출 대비)'), C('sales', '광고·홍보비', 'pct_sales', 1.5, ''),
           C('sales', 'MD 구성·앵커 테넌트 유치', 'fixed', 1_000_000_000, '임대 확정 후 분양 시 분양가 상승'), C('sales', '홍보관 (임차·운영)', 'fixed', 800_000_000, ''),
           C('sales', '분양보증·대리사무 수수료', 'pct_sales', 0.3, '건축물분양법: 판매시설 3,000㎡ 이상')],
    schedule=sched(construction_months=28, sales_start_month=8, initial_sales_share_pct=30, sales_period_months=24, deposit_pct=10, midpay_pct=40, midpay_installments=4),
    midpay=dict(enabled=True, mode='with_interest', ratio_pct=40, annual_rate_pct=5.5, avg_months=14, developer_share_pct=0),
    balcony=0, building_ratio=50, criteria=dict(margin_min_pct=15, margin_warn_pct=8, bep_max_pct=70, bep_warn_pct=80, equity_irr_min_pct=18), target=20))

# 6) 업무시설 (구분분양 오피스)
T.append(dict(key='office', title='업무시설 (분양 오피스)', zone='일반상업지역', land=2500, above=20000, below=9000, months=46,
    desc='층별 구분분양 오피스 + 저층 근생 · 서울은 과밀부담금 대상 여부 확인 · 통매각(리츠) 시 단일 타입으로 변경',
    units=[U('오피스 저층 (3~7F)', 'office', 70, 120, 40, 1.0), U('오피스 중층 (8~12F)', 'office', 70, 120, 40, 1.05),
           U('오피스 고층 (13~17F)', 'office', 70, 120, 40, 1.1), U('근생 1~2층', 'retail', 55, 90, 16, 1.8)],
    base_price=20_000_000, land_price=35_000_000, land_note='일반상업 (업무지구) — 인근 실거래·감정가로 교체',
    cons=(8_500_000, 6_500_000, '업무시설 (커튼월·기계식 공조)'),
    extra=[C('charges', '과밀부담금', 'fixed', 0, '수도권정비계획법: 서울 내 업무·판매 일정 규모 초과 시 부과 — 해당 시 금액 입력'),
           C('sales', '분양대행 수수료', 'pct_sales', 3.0, ''), C('sales', '광고·홍보비', 'pct_sales', 1.0, ''),
           C('sales', '홍보관 (임차·운영)', 'fixed', 800_000_000, ''), C('sales', '분양보증·대리사무 수수료', 'pct_sales', 0.3, '건축물분양법: 업무시설 3,000㎡ 이상')],
    schedule=sched(construction_months=32, sales_start_month=8, initial_sales_share_pct=40, sales_period_months=20, deposit_pct=10, midpay_pct=40, midpay_installments=4),
    midpay=dict(enabled=True, mode='with_interest', ratio_pct=40, annual_rate_pct=5.5, avg_months=16, developer_share_pct=0),
    balcony=0, building_ratio=55, criteria=dict(margin_min_pct=12, bep_max_pct=75, equity_irr_min_pct=15)))

# 7) 근린생활시설 (소형 근생 건물)
T.append(dict(key='neighborhood', title='근린생활시설 (소형 근생 건물)', zone='제2종일반주거지역', land=500, above=1000, below=300, months=20,
    desc='대지 500㎡ 내외 꼬마빌딩 신축 · 층별 분양 또는 준공 후 통매각 · 소규모라 분양대행·모델하우스 없음',
    units=[U('1층 근생', 'retail', 60, 85, 2, 2.0), U('2층 근생', 'retail', 150, 190, 1, 1.0), U('3층 근생', 'retail', 150, 190, 1, 0.9),
           U('4층 근생', 'retail', 150, 190, 1, 0.85), U('5층 근생', 'retail', 150, 190, 1, 0.85)],
    base_price=20_000_000, land_price=18_000_000, land_note='제2종일반주거 이면도로 — 인근 실거래로 교체',
    cons=(6_500_000, 5_500_000, '소형 근생 (철근콘크리트)'),
    extra=[C('sales', '중개 수수료 (매각)', 'pct_sales', 0.9, '공인중개사법 비주택 상한 0.9%')],
    schedule=sched(construction_start_month=3, construction_months=12, sales_start_month=12, initial_sales_share_pct=50, sales_period_months=6,
                   deposit_pct=10, midpay_pct=0, midpay_installments=0, land_balance_month=2),
    midpay=dict(enabled=True, mode='with_interest', ratio_pct=0, annual_rate_pct=5.0, avg_months=0, developer_share_pct=0),
    balcony=0, building_ratio=45, criteria=dict(margin_min_pct=12, bep_max_pct=80, equity_irr_min_pct=12), small=True, fin=(0.30, 0.0, 0.60)))

# 8) 지식산업센터
T.append(dict(key='knowledge', title='지식산업센터', zone='준공업지역', land=8000, above=24000, below=11000, months=44,
    desc='준공업지역 제조형(드라이브인)·업무형 + 지원시설 · 산업집적법 입주자격 제한 · 취득세·재산세 감면(지특법) 적용 여부 확인',
    units=[U('제조형 (1~3F 드라이브인)', 'knowledge', 200, 380, 30, 1.1), U('업무형 (4~8F)', 'knowledge', 80, 150, 70, 1.0),
           U('지원시설 (근생)', 'retail', 35, 60, 15, 2.0)],
    base_price=10_000_000, land_price=12_000_000, land_note='준공업 — 인근 실거래·감정가로 교체',
    cons=(6_000_000, 5_500_000, '지식산업센터 (고하중 바닥·화물 엘리베이터·램프)'),
    extra=[C('sales', '분양대행 수수료', 'pct_sales', 3.0, ''), C('sales', '광고·홍보비', 'pct_sales', 1.0, ''),
           C('sales', '홍보관 (임차·운영)', 'fixed', 1_000_000_000, ''),
           C('indirect', '지식산업센터 설립승인·입주관리 용역', 'fixed', 200_000_000, '산업집적법 제28조의2 설립승인 · 입주계약 관리')],
    schedule=sched(construction_months=30, sales_start_month=8, initial_sales_share_pct=40, sales_period_months=18, deposit_pct=10, midpay_pct=40, midpay_installments=4),
    midpay=dict(enabled=True, mode='interest_free', ratio_pct=40, annual_rate_pct=5.0, avg_months=16, developer_share_pct=100),
    balcony=0, building_ratio=55, criteria=dict(margin_min_pct=12, bep_max_pct=75, equity_irr_min_pct=15)))

# 9) 데이터센터
T.append(dict(key='datacenter', title='데이터센터 (개발 후 일괄매각)', zone='준공업지역', land=6000, above=12000, below=2000, months=42,
    desc='IT 20MW급 · 착공 시 투자자·운영사와 선매각(Forward Sale) · 전력 인입(한전)·수전·냉각 설비비가 사업비 대부분 · 전력계통영향평가',
    units=[U('데이터센터 일괄매각 (IT 20MW)', 'datacenter', 12000, 14000, 1, 1.0)],
    base_price=60_000_000, land_price=10_000_000, land_note='준공업 (변전소 인접 부지 프리미엄) — 실거래로 교체',
    cons=(9_000_000, 6_500_000, '건축 골조·외장 (고하중·내진 특등급)'),
    extra=[C('construction', '전력·냉각 설비 (MEP: 수배전·UPS·발전기·냉동기)', 'fixed', 160_000_000_000, 'IT 1MW당 약 80억 가정 × 20MW — 설계 단계 견적으로 교체'),
           C('charges', '한전 전력 인입 시설부담금', 'fixed', 10_000_000_000, '전기공급약관 시설부담금 + 송전선로 — 한전 협의로 확정'),
           C('indirect', '전력계통영향평가·인허가 용역', 'fixed', 1_000_000_000, '분산에너지 활성화 특별법 전력계통영향평가 (대규모 전력수요)'),
           C('construction', '통신 인입 (다중 캐리어)', 'fixed', 2_000_000_000, ''),
           C('sales', '매각 자문 수수료', 'pct_sales', 1.0, '선매각 투자자 유치 (분양대행·모델하우스 없음)')],
    schedule=sched(construction_months=30, sales_start_month=8, initial_sales_share_pct=100, sales_period_months=1, deposit_pct=10, midpay_pct=0, midpay_installments=0),
    midpay=dict(enabled=True, mode='with_interest', ratio_pct=0, annual_rate_pct=5.0, avg_months=0, developer_share_pct=0),
    balcony=0, building_ratio=85, criteria=dict(margin_min_pct=12, bep_max_pct=90, bep_warn_pct=95, equity_irr_min_pct=12), fin=(0.25, 0.10, 0.65), target=15))


def build(t: dict) -> dict:
    margin_target = t.get('target', 14.0)
    eq_r, br_r, pf_r = t.get('fin', (0.10, 0.25, 0.55))   # 자기자본 · 브릿지 · 본PF (총사업비 대비)
    d = deepcopy(BASE)
    d['project_name'] = f"템플릿 — {t['title']} (예시 가정)"
    d['land_area_sqm'], d['above_gfa_sqm'], d['below_gfa_sqm'], d['duration_months'] = t['land'], t['above'], t['below'], t['months']
    d['building_ratio_pct'] = t['building_ratio']
    d['balcony_per_unit'] = t['balcony']
    d['balcony_taxable'] = True
    cons_above, cons_below, cons_note = t['cons']
    costs = common_costs(t['land_price'], t['land_note'], cons_above, cons_below, cons_note)
    if t.get('small'):   # 소규모: 인허가·원인자부담금·운영비 축소
        for c in costs:
            if c['name'] == '인허가·영향평가 용역': c['value'] = 50_000_000
            if c['name'].startswith('기반시설'): c['value'] = 50_000_000
            if c['name'] == '시행사 운영비': c['value'] = 10_000_000
            if c['name'] == '재산세·종부세 등': c['value'] = 20_000_000
            if c['name'] == '신탁 수수료': c['value'] = 0
    # 용도 고유 항목을 같은 분류 뒤에 끼워 넣음
    for e in t['extra']:
        idx = max((i for i, c in enumerate(costs) if c['category'] == e['category']), default=len(costs) - 2)
        costs.insert(idx + 1, e)
    d['costs'] = costs
    d['schedule'] = t['schedule']
    d['midpay'] = t['midpay']
    d['criteria'] = {**BASE['criteria'], **t['criteria']}
    d['site'] = {**BASE['site'], 'zones': [{'zone': t['zone'], 'area_sqm': t['land']}], 'parcels': [], 'flags': [],
                 'building_area_sqm': None, 'plan_parking': None, 'address': ''}
    d['site']['plan'] = {**BASE['site'].get('plan', {}), 'kind': 'none'}
    rel = [u['price_per_py'] for u in t['units']]

    def apply(f):
        d['units'] = [{**u, 'price_per_py': int(round(t['base_price'] * r * f / 100_000) * 100_000)} for u, r in zip(t['units'], rel)]

    def margin(f):
        apply(f)
        return float(analyze(Proforma.model_validate(d))['summary']['margin_pct'] or -999)

    for _ in range(2):    # 금융 구조 ↔ 분양가 보정 2회 반복
        lo, hi = 0.3, 3.0
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if margin(mid) < margin_target else (lo, mid)
        apply(hi)
        r = analyze(Proforma.model_validate(d))['summary']
        tc = float(r['total_cost'])
        rnd = lambda x: int(round(x / 1e8) * 1e8)
        d['equity'] = rnd(tc * eq_r)
        d['loans'] = ([{**BASE['loans'][0], 'amount': rnd(tc * br_r)}] if br_r else []) +                      [{**BASE['loans'][1], 'amount': rnd(tc * pf_r), 'months': t['schedule']['construction_months'] + 6,
                       'start_month': BASE['loans'][1]['start_month'] if br_r else 0}]
    s = analyze(Proforma.model_validate(d))
    d['_template'] = {'key': t['key'], 'title': t['title'], 'desc': t['desc'],
                      'note': f"분양가는 매출이익률 약 {margin_target:.0f}%가 되도록 맞춘 예시값입니다. 토지가·분양가·공사비를 시세와 견적으로 반드시 바꾸세요."}
    print(f"추가자본 {s['summary'].get('extra_equity') or 0:>14,.0f} ", end='')
    print(f"{t['title']:24} 매출 {s['summary']['revenue_net']/1e8:9,.0f}억  사업비 {s['summary']['total_cost']/1e8:9,.0f}억  이익률 {s['summary']['margin_pct']:5.1f}%"
          f"  BEP {s['summary']['bep_sales_rate_pct'] or 0:5.1f}%  IRR {s['summary']['equity_irr_pct'] or 0:6.1f}%  대표가 {d['units'][0]['price_per_py']/1e4:,.0f}만/평  판정 {s['verdict']['overall']}")
    return d


if __name__ == '__main__':
    out = ROOT / 'samples'
    index = []
    for t in T:
        d = build(t)
        (out / f"tpl_{t['key']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1, default=lambda x: float(x) if isinstance(x, Decimal) else str(x)), encoding='utf-8')
        index.append({'key': t['key'], 'title': t['title'], 'desc': t['desc']})
    (out / 'templates.json').write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    print('templates:', len(index))
