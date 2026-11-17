"""운영형(project_mode='operating') — 부산 영화인 호텔·전시장 워크북(e_busan.xlsx) 재현 및 일반 동작."""
import unittest
from decimal import Decimal as D

from app.proforma import Proforma, analyze

UND = [('관리 (A&G)', [12.264659, 12.790594, 12.972317, 13.295945, 13.35649, 13.320795, 13.285456, 13.250469, 13.21583, 13.181536]),
       ('영업 (S&M)', [3.290283, 3.231805, 3.149971]),
       ('수선유지 (R&M)', [1.162421, 1.149964, 1.132531]),
       ('수도광열 (Utility)', [3.805982, 3.809369, 3.814108])]
COSTS = [   # (분류, 항목, 기준, 값) — 수지분석 E34:E78
    ('land', '토지비', 'fixed', 22100100000), ('taxes', '취·등록세', 'pct_land', 4.6), ('taxes', '국민주택채권 매입', 'fixed', 51388838),
    ('indirect', '토지관련 제비용', 'fixed', 50000000), ('construction', '도급공사비', 'per_gfa_py', 4300000),
    ('construction', '인테리어 공사비', 'fixed', 5501291669), ('construction', 'FF&E', 'per_room', 10000000),
    ('construction', '인입공사비', 'per_gfa_py', 20000), ('construction', '예술장식품비', 'fixed', 360001382),
    ('indirect', '설계비', 'per_gfa_py', 100000), ('indirect', 'CM/감리비', 'fixed', 1075000000),
    ('taxes', '보존등기비', 'fixed', 2067115349), ('taxes', '보유세 (2017)', 'fixed', 123943134), ('taxes', '토지분 VAT 불공제액', 'fixed', 785343567),
    ('indirect', '신탁수수료', 'fixed', 100000000), ('indirect', '세무/회계 관리', 'fixed', 150000000), ('indirect', '금융FA용역', 'fixed', 200000000),
    ('indirect', '지구단위계획용역', 'fixed', 100000000), ('indirect', '기타 용역비', 'fixed', 350000000), ('indirect', '호텔 컨설팅비', 'fixed', 200000000),
    ('indirect', '민원 해결비', 'fixed', 100000000), ('indirect', '테마시설 설치비', 'fixed', 5000000000), ('charges', '상하수도분담금', 'fixed', 1000000000),
    ('admin', '시행사운영비', 'fixed', 1720000000), ('contingency', '예비비 (건축비 소계 3%)', 'pct_construction_total', 3),
]


def busan(**op):
    o = {
        'hold_years': 10, 'dev_years': 3, 'cost_split_pct_by_year': [3.714, 38.9027, 57.3833], 'equity_split_pct_by_year': [45.4545, 54.5455, 0],
        'hotel': {'enabled': True, 'rooms': 362, 'days': 365, 'occupancy_pct_by_year': [77.6243093923, 80.6243093923, 82.6243093923],
                  'adr_year1': 115309.9267, 'adr_growth_pct': 1.5, 'round_sold_rooms': True, 'room_other_pct': 5,
                  'fnb_pct_of_room_by_year': [7.199901, 6.984978, 6.685622], 'other_revenue_pct_of_room': 0,
                  'rooms_cost_pct_by_year': [25.047583, 24.598402, 23.972756], 'room_other_cost_pct': 30, 'fnb_cost_pct': 91.998357,
                  'undistributed': [{'name': n, 'pct_by_year': v} for n, v in UND],
                  'base_fee_pct': 2.5, 'incentive_fee_pct': 5, 'insurance_pct': 1, 'ffe_reserve_pct': 1.5},
        'lines': [{'name': '박물관/전시장', 'kind': 'business', 'revenue_year1': 2641212049, 'cost_pct': 60, 'growth_pct': 1.5, 'start_year': 1}],
        'property_tax_year1': 0, 'debt_mode': 'carry', 'exit_cap_pct': 8, 'exit_noi_basis': 'trailing', 'sale_cost_pct': 0,
        'valuation_cap_pct': 7, 'discount_rate_pct': 7, 'yield_min_pct': 6, 'dscr_min': 1.2, 'irr_min_pct': 8,
    }
    o.update(op)
    return Proforma.model_validate({
        'project_name': '부산 영화인호텔', 'project_mode': 'operating', 'duration_months': 30,
        'land_area_sqm': 6105, 'above_gfa_sqm': 30377.3, 'below_gfa_sqm': 10652.44,
        'units': [{'name': '호텔 객실', 'kind': 'other', 'exclusive_sqm': 33.9735, 'supply_sqm': 67.8551, 'count': 362, 'price_per_py': 0, 'buyer': 'rental'},
                  {'name': '박물관/전시장', 'kind': 'other', 'exclusive_sqm': 12191.13, 'supply_sqm': 16466.21, 'count': 1, 'price_per_py': 0, 'buyer': 'rental'}],
        'costs': [{'category': c, 'name': n, 'basis': b, 'value': v} for c, n, b, v in COSTS],
        'equity': 11000000000,
        'loans': [{'name': '선순위 PF', 'amount': 79700000000, 'annual_rate_pct': 5, 'months': 16, 'utilization_pct': 49.090339, 'fee_pct': 1.5, 'start_month': 13},
                  {'name': '후순위 PF', 'amount': 18800000000, 'annual_rate_pct': 7, 'months': 18, 'utilization_pct': 100, 'fee_pct': 1.5, 'start_month': 11}],
        'corporate_tax': {'enabled': False},
        'site': {'province': '부산광역시', 'municipality': '수영구', 'zones': [{'zone': '일반상업지역', 'area_sqm': 6105}]},
        'operating': o,
    })


