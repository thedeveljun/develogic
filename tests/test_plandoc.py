"""지구단위계획 결정조서 획지별 판독 (토지이음 실제 고시 형식을 줄인 예시)."""
import unittest

from app import plandoc

# 은평 대조1 형식: 세로 나열, 기정·변경 조서, 두 획지가 한 칸씩 이어짐
VERTICAL = '\n'.join("""2) 건축물의 용도·건폐율·용적률·높이·건축선에 관한 결정(변경)조서
구분
위치
기정
택지1
택지2
용 도
허용용도
⋅ 「건축법 시행령」 별표1 제2호의 공동주택(아파트)
건폐율
⋅ 30% 이하
용적률
⋅ 244.16% 이하
높  이
⋅ 80m이하 / 25층 이하
변경
택지1
택지2
용 도
허용용도
⋅ 「건축법 시행령」 별표1 제2호의 공동주택(아파트)
건폐율
⋅ 30% 이하
용적률
⋅ 244.13% 이하
높  이
⋅ 80m이하 / 25층 이하
기정
택지3
용 도
권장용도
⋅ 제1종근린생활시설
건폐율
⋅ 60% 이하
용적률
⋅ 200% 이하
높  이
⋅ - / 7층 이하""".split('\n'))

# 오류동 형식: 획지 번호 없이 기준·허용·상한·법적상한 표, 뒤 행이 변경
DENSITY = '\n'.join("""2) 건축물의 개발밀도(건폐율, 용적률, 높이)에 관한 결정(변경) 조서
가) 건폐율 계획
구분
건폐율(%)
비고
기정
획지
제2종일반주거지역(7층 이하)
60 이하
-
변경
획지
제2종일반주거지역
60 이하
나) 용적률 계획
구분
용적률(%)
기준
허용
상한
법적상한(예정)
170
173 이하
197.5 이하
220.78 이하
기정
-
190
218.96 이하
244.57 이하
250 이하(249.99)
변경
사업성 보정계수 2.0 적용
소계
최대 20%
14.48%
다) 높이 계획
기정
제2종일반주거지역(7층 이하)
∙ 최고 15층(50m) 이하
변경
제2종일반주거지역
∙ 최고 25층 이하
∙ 80m 이하""".split('\n'))

# 아산 탕정 형식: 가로 표 (필지번호 … 건폐율 · 전체용적률), 빈 칸 '-'
GRID = '\n'.join("""가) 건축물 용도․건폐율․용적률․높이․배치․형태․색채․건축선에 관한 도시관리계획 결정(변경)조서(변경)
④ 복합용지(변경)
필지번호
주택유형
(㎡)
대지면적
(㎡)
세대수
(호)
인구수
(인)
표준면적형
(㎡)
최고
층수
건폐율
(%)
전체용적률(%)
(주거부문용적률)
비고
주상복합용지 계
231,799.6
3,931
9,922
-
-
-
-
1-C1
소 계
36,949.0
595
1,548
-
-
60
275 (주거 : 220)
분양
60~85㎡이하
15,500.0
297
773
115
복합1
-
56,332.7
815
2,119
-
-
60
300
분양""".split('\n'))


