"""현금흐름·세금·조례 판독·정비사업·자료함 테스트 (네트워크 불필요)."""
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from app import lawdata, documents
from app.proforma import Proforma, analyze
from app.schedule import Schedule, curve_weights, _irr, _bracket_tax
from app.proforma import TaxBracket

ROOT = Path(__file__).parent.parent
SAMPLE = json.loads((ROOT / 'samples' / 'proforma.json').read_text(encoding='utf-8'))
GAROJU = json.loads((ROOT / 'samples' / 'garoju.json').read_text(encoding='utf-8'))

ORD_TEXT = """
제49조(용도지역에서의 건폐율) ① 영 제84조제1항에 따라 도시계획조례로 정하는 용도지역에서의 건폐율은 다음 각 호와 같다.
1. 제1종 전용주거지역: 50퍼센트 이하
2. 제2종일반주거지역 : 60퍼센트 이하
3. 삭제 <2021. 12. 30.>
4. 중심상업지역 : 90퍼센트 이하(공동주택과 주거용 외의 용도가 복합된 건축물은 80퍼센트 이하)
② 다른 항
제50조(용도지역에서의 용적률) ① 각 용도지역의 용적률은 다음 각 호와 같다.
1. 제1종 전용주거지역: 100퍼센트 이하
2. 제2종일반주거지역 : 일반건축은 250퍼센트 이하(다만, 공동주택 또는 공동주택 용도가 복합된 건축물은 230퍼센트 이하, 법 제51조 에 따라 지정된 지구단위계획구역 내 공동주택은 250퍼센트 이하)
3. 삭제 <2021. 12. 30.>
4. 중심상업지역 : 1천3백퍼센트 이하
② 기타
제51조(다른 조문) 내용
"""


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(lawdata, 'DB', Path(self.tmp.name) / 'o.sqlite3')
        self.p.start()
        lawdata.seed_builtin()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_curve_sums_to_one(self):
        for c in ('s_curve', 'linear'):
            w = curve_weights(Schedule(curve=c, construction_months=24))
            self.assertAlmostEqual(float(sum(w)), 1.0, places=9)
        w = curve_weights(Schedule(curve='s_curve', construction_months=24))
        self.assertLess(w[0], w[12])  # S커브: 초기 완만

    def test_irr_known(self):
        self.assertAlmostEqual(_irr([-100] + [0] * 11 + [110]) * 100, 0.7974, places=3)

    def test_bracket_tax(self):
        b = [TaxBracket(up_to=D(200_000_000), rate_pct=D(10)), TaxBracket(up_to=None, rate_pct=D(20))]
        self.assertEqual(_bracket_tax(D(500_000_000), b), D(80_000_000))

    def test_sample_cashflow_consistency(self):
        r = analyze(Proforma(**SAMPLE))
        s, cf = r['summary'], r['cashflow']
        # 금융비용 = 현금흐름 산출 합계
        self.assertEqual(s['finance_cost'], cf['interest_total'] + cf['fee_total'] + cf['midpay_interest_total'])
        # 공사비는 전액 지급되고, 분양대금은 전액 수납된다
        rows = cf['rows']
        cons = next(c for c in r['costs'] if c['key'] == 'construction')['amount']
        self.assertAlmostEqual(sum(x['cost_construction'] for x in rows), cons, delta=len(rows))
        self.assertAlmostEqual(sum(x['deposit'] + x['midpay'] + x['balance_pay'] for x in rows),
                               r['revenue']['sales_cash'] + r['revenue']['balcony_cash'], delta=len(rows))
        # 모든 대출은 상환 완료, 세후이익 = 잔여 현금 − 자기자본
        self.assertEqual(rows[-1]['loan_balance'], 0)
        self.assertAlmostEqual(cf['residual_cash'] - cf['equity_total'], s['npat'], delta=len(rows) * 2)
        # 법인세: 연도별 소득 합계 ≈ 세전이익 (분양률 100%)
        self.assertAlmostEqual(sum(t['income'] for t in cf['tax_years']), s['pbt'], delta=len(rows) * 2)

    def test_pf_repaid_at_move_in_by_default(self):
        cf = analyze(Proforma(**SAMPLE))['cashflow']
        pf = next(l for l in cf['loans'] if l['name'] == '본PF')
        self.assertEqual(pf['end'], cf['move_in_month'])

    def test_compliance_uses_verified_ordinance(self):
        r = analyze(Proforma(**SAMPLE))
        far = next(i for i in r['compliance']['items'] if i['name'] == '용적률')
        self.assertEqual(far['limit'], 250.0)   # 안양시 도시계획 조례 제50조 제2종일반주거
        self.assertEqual(far['status'], 'ok')
        self.assertEqual(r['compliance']['zones'][0]['level'], 'ordinance')

    def test_national_fallback_is_flagged(self):
        d = json.loads(json.dumps(SAMPLE))
        d['site']['municipality'] = '미등록시'
        r = analyze(Proforma(**d))
        z = r['compliance']['zones'][0]
        self.assertEqual(z['level'], 'national')
        self.assertEqual(z['far'], 250)
        self.assertEqual(next(i for i in r['compliance']['items'] if i['name'] == '용적률')['status'], 'warn')

    def test_parking_rule(self):
        r = analyze(Proforma(**SAMPLE))
        pk = r['compliance']['parking']
        # 수도권 시: 85㎡ 이하 85㎡당 1대, 85㎡ 초과 70㎡당 1대 vs 세대당 1대(60㎡ 이하 0.7대)
        by_area = (59.9 * 120 + 84.9 * 100) / 85 + 114.5 * 10 / 70
        by_unit = 120 * 0.7 + 100 + 10
        res = max(-(-by_area // 1), -(-by_unit // 1))
        # 상가 500㎡ ÷ 안양시 조례가 없으면(테스트 DB) 시행령 근생 200㎡당 1대 = 2.5 → 0.5 이상 올림 3대
        self.assertEqual(pk['required'], res + 3)
        self.assertEqual(pk['level'], 'national')

    def test_parking_ordinance_nonres(self):
        from app import parking
        parking._save('경기도', '안양시', {'rates': {'retail': 134.0, 'office': 100.0, 'knowledge': 150.0, 'other': 200.0},
                                       'residential': {'small': 85.0, 'large': 70.0, 'per_unit': [[None, 1.0]]}, 'texts': {},
                                       'title': '안양시 주차장 설치 및 관리 조례', 'appendix': '[별표 3]', 'effective': '2025-05-16', 'url': '', 'parser': parking.PARSER_VERSION})
        d = json.loads(json.dumps(SAMPLE))
        d['units'] += [{'name': '업무', 'kind': 'office', 'exclusive_sqm': 100, 'supply_sqm': 250, 'count': 4, 'price_per_py': 1},
                       {'name': '오피스텔', 'kind': 'officetel', 'exclusive_sqm': 30, 'supply_sqm': 60, 'count': 20, 'price_per_py': 1}]
        pk = analyze(Proforma(**d))['compliance']['parking']
        self.assertEqual(pk['level'], 'ordinance')
        # 주거: 조례 세대(호실)당 1대 → 120+100+10+20 = 250 > 면적 기준
        by_area = (59.9 * 120 + 84.9 * 100 + 30 * 20) / 85 + 114.5 * 10 / 70
        self.assertEqual(pk['rows'][0]['spaces'], max(250, -(-by_area // 1)))
        # 비주거: 상가 500/134 = 3.7(소수 첫째 자리 버림) + 업무 1000/100 = 10.0 → 13.7 → 14대
        self.assertEqual(pk['rows'][-1]['spaces'], 14)
        self.assertEqual(pk['required'], pk['rows'][0]['spaces'] + 14)

    def test_parking_banded_and_missing(self):
        from app import parking
        parking._save('경기도', '안양시', {'rates': {}, 'texts': {}, 'title': '조례', 'parser': parking.PARSER_VERSION,
                                       'residential': {'bands': [[60.0, 1.0, None, None, None], [85.0, 1.5, None, None, None], [None, None, 50.0, None, None]], 'apt_min': None}})
        pk = analyze(Proforma(**SAMPLE))['compliance']['parking']
        # 59.9㎡ 120세대 × 1.0 + 84.9㎡ 100세대 × 1.5 + 114.5㎡ 10세대 × (114.5/50) = 120 + 150 + 22.9 → 293
        self.assertEqual(pk['rows'][0]['spaces'], 293)
        parking._save('경기도', '안양시', {'missing': True, 'rates': {}, 'residential': None, 'texts': {}, 'title': '', 'parser': parking.PARSER_VERSION})
        pk = analyze(Proforma(**SAMPLE))['compliance']['parking']
        self.assertEqual(pk['level'], 'national')

    def test_plan_values_out_of_range_do_not_break(self):
        d = json.loads(json.dumps(SAMPLE))
        d['site']['plan'] = {'kind': 'district', 'base_far': 250, 'max_floors': 25.4, 'height_limit_m': 99999, 'allowed_uses': 'x' * 1000, 'block': 'y' * 99}
        pl = Proforma(**d).site.plan
        self.assertEqual((pl.max_floors, pl.height_limit_m, len(pl.allowed_uses), len(pl.block)), (25, None, 400, 40))

    def test_plan_far_without_zone_far(self):
        d = json.loads(json.dumps(SAMPLE))
        d['site']['zones'] = [{'zone': '미지정', 'area_sqm': 10000}]
        d['site']['plan'] = {'kind': 'district', 'base_far': 250, 'notice_no': 'x'}
        self.assertEqual(analyze(Proforma(**d))['compliance']['plan']['far'], 250)


class OrdinanceParserTests(unittest.TestCase):
    def test_parse(self):
        r = lawdata.parse_ordinance(ORD_TEXT)
        L = r['limits']
        self.assertEqual(L['제1종전용주거지역'], {'bcr': 50.0, 'far': 100.0})
        self.assertEqual(L['제2종일반주거지역']['far'], 250.0)
        self.assertEqual(L['제2종일반주거지역']['far_apt'], 230.0)     # 공동주택 별도 기준
        self.assertEqual(L['중심상업지역']['far'], 1300.0)              # 한글 단위 숫자
        self.assertEqual(L['중심상업지역']['bcr_apt'], 80.0)
        self.assertEqual((r['articles']['bcr'], r['articles']['far']), ('제49조', '제50조'))
        self.assertEqual(r['parse_warnings'], [])

    def test_out_of_range_warns(self):
        r = lawdata.parse_ordinance(ORD_TEXT.replace('100퍼센트 이하', '180퍼센트 이하', 1))
        self.assertTrue(any('시행령 범위' in w for w in r['parse_warnings']))

    def test_candidates(self):
        self.assertEqual(lawdata.ordinance_candidates('서울특별시', '강남구'), ['서울특별시도시계획조례'])
        self.assertEqual(lawdata.ordinance_candidates('경상북도', '예천군')[0], '예천군군계획조례')
        self.assertEqual(lawdata.ordinance_candidates('제주특별자치도', '서귀포시'), ['제주특별자치도도시계획조례'])
        self.assertEqual(lawdata.ordinance_candidates('경기도', '안양시')[0], '안양시도시계획조례')
        self.assertIn('장흥군관리계획조례', lawdata.ordinance_candidates('전라남도', '장흥군'))

    def test_article_heading_variants(self):
        body = '\n 1. 제1종일반주거지역 : 60퍼센트 이하 \n 2. 일반상업지역 : 80퍼센트 이하 \n'
        for head in ('제51조(용도지역 안에서의 건폐율 <개정 2014.5.30>)', '제33조(용도구역·지역·지구안에서의 건폐율)'):
            r = lawdata.parse_ordinance(head + ' ① 용도지역 안에서의 건폐율은 다음 각 호와 같다.' + body)
            self.assertEqual(r['limits']['일반상업지역']['bcr'], 80.0, head)

    def test_source_typos_and_inline_items(self):   # 정선·고양·옥천·성주 원문 표기
        body = ('\n 1. 제1전용주거지역: 100퍼센트 이하 \n 2. 제1종일반주거지역 : 200센트 이하 \n'
                ' 3. 계획관리지역 : 100퍼센트 이하. 다만, 성장관리계획을 수립한 지역은 125퍼센트 이하. 4. 농림지역 : 80퍼센트 이하 \n'
                ' 5. 자연환경보존지역 : 50퍼센트 이하 \n')
        L = lawdata.parse_ordinance('제50조(용도지역 안에서의 용적률) ① 각 용도지역의 용적률은 다음 각 호와 같다.' + body)['limits']
        self.assertEqual({z: v['far'] for z, v in L.items()},
                         {'제1종전용주거지역': 100.0, '제1종일반주거지역': 200.0, '계획관리지역': 100.0, '농림지역': 80.0, '자연환경보전지역': 50.0})

    def test_search_result_title(self):
        html = """<a onclick="ordinInfPop('2168389','ELIS','1','Y'); return false;"><strong class="x">청도군</strong> 군계획 조례 [제명개정 2020. 10. 5.]</a>
                  <a onclick="ordinInfPop('1947625','ELIS','1','Y'); return false;">청도군장기미집행군계획시설대지보상임시특별회계설치및운영조례</a>"""
        with patch.object(lawdata, '_get', return_value=html):
            self.assertEqual(lawdata.search_ordinance('청도군'), ('2168389', '청도군 군계획 조례'))

    def test_mixed_table_fraction_notation(self):   # 가평 별표 25
        t = '공동주택 비율\n중심상업지역\n일반상업지역\n근린상업지역\n100분의 80 이상 ～ \n100분의 90 미만\n100분의 500 이하\n100분의 350 이하\n100분의 250 이하\n100분의 20 미만\n100분의 1000 이하\n100분의 800 이하\n100분의 600 이하'
        r = lawdata.parse_mixed_table(t)
        self.assertEqual(r['일반상업지역'], [{'min': 0.0, 'max': 20.0, 'far': 800.0}, {'min': 80.0, 'max': 90.0, 'far': 350.0}])

    def test_residential_part_sum(self):   # 대구 별표 2
        t = ('가. 주거용(부대시설을 포함한다) 외의 용도로 사용되는 부분의 면적은 전체 연면적의 10퍼센트 이상으로 한다. '
             '2. … 다만, 주거용 용도[공동주택 및 준주택(부대시설을 포함한다)]의 용적률 합계는 다음 각 목에서 정한 비율로 한다. '
             '가. 중심상업지역 : 450퍼센트 이하 나. 일반상업지역 : 430퍼센트 이하 다. 근린상업지역 : 400퍼센트 이하')
        self.assertEqual(lawdata.parse_res_part(t)['일반상업지역'], {'far_res_part': 430.0, 'res_max': 90.0})

    def test_unnamed_appendix_bundle(self):   # 용인 '별표', 목포 '별지서식' 안의 [별표 N]
        html = ('<a class="blu" onclick="x"><img src="a" /> 별지서식 </a> <a href="flDownload.do?flSeq=1&amp;flNm=x">'
                '<img alt="HWP" /></a>')
        body = '[별표 19] 다른 표\n[별표 20] <신설 2021.12.27.>\n상업지역 안에서 주거복합건축물의 용적률\n표\n[별표 21] 끝'
        with patch.object(lawdata, '_download_text', return_value=body):
            title, seg = lawdata.fetch_appendix('1', html, '20')
        self.assertEqual(title, '상업지역 안에서 주거복합건축물의 용적률')
        self.assertNotIn('끝', seg)


class RedevelopmentTests(unittest.TestCase):
    def test_garoju_matches_pdf_logic(self):
        d = json.loads(json.dumps(GAROJU))
        d['building_ratio_pct'] = 0  # PDF처럼 부가세 미반영
        r = analyze(Proforma(**d))
        cost = {c['key']: c for c in r['costs']}
        self.assertAlmostEqual(cost['construction']['items'][1]['amount'] / cost['construction']['items'][0]['amount'], 0.15, places=6)
        self.assertEqual(cost['finance']['amount'], 2_273_594_400)   # 직접×70% × 2% × 3년
        rd = r['redevelopment']
        ratio = (r['summary']['pbt']) / 23_790_000_000
        self.assertAlmostEqual(rd['proportional_rate_pct'], ratio * 100, places=6)
        a = rd['cases'][0]
        self.assertAlmostEqual(a['right_value'], 190_000_000 * ratio, delta=1)
        self.assertEqual(a['contribution'], 650_000_000 - a['right_value'])
        self.assertIsNotNone(rd['cases'][1]['settlement'])
        self.assertEqual(r['verdict']['financial'][0]['name'], '비례율')

    def test_general_only_sales_rate(self):
        d = json.loads(json.dumps(GAROJU))
        d['sales_rate_pct'] = 50
        rows = analyze(Proforma(**d))['revenue']['rows']
        self.assertEqual(rows[0]['buyer'], 'member')
        full = analyze(Proforma(**GAROJU))['revenue']['rows']
        self.assertEqual(rows[0]['cash'], full[0]['cash'])               # 조합원분은 분양률 무관
        self.assertAlmostEqual(rows[1]['cash'], full[1]['cash'] / 2, delta=1)


class DocumentTests(unittest.TestCase):
    def test_land_use_plan_parse(self):
        t = ('토지이용계획확인서 소재지 경기도 안양시 동안구 예시동 101-1 지목 대 면적 1,250.5 ㎡ 개별공시지가(㎡당) 4,830,000원 '
             '「국토의 계획 및 이용에 관한 법률」에 따른 지역ㆍ지구등 제2종일반주거지역 , 지구단위계획구역 , 중로1류(폭 20M~25M)(저촉) '
             '다른 법령 등에 따른 지역ㆍ지구등 과밀억제권역<수도권정비계획법> 「토지이용규제 기본법 시행령」')
        ps, warns = documents.parse_land_use_plan(t, 'x.pdf')
        p = ps[0]
        self.assertEqual((p['area_sqm'], p['jimok'], p['zones'], p['price_per_sqm']), (1250.5, '대', ['제2종일반주거지역'], 4830000.0))
        self.assertEqual(p['flags'], ['과밀억제권역', '도로', '도시계획시설', '지구단위계획구역'])
        self.assertEqual(warns, [])

    def test_address(self):
        self.assertEqual(documents.parse_address('경기도 안양시 동안구 관양동 1'), {'province': '경기도', 'municipality': '안양시'})
        self.assertEqual(documents.parse_address('서울특별시 강남구 역삼동 1'), {'province': '서울특별시', 'municipality': '강남구'})

    def test_bad_names_rejected(self):
        for n in ('../x', '_양식', '', '.hidden'):
            with self.assertRaises(ValueError):
                documents.site_dir(n) if n != '../x' else documents.site_dir(n).relative_to(documents.INBOX)


if __name__ == '__main__':
    unittest.main()


class UrbanPlanTests(unittest.TestCase):
    """3차 지자체 도시계획 (법령 원문 확인: 국토계획법 시행령 제46조, 도시정비법 제54조, 빈집법 제49조)."""
    def run_plan(self, plan, flags=()):
        d = json.loads(json.dumps(SAMPLE))
        d['site']['plan'] = plan
        d['site']['flags'] = list(flags)
        return analyze(Proforma(**d))['compliance']

    def test_district_public_land_bonus(self):
        c = self.run_plan({'kind': 'district', 'base_far': 230, 'allowed_far': 250, 'max_far': 300, 'plan_bcr': 50, 'public_land_sqm': 500,
                           'notice_no': 'x'})
        pl = c['plan']
        # 250 + 1.5 × 500 × 230 / 9,500
        self.assertAlmostEqual(pl['far'], 250 + 1.5 * 500 * 230 / 9500, places=6)
        self.assertAlmostEqual(pl['gfa'], 9500 * pl['far'] / 100, places=4)
        self.assertAlmostEqual(pl['bcr'], 50 * (1 + 500 / 10000), places=6)   # 제46조①1호가목

    def test_district_capped_by_max(self):
        c = self.run_plan({'kind': 'district', 'base_far': 230, 'allowed_far': 250, 'max_far': 260, 'public_land_sqm': 2000})
        self.assertEqual(c['plan']['far'], 260)

    def test_district_block_height_uses(self):
        c = self.run_plan({'kind': 'district', 'base_far': 244.13, 'plan_bcr': 30, 'notice_no': 'x', 'block': '택지1',
                           'max_floors': 25, 'height_limit_m': 80, 'allowed_uses': '공동주택(아파트)'})
        it = next(i for i in c['items'] if i['name'].startswith('높이·용도'))
        self.assertIn('택지1', it['name'])
        self.assertIn('최고 25층', it['detail'])
        self.assertIn('공동주택', it['detail'])
        self.assertIn('획지 택지1', next(i for i in c['items'] if i['name'] == '3차 도시계획 적용')['detail'])

    def test_reconstruction_obligation_and_range(self):
        c = self.run_plan({'kind': 'reconstruction', 'base_far': 250, 'max_far': 300, 'use_max': True, 'housing_ratio_pct': 20}, ['과밀억제권역'])
        self.assertEqual(c['plan']['far'], 300)
        self.assertAlmostEqual(c['plan']['obligation_sqm'], 50 / 100 * 10000 * 0.20, places=4)
        item = next(i for i in c['items'] if i['name'] == '국민주택규모 주택 건설 의무')
        self.assertEqual(item['status'], 'bad')   # 과밀억제권역 재건축 30~50% 범위 밖

    def test_small_scale_rental_threshold(self):
        ok = self.run_plan({'kind': 'small', 'base_far': 250, 'max_far': 300, 'use_max': True, 'housing_ratio_pct': 20})
        low = self.run_plan({'kind': 'small', 'base_far': 250, 'max_far': 300, 'use_max': True, 'housing_ratio_pct': 15})
        st = lambda c: next(i for i in c['items'] if '공공임대' in i['name'])['status']
        self.assertEqual(st(ok), 'warn')
        self.assertEqual(st(low), 'bad')

    def test_district_flag_without_plan_blocks(self):
        c = self.run_plan({'kind': 'none'}, ['지구단위계획구역'])
        self.assertTrue(any(i['name'].startswith('3차 도시계획') and i['status'] == 'bad' for i in c['items']))

    def test_plan_notice_parse(self):
        n = documents.parse_plan_notice('안양시 고시 제2026-15호 관양지구 지구단위계획 결정(변경) 고시 2026. 3. 2. 기준용적률 230% 허용용적률 250% 상한용적률 280%', 'x.pdf')
        self.assertEqual((n['kind'], n['base_far'], n['allowed_far'], n['max_far'], n['notice_date']), ('district', 230.0, 250.0, 280.0, '2026-03-02'))
        self.assertIsNone(documents.parse_plan_notice('일반 문서', 'y.pdf'))

    def test_scenario_name_rejects_paths(self):
        for bad in (r'..\..\x', '../x', '..'):
            with self.assertRaises(ValueError):
                documents._scn_name(bad)


class RentalTests(unittest.TestCase):
    """공공지원민간임대 (민간임대주택법·시행규칙 별표1·2, 지특법 제31조의3, 주택도시기금 — 2026-11-16 확인)."""
    def load(self, **rental):
        d = json.loads((ROOT / 'samples' / 'rental.json').read_text(encoding='utf-8'))
        d['rental'].update(rental)
        return analyze(Proforma(**d))

    def test_fund_loan_auto(self):
        R = self.load()['rental']
        # 59.9㎡ 120호 × 1억(2.9%) + 84.9㎡ 110호 × 1.2억(3.4%)
        self.assertEqual(R['fund_loan'], 120 * 100_000_000 + 110 * 120_000_000)
        self.assertAlmostEqual(R['fund_rate_pct'], (120e8 * 2.9 + 132e8 * 3.4) / 252e8, places=6)

    def test_property_tax_relief_weighted(self):
        R = self.load()['rental']
        self.assertAlmostEqual(R['property_tax_relief_pct'], (120 * 75 + 110 * 50) / 230, places=6)   # 40~60㎡ 75%, 60~85㎡ 50%

    def test_special_rent_cap_by_share(self):
        self.assertTrue(any('특별공급 임대료' in w for w in self.load(special_share_pct=20, special_rent_ratio_pct=72)['rental']['warnings']))
        self.assertFalse(any('특별공급 임대료' in w for w in self.load(special_share_pct=30, special_rent_ratio_pct=75)['rental']['warnings']))
        self.assertTrue(any('의무비율' in w for w in self.load(special_share_pct=15)['rental']['warnings']))

    def test_rent_growth_cap(self):
        self.assertTrue(any('증액률' in w for w in self.load(rent_growth_pct=6)['rental']['warnings']))

    def test_equity_flows_close(self):
        r = self.load()
        R = r['rental']
        self.assertEqual(len(R['equity_flows']), R and 11)
        self.assertEqual(R['equity_flows'][0], -R['equity'] + R['equity_release'])


class LandInfoTests(unittest.TestCase):
    def test_pnu(self):
        from app.landinfo import make_pnu
        self.assertEqual(make_pnu('4117310400', '경기 안양시 동안구 관양동 1591'), '4117310400115910000')
        self.assertEqual(make_pnu('4117310400', '관양동 1593-1'), '4117310400115930001')
        self.assertEqual(make_pnu('4117310400', '관양동 산 12-3'), '4117310400200120003')
        with self.assertRaises(ValueError):
            make_pnu('41173', '1591')

    def test_parse_latest_year(self):
        import io as _io
        from app import landinfo
        body = {'landCharacteristicss': {'field': [
            {'stdrYear': '2024', 'lndpclAr': '1180.5', 'lndcgrCodeNm': '대', 'prposArea1Nm': '제2종일반주거지역', 'pblntfPclnd': '4500000'},
            {'stdrYear': '2025', 'lndpclAr': '1200', 'lndcgrCodeNm': '대', 'prposArea1Nm': '제2종일반주거지역', 'prposArea2Nm': '지정되지않음', 'pblntfPclnd': '4830000'}]}}
        class Resp(_io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with patch.object(landinfo, 'load_settings', return_value={'vworld_key': 'TESTKEY'}), \
             patch('urllib.request.urlopen', return_value=Resp(json.dumps(body).encode())):
            r = landinfo.land_info('4117310400115910000')
        self.assertEqual((r['area_sqm'], r['jimok'], r['zone'], r['price_per_sqm'], r['year']), (1200.0, '대', '제2종일반주거지역', 4830000.0, '2025'))
        self.assertEqual(r['zones'], ['제2종일반주거지역'])

    def test_no_key(self):
        from app import landinfo
        with patch.object(landinfo, 'load_settings', return_value={}):
            with self.assertRaises(PermissionError):
                landinfo.land_info('4117310400115910000')


class EumTests(unittest.TestCase):
    """토지이음 결정조서 용적률 추출 (안양시 고시 제2025-132호 결정조서 문구 형식)."""
    def test_extract_far(self):
        from app.eum import extract_far
        t = ('건폐율 60% 이하 용적률 기준용적률 : 200% 이하 허용용적률 : 280% 이하 상한용적률 : 400% 이하 '
             '※ 기부채납 등 인센티브에 따른 완화 높이 최고 33층')
        r = extract_far(t)
        self.assertEqual((r['base_far'], r['allowed_far'], r['max_far'], r['plan_bcr']), (200.0, 280.0, 400.0, 60.0))

    def test_msvc_rand_sequence(self):
        from app.eum import _msvc_rand
        g = _msvc_rand(1)
        self.assertEqual([next(g) for _ in range(3)], [41, 18467, 6334])   # MSVC rand() 표준 수열 (srand(1))


class DesignPdfTests(unittest.TestCase):
    """설계도서 PDF: 2단 머리(분양면적 › 전용/공용/계 › ㎡/평) 타입별 표 + 설계개요."""
    def test_parse(self):
        import tempfile
        from pathlib import Path
        import pymupdf
        from app import design
        with tempfile.TemporaryDirectory() as td:
            d = pymupdf.open(); p = d.new_page(width=842, height=595)
            for y, t in [(50, '설계개요'), (70, '대지면적 2,450.30㎡ (741.22평)'), (86, '건축면적 1,450.12㎡'), (102, '지상층 면적 24,410.20㎡'),
                         (118, '지하층 면적 8,150.30㎡'), (134, '주차대수 법정 210대 / 계획 230대')]:
                p.insert_text((60, y), t, fontname='korea', fontsize=9)
            p = d.new_page(width=842, height=595)
            cols = [0, 50, 110, 170, 230, 290, 350, 410]
            rows = [['', '분양면적', '', '', '', '', '', '실수'], ['TYPE', '전용', '', '공용', '', '계', '', ''],
                    ['', '㎡', '평', '㎡', '평', '㎡', '평', ''], ['A', '26.40', '7.99', '18.62', '5.63', '45.02', '13.62', '160'],
                    ['B', '33.85', '10.24', '23.87', '7.22', '57.72', '17.46', '120']]
            p.insert_text((60, 40), '오피스텔 타입별 분양면적표', fontname='korea', fontsize=9)
            for r, row in enumerate(rows):
                for c, t in enumerate(row):
                    if t: p.insert_text((60 + cols[c], 70 + r * 16), t, fontname='korea', fontsize=9)
            f = Path(td) / 'design.pdf'; d.save(f); d.close()
            r = design.parse_pdfs([f])
        ov = r['overview']
        self.assertEqual((ov['land_area_sqm'], ov['above_gfa_sqm'], ov['below_gfa_sqm'], ov['parking']), (2450.3, 24410.2, 8150.3, 230))
        self.assertEqual([(u['name'], u['count'], u['exclusive_sqm'], u['supply_sqm']) for u in r['units']],
                         [('오피스텔 A', 160, 26.4, 45.02), ('오피스텔 B', 120, 33.85, 57.72)])

    def test_floor_label(self):
        from app.design import floor_of
        self.assertEqual([floor_of(x) for x in ('B2', '지하1층', '1F', '12층', '지상3층', 'PH')], [-2, -1, 1, 12, 3, None])


class AuthTests(unittest.TestCase):
    """접속 비밀번호: 원격(테스트 클라이언트)은 로그인 필요, 직원은 삭제·설정 불가. 임시 설정 파일 사용."""
    def setUp(self):
        import tempfile
        from pathlib import Path
        from app import landinfo, auth
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = landinfo.SETTINGS
        landinfo.SETTINGS = Path(self.tmp.name) / 'settings.json'
        auth._fails.clear()

    def tearDown(self):
        from app import landinfo
        landinfo.SETTINGS = self._orig
        self.tmp.cleanup()

    def test_flow(self):
        import asyncio, json as _j
        from app.main import app
        from app import auth
        jar = {}

        def req(method, path, body=None, cookie=None):
            """원격 PC(10.0.0.5)에서 보낸 요청을 ASGI 로 직접 실행."""
            data = _j.dumps(body).encode() if body is not None else b''
            ck = cookie if cookie is not None else '; '.join(f'{k}={v}' for k, v in jar.items())
            headers = [(b'content-type', b'application/json'), (b'host', b'x')] + ([(b'cookie', ck.encode())] if ck else [])
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http',
                     'path': path, 'raw_path': path.encode(), 'query_string': b'', 'root_path': '', 'headers': headers,
                     'client': ('10.0.0.5', 50000), 'server': ('x', 80)}
            out = {'status': None, 'headers': []}
            sent = [False]

            async def receive():
                if not sent[0]:
                    sent[0] = True
                    return {'type': 'http.request', 'body': data, 'more_body': False}
                return {'type': 'http.disconnect'}

            async def send(m):
                if m['type'] == 'http.response.start':
                    out['status'] = m['status']; out['headers'] = m['headers']
            asyncio.run(app(scope, receive, send))
            for k, v in out['headers']:
                if k == b'set-cookie':
                    name, _, rest = v.decode().partition('=')
                    val = rest.split(';')[0].strip('"')
                    if val and 'Max-Age=0' not in v.decode() and 'expires=Thu, 01 Jan 1970' not in v.decode():
                        jar[name] = val
                    else:
                        jar.pop(name, None)
            return out['status']

        self.assertEqual(req('GET', '/api/v4/sites'), 401)
        self.assertEqual(req('GET', '/'), 303)
        self.assertEqual(req('POST', '/api/v4/auth/login', {'password': 'x'}), 403)          # 비밀번호 미설정
        auth.set_passwords('admin-pass-1', 'staff-pass-1')
        self.assertNotIn('admin-pass-1', auth.landinfo.SETTINGS.read_text(encoding='utf-8'))  # 해시만 저장
        self.assertEqual(req('POST', '/api/v4/auth/login', {'password': 'wrong'}), 401)
        self.assertEqual(req('POST', '/api/v4/auth/login', {'password': 'staff-pass-1'}), 200)
        self.assertEqual(req('GET', '/api/v4/sites'), 200)
        self.assertEqual(req('DELETE', '/api/v4/sites/anything'), 403)                        # 직원: 사업지 삭제 불가
        self.assertEqual(req('PUT', '/api/v4/settings', {}), 403)
        self.assertEqual(req('POST', '/api/v4/auth/passwords', {'admin': 'hijack-123'}), 403)
        req('POST', '/api/v4/auth/logout')
        self.assertEqual(req('GET', '/api/v4/sites'), 401)
        self.assertEqual(req('POST', '/api/v4/auth/login', {'password': 'admin-pass-1'}), 200)
        self.assertEqual(req('DELETE', '/api/v4/sites/없는사업지_테스트'), 404)              # 관리자: 통과 (대상 없음)
        self.assertEqual(req('GET', '/api/v4/sites', cookie=f'{auth.COOKIE}=admin.9999999999.forged'), 401)   # 위조 쿠키

    def test_lockout(self):
        from app import auth
        auth.set_passwords('admin-pass-1', None)
        for _ in range(5):
            self.assertIsNone(auth.login('bad', '10.0.0.9'))
        with self.assertRaises(PermissionError):
            auth.login('admin-pass-1', '10.0.0.9')


class TemplateTests(unittest.TestCase):
    """용도별 템플릿 9종: 모두 계산되고, 자금 부족·용적률 초과 같은 구조적 부적합이 없어야 한다."""
    def test_templates(self):
        import json
        from pathlib import Path
        from app.proforma import Proforma, analyze
        idx = json.loads(Path('samples/templates.json').read_text(encoding='utf-8'))
        self.assertEqual(len(idx), 9)
        for t in idx:
            d = json.loads(Path(f"samples/tpl_{t['key']}.json").read_text(encoding='utf-8'))
            r = analyze(Proforma.model_validate(d))
            self.assertGreater(r['summary']['margin_pct'], 10, t['key'])
            self.assertFalse(r['summary'].get('extra_equity'), t['key'])
            self.assertNotEqual(r['verdict']['overall'], 'bad', (t['key'], [x['text'] for x in r['verdict']['reasons'] if x['status'] == 'bad']))


class MixedUseTests(unittest.TestCase):
    """용도용적제: 지자체 별표 표 형식 (군포·시흥·김포·구리·광명 원문 형식) + 사업수지 적용."""
    def test_formats(self):
        P = lawdata.parse_mixed_table
        gunpo = '\n'.join(['연면적의', '합계에 대한', '주거용 비율', '중심', '상업지역', '일반', '상업지역', '근린', '상업지역',
                           '80이상∼90미만', '-', '400% 이하', '300% 이하', '30미만', '1,000% 이하', '800% 이하', '600% 이하'])
        self.assertEqual(lawdata.mixed_far(P(gunpo)['일반상업지역'], 85), 400)
        siheung = "주거용 비율 | 중심·일반상업지역 | 근린상업지역 | 80% 이상 90% 미만 | 800% 이하 | 500% 이하 | 70% 미만 | 1,000% 이하 | 700% 이하"
        r = P(siheung)
        self.assertEqual((lawdata.mixed_far(r['중심상업지역'], 85), lawdata.mixed_far(r['일반상업지역'], 50)), (800, 1000))
        gimpo = "주거용 비율(%) | 중심상업지역 | 일반상업지역 | 근린상업지역 | 90미만~ 80이상 | - | 500~549 | 450~499 | 40미만 | 1,000이하 | 800이하 | 700이하"
        self.assertEqual(lawdata.mixed_far(P(gimpo)['일반상업지역'], 85), 524.5)      # 범위 값 비례
        guri = "1. 중심·근린상업지역 | 주거면적 비율 | 중심상업지역 | 근린상업지역 | 40퍼센트 미만 | 900퍼센트 이하 | 600퍼센트 이하 | 2. 일반상업지역 | 주거면적 비율 | 일반상업지역 | 80퍼센트 이상 90퍼센트 미만 | 450퍼센트 이하"
        r = P(guri)
        self.assertEqual((r['근린상업지역'][0]['far'], r['일반상업지역'][0]['far']), (600, 450))
        gwangmyeong = "주거면적 비율(%)        중심상업지역(%)        일반상업지역(%)        근린상업지역(%)          80 이상 ～ 90 미만        500 이하        400 이하        250 이하          70 이상 ～ 80 이하        550 이하        450 이하        300 이하"
        self.assertEqual(lawdata.mixed_far(P(gwangmyeong)['일반상업지역'], 75), 450)

    def test_compliance(self):
        d = json.loads(json.dumps(SAMPLE))
        d['site']['province'], d['site']['municipality'] = '경기도', '테스트시'
        d['site']['zones'] = [{'zone': '일반상업지역', 'area_sqm': d['land_area_sqm']}]
        lim = {'일반상업지역': {'bcr': 80, 'far': 800, 'mixed': [{'min': 80, 'max': 90, 'far': 400}, {'min': 0, 'max': 30, 'far': 800}], 'mixed_src': '[별표 18]', 'mixed_basis': 'res'}}
        lawdata.save_cache('경기도', '테스트시', {'ordin_seq': 'T', 'title': '테스트시 도시계획 조례', 'effective': '2026-01-01', 'url': '', 'limits': lim, 'articles': {}})
        try:
            r = analyze(Proforma(**d))
            z = r['compliance']['zones'][0]
            self.assertEqual(z['far'], 400)                                  # 주거비율 약 88% → 400%
            self.assertTrue(any('용도용적제' in i['name'] for i in r['compliance']['items']))
        finally:
            c = lawdata._conn(); c.execute("DELETE FROM ordinance_cache WHERE municipality='테스트시'"); c.commit(); c.close()


class ReportBuildTests(unittest.TestCase):
    def test_report_builds_for_all_samples(self):
        # 주차 산정 내역 루프 변수가 분석 결과(r)를 덮어써 보고서가 깨졌던 문제 회귀 방지
        from app.report import build
        for name in ('proforma.json', 'garoju.json', 'rental.json'):
            p = Proforma(**json.loads((ROOT / 'samples' / name).read_text(encoding='utf-8')))
            self.assertTrue(build(p, analyze(p))[:2] == b'PK', name)


class PlanResFarTests(unittest.TestCase):
    def test_residential_part_cap(self):
        d = json.loads(json.dumps(SAMPLE))
        d['site']['plan'] = {'kind': 'district', 'base_far': 275, 'res_far': 220, 'notice_no': 'x'}
        p = Proforma(**d)
        from app.proforma import residential_share
        share = residential_share(p, include_officetel=True)
        far = analyze(p)['compliance']['plan']['far']
        self.assertAlmostEqual(far, min(275, 220 * 100 / share), places=4)