# 워크북 연도별 (2018~2027): 호텔 NOI, 합산 NOI(호텔 + 전시장 영업이익)
WB_HOTEL_NOI = [5645096079, 5948117096, 6258891315, 6307574277, 6393604800, 6494644925, 6597225815, 6701370691, 6807103122, 6914447034]
WB_NOI = [6701580899, 7020449188, 7347308388, 7412317606, 7514919279, 7632779122, 7752432025, 7873904993, 7997225439, 8122421186]


class OperatingBusanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = analyze(busan())
        cls.o = cls.r['operating']

    def test_output_shape(self):
        for k in ('project_name', 'area', 'revenue', 'costs', 'summary', 'sensitivity', 'redevelopment', 'cashflow', 'compliance',
                  'hug_eligibility', 'verdict', 'warnings', 'notice', 'operating', 'rental'):
            self.assertIn(k, self.r)
        self.assertIsNone(self.r['rental'])
        self.assertEqual(len(self.o['rows']), 10)
        self.assertEqual(len(self.o['equity_flows']), 13)

    def test_development_cost(self):
        # 워크북 108,482,338,299원 — per_gfa_py 항목의 ROUND(-2) 미적용·선순위 인출률 근사로 +66,171원
        self.assertAlmostEqual(self.o['total_cost'], 108_482_404_470, delta=10)
        self.assertAlmostEqual(self.o['finance_cost'], 6_059_833_333, delta=100)
        fin = next(c for c in self.r['costs'] if c['key'] == 'finance')
        self.assertEqual(fin['amount'], self.o['finance_cost'])
        self.assertEqual(len(fin['items']), 4)   # 대출별 이자·수수료
        self.assertEqual(self.r['summary']['total_cost'], self.o['total_cost'])
        ffe = next(i for c in self.r['costs'] for i in c['items'] if i['name'] == 'FF&E')
        self.assertEqual(ffe['amount'], 3_620_000_000)   # 객실당 1,000만 × 362실

    def test_hotel_and_noi_by_year(self):
        rows = self.o['rows']
        self.assertEqual([x['sold_rooms'] for x in rows[:3]], [102565, 106529, 109172])
        for x, h, n in zip(rows, WB_HOTEL_NOI, WB_NOI):
            self.assertAlmostEqual(x['hotel_noi'], h, delta=1000)
            self.assertAlmostEqual(x['noi'], n, delta=1000)
            self.assertAlmostEqual(x['interest'], 5_301_000_000, delta=1)
        self.assertAlmostEqual(rows[0]['hotel_revenue'], 13_269_615_927, delta=1000)
        self.assertAlmostEqual(rows[0]['gop'], 6_623_147_217, delta=1000)
        self.assertAlmostEqual(rows[0]['dscr'], 1.2642, places=4)

    def test_exit_and_returns(self):
        o = self.o
        self.assertAlmostEqual(o['exit_value'], 101_530_264_821, delta=1000)
        self.assertAlmostEqual(o['exit_net_to_equity'], 3_030_264_821, delta=1000)
        self.assertAlmostEqual(o['equity_irr_pct'], 11.84, delta=0.01)       # 워크북 XIRR 11.83% (매각일 2028-01-01)
        self.assertAlmostEqual(o['unlevered_irr_pct'], 6.02, delta=0.01)
        self.assertAlmostEqual(o['yield_on_cost_pct'], 6.18, delta=0.01)
        self.assertAlmostEqual(o['equity_multiple'], 2.3087, delta=0.001)
        self.assertAlmostEqual(o['equity_npv'], 3_969_799_480, delta=100_000)
        self.assertEqual(o['payback_year'], 6)
        self.assertEqual(self.r['summary']['equity_irr_pct'], o['equity_irr_pct'])
        self.assertEqual([x['status'] for x in self.r['verdict']['financial']], ['ok'] * 4)

    def test_property_tax_lowers_irr(self):
        o = analyze(busan(property_tax_year1=312407000, property_tax_growth_pct=2.4))['operating']
        self.assertAlmostEqual(o['rows'][0]['noi'], WB_NOI[0] - 312407000, delta=1000)
        self.assertLess(o['equity_irr_pct'], self.o['equity_irr_pct'])


