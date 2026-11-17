import json
import unittest
from decimal import Decimal as D
from pathlib import Path
from app.proforma import Proforma, analyze, _tax, py

SAMPLE = json.loads((Path(__file__).parent.parent / 'samples' / 'proforma.json').read_text(encoding='utf-8'))


def base(**kw):
    d = dict(land_area_sqm=D(1000), above_gfa_sqm=D(2000), below_gfa_sqm=D(0),
             units=[dict(name='소형', kind='apartment', exclusive_sqm=D(30), supply_sqm=D(400) / 121 * 10, count=10, price_per_py=D(1000))],
             costs=[], corporate_tax=dict(enabled=False), midpay=dict(enabled=False))
    d.update(kw)
    return Proforma(**d)


class ProformaTests(unittest.TestCase):
    def test_pyeong_exact(self):
        self.assertEqual(py(D(400) / 121 * 10).quantize(D(1)), D(10))

    def test_national_housing_is_vat_exempt(self):
        r = analyze(base())
        # 10평 × 1,000원 × 10세대 = 100,000원, 면세
        self.assertEqual(r['revenue']['sales_cash'], 100000)
        self.assertEqual(r['revenue']['sales_vat'], 0)

    def test_over_85_building_vat(self):
        r = analyze(base(units=[dict(name='대형', kind='apartment', exclusive_sqm=D(86), supply_sqm=D(400) / 121 * 30, count=11, price_per_py=D(1000))]))
        # 30평 × 1,000원 × 11세대 = 330,000 → 건물분 60% × 1/11 = 18,000
        self.assertEqual(r['revenue']['sales_vat'], 18000)
        self.assertEqual(r['revenue']['sales_net'], 312000)

    def test_cost_bases_and_contingency(self):
        costs = [dict(category='land', name='토지', basis='per_land_py', value=D(100)),
                 dict(category='land', name='취득세', basis='pct_land', value=D(10)),
                 dict(category='sales', name='광고', basis='pct_sales', value=D(1)),
                 dict(category='contingency', name='예비비', basis='pct_total', value=D(10))]
        r = analyze(base(land_area_sqm=D(400) / 121 * 100, costs=costs))
        cat = {c['key']: c['amount'] for c in r['costs']}
        self.assertEqual(cat['land'], 11000)      # 100평 × 100 + 10%
        self.assertEqual(cat['sales'], 1000)      # 분양대금 100,000 × 1%
        self.assertEqual(cat['contingency'], 1200)

    def test_bep_is_exact_breakeven(self):
        p = base(costs=[dict(category='construction', name='공사', basis='fixed', value=D(60000)),
                        dict(category='sales', name='대행', basis='pct_sales', value=D(10))])
        r = analyze(p)
        bep = r['summary']['bep_sales_rate_pct']
        # 이익 = 100,000×r×0.9 − 60,000 → r = 66.67%
        self.assertAlmostEqual(bep, 66.6667, places=3)
        at_bep = analyze(base(costs=p.model_dump()['costs'], sales_rate_pct=D(str(bep))))
        self.assertAlmostEqual(at_bep['summary']['pbt'], 0, delta=1)

    def test_finance_cost(self):
        r = analyze(base(loans=[dict(name='PF', amount=D(1_000_000), annual_rate_pct=D(6), months=D(24), utilization_pct=D(50), fee_pct=D(2))]))
        fin = next(c for c in r['costs'] if c['key'] == 'finance')
        self.assertEqual(fin['amount'], 60000 + 20000)

    def test_progressive_corporate_tax(self):
        p = base(corporate_tax=dict(enabled=True, local_surtax_pct=D(10)))
        # 5억: 2억×10% + 3억×20% = 8,000만 → 지방세 포함 8,800만
        self.assertEqual(_tax(p, D(500_000_000)), D(88_000_000))
        self.assertEqual(_tax(p, D(-1)), 0)

    def test_sample_runs(self):
        r = analyze(Proforma(**SAMPLE))
        self.assertGreater(r['summary']['revenue_net'], 0)
        self.assertEqual(len(r['sensitivity']['cells']), 5)
        self.assertEqual(r['costs'][0]['items'][0]['amount'], 36_300_000_000)  # 3,025평 × 1,200만

    def test_exclusive_larger_than_supply_rejected(self):
        with self.assertRaises(ValueError):
            base(units=[dict(name='x', kind='apartment', exclusive_sqm=D(90), supply_sqm=D(80), count=1, price_per_py=D(1))])


if __name__ == '__main__':
    unittest.main()
