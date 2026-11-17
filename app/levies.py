"""부담금·제세공과금 법정 자동 산정 (사업비 항목의 산정 기준이 'auto_*' 일 때).

원문 대조 2026-11-17 (국가법령정보센터):
- 학교용지부담금: 학교용지 확보 등에 관한 특례법 제2조·제5조·제5조의2 — 300세대 이상 개발사업, 공동주택 분양가격 × 1천분의 4
  (2024.12.20 개정 전 1천분의 8), 임대주택 분양·세대수 증가 없는 정비사업 등 면제.
- 광역교통시설부담금: 대도시권 광역교통 관리에 관한 특별법 제11조·제11조의2·제11조의3, 시행령 제16조의2·별표 1(2026.6.23)
  — {표준건축비 × 부과율(수도권 4%, 그 밖의 대도시권 2%) × 건축연면적} − 공제액, 도시지역 50% 경감(정비사업 75%).
  표준건축비: 공공건설임대주택 표준건축비(국토교통부고시 제2023-64호).
- 보존등기(건물 원시취득) 취득세: 지방세법 제11조①3 2.8% + 농어촌특별세 0.2%(국민주택규모 이하 주택 비과세) + 지방교육세 0.16%.
- 토지 취득세: 지방세법 제11조①7 — 농지 외 4%+0.2%+0.4% = 4.6%, 농지 3%+0.2%+0.2% = 3.4%.
- 토지 보유세(재산세): 지방세법 제111조·제112조, 시행령 제102조⑦7·제109조 — 사업계획승인 받은 주택건설사업 토지 분리과세 0.2%,
  공정시장가액비율 70%, 도시지역분 0.14%, 지방교육세 = 재산세의 20%.
"""
import math
from decimal import Decimal

D = Decimal
ZERO = D(0)

AUTO_BASES = {
    'auto_school': '학교용지부담금 (학교용지법)',
    'auto_metro': '광역교통시설부담금 (광역교통법)',
    'auto_sewer': '하수도 원인자부담금 (하수도법·조례)',
    'auto_water': '상수도 원인자부담금 (수도법·조례)',
    'auto_preservation': '보존등기 취득세 (지방세법)',
    'auto_land_tax': '토지 취득세 (지방세법)',
    'auto_holding': '토지 재산세 (지방세법)',
}

# 공공건설임대주택 표준건축비 (국토교통부고시 제2023-64호, 천원/㎡, 주택공급면적 기준) — [층수구간][전용면적구간]
STD_COST = {
    5: (1126.7, 1145.2, 1109.5, 1120.8),
    10: (1209.8, 1226.1, 1188.5, 1192.3),
    20: (1143.0, 1154.1, 1119.3, 1118.8),
    999: (1162.6, 1173.8, 1139.2, 1138.4),
}
STD_COST_SOURCE = '공공건설임대주택 표준건축비 (국토교통부고시 제2023-64호, 2023.2.1)'

# 대도시권광역교통관리에관한특별법 시행령 [별표 1] (2026.6.23) — 수도권은 부과율 4%, 그 밖의 대도시권 2%
METRO_CAPITAL = ('서울특별시', '인천광역시', '경기도')
METRO_WHOLE = ('부산광역시', '울산광역시', '대구광역시', '광주광역시', '대전광역시', '세종특별자치시')
METRO_MUNIS = {
    '경상북도': ('경주시', '구미시', '경산시', '영천시', '청도군', '고령군', '성주군', '칠곡군', '의성군', '청송군'),
    '경상남도': ('양산시', '김해시', '창원시', '거제시', '밀양시', '창녕군'),
    '전라남도': ('나주시', '담양군', '화순군', '함평군', '장성군'),
    '전남광주통합특별시': ('동구', '서구', '남구', '북구', '광산구', '나주시', '담양군', '화순군', '함평군', '장성군'),
    '충청남도': ('공주시', '논산시', '계룡시', '금산군'),
    '충청북도': ('청주시', '보은군', '옥천군'),
    '전북특별자치도': ('전주시', '김제시', '익산시', '군산시', '완주군'),
}


