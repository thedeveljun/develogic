"""Business-type rules: intentionally no invented zoning/FAR rules."""
MODULES={
 'general_housing':{'label':'일반 공동주택 시행','required_reviews':['주택법','국토계획법','지자체 도시계획조례','지구단위계획','주차장법']},
 'station_area_renewal':{'label':'역세권 정비사업','required_reviews':['도시정비법','해당 지자체 정비조례','정비계획 고시','공공기여 및 임대주택 기준','매입약정']}
}
def review_requirements(project_type):return MODULES[project_type]
