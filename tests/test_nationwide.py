import unittest
from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from app import nationwide as n
class NationalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.patch=patch.object(n,'DB',Path(self.tmp.name)/'rules.sqlite');self.patch.start()
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def q(self):return n.Feasibility(province='경기도',municipality='광주시',zone='제2종일반주거지역',project_type='general_housing',as_of=date(2026,11,16),site_area_sqm=Decimal(10000))
 def test_missing_ordinance_blocks(self):
  self.assertEqual(n.evaluate(self.q())['status'],'review_required')
 def test_verified_assumptions(self):
  n.save_rule(n.Rule(province='경기도',municipality='광주시',zone='제2종일반주거지역',project_type='general_housing',valid_from=date(2026,1,1),far_pct=Decimal(200),bcr_pct=Decimal(60),legal_title='검증 테스트용 조례',article='제1조',source_url='https://example.org',reviewed_by='테스트 담당자',reviewed_on=date(2026,11,16)))
  q=self.q();q.confirmed_buildable_site_sqm=Decimal(8000);q.verified_parcel_and_overlays=True;q.verified_district_or_renewal_plan=True;q.sale_price_krw_per_sqm=Decimal(100);q.construction_cost_krw_per_sqm=Decimal(50)
  r=n.evaluate(q);self.assertEqual(r['status'],'assumption_based');self.assertEqual(r['calculation']['illustrative_far_floor_sqm'],'16000');self.assertEqual(r['calculation']['pre_financing_pre_tax_margin_krw'],'400000')
 def test_incentive_gate(self):
  q=self.q();q.incentive_far_pct=Decimal(50);self.assertIn('용적률 인센티브·공공기여 요건 미확인',n.evaluate(q)['blockers'])
if __name__=='__main__':unittest.main()