def metro_rate(province: str | None, municipality: str | None) -> tuple[Decimal, str]:
    p, m = province or '', municipality or ''
    if p in METRO_CAPITAL:
        return D('0.04'), '수도권'
    if p in METRO_WHOLE or m in METRO_MUNIS.get(p, ()):
        return D('0.02'), '대도시권'
    return ZERO, '대도시권 밖'


def _floors_estimate(p) -> int:
    pl = p.site.plan
    if getattr(pl, 'max_floors', None):
        return int(pl.max_floors)
    ba = p.site.building_area_sqm
    if ba and ba > 0 and p.above_gfa_sqm:
        return max(1, math.ceil(p.above_gfa_sqm / ba))
    return 15   # 정보 없으면 11~20층 구간


def std_cost(floors: int, exclusive: Decimal) -> Decimal:
    band = 5 if floors <= 5 else 10 if floors <= 10 else 20 if floors <= 20 else 999
    e = float(exclusive)
    col = 0 if e <= 40 else 1 if e <= 50 else 2 if e <= 60 else 3
    return D(str(STD_COST[band][col])) * 1000


def _urban(p) -> bool:
    zs = [z.zone for z in p.site.zones] or [x.zone for x in p.site.parcels if x.zone]
    return any(any(k in z for k in ('주거', '상업', '공업', '녹지')) for z in zs) if zs else True


def _is_renewal(p) -> bool:
    return p.project_mode == 'redevelopment' or p.site.plan.kind in ('redevelopment', 'reconstruction', 'small')


def school_levy(p, adj: Decimal) -> tuple[Decimal, str]:
    apts = [u for u in p.units if u.kind == 'apartment' and u.count]
    total_units = sum(u.count for u in apts)
    existing = int(getattr(p.prior_assets, 'members', 0) or 0) if _is_renewal(p) else 0
    target_units = total_units - existing if _is_renewal(p) else total_units
    if target_units < 300:
        why = f'공동주택 {total_units}세대' + (f' − 기존 {existing}세대 = {target_units}세대' if existing else '') + ' — 300세대 미만 개발사업은 부과 대상 아님(제2조)'
        return ZERO, why
    sold = [u for u in apts if u.buyer == 'general' or (u.buyer == 'member' and not _is_renewal(p))]   # 임대 면제, 정비사업 조합원분 제외
    base = sum((u.supply_sqm / D('3.305785') * u.price_per_py * u.count * adj for u in sold), ZERO)
    amt = base * D('0.004')
    return amt, f"분양가격 {float(base) / 1e8:,.1f}억 × 0.4% (공동주택 {sum(u.count for u in sold):,}세대{', 임대·조합원분 제외' if len(sold) < len(apts) else ''})"


def metro_levy(p) -> tuple[Decimal, str]:
    rate, region = metro_rate(p.site.province, p.site.municipality)
    if not rate:
        return ZERO, f'{p.site.province or ""} {p.site.municipality or ""}: 대도시권(시행령 별표 1) 밖 — 부과 대상 아님'.strip()
    houses = [u for u in p.units if u.kind == 'apartment' and u.count]
    if sum(u.count for u in houses) < 20:
        return ZERO, '주택 20세대 미만 — 부과 대상 아님(법 제11조①)'
    floors = _floors_estimate(p)
    area = ZERO
    gross = ZERO
    for u in houses:
        if u.buyer == 'rental' and u.exclusive_sqm <= 85:
            continue   # 국민주택규모 이하 임대주택 연면적 제외(시행령 제16조의2⑥7)
        a = u.supply_sqm * u.count
        area += a
        gross += std_cost(floors, u.exclusive_sqm) * a
    levy = gross * rate
    cut = D('0.75') if _is_renewal(p) and _urban(p) else D('0.5') if (_urban(p) or _is_renewal(p)) else ZERO
    amt = levy * (1 - cut)
    return amt, (f'표준건축비(약 {floors}층) × {float(rate) * 100:g}%({region}) × 주택 연면적 {float(area):,.0f}㎡'
                 + (f' − 경감 {float(cut) * 100:g}%(도시지역{"·정비사업" if cut == D("0.75") else ""})' if cut else '')
                 + ' · 공제액(철도·도로 등 부담) 미반영')


