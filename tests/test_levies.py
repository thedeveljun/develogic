"""부담금·제세공과금 법정 자동 산정 (app/levies.py) — 법령 원문 대조 2026-11-17."""
import json
import unittest
from decimal import Decimal as D
from pathlib import Path

from app import levies
from app.proforma import Proforma, analyze

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = json.loads((ROOT / 'samples' / 'proforma.json').read_text(encoding='utf-8'))


def run(costs, **site):
    d = json.loads(json.dumps(SAMPLE))
    d['costs'] = [c for c in d['costs'] if c['category'] not in ('charges', 'taxes')] + costs
    d['site'].update(site)
    r = analyze(Proforma(**d))
    return {it['name']: it for cat in r['costs'] for it in cat['items']}


class LevyTests(unittest.TestCase):
    def test_school_levy_threshold_and_rate(self):
        it = run([{'category': 'charges', 'name': '학교', 'basis': 'auto_school', 'value': 0}])['학교']
        self.assertEqual(float(it['amount']), 0)            # 샘플 230세대 < 300세대
        self.assertIn('300세대 미만', it['detail'])
        d = json.loads(json.dumps(SAMPLE))
        for u in d['units']:
            if u['kind'] == 'apartment':
                u['count'] *= 2                                # 460세대
        d['costs'] = [{'category': 'charges', 'name': '학교', 'basis': 'auto_school', 'value': 0}]
        p = Proforma(**d)
        base = sum(u.supply_sqm / D('3.305785') * u.price_per_py * u.count for u in p.units if u.kind == 'apartment')
        amt = next(it for cat in analyze(p)['costs'] for it in cat['items'] if it['name'] == '학교')['amount']
        self.assertAlmostEqual(float(amt), float(base * D('0.004')), delta=1)   # 1천분의 4

    def test_metro_levy_capital_urban(self):
        it = run([{'category': 'charges', 'name': '광역', 'basis': 'auto_metro', 'value': 0}])['광역']
        self.assertIn('4%(수도권)', it['detail'])
        self.assertIn('경감 50%', it['detail'])
        self.assertGreater(float(it['amount']), 0)
        it = run([{'category': 'charges', 'name': '광역', 'basis': 'auto_metro', 'value': 0}], province='강원특별자치도', municipality='춘천시')['광역']
        self.assertEqual(float(it['amount']), 0)            # 대도시권 밖

    def test_std_cost_bands(self):
        self.assertEqual(levies.std_cost(15, D('84.9')), D('1118800'))
        self.assertEqual(levies.std_cost(25, D('39')), D('1162600'))
        self.assertEqual(levies.metro_rate('경상남도', '김해시')[0], D('0.02'))

    def test_sewer_needs_unit_price_and_threshold(self):
        it = run([{'category': 'charges', 'name': '하수', 'basis': 'auto_sewer', 'value': 0}])['하수']
        self.assertEqual(float(it['amount']), 0)
        self.assertIn('단위단가', it['detail'])
        it = run([{'category': 'charges', 'name': '하수', 'basis': 'auto_sewer', 'value': 1000000}])['하수']
        m3, _ = levies.sewage_m3_per_day(Proforma(**SAMPLE))
        self.assertAlmostEqual(float(it['amount']), float(m3 * 1000000), delta=1)

    def test_water_anyang_builtin(self):
        it = run([{'category': 'charges', 'name': '상수', 'basis': 'auto_water', 'value': 0}], province='경기도', municipality='안양시')['상수']
        self.assertEqual(float(it['amount']), 230 * 338000)

    def test_taxes(self):
        items = run([{'category': 'taxes', 'name': '보존', 'basis': 'auto_preservation', 'value': 0},
                     {'category': 'land', 'name': '토지세', 'basis': 'auto_land_tax', 'value': 0}])
        self.assertIn('2.8%', items['보존']['detail'])
        land = next(float(it['amount']) for it in items.values() if it['name'] == '토지매입비')
        self.assertAlmostEqual(float(items['토지세']['amount']), land * 0.046, delta=1)

    def test_manual_parcel_field(self):
        d = json.loads(json.dumps(SAMPLE))
        d['site']['parcels'] = [{'address': '경기도 화성시 A1블록 (지번 미확정)', 'area_sqm': 12500, 'zone': '제3종일반주거지역', 'manual': True}]
        self.assertTrue(Proforma(**d).site.parcels[0].manual)


if __name__ == '__main__':
    unittest.main()


class LandReportTests(unittest.TestCase):
    def test_report_pdf_is_readable_by_site_parser(self):
        import tempfile
        from app import landreport, documents
        rows = [{'pnu': '4117310300101380008', 'address': '경기도 안양시 동안구 평촌동', 'jibun': '138-8', 'area_sqm': 340.0, 'jimok': '대',
                 'zone': '제2종일반주거지역', 'price_per_sqm': 3301000.0, 'year': '2026',
                 'uses': [{'name': '도시지역', 'code': 'UQA001', 'relation': '포함', 'registered': '2022-11-14'},
                          {'name': '제2종일반주거지역', 'code': 'UQA122', 'relation': '포함', 'registered': '2026-03-16'},
                          {'name': '과밀억제권역', 'code': 'UBA100', 'relation': '포함', 'registered': '2015-11-16'}]},
                {'input_address': '없는주소 1', 'error': '주소를 필지로 찾지 못했습니다'}]
        with tempfile.TemporaryDirectory() as d:
            out = landreport.build_pdf('시험', rows, Path(d) / 'r.pdf')
            ps, warns = documents.parse_land_use_plan(documents.pdf_text(out), 'r.pdf')
        self.assertEqual(len(ps), 1)
        self.assertEqual((ps[0]['address'], ps[0]['area_sqm'], ps[0]['zones'], ps[0]['price_per_sqm']),
                         ('경기도 안양시 동안구 평촌동 138-8', 340.0, ['제2종일반주거지역'], 3301000.0))
        self.assertIn('과밀억제권역', ps[0]['flags'])
