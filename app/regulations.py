"""Evidence-led legal review. No automatic approval from a zoning label."""
from decimal import Decimal
from datetime import date

SOURCES = {
 'gwangju': {'jurisdiction':'경기도 광주시','effective':'2026-04-15','ordinance':'광주시 도시계획 조례','url':'https://www.law.go.kr/ordinInfoP.do?gubun=ELIS&ordinSeq=2123363',
  'zones':{'제2종일반주거지역':{'far':250,'bcr':60},'제3종일반주거지역':{'far':300,'bcr':50},'제1종일반주거지역':{'far':180,'bcr':60}},'articles':{'far':'제60조 제1항','bcr':'제55조 제1항'}},
 'seoul': {'jurisdiction':'서울특별시','effective':'2026-05-18','ordinance':'서울특별시 역세권 장기전세주택 공급 및 지원에 관한 조례','url':'https://www.law.go.kr/ordinInfoP.do?ordinSeq=2130153','station_distance_m':500,'articles':{'station':'제2조 제1호'},'zones':{}}
}

def review(site:dict):
    region=site.get('jurisdiction','').strip(); zone=site.get('zone','').strip()
    selected=next((v for v in SOURCES.values() if v['jurisdiction']==region),None)
    issues=[]; citations=[]; limits={}
    if not selected: issues.append('해당 지자체 조례가 등록·검증되지 않았습니다. 자동 수지 확정 불가')
    else:
        citations.append({'title':selected['ordinance'],'effective':selected['effective'],'url':selected['url']})
        if zone in selected['zones']:
            limits=selected['zones'][zone].copy()
        else: issues.append('해당 용도지역의 조례 수치가 검증 등록되지 않았습니다')
    if site.get('project_type')=='station_area_renewal':
        if region=='서울특별시':
            dist=site.get('station_distance_m')
            if dist is None: issues.append('역 승강장 경계 기준 거리 확인 필요')
            elif Decimal(str(dist))>500: issues.append('입력된 역 거리 500m 초과: 조례상 역세권 정의 충족 여부 별도 검토')
            else: issues.append('역 거리 조건만 검토됨: 정비계획·공공기여·임대주택 등 추가 심사 필요')
        else: issues.append('해당 지역의 역세권 정비사업 특별 기준 검토 필요')
    if not site.get('district_plan_verified'): issues.append('지구단위계획·정비계획·개별 고시 검토 미완료')
    if not site.get('parcel_zoning_verified'): issues.append('필지별 용도지역·중첩 규제 검토 미완료')
    area=site.get('site_area_sqm')
    result={'jurisdiction':region,'zone':zone,'ordinance_limits':limits,'sources':citations,'issues':issues,'status':'검토필요'}
    if area is not None and limits:
        a=Decimal(str(area))
        if a<=0: raise ValueError('사업부지 면적은 0보다 커야 합니다')
        result['illustrative_max_footprint_sqm']=str(a*Decimal(str(limits['bcr']))/100)
        result['illustrative_max_far_floor_sqm']=str(a*Decimal(str(limits['far']))/100)
        result['disclaimer']='조례 일반 상한에 의한 단순 산술값. 건축허가 가능 면적·확정 용적률 아님'
    return result