def preservation_tax(p, base: Decimal) -> tuple[Decimal, str]:
    """건물 원시취득: 취득세 2.8% + 농특세 0.2%(국민주택규모 이하 주택 비과세) + 지방교육세 0.16%."""
    tot = sum((u.supply_sqm * u.count for u in p.units), ZERO)
    small = sum((u.supply_sqm * u.count for u in p.units if u.kind == 'apartment' and u.exclusive_sqm <= 85), ZERO)
    share = small / tot if tot else ZERO
    rate = D('0.0316') - D('0.002') * share
    return base * rate, f'과세표준(공사비·설계감리 등) {float(base) / 1e8:,.1f}억 × {float(rate) * 100:.3f}% (2.8%+농특 0.2%+교육 0.16%, 국민주택규모 이하 주택 {float(share) * 100:.0f}%는 농특세 비과세)'


FARM = ('전', '답', '과수원', '과')


def land_tax(p, base: Decimal) -> tuple[Decimal, str]:
    ps = [x for x in p.site.parcels if x.area_sqm]
    tot = sum((x.area_sqm for x in ps), ZERO)
    farm = sum((x.area_sqm for x in ps if str(x.jimok or '').strip() in FARM), ZERO)
    share = farm / tot if tot else ZERO
    rate = D('0.046') - D('0.012') * share
    return base * rate, f'토지 매입가 {float(base) / 1e8:,.1f}억 × {float(rate) * 100:.2f}% (농지 외 4.6%, 농지 3.4%{f" · 농지 {float(share) * 100:.0f}%" if share else ""})'


def holding_tax(p) -> tuple[Decimal, str]:
    ps = [x for x in p.site.parcels if x.area_sqm and x.price_per_sqm]
    official = sum((x.area_sqm * x.price_per_sqm for x in ps), ZERO)
    if not official:
        return ZERO, '공시지가가 없어 산정하지 못했습니다 (필지 조회로 공시지가를 채우세요)'
    sc = p.schedule
    if sc and sc.enabled:
        months = sc.construction_start_month + sc.construction_months + sc.move_in_lag_months - sc.land_balance_month
    else:
        months = p.duration_months
    years = max(1, math.ceil(D(months) / 12))
    std = official * D('0.7')
    per_year = std * D('0.002') * D('1.2') + std * D('0.0014')   # 분리과세 0.2% + 지방교육세 20% + 도시지역분 0.14%
    return per_year * years, (f'공시지가 {float(official) / 1e8:,.1f}억 × 70% × (0.2%×1.2 + 도시지역분 0.14%) × {years}년 '
                              '(사업계획승인 후 분리과세 가정 — 승인 전은 종합합산·종부세 대상일 수 있음)')


def _rooms(exclusive: Decimal) -> int:
    """전용면적으로 거실(방) 수 추정 — 분양 평면 일반값 (원룸 ≤30㎡, 2룸 ≤50㎡, 3룸 ≤102㎡, 그 이상 4룸)."""
    e = float(exclusive)
    return 1 if e <= 30 else 2 if e <= 50 else 3 if e <= 102 else 4


