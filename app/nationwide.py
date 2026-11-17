"""Nationwide ordinance evidence registry and gated feasibility calculations.
No ordinance is presumed to apply merely because a jurisdiction is selected.
Verified legal figures must be supplied by a reviewer with documentary evidence.
"""
import json
import sqlite3
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, model_validator

from .config import DB
PROVINCES = ['서울특별시','부산광역시','대구광역시','인천광역시','광주광역시','대전광역시','울산광역시','세종특별자치시','경기도','강원특별자치도','충청북도','충청남도','전북특별자치도','전라남도','경상북도','경상남도','제주특별자치도']

def connection():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS rules (
      id INTEGER PRIMARY KEY AUTOINCREMENT, province TEXT NOT NULL,
      municipality TEXT NOT NULL, zone TEXT NOT NULL, project_type TEXT NOT NULL,
      valid_from TEXT NOT NULL, valid_to TEXT, far_pct TEXT NOT NULL,
      bcr_pct TEXT NOT NULL, legal_title TEXT NOT NULL, article TEXT NOT NULL,
      source_url TEXT NOT NULL, reviewed_by TEXT NOT NULL,
      reviewed_on TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
      UNIQUE(province,municipality,zone,project_type,valid_from))''')
    c.commit()
    return c

class Rule(BaseModel):
    province: str
    municipality: str
    zone: str
    project_type: Literal['general_housing','station_area_renewal']
    valid_from: date
    valid_to: date|None=None
    far_pct: Decimal=Field(gt=0,le=1500)
    bcr_pct: Decimal=Field(gt=0,le=100)
    legal_title: str=Field(min_length=2)
    article: str=Field(min_length=1)
    source_url: str=Field(pattern=r'^https?://')
    reviewed_by: str=Field(min_length=2)
    reviewed_on: date
    notes: str=''
    @model_validator(mode='after')
    def check(self):
        if self.province not in PROVINCES: raise ValueError('지원하지 않는 광역지자체')
        if self.valid_to and self.valid_to<self.valid_from: raise ValueError('종료일이 시작일보다 빠름')
        return self

class Feasibility(BaseModel):
    province:str
    municipality:str
    zone:str
    project_type:Literal['general_housing','station_area_renewal']
    as_of:date
    site_area_sqm:Decimal=Field(gt=0)
    confirmed_buildable_site_sqm:Decimal|None=Field(default=None,gt=0)
    verified_parcel_and_overlays:bool=False
    verified_district_or_renewal_plan:bool=False
    verified_incentive_and_contribution:bool=False
    incentive_far_pct:Decimal=Field(default=Decimal('0'),ge=0)
    contribution_cost_krw:Decimal=Field(default=Decimal('0'),ge=0)
    saleable_ratio:Decimal=Field(default=Decimal('0.75'),gt=0,le=1)
    sale_price_krw_per_sqm:Decimal=Field(default=Decimal('0'),ge=0)
    construction_cost_krw_per_sqm:Decimal=Field(default=Decimal('0'),ge=0)
    other_cost_krw:Decimal=Field(default=Decimal('0'),ge=0)
    @model_validator(mode='after')
    def check(self):
        if self.confirmed_buildable_site_sqm and self.confirmed_buildable_site_sqm>self.site_area_sqm:
            raise ValueError('확정 대지면적이 사업부지 면적을 초과')
        return self

def save_rule(rule:Rule):
    c=connection()
    try:
        v=rule.model_dump(mode='json')
        c.execute('''INSERT INTO rules (province,municipality,zone,project_type,valid_from,valid_to,far_pct,bcr_pct,legal_title,article,source_url,reviewed_by,reviewed_on,notes)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',tuple(str(v[k]) if v[k] is not None else None for k in ['province','municipality','zone','project_type','valid_from','valid_to','far_pct','bcr_pct','legal_title','article','source_url','reviewed_by','reviewed_on','notes']))
        c.commit()
        return {'id':c.execute('SELECT last_insert_rowid()').fetchone()[0],'status':'registered_for_review','notice':'입력 근거의 진위 및 현행 여부는 등록자가 확인해야 합니다.'}
    finally:c.close()

def find_rule(q:Feasibility):
    c=connection()
    try:
        rows=c.execute('''SELECT * FROM rules WHERE province=? AND municipality=? AND zone=? AND project_type=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>=?) ORDER BY valid_from DESC''',
          (q.province,q.municipality,q.zone,q.project_type,q.as_of.isoformat(),q.as_of.isoformat())).fetchall()
        return [dict(r) for r in rows]
    finally:c.close()

def num(x):return str(x.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def evaluate(q:Feasibility):
    rules=find_rule(q)
    blockers=[]
    if len(rules)!=1: blockers.append('해당 날짜·사업유형·지역의 조례 수치가 유일하게 확인되지 않았습니다 (0건 또는 중복)')
    if not q.verified_parcel_and_overlays: blockers.append('필지별 용도지역 및 중첩규제 미검토')
    if not q.verified_district_or_renewal_plan: blockers.append('지구단위계획·정비계획·개별 고시 미검토')
    if not q.confirmed_buildable_site_sqm: blockers.append('건축법상 산정 대지면적 미확정')
    if q.incentive_far_pct and not q.verified_incentive_and_contribution: blockers.append('용적률 인센티브·공공기여 요건 미확인')
    result={'status':'review_required' if blockers else 'assumption_based','blockers':blockers,'rule':rules[0] if len(rules)==1 else None,'calculation':None,
      'notice':'검토자가 등록한 조례 및 사업 가정의 산술 결과입니다. 인허가 승인 또는 사업수지 확정이 아닙니다.'}
    if blockers:return result
    rule=rules[0]; area=q.confirmed_buildable_site_sqm
    far=Decimal(rule['far_pct'])+q.incentive_far_pct
    bcr=Decimal(rule['bcr_pct'])
    far_floor=area*far/100
    footprint=area*bcr/100
    saleable=far_floor*q.saleable_ratio
    revenue=saleable*q.sale_price_krw_per_sqm
    construction=far_floor*q.construction_cost_krw_per_sqm
    total=construction+q.contribution_cost_krw+q.other_cost_krw
    result['calculation']={'far_pct':str(far),'bcr_pct':str(bcr),'illustrative_far_floor_sqm':str(far_floor),'illustrative_footprint_sqm':str(footprint),
      'assumed_saleable_sqm':str(saleable),'assumed_revenue_krw':num(revenue),'assumed_construction_krw':num(construction),
      'assumed_contribution_krw':num(q.contribution_cost_krw),'assumed_other_cost_krw':num(q.other_cost_krw),
      'assumed_total_cost_krw':num(total),'pre_financing_pre_tax_margin_krw':num(revenue-total)}
    return result