class PlanDocTests(unittest.TestCase):
    def test_vertical_prefers_changed(self):
        b = {x['block']: x for x in plandoc.parse_blocks(VERTICAL)}
        self.assertEqual(set(b), {'택지1', '택지2', '택지3'})
        self.assertEqual((b['택지1']['phase'], b['택지1']['far'], b['택지1']['bcr']), ('변경', 244.13, 30.0))
        self.assertEqual((b['택지2']['floors'], b['택지2']['height_m']), (25, 80.0))
        self.assertEqual((b['택지3']['phase'], b['택지3']['far'], b['택지3']['floors']), ('기정', 200.0, 7))
        self.assertIn('공동주택', b['택지1']['uses'])

    def test_density_table_last_row(self):
        (r,) = plandoc.parse_blocks(DENSITY)
        self.assertEqual((r['base_far'], r['allowed_far'], r['max_far'], r['legal_max_far']), (190.0, 218.96, 244.57, 250.0))
        self.assertEqual(r['far'], 218.96)       # 인센티브 소계 14.48% 가 용적률을 덮어쓰지 않음
        self.assertEqual((r['bcr'], r['floors'], r['height_m']), (60.0, 25, 80.0))

    def test_grid_alignment(self):
        b = {x['block']: x for x in plandoc.parse_blocks(GRID)}
        self.assertEqual((b['1-C1']['bcr'], b['1-C1']['far'], b['1-C1']['far_res'], b['1-C1']['area_sqm']), (60.0, 275.0, 220.0, 36949.0))
        self.assertEqual((b['복합1']['bcr'], b['복합1']['far']), (60.0, 300.0))

    def test_arrow_change(self):
        t = '건축물에 관한 결정조서\n획지1\n건폐율\n60% 이하\n용적률\n200% 이하\n높이\n3층 → 4층 이하'
        (r,) = plandoc.parse_blocks(t)
        self.assertEqual(r['floors'], 4)

    def test_locate_and_match(self):
        text = '가구 및 획지\n택지1\n대조동 88- 22번지일대\n45,614.6\n택지2\n대조동 88- 8번지일대\n' + VERTICAL
        blocks = plandoc.parse_blocks(text)
        plandoc.locate(text, blocks)
        self.assertEqual(plandoc.match_address(blocks, '서울특별시 은평구 대조동 88-22'), '택지1')
        self.assertIsNone(plandoc.match_address(blocks, '서울특별시 은평구 대조동 88-5'))   # 같은 본번 여러 획지 → 사용자 선택


if __name__ == '__main__':
    unittest.main()


class ParkingParseTests(unittest.TestCase):
    TEXT = '\n'.join("""[별표 3] 건축물 부설주차장의 설치기준
시   설   물
설  치  기  준
1. 위락시설
○시설면적 67㎡당 1대
2. 문화 및 집회시설(관람장을 제외한다), 종교시설, 판매시설, 업무시설(외국공관 및 오피스텔은 제외한다), 장례식장
○시설면적 100㎡당 1대
3. 제1종 근린생활시설, 제2종 근린생활시설, 숙박시설
○시설면적 134㎡당 1대
5. 다가구 주택, 공동주택(기숙사를 제외한다), 업무시설 중 오피스텔
○전용면적을 기준으로 85㎡ 이하인 경우 85㎡당 1대, 85㎡를 초과하는 경우 70㎡당 1대로 한다. 다만, 세대당 또는 호실당 1대에 미달되는 경우에는 세대 또는 호실당 1대 이상
10. 그 밖의 건축물
○ 학생용기숙사: 시설면적 400㎡당 1대
○ 학생용기숙사를 제외한 그 밖의 건축물: 시설면적 200㎡ 당 1대
가. 「산업집적 활성화 및 공장 설립에 관한 법률」에 따른 지식산업센터에 해당되는 건축물은 시설 면적 150㎡당 1대
<비고>
1. 공동주택 … 300㎡당 1대""".split('\n'))

    def test_parse(self):
        from app import parking
        d = parking.parse(self.TEXT)
        self.assertEqual({k: d['rates'][k] for k in ('retail', 'office', 'knowledge', 'other')},
                         {'retail': 134.0, 'office': 100.0, 'knowledge': 150.0, 'other': 200.0})
        self.assertEqual(d['residential'], {'small': 85.0, 'large': 70.0, 'per_unit': [(None, 1.0)]})

    def test_per_unit_tiers(self):
        from app import parking
        r = parking._residential('세대당 1대에 미달되는 경우에는 세대당 1대(전용면적이 30제곱미터이하인 경우에는 0.5대, 60제곱미터이하인 경우0.8대)이상')
        self.assertEqual(r['per_unit'], [(30.0, 0.5), (60.0, 0.8), (None, 1.0)])
        self.assertIsNone(parking._residential('「주택건설기준 등에 관한 규정」 제27조제1항에 따라 산정된 주차대수'))


