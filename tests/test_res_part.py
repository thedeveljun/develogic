"""조례 용적률 조문 ②항 이하의 주거복합건물 주거·오피스텔 부분 용적률 (과천 도시계획 조례 제58조③)."""
import unittest
from app.lawdata import parse_items, parse_res_part_paragraph

BODY = '''1. 제1종전용주거지역 : 100퍼센트 이하
2. 제2종전용주거지역 : 150퍼센트 이하
3. 제1종일반주거지역 : 200퍼센트 이하
4. 제2종일반주거지역 : 250퍼센트 이하
5. 제3종일반주거지역 : 300퍼센트 이하
6. 준주거지역 : 500퍼센트 이하
7. 중심상업지역 : 1,500퍼센트 이하
8. 일반상업지역 : 1,300퍼센트 이하
9. 근린상업지역 : 900퍼센트 이하
10. 유통상업지역 : 1,100퍼센트 이하
15. 준공업지역 : 400퍼센트 이하'''
PARA = ('③ 제1항제7호부터 제9호까지의 상업지역 및 제1항제15호의 준공업지역안에서의 주거복합건물(주거용 및 오피스텔과 그 외의 용도가 '
        '복합된 건축물)은 주거용 및 오피스텔로 사용되는 부분의 용적률(부대시설의 용적률을 포함한다)을 400퍼센트 이하로 한다.')


class ResPartTest(unittest.TestCase):
    def test_gwacheon_58_3(self):
        limits, nos = {}, {}
        parse_items(BODY, 'far', limits, nos)
        parse_res_part_paragraph('제58조', [PARA], limits, nos)
        for z in ('중심상업지역', '일반상업지역', '근린상업지역', '준공업지역'):
            self.assertEqual(limits[z]['far_res_part'], 400, z)
            self.assertEqual(limits[z]['mixed_src'], '제58조③')
        for z in ('유통상업지역', '준주거지역'):
            self.assertNotIn('far_res_part', limits[z], z)
        self.assertNotIn('_far_no', limits['일반상업지역'])


if __name__ == '__main__':
    unittest.main()
