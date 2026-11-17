from app.regulations import review

def test_gwangju_ordinance_basic():
    r=review({'jurisdiction':'경기도 광주시','zone':'제2종일반주거지역','site_area_sqm':10000})
    assert r['ordinance_limits']=={'far':250,'bcr':60}
    assert r['illustrative_max_far_floor_sqm']=='25000'
    assert r['status']=='검토필요'

def test_unknown_region_does_not_invent():
    r=review({'jurisdiction':'부산광역시','zone':'제2종일반주거지역','site_area_sqm':10000})
    assert r['ordinance_limits']=={}