class ParkingResidentialTests(unittest.TestCase):
    def test_special_housing_excluded_and_complex(self):
        from app import parking
        # 도시형 생활주택 별도 기준(0.9·0.7대)은 일반 공동주택에 쓰지 않는다 (안양)
        r = parking._residential('○전용면적을 기준으로 85㎡ 이하인 경우 85㎡당 1대, 85㎡를 초과하는 경우 70㎡당 1대로 한다. 다만, 세대당 또는 호실당 1대에 미달되는 경우에는 세대 또는 호실당 1대 이상 '
                                 '○「주택건설기준 등에 관한 규정」 제27조제1항제2호에 따른 도시형 생활주택은 세대당 1대(세대당 전용면적이 30제곱미터 이상 60제곱미터 이하인 경우에는 0.9대, 30제곱미터 미만인 경우에는 0.7대)')
        self.assertEqual(r, {'small': 85.0, 'large': 70.0, 'per_unit': [(None, 1.0)]})
        # 면적대별 세대당 대수(춘천): 85㎡ 초과는 50㎡당 1대
        r = parking._residential('【전용면적 60㎡ 이하】 - 세대 또는 가구․실당 1.0대 이상 【전용면적 60㎡ 초과 ∼ 85㎡ 이하】 - 세대 또는 가구․실당 1.5대 이상 '
                                 '【전용면적 85㎡ 초과】 - 세대 또는 가구․실 전용면적50㎡당 1대 이상')
        self.assertEqual([parking.per_unit_spaces(r, e, True) for e in (59, 84, 120)], [1.0, 1.5, 2.4])
        # 양양: 85㎡ 초과는 1.5대 + (전용 − 85) ÷ 85
        r = parking._residential('-전용면적 60㎡이하 : 세대(실)당 1대 -전용면적 60㎡초과∼85㎡이하 : 세대(실)당 1.5대 -전용면적 85㎡초과 : 1.5대에 85㎡를 초과하는 85㎡당 1대를 더한 대수')
        self.assertAlmostEqual(parking.per_unit_spaces(r, 120, True), 1.5 + 35 / 85)
        # 이천: 아파트만 세대당 1.4대 이상 (오피스텔은 면적대 기준)
        r = parking._residential('전용면적85㎡ 이하 : 세대당 또는호실별1대 나. 전용면적85㎡ 초과 : 70㎡당 1대 다. 가목 및 나목 중「건축법」에 따른 아파트의 경우 세대당 1.4대 이상으로 한다.')
        self.assertEqual((parking.per_unit_spaces(r, 59, True), parking.per_unit_spaces(r, 59, False)), (1.4, 1.0))
        # 면적대 표로 읽지 못하는 형식은 자동 적용하지 않음
        self.assertEqual(parking._residential('세대당 1대 이상 다만 세대당 1.3대'), {'complex': True})
        # 주택건설기준의 1.5배 (홍천)
        self.assertEqual(parking._residential('공동주택은 「주택건설기준 등에 관한 규정」제27조제1항에 따라 산정된 주차대수의 1.5배로 하되, 세대당 1대에 미달되는 경우에는 세대당 1대이상')['multiplier'], 1.5)


class RenewalRowTests(unittest.TestCase):
    def test_renewal_plan_row_uses_changed(self):
        cells = ['8. 건축시설계획', '구분', '건폐율', '(%)', '용적률(%)', '높이(m)', '정비계획', '법적상한',
                 '기정', '획지1', '공동주택 및', '부대복리시설', '50%', '이하', '270%', '이하', '299.7%', '이하', '132m이하', '(45층이하)', '-',
                 '변경', '획지1', '공동주택 및', '부대복리시설', '50%', '이하', '270%', '이하', '299.7%', '이하', '132.5m이하', '(45층이하)', '-']
        (r,) = plandoc.parse_blocks('\n'.join(cells))
        self.assertEqual((r['bcr'], r['base_far'], r['legal_max_far'], r['height_m'], r['floors']), (50.0, 270.0, 299.7, 132.5, 45))