def sewage_m3_per_day(p) -> tuple[Decimal, list[str]]:
    """「건축물의 용도별 오수발생량 및 정화조 처리대상인원 산정방법」(환경부고시 제2025-165호) 별표 기준 1일 오수발생량(㎥)."""
    total, parts = ZERO, []
    apts = [u for u in p.units if u.kind == 'apartment' and u.count]
    if apts:
        litres = ZERO
        for u in apts:
            r = _rooms(u.exclusive_sqm)
            n = D(2) if r == 1 else D('2.7') + (r - 2) * D('0.5')   # 1인 원룸 2인, N = 2.7 + (R−2)×0.5
            litres += 200 * n * u.count
        total += litres / 1000
        parts.append(f'공동주택 {sum(u.count for u in apts):,}세대 × 200L/인·일 × 세대당 인원(방 수 추정) = {float(litres) / 1000:,.1f}㎥')
    per_sqm = {'officetel': (10, '오피스텔'), 'office': (15, '업무'), 'retail': (15, '근린생활·소매'), 'knowledge': (15, '지식산업센터(사무소 기준)'),
               'datacenter': (15, '데이터센터(사무소 기준)'), 'other': (15, '기타(사무소 기준)')}
    for kind, (lpm, label) in per_sqm.items():
        area = sum((u.supply_sqm * u.count for u in p.units if u.kind == kind), ZERO)
        if not area:
            continue
        if kind == 'retail' and area >= 3000:
            lpm, label = 20, '대규모점포'
        m3 = area * lpm / 1000
        total += m3
        parts.append(f'{label} {float(area):,.0f}㎡ × {lpm}L/㎡ = {float(m3):,.1f}㎥')
    return total, parts


# 「안양시 상수도원인자부담금 산정ㆍ징수 등에 관한 조례」(제3807호, 2025.10.13) 별표1 — 계량기 구경별 부담액(원), 공동주택은 세대별 D15
WATER_METER = {
    ('경기도', '안양시'): {'d15': 338000, 'source': '안양시 상수도원인자부담금 산정ㆍ징수 등에 관한 조례 별표1 (2025.10.13)'},
}


def utility_levy(p, basis: str, value: Decimal = ZERO) -> tuple[Decimal, str]:
    """상·하수도 원인자부담금.
    - 하수도(하수도법 제61조, 시행령 제35조①): 1일 오수발생량 10㎥ 이상이면 오수량(㎥/일) × 단위단가(원/㎥·일, 지자체 매년 공고).
      입력값 = 단위단가. (예: 서울 2025 공고 92.8만~130.9만원/㎥)
    - 상수도(수도법 제71조): 공동주택은 세대별 구경 15mm 부담액 × 세대수 + 비주거 구경별 부담액. 조례 표가 내장된 지자체는 자동,
      그 밖은 입력값 = 세대당(15mm) 부담액."""
    if basis == 'auto_sewer':
        m3, parts = sewage_m3_per_day(p)
        if m3 < 10:
            return ZERO, f'1일 오수발생량 {float(m3):,.1f}㎥ — 10㎥ 미만은 원인자부담금 대상 아님(하수도법 시행령 제35조①)'
        if not value:
            return ZERO, f'1일 오수발생량 {float(m3):,.1f}㎥ ({" · ".join(parts)}) → 입력값에 지자체 공고 단위단가(원/㎥)를 넣으세요'
        return m3 * value, f'오수발생량 {float(m3):,.1f}㎥/일 × 단위단가 {float(value):,.0f}원 ({" · ".join(parts)}) · 기존 건축물 오수량 공제 미반영'
    units = sum(u.count for u in p.units if u.kind in ('apartment', 'officetel') and u.count)
    conf = WATER_METER.get((p.site.province or '', p.site.municipality or ''))
    rate = D(conf['d15']) if conf and not value else value
    if not rate:
        return ZERO, f'주거 {units:,}세대 — 입력값에 조례의 세대당(구경 15mm) 부담액을 넣으세요 (예: 안양 338,000원)'
    nonres = sum((u.supply_sqm * u.count for u in p.units if u.kind not in ('apartment', 'officetel')), ZERO)
    return rate * units, (f'주거 {units:,}세대 × 세대당 {float(rate):,.0f}원 (구경 15mm{" · " + conf["source"] if conf and not value else ""})'
                          + (f' · 비주거 {float(nonres):,.0f}㎡는 계량기 구경별 부담액 별도' if nonres else '') + ' · 추가사업비(관로공사) 미반영')