class OperatingGeneralTests(unittest.TestCase):
    def test_finance_category_item_merged(self):
        p = busan()
        p.costs.append(p.costs[0].model_copy(update={'category': 'finance', 'name': 'PF 자문수수료', 'basis': 'fixed', 'value': D(500_000_000)}))
        r = analyze(p)
        fin = next(c for c in r['costs'] if c['key'] == 'finance')
        self.assertEqual([c['key'] for c in r['costs']].count('finance'), 1)
        self.assertEqual(fin['items'][0]['name'], 'PF 자문수수료')
        self.assertEqual(r['operating']['finance_cost'], analyze(busan())['operating']['finance_cost'] + 500_000_000)
        self.assertEqual(r['summary']['development_cost'] + r['summary']['finance_cost'], r['summary']['total_cost'])

    def test_lease_refinance_with_tax(self):
        p = Proforma.model_validate({
            'project_name': '근생 임대', 'project_mode': 'operating', 'land_area_sqm': 1000, 'above_gfa_sqm': 3000,
            'units': [{'name': '상가', 'kind': 'retail', 'exclusive_sqm': 2000, 'supply_sqm': 3000, 'count': 1, 'price_per_py': 0}],
            'costs': [{'category': 'land', 'name': '토지비', 'basis': 'fixed', 'value': 10_000_000_000},
                      {'category': 'construction', 'name': '공사비', 'basis': 'per_above_py', 'value': 8_000_000}],
            'equity': 6_000_000_000,
            'operating': {'hotel': {'enabled': False}, 'debt_mode': 'refinance', 'refi_rate_pct': 5, 'refi_amort_years': 20,
                          'lines': [{'name': '상가 임대', 'kind': 'lease', 'area_py': 600, 'rent_per_py_month': 150_000, 'occupancy_pct': 95, 'opex_pct': 10}],
                          'property_tax_year1': 30_000_000},
        })
        r = analyze(p)
        o = r['operating']
        self.assertEqual(o['rooms'], 0)
        rent1 = 600 * 150_000 * 12 * 0.95
        self.assertAlmostEqual(o['rows'][0]['noi'], rent1 * 0.9 - 30_000_000, delta=1)
        self.assertEqual(o['debt'], o['total_cost'] - 6_000_000_000)
        self.assertGreater(o['rows'][0]['principal'], 0)
        self.assertAlmostEqual(o['exit_debt_repaid'], o['debt'] - sum(x['principal'] for x in o['rows']), delta=10)
        self.assertIsNotNone(o['min_dscr'])
        self.assertTrue(any(x['tax'] >= 0 for x in o['rows']))
        self.assertEqual(r['summary']['finance_cost'], 0)

    def test_defaults_and_exports(self):
        p = busan()
        r = analyze(p)
        from app.report import build
        self.assertTrue(build(p, r).startswith(b'PK'))
        from app.scenarios import stress
        cases = stress(p)
        self.assertEqual([c['key'] for c in cases][:3], ['base', 'rev10', 'occ10'])
        base = cases[0]['kpi']['equity_irr_pct']
        for c in cases[1:]:   # 모든 하방 시나리오에서 IRR 하락 (지분 CF 가 모두 음수면 IRR 없음)
            self.assertTrue(c['kpi']['equity_irr_pct'] is None or c['kpi']['equity_irr_pct'] < base, c['key'])
        delay = next(c for c in cases if c['key'] == 'delay6')
        self.assertGreater(delay['kpi']['extra_equity'], 0)   # 건설이자 증가분 → 추가 자기자본
        # 기본값(호텔 객실 0, 라인 없음)도 계산은 되고 경고를 낸다
        q = Proforma.model_validate({'project_mode': 'operating', 'land_area_sqm': 1000, 'above_gfa_sqm': 2000,
                                     'units': [{'name': '호텔', 'kind': 'other', 'exclusive_sqm': 10, 'supply_sqm': 20, 'count': 1, 'price_per_py': 0}],
                                     'costs': [{'category': 'land', 'name': '토지비', 'basis': 'fixed', 'value': 1_000_000_000}]})
        rq = analyze(q)
        self.assertTrue(rq['warnings'])
        self.assertEqual(rq['operating']['rows'][0]['noi'], 0)


if __name__ == '__main__':
    unittest.main()
