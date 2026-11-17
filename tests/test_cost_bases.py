"""사업비 산정 기준 추가분: 금융비 분류, 부가세 제외 매출 %, 적용 용도, 토지 매입대금 %, 법정 자동(지산 감면·보유세·채권·미술작품·개발부담금)."""
import unittest
from decimal import Decimal as D
from app.proforma import Proforma, analyze


def base(**kw):
    p = {
        'project_name': '테스트', 'duration_months': 30, 'land_area_sqm': 1000, 'above_gfa_sqm': 9000, 'below_gfa_sqm': 3000,
        'price_includes_vat': False, 'building_ratio_pct': 0,
        'units': [
            {'name': '근생', 'kind': 'retail', 'exclusive_sqm': 100, 'supply_sqm': 200, 'count': 10, 'price_per_py': 20_000_000},
            {'name': '오피스텔', 'kind': 'officetel', 'exclusive_sqm': 30, 'supply_sqm': 60, 'count': 100, 'price_per_py': 10_000_000},
        ],
        'costs': [{'category': 'land', 'name': '토지매입비', 'basis': 'fixed', 'value': 10_000_000_000}],
        'corporate_tax': {'enabled': False}, 'midpay': {'mode': 'with_interest'},
    }
    p.update(kw)
    return p


def item(r, name):
    return next(i for c in r['costs'] for i in c['items'] if i['name'] == name)


PY = D(121) / D(400)


class CostBaseTest(unittest.TestCase):
    def test_kind_rates_and_finance_category(self):
        p = base()
        p['costs'] += [
            {'category': 'sales', 'name': '수수료 근생', 'basis': 'pct_sales_net', 'value': 7, 'applies_to': ['retail']},
            {'category': 'sales', 'name': '수수료 오피', 'basis': 'pct_sales_net', 'value': 5, 'applies_to': ['officetel']},
            {'category': 'finance', 'name': '지주작업비', 'basis': 'pct_land_purchase', 'value': 3},
            {'category': 'land', 'name': '법무사', 'basis': 'fixed', 'value': 50_000_000},
        ]
        r = analyze(Proforma.model_validate(p))
        retail = 200 * PY * 10 * 20_000_000
        offi = 60 * PY * 100 * 10_000_000
        self.assertAlmostEqual(item(r, '수수료 근생')['amount'], float(retail * D('0.07')), delta=1)
        self.assertAlmostEqual(item(r, '수수료 오피')['amount'], float(offi * D('0.05')), delta=1)
        self.assertEqual(item(r, '지주작업비')['amount'], 300_000_000)   # 법무사 제외, 매입대금만
        fin = next(c for c in r['costs'] if c['key'] == 'finance')
        self.assertEqual(fin['items'][0]['name'], '지주작업비')
        self.assertEqual(r['summary']['finance_cost'], fin['amount'])
        self.assertEqual(r['summary']['development_cost'] + r['summary']['finance_cost'], r['summary']['total_cost'])

    def test_pct_sales_net_excludes_vat(self):
        p = base(building_ratio_pct=50)   # VAT 별도 → 현금에 건물분 부가세 가산
        p['costs'] += [{'category': 'sales', 'name': '광고', 'basis': 'pct_sales_net', 'value': 1},
                       {'category': 'sales', 'name': '광고2', 'basis': 'pct_sales', 'value': 1}]
        r = analyze(Proforma.model_validate(p))
        self.assertLess(item(r, '광고')['amount'], item(r, '광고2')['amount'])
        self.assertAlmostEqual(item(r, '광고')['amount'], r['revenue']['sales_net'] * 0.01, delta=1)

    def test_negative_only_fixed(self):
        p = base()
        p['costs'].append({'category': 'land', 'name': '선납할인', 'basis': 'fixed', 'value': -100_000_000})
        analyze(Proforma.model_validate(p))
        p['costs'][-1]['basis'] = 'pct_land'
        with self.assertRaises(ValueError):
            Proforma.model_validate(p)

    def test_knowledge_relief(self):
        p = base(knowledge_relief_pct=50)
        p['units'] = [{'name': '지산', 'kind': 'knowledge', 'exclusive_sqm': 100, 'supply_sqm': 100, 'count': 1, 'price_per_py': 1}]
        p['costs'].append({'category': 'land', 'name': '취득세', 'basis': 'auto_land_tax', 'value': 0})
        p['costs'].append({'category': 'taxes', 'name': '보존등기', 'basis': 'auto_preservation', 'value': 1_000_000})
        r = analyze(Proforma.model_validate(p))
        self.assertAlmostEqual(item(r, '취득세')['amount'], 10_000_000_000 * 0.027, delta=1)   # 4.6%×50% + 4%×50%×20%
        gfa_py = float(12000 * PY)
        self.assertAlmostEqual(item(r, '보존등기')['amount'], gfa_py * 1_000_000 * 0.0186, delta=1)   # 3.16%×50% + 2.8%×50%×20%

    def test_holding_modes(self):
        p = base(holding={'mode': 'special', 'base': 'purchase', 'years': 1, 'fair_ratio_pct': 70})
        p['costs'].append({'category': 'land', 'name': '보유세', 'basis': 'auto_holding', 'value': 0})
        r = analyze(Proforma.model_validate(p))
        std = 7_000_000_000
        prop = 2_800_000 + (std - 1_000_000_000) * 0.004
        comp = (10_000_000_000 - 8_000_000_000) * 0.005 * 1.2
        self.assertAlmostEqual(item(r, '보유세')['amount'], prop * 1.2 + std * 0.0014 + comp, delta=1)
        p['holding']['mode'] = 'separate'
        r = analyze(Proforma.model_validate(p))
        self.assertAlmostEqual(item(r, '보유세')['amount'], std * 0.002 * 1.2 + std * 0.0014, delta=1)

    def test_bond_art_devcharge(self):
        p = base(site={'province': '서울특별시', 'municipality': '중랑구'},
                 dev_charge={'start_value': 10_000_000_000, 'end_value': 20_000_000_000, 'normal_rise_pct': 10, 'rate_pct': 25})
        p['costs'] += [{'category': 'land', 'name': '채권', 'basis': 'auto_housing_bond', 'value': 2.5},
                       {'category': 'construction', 'name': '공사비', 'basis': 'fixed', 'value': 5_000_000_000},
                       {'category': 'construction', 'name': '미술', 'basis': 'auto_art', 'value': 2_000_000},
                       {'category': 'charges', 'name': '개발부담금', 'basis': 'auto_dev_charge', 'value': 0}]
        r = analyze(Proforma.model_validate(p))
        self.assertAlmostEqual(item(r, '채권')['amount'], 10_000_000_000 * 0.05 * 0.025, delta=1)   # 특별시 5%
        self.assertAlmostEqual(item(r, '미술')['amount'], 12000 * 2_000_000 * 0.005, delta=1)
        # (200억 − 100억 − 10억 − 개발비용(공사비 50억 + 미술 1.2억)) × 25%
        self.assertAlmostEqual(item(r, '개발부담금')['amount'], (20e9 - 10e9 - 1e9 - 5e9 - 120_000_000) * 0.25, delta=1)

    def test_monthly_months_override(self):
        p = base()
        p['costs'].append({'category': 'admin', 'name': '관리비', 'basis': 'monthly', 'value': 10_000_000, 'months': 18})
        r = analyze(Proforma.model_validate(p))
        self.assertEqual(item(r, '관리비')['amount'], 180_000_000)


if __name__ == '__main__':
    unittest.main()
