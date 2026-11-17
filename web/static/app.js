/* 디벨로직 · 개발사업 통합 분석 — 화면 스크립트 */
'use strict';
const $ = id => document.getElementById(id);
const localDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;   // 한국 시간 기준 (toISOString은 UTC라 오전 9시 전엔 전날)
const today = localDate(new Date());

/* ───────────── 공통 유틸 ───────────── */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n, d = 0) => (n === null || n === undefined || n === '' || !isFinite(Number(n))) ? '–' : Number(n).toLocaleString('ko-KR', { maximumFractionDigits: d });
const pct = (n, d = 1) => (n === null || n === undefined || !isFinite(n)) ? '–' : Number(n).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }) + '%';
const PY = sqm => Number(sqm) * 121 / 400;
// 금액 표기: 소수점 없이 '13억 9,412만' (만원 단위 반올림)
function krw(n) {
  n = Number(n); if (!isFinite(n)) return '–';
  const s = n < 0 ? '-' : '', man = Math.round(Math.abs(n) / 1e4);
  if (man >= 1e4) { const eok = Math.floor(man / 1e4), rest = man % 1e4; return s + eok.toLocaleString('ko-KR') + '억' + (rest ? ' ' + rest.toLocaleString('ko-KR') + '만' : ''); }
  if (man >= 1) return s + man.toLocaleString('ko-KR') + '만';
  return s + Math.round(Math.abs(n)).toLocaleString('ko-KR');
}
const krwW = n => krw(n) + (Math.abs(Number(n)) >= 1e4 ? ' 원' : '원');
function inUnit(n, u) {
  n = Number(n); if (!isFinite(n)) return '–';
  if (u === 1) return n.toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  return Math.round(n / u).toLocaleString('ko-KR');
}
const parseNum = v => { const s = String(v ?? '').replace(/,/g, '').trim(); return s === '' || s === '-' ? null : Number(s); };
const num = id => parseNum($(id).value);
function notice(msg, err) { const t = $('notice'); t.textContent = msg; t.className = 'show' + (err ? ' err' : ''); clearTimeout(t._h); t._h = setTimeout(() => t.className = '', 3200); }
async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401 && !path.startsWith('/api/v4/auth/')) { location.href = '/login?next=' + encodeURIComponent(location.pathname + location.hash); throw new Error('로그인이 필요합니다'); }
  let j; try { j = await r.json(); } catch { j = { detail: r.statusText }; }
  if (!r.ok) throw new Error(errText(j));
  return j;
}
function errText(j) {
  const d = j && j.detail;
  if (Array.isArray(d)) return d.map(e => (e.loc || []).filter(x => x !== 'body').join(' › ') + ': ' + e.msg).join('\n');
  return typeof d === 'string' ? d : JSON.stringify(j);
}
const errBox = e => `<div class="alert bad"><b>요청을 처리하지 못했습니다.</b><div style="white-space:pre-wrap">${esc(e.message)}</div></div>`;
async function busy(btn, fn) { const t = btn.textContent; btn.disabled = true; btn.textContent = '처리 중…'; try { await fn(); } finally { btn.disabled = false; btn.textContent = t; } }
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 저장 불가 환경 무시 */ } },
};
function download(name, text, type) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* 금액 입력: 천 단위 구분 표시 + 억/평 힌트 */
function fmtMoneyInput(el) {
  const raw = el.value.replace(/[^\d.\-]/g, '');
  if (raw === '' || raw === '-') { el.value = raw; return; }
  const [i, d] = raw.split('.');
  el.value = (i.startsWith('-') ? '-' : '') + Number(i.replace('-', '') || 0).toLocaleString('ko-KR') + (d !== undefined ? '.' + d : '');
}
const moneyVal = v => fmt(v, 2);
function refreshHints() {
  document.querySelectorAll('[data-krw]').forEach(h => { const v = num(h.dataset.krw); h.textContent = v ? '≈ ' + krwW(v) : ''; });
  document.querySelectorAll('[data-py]').forEach(h => { const v = num(h.dataset.py); h.textContent = v ? '≈ ' + fmt(PY(v), 1) + ' 평' : ''; });
}
document.addEventListener('input', e => {
  const t = e.target;
  if (t.classList.contains('money-in')) {
    const fromEnd = t.value.length - t.selectionEnd; fmtMoneyInput(t);
    const p = Math.max(0, t.value.length - fromEnd); try { t.setSelectionRange(p, p); } catch { }
  }
  refreshHints();
});

/* ───────────── 라우팅 ───────────── */
const VIEWS = {
  easy: ['간편 분석', '주소 → 용도 → 핵심 숫자 → 판정, 4단계로 사업성 확인 (처음 사용자용)'],
  overview: ['사업지 현황', '사업지별 사업수지 · 타당성 판정 비교 — 행을 누르면 해당 사업지로 전환'],
  sites: ['자료 · 필지 분석', '토지이용계획확인서·필지목록을 읽어 필지·용도지역·규제 정리'],
  proforma: ['사업수지 분석', '분양·사업비·금융비용·세금 반영 · 입력하면 바로 계산'],
  cashflow: ['Cash Flow (수동 입력)', '날짜별 수입·지출·대출 실행/상환을 직접 입력해 월별 현금흐름 계산 (사업수지와 별개 도구)'],
  feasibility: ['사업지 법규 검토', '등록된 조례 근거 기반 용적률·건폐율 적용 및 검토 게이트'],
  quick: ['간이 조례 검토', '내장 조례의 일반 상한 빠른 확인'],
  rules: ['조례 근거 등록', '검토자용 — 공식 근거와 함께 조례 수치 등록'],
  ci: ['설정 · CI 가이드', 'API 설정 (필지 정보 자동 조회) · 디벨로직 브랜드 · 색상 · 서체 · 컴포넌트 규칙'],
};
const PATH_DEFAULT = { '/dashboard': 'cashflow', '/nationwide': 'feasibility' };
function show(v) {
  if (!VIEWS[v]) v = 'overview';
  document.querySelectorAll('.view').forEach(s => s.classList.toggle('active', s.id === 'view-' + v));
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  document.querySelectorAll('[data-tools]').forEach(t => t.classList.toggle('hidden', t.dataset.tools !== v));
  $('heading').textContent = VIEWS[v][0]; $('subheading').textContent = VIEWS[v][1];
  document.title = VIEWS[v][0] + ' · 디벨로직';
  if (v === 'overview') renderOverview();
  if (v === 'sites') openSite(curSite);
  if (v === 'ci') loadApiSettings();
  if (v === 'easy') easyEnter();
  if (VIEWS[v] && (v === 'sites' || v === 'proforma'))   // 사업지는 제목 옆 칩으로 구분해 한눈에 보이게
    $('heading').innerHTML = esc(VIEWS[v][0]) + (curSite ? ` <span class="site-chip" title="현재 사업지">📍 ${esc(curSite)}</span>`
      : ' <span class="site-chip none" title="왼쪽 위 「현재 사업지」에서 선택">⚠ 사업지 미선택</span>');
  window.scrollTo(0, 0);
}
function go(v) { if (location.hash !== '#' + v) location.hash = v; else show(v); }
window.addEventListener('hashchange', () => show(location.hash.slice(1)));
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => go(b.dataset.view)));
document.addEventListener('click', e => { const g = e.target.closest('[data-go]'); if (g) go(g.dataset.go); });

/* 서버 상태 · 광역지자체 */
/* 광역지자체 → 시·군·구 (2026.7.1 인천 행정체제 개편·2023 군위군 대구 편입 반영) */
const SIGUNGU = {
  서울특별시: ['종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구', '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구', '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구'],
  부산광역시: ['중구', '서구', '동구', '영도구', '부산진구', '동래구', '남구', '북구', '해운대구', '사하구', '금정구', '강서구', '연제구', '수영구', '사상구', '기장군'],
  대구광역시: ['중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군', '군위군'],
  인천광역시: ['제물포구', '영종구', '미추홀구', '연수구', '남동구', '부평구', '계양구', '서구', '검단구', '강화군', '옹진군'],
  광주광역시: ['동구', '서구', '남구', '북구', '광산구'],
  대전광역시: ['동구', '중구', '서구', '유성구', '대덕구'],
  울산광역시: ['중구', '남구', '동구', '북구', '울주군'],
  세종특별자치시: [],
  경기도: ['수원시', '성남시', '의정부시', '안양시', '부천시', '광명시', '평택시', '동두천시', '안산시', '고양시', '과천시', '구리시', '남양주시', '오산시', '시흥시', '군포시', '의왕시', '하남시', '용인시', '파주시', '이천시', '안성시', '김포시', '화성시', '광주시', '양주시', '포천시', '여주시', '연천군', '가평군', '양평군'],
  강원특별자치도: ['춘천시', '원주시', '강릉시', '동해시', '태백시', '속초시', '삼척시', '홍천군', '횡성군', '영월군', '평창군', '정선군', '철원군', '화천군', '양구군', '인제군', '고성군', '양양군'],
  충청북도: ['청주시', '충주시', '제천시', '보은군', '옥천군', '영동군', '증평군', '진천군', '괴산군', '음성군', '단양군'],
  충청남도: ['천안시', '공주시', '보령시', '아산시', '서산시', '논산시', '계룡시', '당진시', '금산군', '부여군', '서천군', '청양군', '홍성군', '예산군', '태안군'],
  전북특별자치도: ['전주시', '군산시', '익산시', '정읍시', '남원시', '김제시', '완주군', '진안군', '무주군', '장수군', '임실군', '순창군', '고창군', '부안군'],
  전라남도: ['목포시', '여수시', '순천시', '나주시', '광양시', '담양군', '곡성군', '구례군', '고흥군', '보성군', '화순군', '장흥군', '강진군', '해남군', '영암군', '무안군', '함평군', '영광군', '장성군', '완도군', '진도군', '신안군'],
  경상북도: ['포항시', '경주시', '김천시', '안동시', '구미시', '영주시', '영천시', '상주시', '문경시', '경산시', '의성군', '청송군', '영양군', '영덕군', '청도군', '고령군', '성주군', '칠곡군', '예천군', '봉화군', '울진군', '울릉군'],
  경상남도: ['창원시', '진주시', '통영시', '사천시', '김해시', '밀양시', '거제시', '양산시', '의령군', '함안군', '창녕군', '고성군', '남해군', '하동군', '산청군', '함양군', '거창군', '합천군'],
  제주특별자치도: ['제주시', '서귀포시'],
};
/* 광역지자체 선택에 맞춰 시·군·구 목록을 채운다. 목록에 없는 기존 값은 보존 */
function fillMuni(provId, muniId, value) {
  const prov = $(provId)?.value || '', list = SIGUNGU[prov] || [], sel = $(muniId);
  if (!sel) return;
  const opts = [`<option value="">${prov ? (list.length ? '시·군·구 선택' : '(광역 단위)') : '광역지자체를 먼저 선택'}</option>`, ...list.map(m => `<option>${esc(m)}</option>`)];
  if (value && !list.includes(value)) opts.push(`<option>${esc(value)}</option>`);
  sel.innerHTML = opts.join('');
  sel.value = value || '';
}
document.addEventListener('change', e => {
  if (e.target.id === 'f_province') fillMuni('f_province', 'f_municipality', '');
  if (e.target.id === 'r_province') fillMuni('r_province', 'r_municipality', '');
});
let PROVINCES = ['서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시', '대전광역시', '울산광역시', '세종특별자치시', '경기도', '강원특별자치도', '충청북도', '충청남도', '전북특별자치도', '전라남도', '경상북도', '경상남도', '제주특별자치도'];
fetch('/api/v2/provinces').then(r => r.json()).then(j => {
  PROVINCES = j.provinces;
  const opts = j.provinces.map(p => `<option>${esc(p)}</option>`).join('');
  $('f_province').innerHTML = opts; $('r_province').innerHTML = opts;
  $('f_province').value = $('r_province').value = '경기도';
  fillMuni('f_province', 'f_municipality', ''); fillMuni('r_province', 'r_municipality', '');
  $('srvText').textContent = '로컬 서버 연결됨';
  loadMe();
}).catch(() => { $('srvDot').classList.add('off'); $('srvText').textContent = '서버 연결 실패'; });
$('f_as_of').value = today; $('r_reviewed_on').value = today;

/* ═════════════════════ 사업수지 분석 ═════════════════════ */
const CATS = [
  ['land', '토지비', '토지매입비, 취득세, 중개·법무, 명도·이주비 등'],
  ['construction', '공사비', '지상·지하 직접공사비, 철거·인입·부대공사'],
  ['indirect', '설계·감리·용역비', '설계, 감리, 인허가·각종 영향평가, CM'],
  ['charges', '부담금·인입비', '학교용지·광역교통·상하수도 원인자부담금, 전기·가스 인입'],
  ['sales', '분양·판매비', '분양대행, 광고·홍보, 모델하우스, 분양보증'],
  ['taxes', '제세공과금', '보존등기비(건물 취득세), 재산세·종부세'],
  ['admin', '일반관리비', '시행사 운영비, 신탁·PM 수수료'],
  ['contingency', '예비비', '사업비 합계 대비 비율 권장'],
];
const CAT_COLORS = { land: '#111a2e', construction: '#1e88d6', indirect: '#7cc0f0', charges: '#6741d9', sales: '#2f9e44', taxes: '#e8590c', admin: '#94a3b8', contingency: '#c9d4db', finance: '#c2255c' };
const BASES = {
  fixed: ['정액', '원'], per_land_py: ['대지 평당', '원/평'], per_above_py: ['지상연면적 평당', '원/평'], per_below_py: ['지하연면적 평당', '원/평'],
  per_gfa_py: ['전체연면적 평당', '원/평'], per_supply_py: ['공급면적 평당', '원/평'], per_unit: ['주거 세대당', '원/세대'], monthly: ['월 금액 × 사업기간', '원/월'],
  pct_land: ['토지비 대비', '%'], pct_construction: ['공사비(정액·평당 항목) 대비', '%'], pct_direct: ['직접공사비(연면적 평당) 대비', '%'],
  pct_construction_total: ['공사비 합계 대비', '%'], pct_sales: ['분양대금 대비', '%'], pct_general_sales: ['일반분양대금 대비', '%'],
  pct_apt_sales: ['공동주택 분양대금 대비', '%'], pct_total: ['사업비 합계 대비', '%'],
  // 법정 자동 산정 (app/levies.py) — 입력값이 필요 없는 항목은 '자동'
  auto_school: ['⚖ 법정: 학교용지부담금', '자동'], auto_metro: ['⚖ 법정: 광역교통시설부담금', '자동'],
  auto_sewer: ['⚖ 법정: 하수도 원인자부담금', '원/㎥'], auto_water: ['⚖ 법정: 상수도 원인자부담금', '원/세대'],
  auto_preservation: ['⚖ 법정: 보존등기 취득세', '자동'], auto_land_tax: ['⚖ 법정: 토지 취득세', '자동'], auto_holding: ['⚖ 법정: 토지 재산세', '자동'],
};
const AUTO_NOVALUE = new Set(['auto_school', 'auto_metro', 'auto_preservation', 'auto_land_tax', 'auto_holding']);
const KINDS = { apartment: '공동주택', officetel: '오피스텔', retail: '상가·근생', office: '업무시설', knowledge: '지식산업센터', datacenter: '데이터센터', other: '기타' };
const BUYERS = { general: '일반분양', member: '조합원', rental: '임대·매각' };
const TIMINGS = {
  auto: '자동 (분류 기본값)', land: '토지 계약금·잔금', contract: '사업 개시월', land_balance: '토지 잔금월', pre_construction: '착공 전 균등',
  construction_start: '착공월', construction_curve: '공정률 연동', construction_even: '공사기간 균등', sales_start: '분양 개시월',
  sales_linked: '분양대금 수납 연동', completion: '준공월', move_in: '입주(잔금)월', even: '전 기간 균등', property_tax: '재산세 (매년 7·9월)',
};
const isPct = b => b.startsWith('pct_');
// 분류별로 의미 있는 산정 기준만 보여 준다 (첫 번째가 새 항목 기본값)
const CAT_BASES = {
  land: ['per_land_py', 'fixed', 'pct_land', 'auto_land_tax'],
  construction: ['per_gfa_py', 'per_above_py', 'per_below_py', 'per_supply_py', 'per_unit', 'fixed', 'pct_direct', 'pct_construction'],
  indirect: ['per_gfa_py', 'per_above_py', 'per_supply_py', 'per_unit', 'fixed', 'pct_direct', 'pct_construction', 'pct_construction_total'],
  charges: ['fixed', 'auto_school', 'auto_metro', 'auto_sewer', 'auto_water', 'per_unit', 'per_land_py', 'per_gfa_py', 'per_supply_py', 'pct_apt_sales', 'pct_sales', 'pct_construction'],
  sales: ['fixed', 'per_unit', 'monthly', 'pct_sales', 'pct_general_sales', 'pct_apt_sales'],
  taxes: ['fixed', 'auto_preservation', 'auto_holding', 'auto_land_tax', 'per_land_py', 'pct_land', 'pct_construction', 'pct_construction_total', 'pct_sales'],
  admin: ['monthly', 'fixed', 'per_unit', 'pct_sales', 'pct_general_sales'],
  contingency: ['pct_total', 'pct_construction', 'pct_direct', 'pct_construction_total', 'fixed'],
};
const basesFor = (cat, cur) => { const l = CAT_BASES[cat] || Object.keys(BASES); return l.includes(cur) ? l : [...l, cur]; };

let pf = null, lastPf = null, pfTimer = null, pfSeq = 0, pfUnit = 1e6, sensMode = 'margin';
const collapsed = new Set();

// 입력칸 id 접두어 → pf 안의 객체
const PREFIX = [['rt_', p => p.rental], ['hg_', p => p.hug], ['sp_', p => p.site.plan], ['sc_', p => p.schedule || {}], ['pa_', p => p.prior_assets], ['cr_', p => p.criteria], ['s_', p => p.site],
  ['p_', p => p], ['m_', p => p.midpay], ['t_', p => p.corporate_tax]];
const target = (obj, id) => { const e = PREFIX.find(([k]) => id.startsWith(k)); return e ? [e[1](obj), id.slice(e[0].length)] : [null, null]; };
function setPath(obj, id, val) {
  if (id === 'sc_enabled') { if (val && !obj.schedule) obj.schedule = { ...DEFAULT_SCHEDULE }; if (obj.schedule) obj.schedule.enabled = val; fillSchedule(); return; }
  const [o, k] = target(obj, id); if (o) o[k] = val;
}
function getPath(obj, id) { const [o, k] = target(obj, id); return o ? o[k] : undefined; }
const DEFAULT_SCHEDULE = {
  enabled: true, start_month: today.slice(0, 7), land_contract_pct: 10, land_balance_month: 3, construction_start_month: 8,
  construction_months: 30, curve: 's_curve', custom_curve: [], payment_lag_months: 1, retention_pct: 0, sales_start_month: 9,
  initial_sales_share_pct: 60, sales_period_months: 12, deposit_pct: 10, midpay_pct: 60, midpay_installments: 6, move_in_lag_months: 1,
  sweep_pct: 0, minimum_cash: 0, discount_rate_pct: 8, vat_settlement: true, corporate_tax_by_progress: true, sme: false,
};
function fillFields() {
  document.querySelectorAll('[data-pf]').forEach(el => {
    const v = el.id === 'sc_enabled' ? !!(pf.schedule && pf.schedule.enabled) : getPath(pf, el.id);
    if (el.type === 'checkbox') el.checked = !!v;
    else if (el.classList.contains('money-in')) el.value = v == null ? '' : moneyVal(v);
    else el.value = v ?? '';
  });
}
function fillSchedule() {
  const on = !!(pf.schedule && pf.schedule.enabled);
  $('scFields').style.opacity = on ? 1 : .45; $('scFields').style.pointerEvents = on ? '' : 'none';
  if (pf.schedule) { fillFields(); $('scCustom').value = (pf.schedule.custom_curve || []).join(','); }
  fillOffsets();
}
function pfLoad(payload, silent) {
  planManual = false;
  pf = JSON.parse(JSON.stringify(payload));
  pf.midpay = pf.midpay || { enabled: false };
  if (!pf.midpay.mode) pf.midpay.mode = pf.midpay.enabled === false ? 'with_interest' : 'interest_free';
  pf.midpay.enabled = true;   // 방식(mode)으로 구분 pf.corporate_tax = pf.corporate_tax || { enabled: false, brackets: [] };
  pf.units = pf.units || []; pf.costs = pf.costs || []; pf.loans = pf.loans || [];
  pf.costs.forEach(c => { c.timing = 'auto'; });
  pf.project_mode = pf.project_mode || 'developer';
  pf.site = { province: null, municipality: null, zones: [], incentive_far_pct: 0, building_area_sqm: null, plan_parking: null, parking_area_per_space: 33, flags: [], auto_far: true, parcels: [], ...(pf.site || {}) };
  pf.site.parcels = pf.site.parcels || [];
  pf.site.plan = { kind: 'none', title: '', notice_no: '', notice_date: '', url: '', base_far: null, allowed_far: null, max_far: null, plan_bcr: null,
    public_land_sqm: 0, use_max: false, housing_ratio_pct: 0, block: '', max_floors: null, height_limit_m: null, allowed_uses: '', res_far: null, ...(pf.site.plan || {}) };
  pf.prior_assets = { land_py: 0, appraisal_per_py: 0, appraisal_total: null, members: 0, cases: [], ...(pf.prior_assets || {}) };
  pf.criteria = pf.criteria || {};
  pf.rental = { hold_years: 10, general_rent_ratio_pct: 95, special_share_pct: 20, special_rent_ratio_pct: 70, auto_relief: true, auto_fund: true,
    occupancy_pct: 97, rent_growth_pct: 2, opex_pct: 12, property_tax_annual: 0, property_tax_relief_pct: 0, guarantee_rate_pct: 0.2, fund_loan: 0,
    fund_rate_pct: 2, mortgage_rate_pct: 4.5, construction_months: 30, construction_rate_pct: 6.5, construction_draw_pct: 55, exit_mode: 'price',
    exit_cap_pct: 4.5, exit_price_per_py: 0, sale_cost_pct: 1.5, building_ratio_pct: 60, depreciation_years: 40, discount_rate_pct: 7,
    yield_min_pct: 4.5, dscr_min: 1.2, irr_min_pct: 7, ...(pf.rental || {}) };
  pf.hug = { enabled: false, product: 'pf', business: 'sale', temp_relief: true, top_contractor: false, grade: 3, loan_name: '', capital_region: true,
    land_trust: false, sale_guarantee: true, sale_build_rate_pct: 0.25, sale_discount_pct: 0, confirm_approval: false, confirm_land_trust: false,
    confirm_contractor: false, confirm_purchase_agreement: false, ...(pf.hug || {}) };
  $('hg_loan_name').innerHTML = '<option value="">자동 (PF 대출)</option>' + pf.loans.map(l => `<option>${esc(l.name)}</option>`).join('');
  if ($('s_province').options.length < 2) $('s_province').innerHTML = '<option value="">선택</option>' + PROVINCES.map(p => `<option>${esc(p)}</option>`).join('');
  fillFields(); fillMuni('s_province', 's_municipality', pf.site.municipality || ''); fillSchedule();
  renderUnits(); renderCostCards(); renderLoans(); renderTax(); renderZones(); renderCases(); renderParcels(); refreshHints(); updateFar(); updateMode(); updatePlanUI(); updateMidUI();
  pfRecalc(true);
  if (!silent) notice('‘' + (pf.project_name || '시나리오') + '’을(를) 불러왔습니다.');
}

/* — 2. 분양 계획 표 — */
function renderUnits() {
  const tb = $('unitTable').tBodies[0];
  tb.innerHTML = pf.units.map((u, i) => `<tr>
    <td><input data-u="${i}" data-k="name" value="${esc(u.name)}"></td>
    <td><select data-u="${i}" data-k="buyer">${Object.entries(BUYERS).map(([k, n]) => `<option value="${k}" ${(u.buyer || 'general') === k ? 'selected' : ''}>${n}</option>`).join('')}</select></td>
    <td><select data-u="${i}" data-k="kind">${Object.entries(KINDS).map(([k, n]) => `<option value="${k}" ${u.kind === k ? 'selected' : ''}>${n}</option>`).join('')}</select></td>
    <td><input class="money-in" style="width:80px" data-u="${i}" data-k="exclusive_sqm" value="${moneyVal(u.exclusive_sqm)}"></td>
    <td><input class="money-in" style="width:80px" data-u="${i}" data-k="supply_sqm" value="${moneyVal(u.supply_sqm)}"></td>
    <td><input class="money-in" style="width:76px" data-u="${i}" data-k="count" value="${fmt(u.count)}"></td>
    <td><input class="money-in" data-u="${i}" data-k="price_per_py" value="${fmt(u.price_per_py)}"></td>
    <td class="rent-col"><input class="money-in" data-u="${i}" data-k="market_deposit" value="${fmt(u.market_deposit || 0)}"></td>
    <td class="rent-col"><input class="money-in" data-u="${i}" data-k="market_rent" value="${fmt(u.market_rent || 0)}"></td>
    <td class="r" data-uc="unit"></td><td class="r money" data-uc="total"></td><td class="c" data-uc="tax"></td>
    <td><button class="del" data-del-u="${i}" title="삭제">✕</button></td></tr>`).join('')
    || `<tr><td colspan="11" class="c muted">타입을 추가하세요.</td></tr>`;
  updateUnitCalc();
}
function updateUnitCalc() {
  const adj = 1 + (Number(pf.price_adjust_pct) || 0) / 100;
  let cnt = 0, supply = 0, total = 0;
  [...$('unitTable').tBodies[0].rows].forEach((tr, i) => {
    const u = pf.units[i]; if (!u) return;
    const unit = PY(u.supply_sqm) * u.price_per_py * adj, t = unit * u.count;
    const taxable = u.kind !== 'apartment' || Number(u.exclusive_sqm) > 85;
    tr.querySelector('[data-uc=unit]').textContent = krw(unit);
    tr.querySelector('[data-uc=total]').textContent = krw(t);
    tr.querySelector('[data-uc=tax]').innerHTML = taxable ? '<span class="chip warn">과세</span>' : '<span class="chip ok">면세</span>';
    cnt += Number(u.count) || 0; supply += PY(u.supply_sqm) * u.count; total += t;
  });
  $('unitTable').tFoot.innerHTML = pf.units.length ? `<tr class="total"><td colspan="5">합계 (공급 ${fmt(supply, 1)}평)</td><td class="r">${fmt(cnt)}</td><td class="r">평균 ${fmt(supply ? total / supply : 0)}</td><td></td><td class="r">${krw(total)}</td><td colspan="2"></td></tr>` : '';
}
$('addUnit').onclick = () => {
  pf.units.push({ name: '', kind: 'apartment', exclusive_sqm: 84.9, supply_sqm: 112, count: 0, price_per_py: pf.units[0]?.price_per_py || 0 });
  renderUnits(); pfRecalc();
  const inp = document.querySelector(`#unitTable [data-u="${pf.units.length - 1}"][data-k="name"]`);   // 새 칸에 바로 입력
  if (inp) { inp.focus(); inp.scrollIntoView({ block: 'nearest' }); }
};

/* — 3. 사업비 — */
function renderCostCards() {
  $('costCards').innerHTML = CATS.map(([key, name, desc]) => {
    const rows = pf.costs.map((c, i) => [c, i]).filter(([c]) => c.category === key);
    return `<div class="card"><div class="card-head"><h2>${name} <span class="sub">${desc}</span></h2><div class="toolbar"><b class="money" data-cat-sum="${key}">–</b><button class="addrow" data-add-c="${key}">+ 항목</button></div></div>
      <div class="tablewrap"><table class="edit"><thead><tr><th style="width:150px;min-width:150px">항목</th><th style="width:195px;min-width:195px">산정 기준</th><th class="r" style="width:185px;min-width:185px">입력값</th><th class="r" style="width:100px;min-width:100px">산출 금액</th><th style="min-width:110px">비고</th><th></th></tr></thead><tbody>
      ${rows.map(([c, i]) => `<tr>
        <td><input data-c="${i}" data-k="name" value="${esc(c.name)}" title="${esc(c.name)}"></td>
        <td><select data-c="${i}" data-k="basis">${basesFor(key, c.basis).map(b => `<option value="${b}" ${c.basis === b ? 'selected' : ''}>${BASES[b][0]}</option>`).join('')}</select></td>
        <td>${AUTO_NOVALUE.has(c.basis) ? `<div class="unit"><input disabled value="법령·조례 기준" style="text-align:right;color:var(--muted)" title="입력값 없이 법령·조례로 자동 계산"><span>자동</span></div>`
          : `<div class="unit"><input class="${isPct(c.basis) ? '' : 'money-in'}" style="text-align:right" ${isPct(c.basis) ? 'type="number" step="any"' : 'inputmode="numeric"'} data-c="${i}" data-k="value" value="${isPct(c.basis) ? c.value : fmt(c.value, 2)}" ${c.basis === 'auto_sewer' ? 'placeholder="지자체 공고 단가"' : c.basis === 'auto_water' ? 'placeholder="조례 내장 지역은 비워도 됨"' : ''}><span>${BASES[c.basis][1]}</span></div>`}</td>
        <td class="r money" data-amt="${i}">–</td>
        <td><input data-c="${i}" data-k="note" value="${esc(c.note || '')}" placeholder="메모"></td>
        <td><button class="del" data-del-c="${i}" title="삭제">✕</button></td></tr>${c.basis.startsWith('auto_') ? `<tr class="auto-detail"><td colspan="6"><span data-det="${i}" class="muted">계산 중…</span></td></tr>` : ''}`).join('') || `<tr><td colspan="6" class="c muted">항목이 없습니다.</td></tr>`}
      </tbody></table></div></div>`;
  }).join('');
  updateCostAmounts();
}
function updateCostAmounts() {
  if (!lastPf || !pf) return;
  const byCat = Object.fromEntries(lastPf.costs.map(c => [c.key, c]));
  const seen = {};
  pf.costs.forEach((c, i) => {
    const k = c.category; seen[k] = (seen[k] || 0);
    const it = byCat[k]?.items?.filter(x => x.basis !== 'derived')[seen[k]++];
    const td = document.querySelector(`[data-amt="${i}"]`); if (td) td.textContent = it ? krw(it.amount) : '–';
    const det = document.querySelector(`[data-det="${i}"]`); if (det) det.textContent = it?.detail ? '⚖ ' + it.detail : '';
  });
  document.querySelectorAll('[data-cat-sum]').forEach(el => { const c = byCat[el.dataset.catSum]; el.textContent = c ? '소계 ' + krwW(c.amount) : '소계 0원'; });
}

/* — 4. 금융·세금 — */
function renderLoans() {
  $('loanTable').tBodies[0].innerHTML = pf.loans.map((l, i) => `<tr>
    <td><input data-l="${i}" data-k="name" value="${esc(l.name)}"></td>
    <td><input class="money-in" data-l="${i}" data-k="amount" value="${fmt(l.amount)}"></td>
    <td><input type="number" step="any" style="text-align:right" data-l="${i}" data-k="annual_rate_pct" value="${l.annual_rate_pct}"></td>
    <td><input type="number" step="any" style="text-align:right" data-l="${i}" data-k="months" value="${l.months}"></td>
    <td><input type="number" step="any" style="text-align:right" data-l="${i}" data-k="utilization_pct" value="${l.utilization_pct ?? 100}"></td>
    <td><input type="number" step="any" style="text-align:right" data-l="${i}" data-k="fee_pct" value="${l.fee_pct ?? 0}"></td>
    <td><input type="number" min="0" style="text-align:right" data-l="${i}" data-k="start_month" value="${l.start_month ?? 0}"></td>
    <td><input type="number" min="0" style="text-align:right" data-l="${i}" data-k="maturity_month" value="${l.maturity_month ?? ''}" placeholder="입주월"></td>
    <td class="r money" data-lc="int"></td><td class="r" data-lc="fee"></td>
    <td><button class="del" data-del-l="${i}" title="삭제">✕</button></td></tr>`).join('')
    || `<tr><td colspan="11" class="c muted">대출이 없습니다.</td></tr>`;
  updateLoanCalc();
}
function updateLoanCalc() {
  const cfl = lastPf?.cashflow?.loans;
  [...$('loanTable').tBodies[0].rows].forEach((tr, i) => {
    const l = pf.loans[i]; if (!l) return;
    if (cfl && cfl[i]) { tr.querySelector('[data-lc=int]').textContent = krw(cfl[i].interest); tr.querySelector('[data-lc=fee]').textContent = krw(cfl[i].fees); return; }
    tr.querySelector('[data-lc=int]').textContent = krw(l.amount * l.annual_rate_pct / 100 * l.months / 12 * (l.utilization_pct ?? 100) / 100);
    tr.querySelector('[data-lc=fee]').textContent = krw(l.amount * (l.fee_pct || 0) / 100);
  });
}
$('addLoan').onclick = () => { pf.loans.push({ name: '대출 ' + (pf.loans.length + 1), amount: 0, annual_rate_pct: 6, months: 24, utilization_pct: 100, fee_pct: 0 }); renderLoans(); pfRecalc(); };
function renderTax() {
  const b = pf.corporate_tax.brackets || [];
  $('taxTable').tBodies[0].innerHTML = b.map((x, i) => `<tr>
    <td>${x.up_to == null ? '<span class="muted">초과 전 구간</span>' : `<input class="money-in" data-t="${i}" data-k="up_to" value="${fmt(x.up_to)}">`}</td>
    <td><input type="number" step="any" style="text-align:right" data-t="${i}" data-k="rate_pct" value="${x.rate_pct}"></td></tr>`).join('');
}

/* — 입력 반영 (이벤트 위임) — */
$('view-proforma').addEventListener('input', e => {
  const t = e.target, k = t.dataset.k; if (!pf) return;
  const val = t.classList.contains('money-in') ? parseNum(t.value) : t.type === 'number' ? (t.value === '' ? null : Number(t.value)) : t.type === 'checkbox' ? t.checked : t.value;
  if (t.hasAttribute('data-pf')) {
    setPath(pf, t.id, t.type === 'month' ? t.value : val);
    if (t.id === 'p_price_adjust_pct') updateUnitCalc();
    if (t.id === 'p_above_gfa_sqm' && pf.site.auto_far) { pf.site.auto_far = false; $('s_auto_far').checked = false; notice('지상 연면적을 직접 입력해 조례 자동 대입을 껐습니다. (법규 연동 카드에서 다시 켤 수 있음)'); }
    if (['s_auto_far', 's_incentive_far_pct'].includes(t.id)) autoApplyFar();
    if (t.id === 'p_project_mode') updateMode();
    if (t.id === 's_province') { pf.site.municipality = ''; fillMuni('s_province', 's_municipality', ''); }
    if (t.id === 's_province' || t.id === 's_municipality') { clearTimeout(ordTimer); ordTimer = setTimeout(() => loadOrdinance(true), 900); }
    if (t.id === 's_address') { clearTimeout(ordTimer); ordTimer = setTimeout(applyAddress, 900); }
    if (t.id === 'sp_kind') updatePlanUI();
    if (t.id === 'sc_start_month') onStartMonthChange();
    if (t.id === 'm_mode') updateMidUI();
    updateFar();
  }
  else if (t.dataset.u !== undefined) { pf.units[t.dataset.u][k] = ['name', 'kind', 'buyer'].includes(k) ? t.value : (val ?? 0); updateUnitCalc(); }
  else if (t.dataset.c !== undefined) {
    const c = pf.costs[t.dataset.c];
    if (k === 'basis') {
      // % ↔ 금액 기준이 바뀌면 기존 값은 의미가 달라지므로 0으로 초기화하고 입력칸으로 이동
      const kindChanged = isPct(c.basis) !== isPct(t.value) || c.basis.startsWith('auto_') || t.value.startsWith('auto_');   // 법정 자동으로/에서 바꾸면 값 의미가 달라짐
      c.basis = t.value; if (kindChanged) c.value = 0;
      renderCostCards();
      const inp = document.querySelector(`input[data-c="${t.dataset.c}"][data-k="value"]`);
      if (kindChanged && inp) { inp.focus(); inp.select(); notice('산정 기준이 바뀌어 입력값을 0으로 초기화했습니다. 새 값을 입력하세요.'); }
    } else c[k] = k === 'value' ? (val ?? 0) : t.value;
  }
  else if (t.dataset.l !== undefined) { pf.loans[t.dataset.l][k] = k === 'name' ? t.value : k === 'maturity_month' ? val : (val ?? 0); updateLoanCalc(); }
  else if (t.dataset.z !== undefined) { pf.site.zones[t.dataset.z][k] = k === 'zone' ? t.value : (val ?? 0); if (k === 'zone') { renderZones(); } autoApplyFar(); }
  else if (t.dataset.u !== undefined && k === 'kind') autoApplyFar();
  else if (t.dataset.pc !== undefined) { pf.prior_assets.cases[t.dataset.pc][k] = k === 'name' ? t.value : val; }
  else if (t.dataset.pl !== undefined) {
    pf.site.parcels[t.dataset.pl][k] = (k === 'area_sqm' || k === 'price_per_sqm') ? (val ?? 0) : t.value;
    const x = pf.site.parcels[t.dataset.pl], cell = document.querySelector(`[data-plv="${t.dataset.pl}"]`);
    const auto = isAuto(x, k); t.classList.toggle('auto-val', auto); t.title = auto ? '주소 조회로 자동 입력된 값' : '';
    if (cell) cell.textContent = x.price_per_sqm && x.area_sqm ? krw(x.price_per_sqm * x.area_sqm) : '–';
    applyParcels(k !== 'address');
  }
  else if (t.id === 'scCustom') { pf.schedule.custom_curve = t.value.split(',').map(x => Number(x.trim())).filter(x => isFinite(x) && x >= 0); }
  else if (t.dataset.t !== undefined) { pf.corporate_tax.brackets[t.dataset.t][k] = val ?? 0; }
  else return;
  pfRecalc();
});
$('view-proforma').addEventListener('click', e => {
  const t = e.target;
  if (t.dataset.delU !== undefined) { pf.units.splice(t.dataset.delU, 1); renderUnits(); pfRecalc(); }
  else if (t.dataset.delC !== undefined) { pf.costs.splice(t.dataset.delC, 1); renderCostCards(); pfRecalc(); }
  else if (t.dataset.delL !== undefined) { pf.loans.splice(t.dataset.delL, 1); renderLoans(); pfRecalc(); }
  else if (t.dataset.addC) {
    const key = t.dataset.addC, last = pf.costs.map(c => c.category).lastIndexOf(key);
    const item = { category: key, name: '신규 항목', basis: CAT_BASES[key]?.[0] || 'fixed', value: 0, note: '' };
    if (last < 0) pf.costs.push(item); else pf.costs.splice(last + 1, 0, item);
    renderCostCards(); pfRecalc();
    const inputs = document.querySelectorAll(`[data-k="name"][data-c]`); [...inputs].find(x => x.value === '신규 항목')?.select();
  }
  else if (t.closest('tr.cat[data-toggle]')) { const k = t.closest('tr').dataset.toggle; collapsed.has(k) ? collapsed.delete(k) : collapsed.add(k); renderPnl(); }
});
document.querySelectorAll('#pfTabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#pfTabs button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.pf-tab').forEach(p => p.classList.toggle('hidden', p.dataset.tab !== b.dataset.tab));
});
const pfTab = name => document.querySelector(`#pfTabs [data-tab="${name}"]`).click();

function updateFar() {
  if (!pf) return;
  const far = pf.land_area_sqm ? pf.above_gfa_sqm / pf.land_area_sqm * 100 : null;
  $('p_far').value = far == null ? '' : fmt(far, 2);
}
$('farApply').onclick = () => {
  const f = Number($('farCalc').value); if (!f || !pf.land_area_sqm) { notice('대지면적과 용적률을 입력하세요.', true); return; }
  pf.above_gfa_sqm = Math.round(pf.land_area_sqm * f / 100 * 100) / 100; $('p_above_gfa_sqm').value = moneyVal(pf.above_gfa_sqm);
  refreshHints(); updateFar(); pfRecalc(); notice('지상 연면적에 반영했습니다.');
};

/* — 계산 (자동, 디바운스) — */
function pfRecalc(now) {
  clearTimeout(pfTimer);
  $('sStatus').innerHTML = '<span class="chip gray">계산 중…</span>';
  pfTimer = setTimeout(async () => {
    const seq = ++pfSeq;
    try {
      const r = await api('POST', '/api/v3/proforma', pf);
      if (seq !== pfSeq) return;
      lastPf = r;
      renderPfResults();
      ezLive();
      scheduleSave();
      $('sStatus').innerHTML = `<span class="chip ok">계산 완료 ${new Date().toTimeString().slice(0, 5)}</span>`;
    } catch (err) {
      if (seq !== pfSeq) return;
      $('sStatus').innerHTML = `<span class="chip bad" title="${esc(err.message)}">입력 확인 필요</span>`;
      $('pfWarnings').innerHTML = errBox(err);
    }
  }, now ? 0 : 350);
}

/* — 결과 렌더링 — */
function renderPfResults() {
  const r = lastPf, s = r.summary;
  $('sPbt').textContent = krwW(s.pbt); $('sPbt').className = s.pbt < 0 ? 'neg' : '';
  $('sNpat').textContent = '법인세 후 ' + krwW(s.npat);
  $('sRev').textContent = krwW(s.revenue_net); $('sRevSub').textContent = '분양대금(VAT 포함) ' + krw(r.revenue.total_cash);
  $('sCost').textContent = krwW(s.total_cost); $('sCostSub').textContent = '금융비용 ' + krw(s.finance_cost) + ' 포함';
  const rd = r.redevelopment;
  $('sMargin').previousElementSibling.textContent = rd ? '비례율' : '매출이익률';
  $('sMargin').textContent = pct(rd ? rd.proportional_rate_pct : s.margin_pct);
  $('sMargin').className = (rd ? rd.proportional_rate_pct < 100 : s.margin_pct < 0) ? 'neg' : '';
  $('sRoe').textContent = rd ? '매출이익률 ' + pct(s.margin_pct) + ' · 평당 ' + krw(rd.value_per_py)
    : (s.equity_irr_pct != null ? 'Equity IRR ' + pct(s.equity_irr_pct) : 'ROE ' + pct(s.roe_pct)) + ' · 원가율 ' + pct(s.cost_to_revenue_pct);
  $('sBep').textContent = s.bep_sales_rate_pct == null ? '–' : pct(s.bep_sales_rate_pct);
  $('sBep').className = s.bep_sales_rate_pct > 100 ? 'neg' : s.bep_sales_rate_pct > 90 ? '' : 'pos';
  $('pfWarnings').innerHTML = r.warnings.length ? `<div class="alert warn fit"><b>확인 필요</b><ul>${r.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : '';
  $('pfNotice').textContent = '※ ' + r.notice;
  updateCostAmounts(); renderArea(); renderPnl(); renderStack(); renderKpi(); renderRev(); renderSens();
  renderVerdict(); renderCfPf(); renderCases(); renderZones(); updateLoanCalc(); renderPlan(); applyPlanGfa(); renderHug(); renderRental();
}
function renderArea() {
  const a = lastPf.area;
  $('areaSummary').tBodies[0].innerHTML = [
    ['대지면적', a.land_sqm, a.land_py], ['지상 연면적', a.above_gfa_sqm, PY(a.above_gfa_sqm)], ['지하 연면적', a.below_gfa_sqm, PY(a.below_gfa_sqm)],
    ['전체 연면적', a.above_gfa_sqm + a.below_gfa_sqm, a.gfa_py], ['분양(공급)면적', a.supply_py * 400 / 121, a.supply_py],
  ].map(([n, s, p]) => `<tr><td>${n}</td><td class="r">${fmt(s, 1)} ㎡</td><td class="r money">${fmt(p, 1)} 평</td></tr>`).join('')
    + `<tr><td>용적률</td><td class="r" colspan="2"><b>${pct(a.far_pct, 2)}</b></td></tr><tr><td>세대·호수</td><td class="r" colspan="2"><b>${fmt(a.units)}</b> <span class="muted">(주거 ${fmt(a.residential_units)})</span></td></tr>`;
}
function renderPnl() {
  const r = lastPf; if (!r) return; const s = r.summary, rv = r.revenue, sp = r.area.supply_py, u = pfUnit;
  const unitName = { 1: '원', 1000000: '백만원', 100000000: '억원' }[u];
  const row = (cls, name, amt, share, extra = '') => `<tr class="${cls}" ${extra}><td>${name}</td><td class="r ${amt < 0 ? 'minus' : ''}">${inUnit(amt, u)}</td><td class="r">${share == null ? '' : pct(share * 100)}</td><td class="r">${rv.total_net ? pct(amt / rv.total_net * 100) : '–'}</td><td class="r">${sp ? fmt(amt / sp / 1e4) : '–'}</td></tr>`;
  let h = `<thead><tr><th>구분</th><th class="r">금액 (${unitName})</th><th class="r">사업비 구성비</th><th class="r">매출 대비</th><th class="r">공급평당 (만원)</th></tr></thead><tbody>`;
  h += `<tr class="cat"><td colspan="5">Ⅰ. 매출 <span class="muted" style="font-weight:500">(부가세 제외)</span></td></tr>`;
  h += row('sub', '분양수입', rv.sales_net) + row('sub', '발코니 확장', rv.balcony_cash - rv.balcony_vat);
  if (rv.other_income) h += row('sub', '기타 수입', rv.other_income);
  h += row('total', '총매출', rv.total_net);
  h += `<tr class="cat"><td colspan="5">Ⅱ. 사업비 <span class="muted" style="font-weight:500">— 분류를 누르면 세부 항목을 접고 펼 수 있습니다</span></td></tr>`;
  r.costs.forEach(c => {
    h += row('cat', `<span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${CAT_COLORS[c.key]};margin-right:7px"></span>${collapsed.has(c.key) ? '▸' : '▾'} ${esc(c.name)}`, c.amount, c.share, `data-toggle="${c.key}" style="cursor:pointer"`);
    if (!collapsed.has(c.key)) c.items.forEach(i => { h += row('sub', `${esc(i.name)} <span class="muted" style="font-size:12.5px">${i.basis === 'derived' ? '' : BASES[i.basis]?.[0] || ''}</span>`, i.amount, s.total_cost ? i.amount / s.total_cost : null); });
  });
  h += row('total', '총사업비', s.total_cost, 1);
  h += row('grand', 'Ⅲ. 세전이익', s.pbt, null);
  h += row('sub', '법인세 (지방소득세 포함, 추정)', -s.corporate_tax, null);
  h += row('total', '세후이익', s.npat, null);
  $('pnlTable').innerHTML = h + '</tbody>';
}
document.querySelectorAll('#pfUnitSeg button').forEach(b => b.onclick = () => { pfUnit = Number(b.dataset.u); document.querySelectorAll('#pfUnitSeg button').forEach(x => x.classList.toggle('on', x === b)); renderPnl(); });
function renderStack() {
  const cs = lastPf.costs.filter(c => c.amount > 0), tot = lastPf.summary.total_cost || 1;
  $('costStack').innerHTML = cs.map(c => `<i style="width:${c.amount / tot * 100}%;background:${CAT_COLORS[c.key]}" title="${esc(c.name)} ${pct(c.amount / tot * 100)}"></i>`).join('');
  $('costLegend').innerHTML = cs.map(c => `<span><i style="background:${CAT_COLORS[c.key]}"></i>${esc(c.name)} <b>${pct(c.amount / tot * 100)}</b></span>`).join('');
}
function renderKpi() {
  const s = lastPf.summary, a = lastPf.area, rv = lastPf.revenue;
  const rows = [
    ['평균 분양가 (공급평당)', a.supply_py ? krwW(rv.sales_cash / a.supply_py) : '–'],
    ['총사업비 (공급평당)', krwW(s.cost_per_supply_py)],
    ['토지비 (대지평당)', krwW(s.land_per_py)],
    ['공사비 (연면적평당)', krwW(s.construction_per_gfa_py)],
    ['원가율 (사업비/매출)', pct(s.cost_to_revenue_pct)],
    ['자기자본', krwW(s.equity)], ['대출 합계', krwW(s.debt)], ['LTC (대출/총사업비)', pct(s.ltc_pct)],
    ['ROE (세후이익/자기자본)', pct(s.roe_pct)],
  ];
  $('kpiTable').tBodies[0].innerHTML = rows.map(([n, v]) => `<tr><td>${n}</td><td class="r"><b>${v}</b></td></tr>`).join('');
}
function renderRev() {
  const rv = lastPf.revenue;
  $('revTable').innerHTML = `<thead><tr><th>타입</th><th>구분</th><th class="r">전용 ㎡</th><th class="r">세대·호수</th><th class="r">공급면적 (평)</th><th class="r">세대당 분양가</th><th class="r">분양대금</th><th class="r">부가세</th><th class="r">공급가액</th></tr></thead><tbody>`
    + rv.rows.map(x => `<tr><td><b>${esc(x.name)}</b></td><td>${KINDS[x.kind]} ${x.taxable ? '<span class="chip warn">과세</span>' : '<span class="chip ok">면세</span>'}</td><td class="r">${fmt(x.exclusive_sqm, 2)}</td><td class="r">${fmt(x.count)}</td><td class="r">${fmt(x.supply_py_total, 1)}</td><td class="r">${krw(x.unit_price)}</td><td class="r">${krw(x.cash)}</td><td class="r">${x.vat ? krw(x.vat) : '–'}</td><td class="r money">${krw(x.net)}</td></tr>`).join('')
    + (rv.balcony_cash ? `<tr><td><b>발코니 확장</b></td><td>공동주택</td><td></td><td></td><td></td><td></td><td class="r">${krw(rv.balcony_cash)}</td><td class="r">${rv.balcony_vat ? krw(rv.balcony_vat) : '–'}</td><td class="r money">${krw(rv.balcony_cash - rv.balcony_vat)}</td></tr>` : '')
    + `</tbody><tfoot><tr class="total"><td colspan="6">합계 (분양률 ${pct(Number(pf.sales_rate_pct), 0)} 반영)</td><td class="r">${krw(rv.total_cash - rv.other_income)}</td><td class="r">${krw(rv.total_vat)}</td><td class="r">${krw(rv.total_net - rv.other_income)}</td></tr></tfoot>`;
}
function heatColor(m) { return m == null ? '#fff' : m < 0 ? '#ffd8d3' : m < 5 ? '#fff1d6' : m < 10 ? '#e3f0fb' : m < 15 ? '#b9dcf5' : '#7cc0f0'; }
function renderSens() {
  const sv = lastPf.sensitivity;
  if (!sv.cells.length) { $('sensTable').innerHTML = ''; $('bepCard').innerHTML = ''; return; }
  let h = `<thead><tr><th>분양가 조정 ＼ 분양률</th>${sv.sales_rates.map(r => `<th class="c">${r}%</th>`).join('')}</tr></thead><tbody>`;
  sv.cells.forEach((row, i) => {
    const a = sv.price_adjusts[i];
    h += `<tr><th>${a > 0 ? '+' : ''}${a}%${a === 0 ? ' (현재)' : ''}</th>` + row.map((c, j) => {
      const m = c.margin == null ? null : c.margin * 100;
      const base = a === 0 && sv.sales_rates[j] === 100;
      return `<td class="${base ? 'base' : ''}" style="background:${heatColor(m)};color:${m < 0 ? '#8a1f18' : 'inherit'}">${sensMode === 'margin' ? pct(m) : krw(c.pbt)}</td>`;
    }).join('') + '</tr>';
  });
  $('sensTable').innerHTML = h + '</tbody>';
  const s = lastPf.summary, i0 = sv.price_adjusts.indexOf(0), im = sv.price_adjusts.indexOf(-10), c100 = sv.sales_rates.indexOf(100);
  const p0 = sv.cells[i0][c100].pbt, pm = sv.cells[im][c100].pbt, slope = (p0 - pm) / 10;
  const tol = slope > 0 ? -p0 / slope : null;
  $('bepCard').innerHTML = `<h2>손익분기 분석</h2><div class="stats" style="margin:0">
    <div class="stat hl"><small>BEP 분양률</small><strong>${s.bep_sales_rate_pct == null ? '–' : pct(s.bep_sales_rate_pct)}</strong><em>이 비율 이상 분양 시 세전이익 발생 (현재 분양가 기준)</em></div>
    <div class="stat"><small>분양가 하락 허용폭</small><strong class="${tol != null && tol > 0 ? 'neg' : ''}">${tol == null ? '–' : (tol > 0 ? '+' : '') + fmt(tol, 1) + '%'}</strong><em>분양률 100% 가정, 이 폭까지 할인해도 손익 0</em></div>
    <div class="stat"><small>현재 분양률 세전이익</small><strong class="${s.pbt < 0 ? 'neg' : ''}">${krwW(s.pbt)}</strong><em>분양률 ${pct(Number(pf.sales_rate_pct), 0)}</em></div></div>`;
}
document.querySelectorAll('#sensSeg button').forEach(b => b.onclick = () => { sensMode = b.dataset.m; document.querySelectorAll('#sensSeg button').forEach(x => x.classList.toggle('on', x === b)); if (lastPf) renderSens(); });

/* — 사업지별 자동 저장 · 시나리오 (자료함/<사업지>/사업수지.json, 시나리오/) — */
let saveTimer = null, loadingSite = false, savedSnap = null;
const siteUrl = (n, extra = '') => `/api/v4/sites/${encodeURIComponent(n)}${extra}`;
function scheduleSave() {
  if (!curSite || loadingSite) { $('saveState').textContent = curSite ? '저장 대기' : '사업지 미선택 · 저장 안 됨'; return; }
  const snap = JSON.stringify(pf);
  if (snap === savedSnap) return;   // 변경 없음 → 저장하지 않음 (최종 저장 시각 유지)
  clearTimeout(saveTimer);
  $('saveState').className = 'chip gray'; $('saveState').textContent = '저장 중…';
  const site = curSite, body = JSON.parse(snap);
  saveTimer = setTimeout(async () => {
    try {
      await api('PUT', siteUrl(site, '/proforma'), body);
      if (site === curSite) savedSnap = snap;
      if (site === curSite) { $('saveState').className = 'chip ok'; $('saveState').textContent = '✓ 저장됨 ' + new Date().toTimeString().slice(0, 5); }
    } catch (err) { $('saveState').className = 'chip bad'; $('saveState').textContent = '저장 실패'; $('saveState').title = err.message; }
  }, 1200);
}
async function renderScnSelect() {
  if (!curSite) { $('scnSelect').innerHTML = '<option value="">시나리오 없음</option>'; return; }
  try {
    const j = await api('GET', siteUrl(curSite, '/proforma?scenario='));
    const list = j.scenarios || [];
    $('scnSelect').innerHTML = `<option value="">📂 저장한 시나리오 ${list.length ? '불러오기 (' + list.length + '개)' : '없음'}</option>` + list.map(s => `<option>${esc(s.name)}</option>`).join('');
    $('scnSelect').title = list.length ? '고르면 그 시나리오 숫자로 바뀝니다 (지금 숫자는 백업)' : '「💾 시나리오 저장」으로 저장한 안이 여기에 나옵니다';
  } catch { /* 목록 실패는 무시 */ }
}
$('scnSelect').onchange = async e => {
  const n = e.target.value; e.target.value = ''; if (!n || !curSite) return;
  await loadScenario(n);
};
$('scnSave').onclick = async () => {
  if (!curSite) { notice('사업지를 먼저 선택하세요.', true); return; }
  await saveScenario(pf);
};
/* 템플릿 규모를 사업지 대지면적에 맞춤 (연면적·세대수·면적·자기자본·대출·정액 사업비) */
function scaleTemplate(t, landSqm) {
  const k = landSqm / t.land_area_sqm, r2 = v => Math.round(v * k * 100) / 100;
  if (!(k > 0) || Math.abs(k - 1) < 1e-6) return t;
  t.above_gfa_sqm = r2(t.above_gfa_sqm); t.below_gfa_sqm = r2(t.below_gfa_sqm);
  t.units.forEach(u => {
    if (u.kind === 'apartment' || u.kind === 'officetel') u.count = Math.max(1, Math.round(u.count * k));
    else if (u.count > 1) u.count = Math.max(1, Math.round(u.count * k));
    else { u.supply_sqm = r2(u.supply_sqm); u.exclusive_sqm = r2(u.exclusive_sqm); }
  });
  t.equity = Math.round(t.equity * k); (t.loans || []).forEach(l => l.amount = Math.round(l.amount * k));
  t.costs.forEach(c => { if (c.basis === 'fixed') c.value = Math.round(c.value * k); });
  if (t.site?.building_area_sqm) t.site.building_area_sqm = r2(t.site.building_area_sqm);
  t.land_area_sqm = Math.round(landSqm * 100) / 100;
  return t;
}
$('pfSample').onclick = async () => {
  const sel = $('pfSampleSel'), label = sel.selectedOptions[0].text.replace('템플릿: ', '');
  try {
    const t = await api('GET', '/sample?name=' + sel.value);
    const info = t._template; delete t._template;
    if (pf && curSite) {
      const ok = await confirmBox(`「${esc(label)}」 템플릿을 적용할까요?`,
        `${info ? esc(info.desc) + '<br><br>' : ''}분양 타입·사업비·일정·금융이 템플릿 구성으로 <b>바뀝니다.</b> 사업지 주소·필지·용도지역·대지면적은 그대로 두고, 템플릿 규모를 대지면적 ${fmt(pf.land_area_sqm, 1)}㎡에 맞춥니다.
        <label style="display:flex;gap:6px;align-items:center;margin-top:10px;font-size:14px"><input type="checkbox" id="tplBackup" checked> 바꾸기 전에 지금 숫자를 시나리오로 보관</label>`, '적용');
      if (!ok) return;
      if (document.getElementById('tplBackup')?.checked)
        await api('PUT', siteUrl(curSite, `/proforma?scenario=${encodeURIComponent(today + ' 템플릿 적용 전 백업')}&memo=${encodeURIComponent('「' + label + '」 템플릿 적용 전 자동 보관')}`), pf);
      t.project_name = pf.project_name; t.site = { ...t.site, ...pf.site };
      scaleTemplate(t, Number(pf.land_area_sqm) || t.land_area_sqm);
    }
    t.template_key = sel.value;
    pfLoad(t, false); loadOrdinance(false); renderScnSelect();
    notice(`「${label}」 템플릿을 적용했습니다. ${info ? info.note : ''}`);
  } catch (e) { notice(e.message, true); }
};
$('pfExport').onclick = () => download((pf.project_name || 'proforma') + '_' + today + '.json', JSON.stringify(pf, null, 2), 'application/json');
$('pfImport').onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  f.text().then(t => pfLoad(JSON.parse(t))).catch(err => notice('파일을 읽지 못했습니다: ' + err.message, true));
  e.target.value = '';
};
$('pfPrint').onclick = () => { pfTab('result'); setTimeout(() => window.print(), 100); };

/* — 사업지·법규 연동 — */
const ZONE_LIST = ['제1종전용주거지역', '제2종전용주거지역', '제1종일반주거지역', '제2종일반주거지역', '제3종일반주거지역', '준주거지역', '중심상업지역', '일반상업지역',
  '근린상업지역', '유통상업지역', '전용공업지역', '일반공업지역', '준공업지역', '보전녹지지역', '생산녹지지역', '자연녹지지역', '보전관리지역', '생산관리지역',
  '계획관리지역', '농림지역', '자연환경보전지역'];
const LEVEL = { registered: ['검토자 등록', 'ok'], ordinance: ['조례 원문 대조', 'ok'], auto: ['조례 자동판독', 'warn'], national: ['시행령 상한 (조례 미확인)', 'bad'], none: ['근거 없음', 'bad'] };
let ordTimer = null, ordCache = null;
const parcelsActive = () => (pf.site.parcels || []).some(x => String(x.address || '').trim() || Number(x.area_sqm) > 0);
function renderZones() {
  const zs = pf.site.zones, lock = parcelsActive();
  $('addZone').closest('div').classList.toggle('hidden', lock);
  $('zoneTable').tBodies[0].innerHTML = zs.map((z, i) => {
    const lim = zoneLimit(z.zone);
    return `<tr><td><select data-z="${i}" data-k="zone">${ZONE_LIST.map(n => `<option ${n === z.zone ? 'selected' : ''}>${n}</option>`).join('')}</select></td>
      <td><input class="money-in" data-z="${i}" data-k="area_sqm" value="${moneyVal(z.area_sqm)}"></td>
      <td class="r">${lim.bcr != null ? lim.bcr + '%' : '–'}</td><td class="r"><b>${lim.far != null ? lim.far + '%' : '–'}</b>${lim.apt ? `<div class="muted" style="font-size:12px">공동주택 ${lim.apt}%</div>` : ''}</td>
      <td><span class="chip ${LEVEL[lim.level][1]}">${LEVEL[lim.level][0]}</span></td>
      <td>${lock ? '' : `<button class="del" data-del-z="${i}">✕</button>`}</td></tr>`;
  }).join('') || `<tr><td colspan="6" class="c muted">${lock ? '필지 목록의 면적·용도지역을 입력하면 자동 합산됩니다.' : '용도지역을 추가하세요 (필지 목록·사업지 자료에서 자동 입력).'}</td></tr>`;
  $('zoneTable').querySelectorAll('select, input').forEach(e => { e.disabled = lock; });
  $('zoneTable').title = lock ? '필지 목록에서 자동 합산됩니다 (필지 목록에서 수정)' : '';
  const cap = $('zoneTable').closest('.card').querySelector('#zoneLockNote');
  if (cap) cap.textContent = lock ? '필지 목록 자동 합산 — 필지 목록에서 수정하세요' : '';
}
function zoneLimit(zone) {
  const o = ordCache?.ordinance, nat = ordCache?.national?.[zone];
  const l = o?.limits?.[zone];
  if (l && l.far != null) return { far: l.far, bcr: l.bcr, apt: l.far_apt, level: o.reviewed_by ? 'ordinance' : 'auto' };
  if (nat) return { far: nat[2], bcr: nat[0], level: 'national' };
  return { level: 'none' };
}
async function loadOrdinance(fetchRemote) {
  const p = pf.site.province, m = (pf.site.municipality || '').trim();
  if (!p) { ordCache = null; renderZones(); $('zoningNotes').innerHTML = ''; return; }
  const q = `province=${encodeURIComponent(p)}&municipality=${encodeURIComponent(m)}`;
  try {
    ordCache = await api('GET', '/api/v4/ordinance?' + q);
    if (!ordCache.ordinance && fetchRemote) {
      $('zoningNotes').innerHTML = '<div class="alert info">국가법령정보센터에서 조례를 불러오는 중…</div>';
      const f = await api('POST', '/api/v4/ordinance/fetch', { province: p, municipality: m });
      ordCache.ordinance = f.ordinance; ordCache.parking = f.parking && !f.parking.error ? f.parking : null;
    } else if (!ordCache.parking && ordCache.ordinance) {   // 주차장 조례만 아직 없으면 뒤에서 한 번 받아 다시 계산 (사업지를 열 때도)
      api('POST', '/api/v4/parking/fetch', { province: p, municipality: m }).then(x => { ordCache.parking = x.parking; pfRecalc(); }).catch(() => {});
    }
  } catch (e) {
    $('zoningNotes').innerHTML = errBox(e) + `<div class="alert warn">광역지자체(${esc(p)})와 시·군·구(${esc(m)})가 맞는지 확인하세요. <b>🔍 주소 검색</b>으로 선택하면 두 칸이 함께 정확히 입력됩니다.</div>`;
    renderZones(); return;
  }
  renderZones(); renderOrdNotes(); autoApplyFar(true); pfRecalc();
}
function renderOrdNotes() {
  const o = ordCache?.ordinance;
  if (!o) { $('zoningNotes').innerHTML = `<div class="alert warn">${esc(pf.site.municipality || pf.site.province)} 조례가 아직 수집되지 않아 <b>국토계획법 시행령 상한</b>을 임시 적용합니다. <b>조례 불러오기</b>를 누르세요.</div>`; return; }
  const w = o.articles?.warnings || [];
  $('zoningNotes').innerHTML = `<div class="alert ${o.reviewed_by ? 'ok' : 'info'}" style="display:inline-block;max-width:100%;margin:0;padding:5px 12px;font-size:13.5px;line-height:1.5;white-space:nowrap;overflow-x:auto"><b>${esc(o.title)}</b> ${esc(o.articles?.bcr || '')}(건폐율)·${esc(o.articles?.far || '')}(용적률) · 시행 ${esc(o.effective || '–')} · ${esc(o.promulgation || '')}
    · <a href="${esc(o.url)}" target="_blank" rel="noopener">원문 ↗</a> · ${o.reviewed_by ? '검토 완료: ' + esc(o.reviewed_by) + ' (' + esc(o.reviewed_on) + ')' : '<span class="muted">자동 판독값 — 원문 대조 필요</span>'}
    ${o.effective && o.effective > today ? '<br><b>⚠ 시행 예정 조례입니다. 현행 조례와 다를 수 있습니다.</b>' : ''}${w.length ? '<ul>' + w.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>' : ''}</div>`;
}
$('ordFetch').onclick = e => busy(e.target, async () => {
  if (!pf.site.province) { notice('광역지자체를 선택하세요.', true); return; }
  try { const f = await api('POST', '/api/v4/ordinance/fetch', { province: pf.site.province, municipality: (pf.site.municipality || '').trim() }); ordCache = { ...(ordCache || {}), ordinance: f.ordinance }; if (!ordCache.national) await loadOrdinance(false); renderZones(); renderOrdNotes(); if (!autoApplyFar(true)) notice('조례를 불러왔습니다.'); pfRecalc(); }
  catch (err) { $('zoningNotes').innerHTML = errBox(err); }
});
/* 공공지원민간임대 결과 */
function renderRental() {
  const R = lastPf.rental;
  if (!R) { $('rentalResult').innerHTML = ''; return; }
  $('sBep').previousElementSibling.textContent = '임대수익률 (1년차)'; $('sBep').textContent = pct(R.yield_on_cost_pct, 2);
  $('rentalResult').innerHTML = `<div class="card"><h2>공공지원민간임대 수지 <span class="sub">${esc(R.notes.join(' · '))}</span></h2>
    <div class="stats">
      <div class="stat hl"><small>Equity IRR (${pf.rental.hold_years}년 운영 후 매각)</small><strong>${pct(R.equity_irr_pct)}</strong><em>Multiple ${R.equity_multiple != null ? fmt(R.equity_multiple, 2) + '배' : '–'} · NPV ${krw(R.equity_npv)}</em></div>
      <div class="stat"><small>임대수익률 (NOI ÷ 총사업비)</small><strong>${pct(R.yield_on_cost_pct, 2)}</strong><em>1년차 NOI ${krw(R.noi_year1)}</em></div>
      <div class="stat"><small>최저 DSCR</small><strong class="${R.min_dscr != null && R.min_dscr < 1 ? 'neg' : ''}">${R.min_dscr != null ? fmt(R.min_dscr, 2) + '배' : '–'}</strong><em>이자 대비 NOI</em></div>
      <div class="stat"><small>매각가 → 자기자본 회수</small><strong>${krw(R.exit_value)}</strong><em>순회수 ${krw(R.exit_net_to_equity)} · 양도세 ${krw(R.exit_gain_tax)}</em></div>
    </div>
    <div class="grid2"><table><tbody>
      <tr><td>총사업비 (건설이자 포함)</td><td class="r"><b>${krwW(R.total_cost)}</b></td></tr>
      <tr><td>임대보증금 (입주율·임대료율 반영)</td><td class="r">${krwW(R.deposit_total)}</td></tr>
      <tr><td>주택도시기금 융자</td><td class="r">${krwW(R.fund_loan)} <span class="muted">연 ${fmt(R.fund_rate_pct, 2)}%</span></td></tr>
      <tr><td>준공 후 담보대출</td><td class="r">${krwW(R.mortgage)}</td></tr>
      <tr><td>자기자본</td><td class="r">${krwW(R.equity)}${R.equity_release ? ' (회수 ' + krw(R.equity_release) + ')' : ''}</td></tr>
    </tbody></table><table><tbody>
      <tr><td>평균 임대료율 (시세 대비)</td><td class="r">${pct(R.rent_ratio_pct)}</td></tr>
      <tr><td>특별공급 임대료 상한</td><td class="r">${pct(R.special_rent_cap_pct, 0)}</td></tr>
      <tr><td>재산세 감면 (가중)</td><td class="r">${pct(R.property_tax_relief_pct)}</td></tr>
      <tr><td>1년차 임대수입</td><td class="r">${krwW(R.rent_year1)}</td></tr>
      <tr><td>장부가 (매각 시)</td><td class="r">${krwW(R.book_value)}</td></tr>
    </tbody></table></div>
    <h3>연도별 현금흐름 (백만원)</h3><div class="tablewrap"><table><thead><tr><th>연차</th><th class="r">임대수입</th><th class="r">보증금 증액</th><th class="r">운영비</th><th class="r">보유세</th><th class="r">보증료</th><th class="r">NOI</th><th class="r">이자</th><th class="r">DSCR</th><th class="r">법인세</th><th class="r">자기자본 CF</th></tr></thead><tbody>
    ${R.rows.map(x => `<tr><td>${x.year}년차</td>${['rent', 'deposit_increase', 'opex', 'property_tax', 'guarantee_fee', 'noi', 'interest'].map(k => `<td class="r">${fmt(x[k] / 1e6, 0)}</td>`).join('')}<td class="r ${x.dscr != null && x.dscr < 1 ? 'minus' : ''}">${x.dscr != null ? fmt(x.dscr, 2) : '–'}</td><td class="r">${fmt(x.tax / 1e6, 0)}</td><td class="r ${x.cash_flow < 0 ? 'minus' : 'money'}">${fmt(x.cash_flow / 1e6, 0)}</td></tr>`).join('')}
    <tr class="total"><td>매각</td><td colspan="9" class="muted">매각가 ${krw(R.exit_value)} − 매각비용 ${krw(R.exit_sale_cost)} − 보증금 반환·대출 상환 − 양도세 ${krw(R.exit_gain_tax)}</td><td class="r money">${fmt(R.exit_net_to_equity / 1e6, 0)}</td></tr>
    </tbody></table></div>
    <p class="muted" style="font-size:13px;margin:10px 0 0">${esc((R.sources || []).join(' / '))}</p></div>`;
}

/* 중도금 대출 이자 방식 */
function updateMidUI() {
  const m = pf.midpay.mode;
  document.querySelectorAll('.mid-free').forEach(e => e.classList.toggle('hidden', m !== 'interest_free'));
  ['m_ratio_pct', 'm_annual_rate_pct', 'm_avg_months'].forEach(id => $(id).closest('.field').classList.toggle('hidden', m === 'with_interest'));
  $('midHint').textContent = {
    interest_free: '이자 = 중도금 × 금리 × 기간 × 부담 비율 → 금융비용. 월별 현금흐름 사용 시 실제 중도금 잔액 기준으로 매월 지급',
    deferred: '사업비 부담 없음. 월별 현금흐름에서는 입주 전까지 매월 대납하고 잔금 때 일괄 회수 (대납 기간 자금 부담 반영)',
    with_interest: '수분양자가 은행에 직접 납부 — 사업비·현금흐름 영향 없음',
  }[m];
}

/* HUG 보증 결과 */
function renderHugElig() {
  const el = lastPf.hug_eligibility; if (!el) return;
  const CONF = { '사업계획승인·건축허가': 'confirm_approval', '사업부지 확보·신탁': 'confirm_land_trust', '시공사 요건': 'confirm_contractor', '신축매입약정 체결': 'confirm_purchase_agreement' };
  $('hugElig').innerHTML = `<div class="alert ${el.eligible ? 'ok' : 'warn'}" style="margin:0"><b>${el.eligible ? '✓ HUG 보증 이용 요건 충족 — 선택할 수 있습니다' : '보증 요건을 모두 충족해야 HUG 보증을 선택할 수 있습니다'}</b>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:6px 18px;margin-top:8px">
    ${el.checks.map(c => c.kind === 'confirm'
      ? `<label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer"><input type="checkbox" data-hugconf="${CONF[c.name]}" ${pf.hug[CONF[c.name]] ? 'checked' : ''} style="margin-top:3px;accent-color:var(--brand-blue)"><span><b>${esc(c.name)}</b> <span class="muted" style="font-size:13px">(확인)</span><br><span style="font-size:13px">${esc(c.detail)}</span></span></label>`
      : `<div style="display:flex;gap:8px"><span style="font-weight:800;color:${c.ok ? 'var(--pos)' : 'var(--neg)'}">${c.ok ? '✓' : '✗'}</span><span><b>${esc(c.name)}</b><br><span style="font-size:13px">${esc(c.detail)}</span></span></div>`).join('')}
    </div><div class="muted" style="font-size:12.5px;margin-top:6px">${esc(el.source)} · 일반분양 ${el.general_units}세대${el.sale_guarantee_allowed ? '' : ' (분양보증은 일반분양 30세대 이상)'}</div></div>`;
  const box = $('hg_enabled');
  box.disabled = !el.eligible;
  $('hugEnableLabel').style.opacity = el.eligible ? 1 : .5;
  $('hugEnableLabel').style.cursor = el.eligible ? 'pointer' : 'not-allowed';
  if (!el.eligible && pf.hug.enabled) {
    pf.hug.enabled = false; box.checked = false;
    notice('HUG 보증 요건을 충족하지 않아 선택을 해제했습니다.', true); pfRecalc();
  }
  const sg = $('hg_sale_guarantee');
  sg.disabled = !el.sale_guarantee_allowed;
  sg.closest('label').style.opacity = el.sale_guarantee_allowed ? 1 : .5;
  if (!el.sale_guarantee_allowed && pf.hug.sale_guarantee) { pf.hug.sale_guarantee = false; sg.checked = false; }
}
document.addEventListener('change', e => {
  const k = e.target.dataset?.hugconf; if (!k || !pf) return;
  pf.hug[k] = e.target.checked; pfRecalc();
});
function renderHug() {
  renderHugElig();
  const on = pf.hug.enabled;
  $('hugFields').style.opacity = on ? 1 : .45; $('hugFields').style.pointerEvents = on ? '' : 'none';
  if (!on) { $('hugResult').innerHTML = ''; return; }
  const fees = lastPf.costs.flatMap(c => c.items).filter(i => i.name.startsWith('HUG'));
  const checks = lastPf.compliance.items.filter(i => i.name.startsWith('HUG'));
  $('hugResult').innerHTML = `<div class="stats" style="margin-bottom:10px">${fees.map(f => `<div class="stat"><small>${esc(f.name)}</small><strong>${krwW(f.amount)}</strong><em>연 ${fmt(f.value, 3)}%</em></div>`).join('')}</div>
    <table><tbody>${checks.map(x => `<tr><td style="white-space:nowrap">${esc(x.name)}</td><td style="font-size:14px">${esc(x.detail)}</td><td class="c"><span class="chip ${ST[x.status][1]}">${ST[x.status][0]}</span></td></tr>`).join('')}</tbody></table>`;
}

/* 토지이용계획(지역·지구) → 규제 사항 · 3차 도시계획 구분 자동 */
const USE_KIND = [[/지구단위계획구역/, 'district'], [/재정비촉진/, 'redevelopment'], [/정비구역|주거환경개선/, 'redevelopment'], [/가로주택|소규모/, 'small']];
function applyLandUse() {
  const uses = pf.site.parcels.flatMap(x => x.uses || []);
  if (!uses.length) return;
  const names = [...new Set(uses.map(u => u.name + (u.relation && u.relation !== '포함' ? `(${u.relation})` : '')))];
  pf.site.flags = [...new Set([...(pf.site.flags || []), ...uses.filter(u => /지구단위|정비|재정비|개발제한|군사|문화|교육환경|토지거래|과밀|비행|고도|경관|철도|공원/.test(u.name) || u.relation === '저촉').map(u => u.name)])];
  if (pf.site.plan.kind === 'none') {
    const hit = USE_KIND.find(([re]) => uses.some(u => re.test(u.name)));
    if (hit) { pf.site.plan.kind = hit[1]; fillFields(); updatePlanUI(); notice(`토지이용계획에 「${uses.find(u => hit[0].test(u.name)).name}」이 있어 3차 도시계획을 ${$('sp_kind').selectedOptions[0].text}(으)로 설정했습니다. 토지이음 고시를 검색합니다.`); searchPlans(true); }
  }
  $('parcelNotes').insertAdjacentHTML('beforeend', `<div class="alert info" style="margin:8px 0 0"><b>토지이용계획 (자동 조회)</b> ${names.map(esc).join(' · ')}</div>`);
  updatePlanVisibility();
}
async function searchPlans(auto) {
  const first = pf.site.parcels.find(x => x.address)?.address || pf.site.address || '';
  if (!first) { if (!auto) notice('사업지 주소나 필지를 먼저 입력하세요.', true); return; }
  const kind = pf.site.plan.kind === 'none' ? 'district' : pf.site.plan.kind;
  const reg = pf.site.parcels.flatMap(x => x.uses || []).find(u => /지구단위|정비/.test(u.name))?.registered || '';
  $('planCands').innerHTML = '<div class="alert info" style="margin:0">토지이음에서 고시를 검색하는 중…</div>';
  try {
    const j = await api('GET', `/api/v4/plans/search?address=${encodeURIComponent(first)}&kind=${kind}&municipality=${encodeURIComponent(pf.site.municipality || '')}&registered=${encodeURIComponent(reg)}`);
    const cs = j.candidates.filter(c => c.match);   // 사업지 지번이 대상지에 있는 고시만
    const anyMatch = cs.length > 0;
    $('planCands').innerHTML = !anyMatch ? `<div class="alert warn" style="display:inline-block;margin:0;padding:5px 12px;font-size:13.5px;line-height:1.5">사업지 지번이 대상지에 포함된 고시를 찾지 못했습니다. <a href="https://www.eum.go.kr/" target="_blank" rel="noopener">토지이음</a>에서 고시를 확인하고 아래에 입력하세요.</div>` : `
      <div class="tablewrap"><table><thead><tr><th style="width:96px">고시일</th><th style="white-space:nowrap">고시번호</th><th>고시 제목</th><th style="width:200px">대상지</th><th style="width:96px"></th></tr></thead><tbody>
      ${cs.map(c => `<tr${c.match ? ' style="background:#e6f4ea"' : ''}><td style="white-space:nowrap">${esc(c.date)}</td><td style="font-size:13.5px;white-space:nowrap">${esc(c.notice_no)}</td><td>${c.match ? '<span class="chip ok">✓ 지번 일치</span> ' : ''}<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a></td>
        <td style="font-size:13.5px">${esc(c.location || '–')}</td><td><button type="button" class="btn ${c.match ? '' : 'secondary'}" data-plan-seq="${esc(c.seq)}">적용</button></td></tr>`).join('')}</tbody></table></div>
      <p class="muted" style="font-size:13px;margin:6px 0 0">대상지에 사업지 지번이 있는 고시만 「✓ 지번 일치」로 표시합니다. <b>적용</b>을 누르면 결정조서(HWP·PDF)에서 기준·허용·상한 용적률과 건폐율을 추출합니다.</p>`
      ;
  } catch (err) { $('planCands').innerHTML = errBox(err); }
}
$('planSearch').onclick = () => searchPlans(false);
let planBlocks = null;   // 마지막으로 읽은 결정조서의 획지 목록
function applyPlanBlock(b) {
  const pl = pf.site.plan;
  Object.assign(pl, { block: b.block, base_far: b.base_far ?? b.far ?? null, allowed_far: b.allowed_far ?? null, max_far: b.max_far ?? b.legal_max_far ?? null,
    plan_bcr: b.bcr ?? null, max_floors: b.floors ?? null, height_limit_m: b.height_m ?? null, allowed_uses: (b.uses || '').slice(0, 400), res_far: b.far_res ?? null });
  if (pl.kind === 'none') pl.kind = 'district';
  fillFields(); updatePlanUI(); pfRecalc();
}
function planBlocksTable(r) {
  const bs = r.blocks || [];
  if (bs.length < 2) return '';
  const v = x => x == null ? '–' : fmt(x, x % 1 ? 2 : 0);
  return `<div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>획지</th><th>위치</th><th style="text-align:right">건폐율</th><th style="text-align:right">용적률 (기준/허용/상한)</th><th>높이</th><th>허용용도</th><th></th></tr></thead><tbody>
    ${bs.map((b, i) => `<tr${b.block === r.block ? ' style="background:#e6f4ea"' : ''}><td style="white-space:nowrap"><b>${esc(b.block)}</b>${b.phase === '기정' ? ' <span class="chip">기정</span>' : ''}</td>
      <td style="font-size:13px">${esc(b.location || '–')}</td><td style="text-align:right">${v(b.bcr)}%</td>
      <td style="text-align:right;white-space:nowrap">${b.base_far != null || b.allowed_far != null ? `${v(b.base_far)} / ${v(b.allowed_far)} / ${v(b.max_far ?? b.legal_max_far)}` : v(b.far)}%${b.far_res != null ? ` <span class="muted">(주거 ${v(b.far_res)})</span>` : ''}</td>
      <td style="font-size:13px;white-space:nowrap">${esc(b.height || [b.floors ? b.floors + '층' : '', b.height_m ? b.height_m + 'm' : ''].filter(Boolean).join(' / ') || '–')}</td>
      <td style="font-size:12.5px;max-width:260px">${esc((b.uses || '–').slice(0, 70))}</td>
      <td><button type="button" class="btn ${b.block === r.block ? '' : 'secondary'}" data-plan-block="${i}">${b.block === r.block ? '적용됨' : '이 획지 적용'}</button></td></tr>`).join('')}</tbody></table></div>
    <p class="muted" style="font-size:13px;margin:6px 0 0">기정·변경 조서가 함께 있으면 변경 값을 씁니다. 「기정」 표시는 변경 조서에 없어 기정 값을 보여준 획지입니다. 자동 판독이므로 원문과 대조하세요.</p>`;
}
document.addEventListener('click', async e => {
  const bb = e.target.closest('[data-plan-block]');
  if (bb && planBlocks) {
    const b = (planBlocks.blocks || [])[+bb.dataset.planBlock];
    if (!b) return;
    planBlocks.block = b.block; applyPlanBlock(b);
    $('planBlockBox').innerHTML = planBlocksTable(planBlocks);
    notice(`획지 ${b.block}의 결정고시 수치를 적용했습니다. 원문과 대조하세요.`);
    return;
  }
  const b = e.target.closest('[data-plan-seq]'); if (!b) return;
  await busy(b, async () => {
    try {
      const addr = pf.site.parcels.find(x => x.address)?.address || pf.site.address || '';
      const r = await api('GET', '/api/v4/plans/extract?seq=' + encodeURIComponent(b.dataset.planSeq) + '&address=' + encodeURIComponent(addr));
      const pl = pf.site.plan;
      Object.assign(pl, { title: r.title || pl.title, notice_no: r.notice_no || pl.notice_no, notice_date: r.date || pl.notice_date, url: r.url });
      planBlocks = r;
      document.querySelectorAll('#planBlockBox').forEach(x => x.remove());   // 이전 고시의 획지 표(버튼 번호가 새 목록과 어긋남) 제거
      const chosen = (r.blocks || []).find(x => x.block === r.block);
      if (chosen) applyPlanBlock(chosen);
      else {
        // 새 고시로 바뀌었으니 이전 고시의 획지·높이·용도는 지우고, 수치는 새 고시에서 읽은 값만 (여러 획지 미선택이면 비움)
        Object.assign(pl, { block: '', max_floors: null, height_limit_m: null, allowed_uses: '', res_far: null,
          base_far: r.base_far ?? null, allowed_far: r.allowed_far ?? null, max_far: r.max_far ?? null, plan_bcr: r.plan_bcr ?? null });
        if (pl.kind === 'none') pl.kind = 'district';
        fillFields(); updatePlanUI(); pfRecalc();
      }
      const many = (r.blocks || []).length > 1, got = r.base_far != null || chosen;
      $('planCands').insertAdjacentHTML('afterbegin', `<div class="alert ${got ? 'ok' : 'warn'}" style="margin:0 0 8px"><b>${esc(r.notice_no)} 적용</b> — ${chosen ? `획지 <b>${esc(chosen.block)}</b>${chosen.location ? ' (' + esc(chosen.location) + ')' : ''} · ` : ''}기준 ${pl.base_far ?? '–'}% · 허용 ${pl.allowed_far ?? '–'}% · 상한 ${pl.max_far ?? '–'}% · 건폐율 ${pl.plan_bcr ?? '–'}%${pl.max_floors ? ' · 최고 ' + pl.max_floors + '층' : ''}
        <span class="muted">(첨부: ${esc((r.parsed_files || []).join(', ') || '없음')})</span><br><span style="font-size:13px">${esc(r.notice)}</span>
        ${!many ? (r.snippets || []).slice(0, 2).map(s => `<div class="muted" style="font-size:12.5px;margin-top:4px">…${esc(s)}…</div>`).join('') : ''}<div id="planBlockBox">${planBlocksTable(r)}</div></div>`);
      notice(chosen ? `결정조서 획지 ${chosen.block} 수치를 적용했습니다. 원문과 대조하세요.` : many ? `결정조서에 획지 ${r.blocks.length}곳이 있습니다. 사업지 획지를 골라 「이 획지 적용」을 누르세요.` : got ? '고시를 적용했습니다. 추출한 용적률을 원문과 대조하세요.' : '고시 정보는 넣었지만 용적률을 추출하지 못했습니다. 원문을 보고 입력하세요.', !chosen && !got);
    } catch (err) { notice(err.message, true); }
  });
});

/* 3차 도시계획: 토지이용계획상 해당 구역일 때만 표시 */
const PLAN_AREA = /지구단위계획구역|정비구역|정비예정구역|재정비촉진|주거환경개선|가로주택|소규모주택정비|특별정비/;
let planManual = false;
function planRelevance() {
  const uses = (pf.site.parcels || []).flatMap(x => x.uses || []);
  const hit = uses.find(u => PLAN_AREA.test(u.name));
  return { known: uses.length > 0, hit };
}
function updatePlanVisibility() {
  const r = planRelevance(), show = !!r.hit || pf.site.plan.kind !== 'none' || planManual;
  $('planSection').classList.toggle('hidden', !show);
  $('planNote').innerHTML = show ? '' : r.known
    ? '3차 · 지자체 도시계획: <b>토지이용계획상 지구단위계획구역·정비구역에 해당하지 않습니다</b> → 2차 조례가 적용됩니다. <a href="#" id="planManualOn">직접 입력</a>'
    : '3차 · 지자체 도시계획: 필지를 조회하면 지구단위계획·정비구역 해당 여부를 자동으로 판단합니다. <a href="#" id="planManualOn">직접 입력</a>';
}
document.addEventListener('click', e => { if (e.target.id === 'planManualOn') { e.preventDefault(); planManual = true; updatePlanVisibility(); } });

/* 3차 도시계획 화면 */
function updatePlanUI() {
  const k = pf.site.plan.kind, on = k !== 'none', renew = ['redevelopment', 'reconstruction', 'small'].includes(k);
  document.querySelectorAll('.plan-on').forEach(e => e.classList.toggle('hidden', !on));
  document.querySelectorAll('.plan-district').forEach(e => e.classList.toggle('hidden', k !== 'district'));
  document.querySelectorAll('.plan-renew').forEach(e => e.classList.toggle('hidden', !renew));
  $('lblBase').textContent = k === 'district' ? '기준용적률' : '정비계획 용적률';
  $('lblMax').textContent = k === 'district' ? '상한용적률' : '법적상한용적률';
  $('lblRatio').textContent = k === 'small' ? '공공임대주택 비율 (전체 연면적 대비)' : '국민주택규모 건설비율 (초과용적률 대비)';
  updatePlanVisibility();
  $('ratioHint').textContent = k === 'small' ? '빈집법 제49조①: 20% 이상(조례 비율 이상) 시 법적상한' : k === 'reconstruction' ? '도시정비법 제54조④: 과밀억제권역 30~50% (외 50% 이하)' : k === 'redevelopment' ? '도시정비법 제54조④: 과밀억제권역 50~75% (외 75% 이하)' : '';
}
function renderPlan() {
  const pl = lastPf?.compliance?.plan;
  $('planResult').innerHTML = pl && pl.far != null ? `<div class="alert ok" style="display:inline-block;margin:0;padding:5px 12px;font-size:13.5px;line-height:1.5"><b>3차 도시계획 적용: ${esc(pl.kind_name)}</b> — 용적률 ${pct(pl.far, 2)} × 순대지 ${fmt(pl.net_site_sqm, 1)}㎡ = <b>허용 연면적 ${fmt(pl.gfa, 1)}㎡</b>${pl.bcr != null ? ` · 건폐율 ${pct(pl.bcr, 2)}` : ''}${pl.obligation_sqm ? ` · 의무 공급 연면적 ${fmt(pl.obligation_sqm, 1)}㎡` : ''}${pl.notes?.length ? '<ul>' + pl.notes.map(n => `<li>${esc(n)}</li>`).join('') + '</ul>' : ''}</div>`
    : pf.site.plan.kind !== 'none' ? '<div class="alert warn">결정고시의 용적률을 입력하면 조례 대신 적용됩니다.</div>' : '';
}
function applyPlanGfa() {
  const pl = lastPf?.compliance?.plan;
  if (!pf.site.auto_far || pf.site.plan.kind === 'none' || !pl || pl.gfa == null) return;
  const g = Math.floor(pl.gfa * 100) / 100;
  if (Math.abs(g - Number(pf.above_gfa_sqm)) < 0.01) return;
  pf.above_gfa_sqm = g; $('p_above_gfa_sqm').value = moneyVal(g); refreshHints(); updateFar(); pfRecalc();
  notice(`3차 도시계획(${pl.kind_name}) 허용 연면적 ${fmt(g, 1)}㎡를 지상 연면적에 대입했습니다.`);
}

/* ── 필지 정보 자동 조회 (브이월드 토지특성정보) ── */
const landState = {};   // 행 번호 → 조회 상태 문구 (화면 표시용)
/* 중복 필지: 주소 글자(띄어쓰기·'번지' 무시)나 PNU(필지 고유번호)가 같은 다른 필지의 번호, 없으면 -1 */
const addrKey = a => String(a || '').replace(/\s+/g, '').replace(/번지$/, '');
function dupParcel(i, addr, pnu) {
  return pf.site.parcels.findIndex((y, j) => j !== i && ((pnu && y.pnu && String(y.pnu) === String(pnu)) || (addr && addrKey(y.address) === addrKey(addr))));
}
function dropDupParcel(i, j, addr) {   // 새로 넣은 i 를 지우고 알림 (기존 j 는 유지)
  pf.site.parcels.splice(i, 1); Object.keys(landState).forEach(k => delete landState[k]);
  renderParcels(); applyParcels();
  notice(`이미 ${j < i ? j + 1 : j}번 필지로 입력된 땅입니다 — 중복이라 추가하지 않았습니다. (${addr})`, true);
  return 'dup';
}
async function fetchLand(i) {
  const x0 = pf.site.parcels[i]; if (!x0 || x0.manual) return;   // 지번 미확정 토지는 브이월드 조회 안 함
  const addr = String(x0.address || '').trim();
  if (!addr) return;
  const d0 = dupParcel(i, addr, null);
  if (d0 >= 0) return dropDupParcel(i, d0, addr);
  landState[i] = '조회 중…'; renderParcels();
  try {
    const L = await api('GET', `/api/v4/land?address=${encodeURIComponent(addr)}`);
    const x = pf.site.parcels[i]; if (!x) return;
    const d1 = dupParcel(i, L.refined_address, L.pnu);   // '관양동 1591'과 전체 주소처럼 다르게 쓴 같은 필지
    if (d1 >= 0) return dropDupParcel(i, d1, L.refined_address || addr);
    if (L.area_sqm) x.area_sqm = L.area_sqm;
    if (L.jimok) x.jimok = L.jimok;
    if (L.zone && ZONE_LIST.includes(L.zone)) x.zone = L.zone;
    x.price_per_sqm = L.price_per_sqm; x.pnu = L.pnu;
    if (L.refined_address) x.address = L.refined_address;   // 시·도까지 포함된 정식 지번 주소
    x.uses = L.uses || [];
    x.auto = { address: x.address, area_sqm: x.area_sqm, zone: x.zone, jimok: x.jimok, price_per_sqm: x.price_per_sqm };
    applyLandUse();
    landState[i] = `✓ 자동 입력 (${L.year || ''}년 · 공시지가 ${L.price_per_sqm ? fmt(L.price_per_sqm) + '원/㎡' : '–'})`;
    renderParcels(); applyParcels();
    notice(`${i + 1}번 필지 자동 입력: 면적 ${fmt(L.area_sqm, 1)}㎡ · ${L.jimok || '지목 미상'} · ${L.zone || '용도지역 미상'}${L.price_per_sqm ? ' · 공시지가 ' + fmt(L.price_per_sqm) + '원/㎡' : ''} (${L.year || ''}년 기준)`);
  } catch (err) {
    const noKey = /인증키/.test(err.message);
    landState[i] = noKey ? '⚠ API 인증키 필요 (설정)' : '⚠ ' + err.message.replace(/^.*?: /, '').slice(0, 60);
    renderParcels();
    notice(noKey ? `${i + 1}번 필지 주소는 입력됐습니다. 면적 자동 입력은 브이월드 API 인증키가 필요합니다 → 설정 화면에서 등록` : `${i + 1}번 필지 면적 자동 조회 실패: ${err.message} — 직접 입력하세요.`, true);
  }
}
async function loadApiSettings() {
  try {
    const s = await api('GET', '/api/v4/settings');
    $('vwState').textContent = s.vworld_key_set ? `✓ 등록됨 (${s.vworld_key_masked})` : '미등록 — 면적 자동 입력을 쓰려면 등록하세요';
    $('vwState').style.color = s.vworld_key_set ? 'var(--pos)' : 'var(--caution)';
    $('vwDomain').value = s.vworld_domain || '';
  } catch { /* 무시 */ }
}
$('vwSave').onclick = async () => {
  try {
    await api('PUT', '/api/v4/settings', { vworld_key: $('vwKey').value.trim() || null, vworld_domain: $('vwDomain').value.trim() || null });
    $('vwKey').value = ''; await loadApiSettings(); notice('API 설정을 저장했습니다.');
  } catch (err) { notice(err.message, true); }
};

/* ── 여러 필지 ── */
const isAuto = (x, k) => !!x.auto && x.auto[k] != null && x.auto[k] !== '' && String(x.auto[k]) === String(x[k] ?? '');
function renderParcels() {
  const ps = pf.site.parcels;
  const A = (x, k) => isAuto(x, k) ? ' auto-val" title="주소 조회로 자동 입력된 값 — 직접 고치면 일반 표시로 바뀝니다' : '';
  $('parcelTable').tBodies[0].innerHTML = ps.map((x, i) => `<tr>
    <td class="c muted">${i + 1}</td>
    <td><div style="display:flex;gap:6px"><input class="${A(x, 'address')}" data-pl="${i}" data-k="address" value="${esc(x.address)}" placeholder="🔍 검색 또는 직접 입력" style="flex:1"><button type="button" class="btn secondary" data-addr-parcel="${i}" title="주소 검색">🔍</button>${mapLinks(x.address)}</div></td>
    <td><input class="money-in${A(x, 'area_sqm')}" data-pl="${i}" data-k="area_sqm" value="${x.area_sqm ? moneyVal(x.area_sqm) : ''}" placeholder="0" style="text-align:right"></td>
    <td><select class="${A(x, 'zone')}" data-pl="${i}" data-k="zone"><option value="">용도지역</option>${ZONE_LIST.map(z => `<option ${z === x.zone ? 'selected' : ''}>${z}</option>`).join('')}</select></td>
    <td><input class="${A(x, 'jimok')}" data-pl="${i}" data-k="jimok" value="${esc(x.jimok || '')}" placeholder="대"></td>
    <td><input class="money-in${A(x, 'price_per_sqm')}" data-pl="${i}" data-k="price_per_sqm" value="${x.price_per_sqm ? fmt(x.price_per_sqm) : ''}" placeholder="자동" style="text-align:right"></td>
    <td class="r money" data-plv="${i}">${x.price_per_sqm && x.area_sqm ? krw(x.price_per_sqm * x.area_sqm) : '–'}</td>
    <td><button class="del" data-del-pl="${i}" title="삭제">✕</button></td>
    <td style="white-space:nowrap"><button type="button" class="btn ghost" data-land="${i}" title="이 필지 다시 조회" style="padding:4px 9px">↻ 조회</button>
      <span style="font-size:13px;margin-left:6px;color:${(landState[i] || '').startsWith('✓') ? 'var(--pos)' : (landState[i] || '').startsWith('⚠') ? 'var(--caution)' : 'var(--muted)'}">${esc(landState[i] || '')}</span></td></tr>`).join('')
    || `<tr><td colspan="9" class="c muted" style="padding:12px">단일 필지면 비워 두세요. 여러 필지면 <b>+ 필지 추가</b>로 입력하면 대지면적·용도지역이 자동 합산됩니다.</td></tr>`;
  parcelSummary();
}
function parcelSummary() {
  const ps = pf.site.parcels, tot = ps.reduce((a, x) => a + Number(x.area_sqm || 0), 0);
  const priced = ps.filter(x => Number(x.price_per_sqm) > 0 && Number(x.area_sqm) > 0);
  const ptot = priced.reduce((a, x) => a + Number(x.price_per_sqm) * Number(x.area_sqm), 0), parea = priced.reduce((a, x) => a + Number(x.area_sqm), 0);
  $('parcelTable').tFoot.innerHTML = ps.length ? `<tr class="total"><td></td><td>합계 ${ps.length}필지</td><td class="r">${fmt(tot, 2)}</td><td class="muted">${fmt(PY(tot), 1)}평</td><td></td>
    <td class="r muted" style="font-size:13px">${parea ? '평균 ' + fmt(ptot / parea) + '원/㎡' : ''}</td><td class="r money">${ptot ? krw(ptot) : '–'}</td><td colspan="2" class="muted" style="font-size:13px">${parea ? '평당 ' + fmt(ptot / PY(parea)) + '원' : ''}</td></tr>` : '';
  const warn = [];
  const munis = [...new Set(ps.map(x => { const r = parseAddress(x.address); return r ? `${r.province} ${r.municipality}`.trim() : null; }).filter(Boolean))];
  if (munis.length > 1) warn.push(`필지가 서로 다른 시·군·구(${munis.join(', ')})에 걸쳐 있습니다. 조례가 다르므로 첫 필지 기준으로 적용됩니다 — 시·군·구별로 별도 검토하세요.`);
  const noZone = ps.filter(x => Number(x.area_sqm) > 0 && !x.zone).length;
  if (noZone) warn.push(`용도지역이 비어 있는 필지 ${noZone}개 — 용도지역별 면적 합산에서 빠집니다.`);
  const special = ps.filter(x => /도로|구거|하천|유지|공원/.test(x.jimok || ''));
  if (special.length) warn.push(`지목 ${[...new Set(special.map(x => x.jimok))].join('·')} 필지 ${fmt(special.reduce((a, x) => a + Number(x.area_sqm || 0), 0), 1)}㎡ — 매입·대지 산입 가능 여부를 확인하세요.`);
  $('parcelNotes').innerHTML = warn.length ? `<div class="alert warn" style="margin:8px 0 0"><ul style="margin:0">${warn.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : '';
}
/* 필지 합계 → 대지면적·용도지역별 면적·대표 주소 (필지가 있을 때만) */
function applyParcels(recalc = true) {
  const ps = pf.site.parcels.filter(x => x.address || Number(x.area_sqm) > 0);
  parcelSummary();
  if (!ps.length) return;
  const tot = ps.reduce((a, x) => a + Number(x.area_sqm || 0), 0);
  if (tot > 0) { pf.land_area_sqm = Math.round(tot * 100) / 100; $('p_land_area_sqm').value = moneyVal(pf.land_area_sqm); }
  const byZone = {};
  ps.forEach(x => { if (x.zone && Number(x.area_sqm) > 0) byZone[x.zone] = (byZone[x.zone] || 0) + Number(x.area_sqm); });
  pf.site.zones = Object.entries(byZone).map(([zone, a]) => ({ zone, area_sqm: Math.round(a * 100) / 100 }));   // 필지 목록이 유일한 기준
  const first = ps.find(x => x.address)?.address || '';
  const addr = first ? first + (ps.length > 1 ? ` 외 ${ps.length - 1}필지` : '') : pf.site.address;
  const prevMuni = `${pf.site.province}|${pf.site.municipality}`;
  if (addr !== pf.site.address) { pf.site.address = addr; $('s_address').value = addr || ''; }
  const r = parseAddress(first);
  if (r) { pf.site.province = r.province; pf.site.municipality = r.municipality; $('s_province').value = r.province; fillMuni('s_province', 's_municipality', r.municipality); }
  refreshHints(); updateFar(); renderZones();
  if (r && `${r.province}|${r.municipality}` !== prevMuni) loadOrdinance(true);
  else autoApplyFar(false);
  if (recalc) pfRecalc();
}
$('addParcel').onclick = () => {
  if (pf.site.parcels.some(x => !String(x.address || '').trim() && !(Number(x.area_sqm) > 0))) { notice('비어 있는 필지 행에 먼저 주소를 입력하세요.', true); return; }
  pf.site.parcels.push({ address: '', area_sqm: 0, zone: pf.site.zones[0]?.zone || '', jimok: '대' }); renderParcels();
};
$('view-proforma').addEventListener('click', e => {
  const d = e.target.closest('[data-del-pl]'); if (d) { pf.site.parcels.splice(d.dataset.delPl, 1); Object.keys(landState).forEach(k => delete landState[k]); renderParcels(); applyParcels(); }
  const lb = e.target.closest('[data-land]'); if (lb) fetchLand(Number(lb.dataset.land));
  const s = e.target.closest('[data-addr-parcel]');
  if (s) {
    const i = Number(s.dataset.addrParcel);
    openAddressSearch(addr => { pf.site.parcels[i].address = addr; renderParcels(); applyParcels(); fetchLand(i); }, pf.site.parcels[i].address);
  }
});

/* 주소 → 시·도 / 시·군·구 → 조례 자동 불러오기·적용 */
const PROV_ALIAS = { 서울: '서울특별시', 부산: '부산광역시', 대구: '대구광역시', 인천: '인천광역시', 광주: '광주광역시', 대전: '대전광역시', 울산: '울산광역시',
  세종: '세종특별자치시', 경기: '경기도', 강원: '강원특별자치도', 강원도: '강원특별자치도', 충북: '충청북도', 충남: '충청남도', 전북: '전북특별자치도', 전라북도: '전북특별자치도',
  전남: '전라남도', 경북: '경상북도', 경남: '경상남도', 제주: '제주특별자치도', 제주도: '제주특별자치도' };
function parseAddress(a) {
  const t = (a || '').replace(/[,()]/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (!t.length) return null;
  const prov = PROVINCES.includes(t[0]) ? t[0] : PROV_ALIAS[t[0]] || PROV_ALIAS[t[0].replace(/(특별시|광역시|특별자치시|특별자치도|도)$/, '')];
  if (!prov) return null;
  let muni = '';
  if (prov.endsWith('특별시') || prov.endsWith('광역시')) muni = /(구|군)$/.test(t[1] || '') ? t[1] : '';
  else if (prov === '세종특별자치시') muni = '';
  else muni = /(시|군)$/.test(t[1] || '') ? t[1] : '';
  return { province: prov, municipality: muni };
}
async function applyAddress() {
  const a = pf.site.address || '', r = parseAddress(a);
  if (!a.trim()) { $('addrHint').textContent = ''; return; }
  if (!r) { $('addrHint').textContent = '⚠ 시·도를 인식하지 못했습니다. "서울특별시 서초구 …"처럼 시·도부터 입력하세요.'; return; }
  const changed = r.province !== pf.site.province || r.municipality !== (pf.site.municipality || '');
  pf.site.province = r.province; pf.site.municipality = r.municipality;
  $('s_province').value = r.province; fillMuni('s_province', 's_municipality', r.municipality);
  $('addrHint').textContent = `인식: ${r.province} ${r.municipality}`.trim() + ' → 해당 지역 조례 적용';
  if (changed || !ordCache?.ordinance) await loadOrdinance(true);
  if (!pf.site.zones.length) notice('조례를 불러왔습니다. 용도지역을 추가하면 허용 연면적이 자동으로 대입됩니다.');
}

/* 조례 허용 연면적 자동 대입: Σ 용도지역 면적 × (조례 용적률 + 인센티브). 조례값이 확인된 경우에만 (시행령 임시값은 대입 안 함) */
function autoApplyFar(announce) {
  if (!pf || !pf.site.auto_far || !pf.site.zones.length) return false;
  if (pf.site.plan.kind !== 'none') return false;   // 3차 도시계획은 서버 계산 후 applyPlanGfa() 에서 대입
  const residential = pf.units.some(u => u.kind === 'apartment');
  let gfa = 0;
  for (const z of pf.site.zones) {
    const lim = zoneLimit(z.zone);
    if (!['ordinance', 'auto', 'registered'].includes(lim.level) || lim.far == null) return false;
    const far = residential && lim.apt != null ? lim.apt : lim.far;
    gfa += Number(z.area_sqm || 0) * (far + Number(pf.site.incentive_far_pct || 0)) / 100;
  }
  gfa = Math.floor(gfa * 100) / 100;
  if (!gfa || Math.abs(gfa - Number(pf.above_gfa_sqm)) < 0.01) return false;
  pf.above_gfa_sqm = gfa; $('p_above_gfa_sqm').value = moneyVal(gfa);
  refreshHints(); updateFar(); pfRecalc();
  if (announce !== false) notice(`조례 허용 연면적 ${fmt(gfa, 1)}㎡를 지상 연면적에 대입했습니다.`);
  return true;
}
function updateMode() {
  const redev = pf.project_mode === 'redevelopment', rent = pf.project_mode === 'rental';
  $('redevCard').classList.toggle('hidden', !redev);
  $('rentalCard').classList.toggle('hidden', !rent);
  $('saleCondCard').classList.toggle('hidden', rent);
  $('unitTable').classList.toggle('rental-mode', rent);
  if ($('rtDep')) $('rtDep').textContent = pf.rental?.depreciation_years ?? 40;
  document.querySelector('#pfTabs [data-tab="units"]').lastChild.textContent = rent ? '임대 계획' : '분양 계획';
  document.querySelector('#pfTabs [data-tab="sens"]').classList.toggle('hidden', rent);
  document.querySelector('#pfTabs [data-tab="cf"]').classList.toggle('hidden', rent);
}
function renderCases() {
  const rc = lastPf?.redevelopment?.cases || [];
  $('caseTable').tBodies[0].innerHTML = pf.prior_assets.cases.map((c, i) => `<tr>
    <td><input data-pc="${i}" data-k="name" value="${esc(c.name)}"></td>
    <td><input class="money-in" style="width:80px" data-pc="${i}" data-k="share_py" value="${moneyVal(c.share_py)}"></td>
    <td><input class="money-in" data-pc="${i}" data-k="appraisal" value="${c.appraisal == null ? '' : fmt(c.appraisal)}" placeholder="지분×평당가"></td>
    <td><input class="money-in" data-pc="${i}" data-k="apply_price" value="${fmt(c.apply_price || 0)}"></td>
    <td class="r money">${rc[i]?.right_value != null ? krw(rc[i].right_value) : '–'}</td>
    <td class="r">${rc[i] ? (rc[i].contribution != null ? `<b class="${rc[i].contribution < 0 ? 'money' : 'minus'}">${rc[i].contribution < 0 ? '환급 ' + krw(-rc[i].contribution) : '분담 ' + krw(rc[i].contribution)}</b>` : rc[i].settlement != null ? `<span class="chip gray">현금청산 ${krw(-rc[i].settlement)}</span>` : '–') : '–'}</td>
    <td><button class="del" data-del-pc="${i}">✕</button></td></tr>`).join('') || `<tr><td colspan="7" class="c muted">조합원 사례를 추가하세요.</td></tr>`;
}
$('addZone').onclick = () => { pf.site.zones.push({ zone: '제2종일반주거지역', area_sqm: pf.site.zones.length ? 0 : pf.land_area_sqm }); renderZones(); pfRecalc(); };
$('addCase').onclick = () => { pf.prior_assets.cases.push({ name: '조합원 ' + (pf.prior_assets.cases.length + 1), share_py: 20, appraisal: null, apply_price: 0 }); renderCases(); pfRecalc(); };
$('view-proforma').addEventListener('click', e => {
  const t = e.target;
  if (t.dataset.delZ !== undefined) { pf.site.zones.splice(t.dataset.delZ, 1); renderZones(); pfRecalc(); }
  if (t.dataset.delPc !== undefined) { pf.prior_assets.cases.splice(t.dataset.delPc, 1); renderCases(); pfRecalc(); }
});

/* — 판정 · 정비사업 결과 — */
const ST = { ok: ['적합', 'ok'], warn: ['주의', 'warn'], bad: ['부적합', 'bad'] };
function renderVerdict() {
  const v = lastPf.verdict;
  const tone = { ok: 'ok', warn: 'warn', bad: 'bad' }[v.overall];
  const rs = v.reasons || [], bad = rs.filter(x => x.status === 'bad'), warn = rs.filter(x => x.status === 'warn');
  const reasonBox = bad.length || warn.length ? `<div class="verdict-why ${bad.length ? 'bad' : 'warn'}"><b>${bad.length ? `부적합 사유 ${bad.length}건` : '확인 필요 사항'}</b>
    <ol>${(bad.length ? bad : warn).map(x => `<li><span class="chip gray" style="margin-right:6px">${x.area}</span>${esc(x.text)}</li>`).join('')}</ol>
    ${bad.length && warn.length ? `<div class="muted" style="font-size:13px">그 밖에 확인 필요 ${warn.length}건은 아래 표의 「주의」 항목을 보세요.</div>` : ''}</div>` : '';
  $('verdictCard').innerHTML = `<div class="card-head"><h2>사업타당성 · 적합성 판정</h2><span class="chip ${tone}" style="font-size:15px;padding:6px 14px">${esc(v.label)}</span></div>${reasonBox}
    <div class="grid2">
      <div><h3 style="margin-top:0">사업성</h3><table><thead><tr><th>항목</th><th class="r">결과</th><th>기준</th><th class="c">판정</th></tr></thead><tbody>
        ${v.financial.map(x => `<tr><td>${esc(x.name)}</td><td class="r"><b>${esc(x.display)}</b></td><td class="muted" style="font-size:13.5px">${esc(x.rule)}</td><td class="c"><span class="chip ${ST[x.status][1]}">${ST[x.status][0]}</span></td></tr>`).join('')}</tbody></table></div>
      <div><h3 style="margin-top:0">법규 적합성</h3><table><thead><tr><th>항목</th><th>내용</th><th class="c">판정</th></tr></thead><tbody>
        ${v.legal.map(x => `<tr><td style="white-space:nowrap">${esc(x.name)}</td><td style="font-size:13.5px">${esc(x.detail)}</td><td class="c"><span class="chip ${ST[x.status][1]}">${ST[x.status][0]}</span></td></tr>`).join('')}</tbody></table></div>
    </div><p class="muted" style="font-size:13px;margin:12px 0 0">${esc(v.note)}</p>`;
  const rd = lastPf.redevelopment;
  $('redevResult').innerHTML = rd ? `<div class="card"><h2>정비사업 지표 <span class="sub">${esc(rd.note)}</span></h2><div class="stats" style="margin:0">
    <div class="stat hl"><small>비례율</small><strong>${pct(rd.proportional_rate_pct)}</strong><em>(총수입 − 총지출) ÷ 종전자산</em></div>
    <div class="stat"><small>종전자산 총액</small><strong>${krwW(rd.prior_assets_total)}</strong><em>${fmt(rd.land_py, 1)}평</em></div>
    <div class="stat"><small>평당 권리가치 (청산단가)</small><strong>${krwW(rd.value_per_py)}</strong><em>사업이익 ÷ 종전 토지면적</em></div>
    <div class="stat"><small>평균 권리가액</small><strong>${krwW(rd.avg_right_value)}</strong><em>평균 지분 ${fmt(rd.avg_share_py, 1)}평</em></div>
    <div class="stat"><small>조합원 / 일반 분양대금</small><strong class="ink">${krw(rd.member_sales)} / ${krw(rd.general_sales)}</strong></div></div></div>` : '';
}

/* — 월별 현금흐름 결과 (5번 탭) — */
let cfView = 'summary';
function renderCfPf() {
  const cf = lastPf.cashflow, out = $('cfOutPf');
  if (!cf) { out.innerHTML = `<div class="card"><div class="empty"><span class="ico">🗓</span>위의 <b>월별 현금흐름으로 정밀 계산</b>을 켜면 공정률·분양대금 일정에 따른 월별 자금흐름, 실제 대출잔액 기준 금융비용, 부가세·법인세 납부 일정을 계산합니다.</div></div>`; return; }
  const rows = cf.rows, u = 1e8;
  const loans = cf.loans.map(l => `<tr><td><b>${esc(l.name)}</b></td><td class="r">${krw(l.limit)}</td><td class="r">${krw(l.drawn)}</td><td class="r">${l.utilization != null ? pct(l.utilization * 100, 0) : '–'}</td><td class="r">${krw(l.peak)}</td><td class="r money">${krw(l.interest)}</td><td class="r">${krw(l.fees)}</td><td style="padding-left:120px">${l.start} ~ ${l.end}</td></tr>`).join('');
  const taxes = cf.tax_years.map(t => `<tr><td><b>${t.year}</b></td><td class="r">${pct(t.progress * 100)}</td><td class="r">${pct(t.contracted * 100)}</td><td class="r">${krw(t.revenue_recognized)}</td><td class="r">${krw(t.cost_recognized)}</td><td class="r">${krw(t.period_cost + t.finance_cost)}</td><td class="r ${t.income < 0 ? 'minus' : ''}">${krw(t.income)}</td><td class="r">${t.nol_used ? krw(t.nol_used) : '–'}</td><td class="r money">${t.corporate_tax ? krw(t.corporate_tax + t.local_tax) : '–'}</td><td>${t.corporate_tax ? t.pay_month : ''}</td></tr>`).join('');
  const cols = [['month', '연월'], ['phase', '단계'], ['progress_cum', '누적 공정률'], ['deposit', '계약금'], ['midpay', '중도금'], ['balance_pay', '잔금'],
    ['cost_land', '토지비'], ['cost_construction', '공사비'], ['cost_other', '기타 사업비'], ['vat_net', '부가세(순)'], ['taxes', '법인세 등'], ['finance', '금융비용'],
    ['equity', '자기자본'], ['draw', '대출 인출'], ['repay', '대출 상환'], ['loan_balance', '대출 잔액'], ['cash', '월말 현금']];
  const val = (r, k) => k === 'cost_other' ? r.cost_indirect + r.cost_charges + r.cost_sales + r.cost_taxes + r.cost_admin + r.cost_contingency
    : k === 'vat_net' ? r.vat_input + r.vat_paid : k === 'taxes' ? r.corporate_tax + r.local_tax : k === 'finance' ? r.interest + r.fees + r.midpay_interest
    : k === 'equity' ? r.equity_in + r.extra_equity : r[k];
  out.innerHTML = `<div class="stats">
      <div class="stat hl"><small>금융비용 합계 (실제 잔액 기준)</small><strong>${krwW(cf.finance_total)}</strong><em>이자 ${krw(cf.interest_total)} · 수수료 ${krw(cf.fee_total)} · 중도금이자 ${krw(cf.midpay_interest_total)}</em></div>
      <div class="stat"><small>최대 대출잔액</small><strong>${krwW(cf.peak_loan)}</strong><em>최저 월말현금 ${krw(cf.min_cash)}</em></div>
      <div class="stat"><small>Equity IRR (세후, 연)</small><strong>${pct(cf.equity_irr_annual)}</strong><em>Multiple ${cf.equity_multiple != null ? fmt(cf.equity_multiple, 2) + '배' : '–'}</em></div>
      <div class="stat"><small>사업 IRR (무차입, 세후)</small><strong>${pct(cf.project_irr_annual)}</strong><em>NPV ${krw(cf.equity_npv)}</em></div>
      <div class="stat"><small>추가 자기자본 필요</small><strong class="${cf.extra_equity > 0 ? 'neg' : 'pos'}">${cf.extra_equity > 0 ? krwW(cf.extra_equity) : '없음'}</strong><em>준공 ${cf.completion_month} · 입주 ${cf.move_in_month}</em></div>
    </div>
    <div class="card"><h2>월별 자금흐름 <span class="sub">막대: 월말 현금 · 선: 대출 잔액 · 점선: 누적 공정률</span></h2>${cfPfChart(rows)}</div>
      <div class="card"><h2>대출별 금융비용</h2><div class="tablewrap"><table><thead><tr><th>대출</th><th class="r">한도</th><th class="r">인출</th><th class="r">인출률</th><th class="r">최대잔액</th><th class="r">이자</th><th class="r">수수료</th><th style="padding-left:120px">기간</th></tr></thead><tbody>${loans}
        <tr><td>중도금 대출이자</td><td colspan="4" class="muted" style="font-size:13px">회차: ${cf.installment_months.join(', ') || '없음'}</td><td class="r money">${krw(cf.midpay_interest_total)}</td><td colspan="2"></td></tr></tbody></table></div></div>
      <div class="card"><h2>법인세 (진행기준) <span class="sub">법인세법 시행령 제69조</span></h2><div class="tablewrap"><table><thead><tr><th>연도</th><th class="r">진행률</th><th class="r">계약률</th><th class="r">익금</th><th class="r">원가 손금</th><th class="r">판관·금융</th><th class="r">소득</th><th class="r">결손공제</th><th class="r">세액(지방 포함)</th><th>납부</th></tr></thead><tbody>${taxes || '<tr><td colspan="10" class="c muted">법인세 진행기준 미사용</td></tr>'}</tbody></table></div>
        <p class="muted" style="font-size:13px;margin:8px 0 0">부가세 순납부 ${krw(cf.vat_net_total)} (분기 신고 정산) ${cf.unused_nol ? '· 미사용 결손금 ' + krw(cf.unused_nol) : ''}</p></div>
    <div class="card"><div class="card-head"><h2>월별 현금흐름표 <span class="sub">단위: 백만원</span></h2><button class="btn" id="cfPfCsv">📊 Excel 다운로드</button></div>
      <div class="tablewrap" style="max-height:520px"><table><thead><tr>${cols.map((c, i) => `<th class="${i > 1 ? 'r' : ''}">${c[1]}</th>`).join('')}</tr></thead><tbody>
      ${rows.map(r => `<tr class="${r.extra_equity > 0 ? 'gap' : ''}">${cols.map(([k], i) => i === 0 ? `<td><b>${r.month}</b></td>` : i === 1 ? `<td><span class="chip gray">${r.phase}</span></td>` : k === 'progress_cum' ? `<td class="r">${pct(r.progress_cum * 100, 0)}</td>` : (() => { const v = val(r, k); return `<td class="r ${v < 0 ? 'minus' : ''}">${v ? fmt(v / 1e6, 0) : '<span class="muted">–</span>'}</td>`; })()).join('')}</tr>`).join('')}
      </tbody></table></div></div>`;
}
function cfPfChart(rows) {
  const W = 1000, H = 250, P = { l: 56, r: 40, t: 12, b: 26 }, iw = W - P.l - P.r, ih = H - P.t - P.b, n = rows.length;
  const vals = rows.flatMap(r => [r.cash, r.loan_balance, 0]), max = Math.max(...vals), min = Math.min(...vals), span = (max - min) || 1;
  const y = v => P.t + ih - (v - min) / span * ih, bw = iw / n, x = i => P.l + bw * i + bw / 2, yp = p => P.t + ih - p * ih;
  let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img" aria-label="월별 현금·대출잔액·공정률">`;
  [0, 1, 2, 3, 4].map(i => min + span * i / 4).forEach(t => s += `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" stroke="#e6edf1"/><text x="${P.l - 6}" y="${y(t) + 4}" text-anchor="end" font-size="9" fill="#627887">${fmt(t / 1e8, 0)}억</text>`);
  s += `<text x="${W - P.r + 4}" y="${yp(1) + 4}" font-size="9" fill="#627887">100%</text>`;
  rows.forEach((r, i) => { const v = r.cash, w = Math.max(2, bw * .62); s += `<rect x="${x(i) - w / 2}" y="${Math.min(y(v), y(0))}" width="${w}" height="${Math.max(1, Math.abs(y(v) - y(0)))}" fill="${v < 0 ? '#b3261e' : '#7cc0f0'}"><title>${r.month} 월말 현금 ${krwW(v)}</title></rect>`; if (i % 6 === 0) s += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="9" fill="#627887">${r.month}</text>`; });
  s += `<polyline fill="none" stroke="#111a2e" stroke-width="2.2" points="${rows.map((r, i) => x(i) + ',' + y(r.loan_balance)).join(' ')}"/>`;
  s += `<polyline fill="none" stroke="#2f9e44" stroke-width="2" stroke-dasharray="5 4" points="${rows.map((r, i) => x(i) + ',' + yp(r.progress_cum)).join(' ')}"/>`;
  return `<div class="legend" style="margin-bottom:6px"><span><i style="background:#7cc0f0"></i>월말 현금</span><span><i style="background:#111a2e"></i>대출 잔액</span><span><i style="background:#2f9e44"></i>누적 공정률</span></div>` + s + '</svg>';
}
/* 월별 현금흐름 CSV: 현금흐름표 형식 (유입·유출·순현금흐름·월말 현금이 정확히 맞도록), 단위 원 */
const CF_IN = [['deposit', '계약금'], ['midpay', '중도금'], ['balance_pay', '잔금'], ['other_income', '기타 수입'], ['midpay_recovery', '중도금이자 회수'],
  ['equity_in', '자기자본 투입'], ['extra_equity', '추가 자기자본'], ['draw', '대출 인출']];
const CF_OUT = [['cost_land', '토지비'], ['cost_construction', '공사비'], ['cost_indirect', '설계·감리·용역비'], ['cost_charges', '부담금·인입비'],
  ['cost_sales', '분양·판매비'], ['cost_taxes', '제세공과금'], ['cost_admin', '일반관리비'], ['cost_contingency', '예비비'], ['vat_input', '매입세액'],
  ['vat_paid', '부가세 납부(−환급)'], ['corporate_tax', '법인세'], ['local_tax', '지방소득세'], ['midpay_interest', '중도금 대출이자'],
  ['interest', 'PF·브릿지 이자'], ['fees', '취급수수료'], ['repay', '대출 상환']];
function cfCsvText(rows) {
  const q = v => /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
  const n = v => Math.round(Number(v) || 0);
  const head = ['연월', '단계', '누적 공정률(%)', ...CF_IN.map(c => '[유입] ' + c[1]), '유입 합계', ...CF_OUT.map(c => '[유출] ' + c[1]), '유출 합계',
    '순현금흐름', '월말 현금', '대출 잔액', '(참고) 매출세액 발생'];
  const tot = {};
  let run = 0;   // 월말 현금 = 전월 + 유입 − 유출 (원 단위 반올림 값으로 누적 → 행마다 정확히 맞음)
  const body = rows.map(r => {
    const ins = CF_IN.map(([k]) => n(r[k])), outs = CF_OUT.map(([k]) => n(r[k]));
    const si = ins.reduce((a, b) => a + b, 0), so = outs.reduce((a, b) => a + b, 0);
    [...CF_IN, ...CF_OUT].forEach(([k]) => tot[k] = (tot[k] || 0) + n(r[k]));
    tot.in = (tot.in || 0) + si; tot.out = (tot.out || 0) + so; tot.vat_out = (tot.vat_out || 0) + n(r.vat_out);
    const [y, m] = r.month.split('-');
    run += si - so;
    return [`${y}년 ${m}월`, r.phase, (Number(r.progress_cum) * 100).toFixed(2), ...ins, si, ...outs, so, si - so, run, n(r.loan_balance), n(r.vat_out)];
  });
  const last = rows[rows.length - 1];
  const total = ['합계', '', '', ...CF_IN.map(([k]) => tot[k]), tot.in, ...CF_OUT.map(([k]) => tot[k]), tot.out, tot.in - tot.out, run, n(last.loan_balance), tot.vat_out];
  return '\ufeff' + ['단위: 원 · 월말 현금 = 전월 월말 현금 + 유입 합계 − 유출 합계 · 매출세액은 분기 신고 때 납부되므로 현금 유출이 아님 (부가세 납부 열에 반영)',
    head.map(q).join(','), ...body.map(r => r.map(q).join(',')), total.map(q).join(',')].join('\r\n');
}
document.addEventListener('click', async e => {
  if (e.target.id !== 'cfPfCsv' || !lastPf?.cashflow) return;
  const btn = e.target;
  await busy(btn, async () => {
    try {
      const r = await fetch('/api/v3/proforma/cashflow.xlsx', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pf) });
      if (!r.ok) throw new Error(errText(await r.json()));
      const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = `월별현금흐름_${pf.project_name || '사업'}_${today}.xlsx`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000); notice('월별 현금흐름 Excel을 내려받았습니다.');
    } catch (err) { notice(err.message, true); }
  });
});

/* — 사업수지분석표 Excel — */
$('pfExcel').onclick = e => busy(e.target, async () => {
  try {
    const r = await fetch('/api/v3/proforma/report.xlsx', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pf) });
    if (!r.ok) throw new Error(errText(await r.json()));
    const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = `사업수지분석표_${pf.project_name || '사업'}_${today}.xlsx`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000); notice('사업수지분석표(Excel)를 내려받았습니다.');
  } catch (err) { notice(err.message, true); }
});

/* ═════════════════════ 접속 비밀번호 · 로그인 상태 ═════════════════════ */
let me = { role: 'admin', local: true };
async function loadMe() {
  try {
    me = await api('GET', '/api/v4/auth/me');
    document.body.classList.toggle('role-staff', me.role === 'staff');
    if (me.multi) { loadMeMulti(); return; }
    $('meRole').textContent = me.role === 'staff' ? '직원' : '관리자';
    $('srvText').textContent = me.local ? '이 PC · 로컬 서버' : me.role === 'staff' ? '조회·입력 권한' : '원격 접속';
    $('logoutBtn').classList.toggle('hidden', me.local);
    $('pwState').innerHTML = me.admin_set
      ? `✓ 관리자 비밀번호 설정됨${me.staff_set ? ' · ✓ 직원 비밀번호 설정됨' : ' · 직원 비밀번호 없음 (직원도 관리자 비밀번호로만 접속)'} — 바꾸려면 새 비밀번호를 입력하고 저장`
      : '<b style="color:var(--caution)">⚠ 아직 비밀번호가 없습니다.</b> 비밀번호를 정하기 전에는 다른 PC에서 접속할 수 없습니다 (로그인 화면에서 막힘).';
    $('pwStaffClear').classList.toggle('hidden', !me.staff_set);
    $('pwClearAll').classList.toggle('hidden', !me.admin_set);
    $('lanUrls').innerHTML = me.lan_urls?.length ? `사무실 접속 주소: ${me.lan_urls.map(u => `<b>${esc(u)}</b>`).join(' · ')} (같은 사무실 네트워크에서만 · Windows 방화벽에서 8001 포트 허용 필요)` : '';
  } catch { /* 이전 서버 */ }
}
/* 클라우드(여러 업체): 업체 계정 · 운영자 관리 */
function loadMeMulti() {
  document.body.classList.add('multi');
  $('meRole').textContent = me.company_name || me.company;
  $('srvText').textContent = `${me.name || me.uid} · ${me.operator ? '운영자' : me.role === 'staff' ? '직원' : '관리자'}`;
  $('logoutBtn').classList.remove('hidden');
  $('pwCard').classList.add('hidden');
  $('myPwCard').classList.remove('hidden');
  $('myAcct').textContent = `아이디 ${me.uid} · ${me.company_name}`;
  $('vwCard').classList.toggle('hidden', !me.operator);
  $('acctCard').classList.toggle('hidden', !me.operator);
  if (me.operator) loadAccounts();
}
const roleName = r => ({ operator: '운영자', admin: '관리자', staff: '직원' })[r] || r;
function renderAccounts(d) {
  const sel = $('acUcomp'), keep = sel.value;
  sel.innerHTML = d.companies.map(c => `<option value="${esc(c.id)}">${esc(c.name)} (${esc(c.id)})</option>`).join('');
  if (keep) sel.value = keep;
  $('acList').innerHTML = `<table><thead><tr><th>업체</th><th>아이디</th><th>이름</th><th>역할</th><th></th></tr></thead><tbody>${
    d.companies.map(c => {
      const head = `<td rowspan="${Math.max(1, c.users.length)}"><b>${esc(c.name)}</b><div class="muted" style="font-size:12.5px">${esc(c.id)} · ${esc(c.created || '')}</div>${
        c.users.some(u => u.role === 'operator') ? '' : `<button class="btn ghost del-site" style="margin-top:6px" data-del-company="${esc(c.id)}">업체 삭제</button>`}</td>`;
      if (!c.users.length) return `<tr>${head}<td colspan="4" class="muted">계정 없음 — 위에서 아이디를 만드세요</td></tr>`;
      return c.users.map((u, i) => `<tr>${i ? '' : head}<td>${esc(u.uid)}</td><td>${esc(u.name)}</td><td>${roleName(u.role)}</td><td class="r">${
        u.role === 'operator' ? '' : `<button class="btn ghost" data-edit-user="${esc(u.uid)}" data-c="${esc(u.company)}" data-n="${esc(u.name)}" data-r="${u.role}">수정</button> <button class="btn ghost del-site" data-del-user="${esc(u.uid)}">삭제</button>`}</td></tr>`).join('');
    }).join('')}</tbody></table>`;
  $('acList').querySelectorAll('[data-del-company]').forEach(b => b.onclick = async () => {
    if (!await confirmBox('업체를 삭제할까요?', `<b>${esc(b.dataset.delCompany)}</b> 업체와 그 계정을 모두 지웁니다. 로그인한 사람은 바로 끊깁니다. (사업지 자료는 보관소에 남습니다)`, '삭제')) return;
    try { renderAccounts(await api('DELETE', `/api/v4/accounts/companies/${encodeURIComponent(b.dataset.delCompany)}`)); notice('업체를 삭제했습니다.'); }
    catch (err) { notice(err.message, true); }
  });
  $('acList').querySelectorAll('[data-del-user]').forEach(b => b.onclick = async () => {
    if (!await confirmBox('계정을 삭제할까요?', `<b>${esc(b.dataset.delUser)}</b> 계정을 지웁니다. 로그인 중이면 바로 끊깁니다.`, '삭제')) return;
    try { renderAccounts(await api('DELETE', `/api/v4/accounts/users/${encodeURIComponent(b.dataset.delUser)}`)); notice('계정을 삭제했습니다.'); }
    catch (err) { notice(err.message, true); }
  });
  $('acList').querySelectorAll('[data-edit-user]').forEach(b => b.onclick = () => {
    $('acUcomp').value = b.dataset.c; $('acUid').value = b.dataset.editUser; $('acUname').value = b.dataset.n; $('acUrole').value = b.dataset.r;
    $('acUpw').value = ''; $('acUpw').focus(); notice('비밀번호를 비워 두면 기존 비밀번호가 유지됩니다.');
  });
}
async function loadAccounts() {
  try { renderAccounts(await api('GET', '/api/v4/accounts')); } catch (err) { notice(err.message, true); }
}
$('acAddCompany').onclick = async () => {
  try {
    renderAccounts(await api('POST', '/api/v4/accounts/companies', { id: $('acCid').value.trim(), name: $('acCname').value.trim() }));
    $('acUcomp').value = $('acCid').value.trim().toLowerCase(); $('acCid').value = ''; $('acCname').value = '';
    notice('업체를 추가했습니다. 아래에서 아이디를 만드세요.'); $('acUid').focus();
  } catch (err) { notice(err.message, true); }
};
$('acGenPw').onclick = () => {
  const abc = 'abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789', b = crypto.getRandomValues(new Uint32Array(10));
  $('acUpw').value = Array.from(b, x => abc[x % abc.length]).join('');
};
$('acSaveUser').onclick = async () => {
  const pw = $('acUpw').value.trim(), uid = $('acUid').value.trim().toLowerCase();
  try {
    renderAccounts(await api('PUT', '/api/v4/accounts/users', { uid, company: $('acUcomp').value, role: $('acUrole').value, name: $('acUname').value.trim(), password: pw || null }));
    notice('계정을 저장했습니다.');
    if (pw) {
      const c = $('acUcomp').selectedOptions[0]?.textContent || '';
      $('acIssued').innerHTML = `<b>업체에 전달할 접속 정보</b> (이 창을 벗어나면 비밀번호는 다시 볼 수 없습니다)<br>${esc(c)}<br>접속 주소: <b>${esc(location.origin)}</b><br>아이디: <b>${esc(uid)}</b> · 비밀번호: <b>${esc(pw)}</b>`;
      $('acIssued').classList.remove('hidden');
    }
    $('acUid').value = ''; $('acUname').value = ''; $('acUpw').value = '';
  } catch (err) { notice(err.message, true); }
};
$('myPwSave').onclick = async () => {
  try {
    await api('POST', '/api/v4/auth/my-password', { current: $('myPwCur').value, new: $('myPwNew').value });
    $('myPwCur').value = ''; $('myPwNew').value = ''; notice('비밀번호를 바꿨습니다.');
  } catch (err) { notice(err.message, true); }
};
$('logoutBtn').onclick = async () => { await api('POST', '/api/v4/auth/logout'); location.href = '/login'; };
$('pwSave').onclick = async () => {
  const admin = $('pwAdmin').value, staff = $('pwStaff').value;
  if (!admin && !staff) { notice('바꿀 비밀번호를 입력하세요.', true); return; }
  if (admin && admin.length < 4 || staff && staff.length < 4) { notice('비밀번호는 4자 이상으로 정하세요.', true); return; }
  if (admin && staff && admin === staff) { notice('관리자와 직원 비밀번호는 서로 달라야 합니다.', true); return; }
  try {
    await api('POST', '/api/v4/auth/passwords', { admin: admin || null, staff: staff || null });
    $('pwAdmin').value = ''; $('pwStaff').value = '';
    notice('접속 비밀번호를 저장했습니다.'); loadMe();
  } catch (err) { notice(err.message, true); }
};
$('pwClearAll').onclick = async () => {
  if (!await confirmBox('비밀번호를 해제할까요?', '관리자·직원 비밀번호를 모두 지웁니다. 다른 PC에서 로그인한 사람은 바로 접속이 끊기고, <b>비밀번호를 다시 정하기 전까지 다른 PC에서는 접속할 수 없습니다.</b> (이 PC는 계속 사용 가능)', '해제')) return;
  try { await api('POST', '/api/v4/auth/passwords', { clear_all: true }); notice('비밀번호를 해제했습니다.'); loadMe(); }
  catch (err) { notice(err.message, true); }
};
$('pwStaffClear').onclick = async () => {
  if (!await confirmBox('직원 비밀번호를 해제할까요?', '직원 비밀번호로 로그인한 사람은 바로 접속이 끊기고, 이후에는 관리자 비밀번호로만 접속할 수 있습니다.', '해제')) return;
  try { await api('POST', '/api/v4/auth/passwords', { clear_staff: true }); notice('직원 비밀번호를 해제했습니다.'); loadMe(); }
  catch (err) { notice(err.message, true); }
};

/* ═════════════════════ 시나리오 · 스트레스 테스트 ═════════════════════ */
const scnDefault = (p, tag = '') => `${today} ${tag || `분양률${Number(p.sales_rate_pct)}% 분양가${Number(p.price_adjust_pct) >= 0 ? '+' : ''}${Number(p.price_adjust_pct)}%`}`;
function scnForm(name, memo, hint) {
  return new Promise(res => {
    $('scnName').value = name; $('scnMemo').value = memo || ''; $('scnHint').textContent = hint || '';
    $('scnBack').classList.remove('hidden'); setTimeout(() => { $('scnName').focus(); $('scnName').select(); }, 30);
    const done = v => { $('scnBack').classList.add('hidden'); document.removeEventListener('keydown', key); res(v); };
    const key = e => { if (e.key === 'Escape') done(null); if (e.key === 'Enter' && e.target.id === 'scnName') $('scnYes').click(); };
    document.addEventListener('keydown', key);
    $('scnNo').onclick = () => done(null);
    $('scnYes').onclick = () => { const n = $('scnName').value.trim(); if (!n) { $('scnName').focus(); return; } done({ name: n, memo: $('scnMemo').value.trim() }); };
    $('scnBack').onclick = e => { if (e.target === $('scnBack')) done(null); };
  });
}
async function saveScenario(p, tag, memo, hint) {
  if (!curSite) { notice('사업지를 먼저 선택하세요.', true); return false; }
  const f = await scnForm(scnDefault(p, tag), memo, hint || `${curSite} 폴더 › 시나리오 에 저장됩니다. 같은 이름이면 덮어씁니다.`);
  if (!f) return false;
  try {
    await api('PUT', siteUrl(curSite, `/proforma?scenario=${encodeURIComponent(f.name)}&memo=${encodeURIComponent(f.memo)}`), p);
    renderScnSelect(); notice(`‘${f.name}’ 시나리오로 저장했습니다.`);
    if (!document.querySelector('.pf-tab[data-tab="scn"]').classList.contains('hidden')) loadCompare();
    return true;
  } catch (err) { notice(err.message, true); return false; }
}
async function loadScenario(n) {
  if (!curSite) return;
  const ok = await confirmBox('시나리오를 불러오시겠습니까?', `<b>${esc(n)}</b> 시나리오로 <b>현재 작업본을 바꿉니다.</b><br>
    <label style="display:flex;gap:6px;align-items:center;margin-top:10px;font-size:14px"><input type="checkbox" id="scnBackup" checked> 바꾸기 전에 현재 작업본을 시나리오로 보관 (「${today} 작업본 백업」)</label>`, '불러오기');
  if (!ok) return;
  try {
    if (document.getElementById('scnBackup')?.checked)
      await api('PUT', siteUrl(curSite, `/proforma?scenario=${encodeURIComponent(today + ' 작업본 백업')}&memo=${encodeURIComponent('‘' + n + '’ 불러오기 전 자동 보관')}`), pf);
    const j = await api('GET', siteUrl(curSite, '/proforma?scenario=' + encodeURIComponent(n)));
    if (j.proforma) { delete j.proforma._scenario; pfLoad(j.proforma, false); loadOrdinance(false); notice(`‘${n}’ 시나리오를 현재 작업본으로 불러왔습니다.`); renderScnSelect(); if (!document.querySelector('.pf-tab[data-tab="scn"]').classList.contains('hidden')) loadCompare(); }
  } catch (err) { notice(err.message, true); }
}
$('scnSave2').onclick = () => saveScenario(pf);
document.querySelector('#pfTabs [data-tab="scn"]').addEventListener('click', () => loadCompare());

/* 비교표 */
const SCN_ROWS = [
  ['결과', [
    ['세전이익', 'kpi.pbt', 'won', 1], ['매출이익률', 'kpi.margin_pct', 'pct', 1], ['Equity IRR (세후)', 'kpi.equity_irr_pct', 'pct', 1],
    ['ROE', 'kpi.roe_pct', 'pct', 1], ['BEP 분양률', 'kpi.bep_sales_rate_pct', 'pct', -1], ['분양가 하락 허용폭', 'kpi.price_drop_tolerance_pct', 'pct', 1],
    ['총매출 (VAT 제외)', 'kpi.revenue_net', 'won', 1], ['총사업비', 'kpi.total_cost', 'won', -1], ['└ 토지비', 'kpi.land_cost', 'won', -1],
    ['└ 공사비', 'kpi.construction_cost', 'won', -1], ['└ 금융비용', 'kpi.finance_cost', 'won', -1], ['공급평당 사업비', 'kpi.cost_per_supply_py', 'won', -1],
    ['LTC', 'kpi.ltc_pct', 'pct', -1], ['최대 대출잔액', 'kpi.peak_loan', 'won', -1], ['추가 자기자본 필요', 'kpi.extra_equity', 'won', -1]]],
  ['주요 가정', [
    ['분양률', 'assume.sales_rate_pct', 'pct', 0], ['분양가 조정', 'assume.price_adjust_pct', 'pctp', 0], ['평균 분양가 (공급 평당)', 'assume.avg_price_per_py', 'won', 0],
    ['세대·호수', 'assume.units', 'int', 0], ['사업기간', 'assume.duration_months', 'mon', 0], ['공사기간', 'assume.construction_months', 'mon', 0],
    ['자기자본', 'assume.equity', 'won', 0], ['대출 합계', 'assume.debt', 'won', 0], ['가중평균 금리', 'assume.avg_rate_pct', 'pct2', 0]]],
];
const pick = (o, path) => path.split('.').reduce((a, k) => a?.[k], o);
const SCN_HELP = {
  '세전이익': '총매출 − 총사업비. 법인세 내기 전 남는 돈', '매출이익률': '세전이익 ÷ 총매출. 보통 10% 이상이면 양호',
  'Equity IRR (세후)': '내가 넣은 자기자본의 연 수익률 (세금 후)', 'ROE': '세후 이익 ÷ 자기자본',
  'BEP 분양률': '이 비율만큼만 팔려도 손해가 없음 — 낮을수록 안전', '분양가 하락 허용폭': '분양가가 이만큼 떨어져도 손해가 없음 — 클수록 안전',
  '공급평당 사업비': '총사업비 ÷ 공급면적(평) — 원가 수준', 'LTC': '대출 ÷ 총사업비 — 높을수록 대출 의존이 큼',
  '최대 대출잔액': '사업 기간 중 대출이 가장 많았던 시점의 잔액', '추가 자기자본 필요': '대출 한도로 모자라 더 넣어야 하는 돈',
  '가중평균 금리': '대출 금액으로 가중한 평균 금리'};
function scnFmt(v, t) {
  if (v == null || Number.isNaN(v)) return '–';
  return t === 'won' ? krw(v) : t === 'pct' ? pct(v) : t === 'pct2' ? pct(v, 2) : t === 'pctp' ? (v > 0 ? '+' : '') + fmt(v, 1) + '%' : t === 'mon' ? fmt(v) + '개월' : fmt(v);
}
function scnDelta(v, b, t, dir) {
  if (v == null || b == null || Math.abs(v - b) < 1e-9) return '';
  const d = v - b, good = dir === 0 ? null : (d > 0) === (dir > 0);
  const txt = t === 'won' ? (d > 0 ? '+' : '−') + krw(Math.abs(d)) : t.startsWith('pct') ? (d > 0 ? '+' : '−') + fmt(Math.abs(d), t === 'pct2' ? 2 : 1) + '%p' : (d > 0 ? '+' : '−') + fmt(Math.abs(d));
  return `<div class="dlt ${good == null ? '' : good ? 'up' : 'down'}">${txt}</div>`;
}
const VD = { ok: ['적합', 'ok'], warn: ['조건부', 'warn'], bad: ['부적합', 'bad'] };
async function loadCompare() {
  if (!curSite) { $('scnCompare').innerHTML = '<div class="empty">사업지를 먼저 선택하세요.</div>'; return; }
  $('scnCompare').innerHTML = '<div class="empty" style="padding:18px">시나리오를 계산하는 중…</div>';
  try {
    const cols = (await api('GET', siteUrl(curSite, '/scenarios/compare'))).columns.filter(c => !c.error);
    if (cols.length <= 1) { $('scnCompare').innerHTML = '<div class="empty" style="padding:18px">아직 저장한 안이 없습니다.<br><span class="muted" style="font-size:13.5px">「💾 지금 숫자를 시나리오로 저장」을 눌러 <b>기본안</b>부터 저장해 보세요. 숫자를 바꿔 <b>보수안</b>도 저장하면 여기서 나란히 비교됩니다.</span></div>'; return; }
    const base = cols[0];
    cols[0].name = '지금 숫자';
    const best = cols.reduce((a, c) => (c.kpi?.pbt ?? -Infinity) > (a.kpi?.pbt ?? -Infinity) ? c : a, cols[0]);
    $('scnCompare').innerHTML = `<div class="tablewrap"><table class="scn-tbl"><thead><tr><th style="min-width:170px">항목</th>${cols.map(c => `<th class="r${c.current ? ' cur' : ''}">
        <div class="scn-name">${c.current ? '● ' : ''}${esc(c.name)}${c === best && cols.length > 2 ? ' <span class="chip ok">최고 이익</span>' : ''}</div>
        <div class="muted scn-meta">${c.current ? '지금 화면의 숫자 (비교 기준)' : '저장 ' + esc((c.saved_at || '').replace('T', ' '))}</div>
        ${c.memo ? `<div class="scn-memo" title="${esc(c.memo)}">${esc(c.memo)}</div>` : ''}
        ${c.current ? '' : `<div class="scn-acts"><button class="btn ghost" data-scn-load="${esc(c.name)}">불러오기</button><button class="btn ghost del-site" data-scn-del="${esc(c.name)}">삭제</button></div>`}</th>`).join('')}</tr></thead>
      <tbody><tr class="scn-verdict"><td>판정</td>${cols.map(c => `<td class="r"><span class="chip ${VD[c.verdict][1]}" title="${esc((c.reasons || []).join(' / '))}">${VD[c.verdict][0]}</span></td>`).join('')}</tr>
      ${SCN_ROWS.map(([g, rows]) => `<tr class="grp"><td colspan="${cols.length + 1}">${g}</td></tr>` + rows.map(([l, path, t, dir]) => `<tr><td>${l}${SCN_HELP[l] ? ` <span class="qhelp" title="${esc(SCN_HELP[l])}">?</span>` : ''}</td>${cols.map(c => {
        const v = pick(c, path), b = pick(base, path);
        return `<td class="r${c.current ? ' cur' : ''}">${scnFmt(v, t)}${c.current ? '' : scnDelta(v, b, t, dir)}</td>`; }).join('')}</tr>`).join('')).join('')}
      </tbody></table></div>
      <p class="muted" style="font-size:13px;margin:8px 0 0">증감은 현재 작업본 대비입니다. <span class="dlt up" style="display:inline">초록</span> = 유리, <span class="dlt down" style="display:inline">빨강</span> = 불리. 판정 칩에 마우스를 올리면 부적합 사유가 보입니다.</p>`;
  } catch (err) { $('scnCompare').innerHTML = errBox(err); }
}
$('scnCompare').addEventListener('click', async e => {
  const l = e.target.closest('[data-scn-load]'), d = e.target.closest('[data-scn-del]');
  if (l) await loadScenario(l.dataset.scnLoad);
  if (d) {
    const n = d.dataset.scnDel;
    if (!await confirmBox('시나리오를 삭제하시겠습니까?', `<b>${esc(n)}</b> 시나리오 파일을 삭제합니다. 현재 작업본에는 영향이 없습니다.<br><span class="muted" style="font-size:13px">삭제한 시나리오는 복원할 수 없습니다.</span>`)) return;
    try { await api('DELETE', siteUrl(curSite, '/scenarios/' + encodeURIComponent(n))); notice(`‘${n}’ 시나리오를 삭제했습니다.`); renderScnSelect(); loadCompare(); }
    catch (err) { notice(err.message, true); }
  }
});

/* 스트레스 테스트 */
let stressCases = [];
function stressSay(c, b) {
  const d = c.kpi.pbt - b.pbt;
  if (c.kpi.pbt < 0) return `${c.desc} → 손실 ${krw(-c.kpi.pbt)} 발생`;
  if (Math.abs(d) < 1e4) return `${c.desc} → 이익 변화 없음`;
  return `${c.desc} → 이익 ${krw(Math.abs(d))} ${d < 0 ? '감소' : '증가'}, 그래도 ${krw(c.kpi.pbt)} 남음`;
}
const STRESS_NAME = { '현재 작업본': '지금 숫자' };
$('stressRun').onclick = async () => {
  await busy($('stressRun'), async () => {
    $('stressOut').innerHTML = '<div class="empty" style="padding:18px">7개 경우를 계산하는 중…</div>';
    try {
      stressCases = (await api('POST', '/api/v4/proforma/stress', pf)).cases;
      const b = stressCases[0].kpi, ok = stressCases.filter(c => !c.error);
      const worst = ok.slice(1).sort((x, y) => x.kpi.pbt - y.kpi.pbt)[0];
      const failing = ok.slice(1).filter(c => c.kpi.pbt < 0 || c.kpi.margin_pct < (pf.criteria?.margin_warn_pct ?? 5));
      const rent = pf.project_mode === 'rental';
      $('stressOut').innerHTML = `<div class="stress-sum ${failing.length ? 'bad' : 'ok'}">
          ${failing.length ? `<b>⚠ ${failing.length}개 경우에서 이익률이 주의 기준 아래로 떨어집니다:</b> ${failing.map(c => esc(c.label)).join(', ')}` : '<b>✓ 모든 하방 경우에서 이익이 유지됩니다.</b>'}
          ${worst ? ` · 가장 큰 위험: <b>${esc(worst.label)}</b> (세전이익 ${krw(worst.kpi.pbt - b.pbt)})` : ''}</div>
        <div class="tablewrap"><table class="scn-tbl"><thead><tr><th>상황</th><th class="r">세전이익 <span class="qhelp" title="총매출 − 총사업비">?</span></th><th class="r">매출이익률 <span class="qhelp" title="세전이익 ÷ 총매출 (10% 이상 양호)">?</span></th><th class="r">Equity IRR <span class="qhelp" title="자기자본 연 수익률 (세후)">?</span></th>${rent ? '<th class="r">임대수익률 <span class="qhelp" title="1년차 순운영수익(NOI) ÷ 총사업비 — 4.5% 이상 양호">?</span></th>' : '<th class="r">BEP 분양률 <span class="qhelp" title="이만큼만 팔려도 손해 없음 — 낮을수록 안전">?</span></th>'}<th class="r">금융비용</th>${rent ? '<th class="r">최저 DSCR <span class="qhelp" title="순운영수익 ÷ 원리금 — 1.2배 이상이어야 대출 상환이 안정적">?</span></th>' : '<th class="r">최대 대출잔액</th>'}<th class="c">판정</th><th></th></tr></thead><tbody>
        ${stressCases.map((c, i) => (c.label = STRESS_NAME[c.label] || c.label, c)).map((c, i) => c.error ? `<tr><td>${esc(c.label)}</td><td colspan="8" class="muted">계산 불가: ${esc(c.error)}</td></tr>` : `<tr class="${i === 0 ? 'cur-row' : ''}">
          <td><b>${esc(c.label)}</b><div class="muted" style="font-size:12.5px">${i ? esc(stressSay(c, b)) : '지금 입력한 숫자 그대로'}</div></td>
          <td class="r"><b class="${c.kpi.pbt < 0 ? 'minus' : ''}">${krw(c.kpi.pbt)}</b>${i ? scnDelta(c.kpi.pbt, b.pbt, 'won', 1) : ''}</td>
          <td class="r">${pct(c.kpi.margin_pct)}${i ? scnDelta(c.kpi.margin_pct, b.margin_pct, 'pct', 1) : ''}</td>
          <td class="r">${c.kpi.equity_irr_pct != null ? pct(c.kpi.equity_irr_pct) : '–'}${i ? scnDelta(c.kpi.equity_irr_pct, b.equity_irr_pct, 'pct', 1) : ''}</td>
          ${rent ? `<td class="r">${c.kpi.rent_yield_pct != null ? pct(c.kpi.rent_yield_pct, 2) : '–'}${i ? scnDelta(c.kpi.rent_yield_pct, b.rent_yield_pct, 'pct2', 1) : ''}</td>`
            : `<td class="r">${c.kpi.bep_sales_rate_pct != null ? pct(c.kpi.bep_sales_rate_pct) : '–'}${i ? scnDelta(c.kpi.bep_sales_rate_pct, b.bep_sales_rate_pct, 'pct', -1) : ''}</td>`}
          <td class="r">${krw(c.kpi.finance_cost)}${i ? scnDelta(c.kpi.finance_cost, b.finance_cost, 'won', -1) : ''}</td>
          <td class="r">${rent ? (c.kpi.min_dscr != null ? fmt(c.kpi.min_dscr, 2) + '배' : '–') : c.kpi.peak_loan != null ? krw(c.kpi.peak_loan) : '–'}</td>
          <td class="c"><span class="chip ${VD[c.verdict][1]}" title="${esc((c.reasons || []).join(' / '))}">${VD[c.verdict][0]}</span></td>
          <td class="r">${i ? `<button class="btn ghost" data-stress-save="${i}">시나리오로 저장</button>` : ''}</td></tr>`).join('')}
        </tbody></table></div>
        <p class="muted" style="font-size:13px;margin:8px 0 0">판정은 사업성·법규를 함께 봅니다. 법규 항목(조례·지구단위계획 미입력 등) 때문에 모든 경우가 같은 판정일 수 있으니 세전이익·이익률·IRR 변화로 위험 크기를 비교하세요.</p>`;
    } catch (err) { $('stressOut').innerHTML = errBox(err); }
  });
};
$('stressOut').addEventListener('click', e => {
  const b = e.target.closest('[data-stress-save]'); if (!b) return;
  const c = stressCases[Number(b.dataset.stressSave)];
  if (c?.proforma) saveScenario(c.proforma, '스트레스 ' + c.label, c.desc, '스트레스 조건을 적용한 사업수지를 시나리오로 저장합니다. 현재 작업본은 바뀌지 않습니다.');
});

/* ═════════════════════ 설계도서 PDF → 면적·분양 타입 자동 반영 ═════════════════════ */
let designUndo = null;
$('designBtn').onclick = () => { if (!curSite) { notice('사업지를 먼저 선택하세요.', true); return; } $('designFiles').click(); };
$('designFiles').onchange = () => designUpload($('designFiles').files);
['dragover', 'drop'].forEach(ev => $('unitTable').closest('.card').addEventListener(ev, e => {
  if (!e.dataTransfer?.types?.includes('Files')) return;
  e.preventDefault(); if (ev === 'drop') designUpload(e.dataTransfer.files);
}));
async function designUpload(files) {
  if (!files || !files.length || !curSite) return;
  const pdfs = [...files].filter(f => /\.pdf$/i.test(f.name));
  if (!pdfs.length) { notice('PDF 파일만 넣을 수 있습니다.', true); return; }
  $('designResult').innerHTML = '<div class="alert info" style="margin:0 0 12px">설계도서를 읽는 중…</div>';
  try {
    const fd = new FormData(); pdfs.forEach(f => fd.append('files', f));
    const up = await fetch(siteUrl(curSite, '/upload'), { method: 'POST', body: fd });
    if (!up.ok) throw new Error(errText(await up.json()));
    const r = await api('GET', siteUrl(curSite, '/design?files=' + encodeURIComponent(pdfs.map(f => f.name).join(','))));
    applyDesign(r);
  } catch (err) { $('designResult').innerHTML = errBox(err); }
  $('designFiles').value = '';
}
function applyDesign(r) {
  designUndo = JSON.stringify(pf);
  const ov = r.overview, ch = [], warn = [...r.checks];
  const set = (label, obj, key, v, unit = '㎡') => {
    if (v == null) return;
    const old = obj[key];
    if (old != null && Math.abs(Number(old) - v) < 0.005) { ch.push([label, old, v, unit, false]); return; }
    obj[key] = v; ch.push([label, old, v, unit, true]);
  };
  // 대지면적: 필지 목록이 있으면 필지 합계가 기준 (설계 값은 대조만)
  if (ov.land_area_sqm != null) {
    if (parcelsActive()) {
      const d = Math.abs(ov.land_area_sqm - pf.land_area_sqm);
      if (d > Math.max(1, pf.land_area_sqm * 0.005)) warn.push(`설계개요 대지면적 ${fmt(ov.land_area_sqm, 2)}㎡ ≠ 필지 합계 ${fmt(pf.land_area_sqm, 2)}㎡ — 도로 편입·분할 여부 확인 (필지 합계 유지)`);
      ch.push(['대지면적', pf.land_area_sqm, ov.land_area_sqm, '㎡', false]);
    } else set('대지면적', pf, 'land_area_sqm', ov.land_area_sqm);
  }
  set('지상 연면적 (용적률 산정용)', pf, 'above_gfa_sqm', ov.far_gfa_sqm ?? ov.above_gfa_sqm);
  set('지하 연면적', pf, 'below_gfa_sqm', ov.below_gfa_sqm);
  set('계획 건축면적', pf.site, 'building_area_sqm', ov.building_area_sqm);
  set('계획 주차대수', pf.site, 'plan_parking', ov.parking, '대');
  // 분양 타입: 인식된 용도만 교체, 분양가는 같은 이름 → 같은 용도 기존 값 순으로 유지
  const uses = [...new Set(r.units.map(u => u.kind))];
  if (r.units.length) {
    const old = pf.units;
    const price = u => old.find(o => o.name === u.name)?.price_per_py ?? old.find(o => o.kind === u.kind)?.price_per_py ?? 0;
    const fresh = r.units.map(u => ({ name: u.name, kind: u.kind, buyer: old.find(o => o.name === u.name)?.buyer || 'general', exclusive_sqm: u.exclusive_sqm, supply_sqm: u.supply_sqm,
      count: u.count, price_per_py: price(u), market_deposit: 0, market_rent: 0 }));
    // 설계도서에 공동주택이 없으면 (템플릿 등) 기존 공동주택 타입도 제외
    const dropApt = !uses.includes('apartment') && !ov.has_apartment && old.some(o => o.kind === 'apartment');
    if (dropApt) warn.push(`설계도서에 공동주택이 없어 기존 공동주택 타입(${old.filter(o => o.kind === 'apartment').map(o => o.name).join(', ')})을 제외했습니다`);
    pf.units = [...old.filter(o => !uses.includes(o.kind) && !(dropApt && o.kind === 'apartment')), ...fresh];
    const noPrice = fresh.filter(u => !u.price_per_py).map(u => u.name);
    if (noPrice.length) warn.push(`평당 분양가가 없는 타입: ${noPrice.join(', ')} — 입력하세요`);
  }
  fillFields(); renderUnits(); pfRecalc();
  const KN = { officetel: '오피스텔', retail: '근린생활시설', office: '업무시설', knowledge: '지식산업센터', datacenter: '데이터센터', other: '기타', apartment: '공동주택' };
  $('designResult').innerHTML = `<div class="design-box">
    <div class="design-head"><b>설계도서 반영 완료</b> <span class="muted">${r.files.map(f => `${esc(f.name)}${f.kinds.length ? ' (' + esc(f.kinds.join('·')) + ')' : ' (인식 안 됨)'}`).join(' · ')}</span>
      <button type="button" class="btn ghost" id="designUndo">↶ 되돌리기</button></div>
    ${ch.length ? `<table class="design-tbl"><thead><tr><th>항목</th><th class="r">기존</th><th class="r">설계도서</th><th></th></tr></thead><tbody>${ch.map(([l, o, v, u, done]) =>
      `<tr><td>${esc(l)}</td><td class="r muted">${o != null ? fmt(o, u === '대' ? 0 : 2) + u : '–'}</td><td class="r"><b>${fmt(v, u === '대' ? 0 : 2)}${u}</b></td><td>${done ? '<span class="chip ok">반영</span>' : '<span class="chip gray">유지</span>'}</td></tr>`).join('')}</tbody></table>` : ''}
    ${r.units.length ? `<div class="muted" style="font-size:13.5px;margin-top:6px">분양 타입 ${r.units.length}개 반영 (${uses.map(k => KN[k] || k).join(', ')} 교체 · 다른 용도 유지): ${r.notes.map(esc).join(' / ')}</div>` : '<div class="muted" style="font-size:13.5px;margin-top:6px">분양면적표를 인식하지 못해 분양 타입은 그대로 두었습니다.</div>'}
    ${warn.length ? `<ul class="design-warn">${warn.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
  </div>`;
  $('designUndo').onclick = () => { if (!designUndo) return; pfLoad(JSON.parse(designUndo), true); pfRecalc(); designUndo = null; $('designResult').innerHTML = ''; notice('설계도서 반영 전으로 되돌렸습니다.'); };
  notice(`설계도서를 반영했습니다 — 면적 ${ch.filter(c => c[4]).length}건, 분양 타입 ${r.units.length}개. 원문과 대조하세요.`);
}

/* ═════════════════════ 사업지 현황 · 선택 ═════════════════════ */
let curSite = null, lastSite = null, siteList = [];
async function loadSites() {
  try {
    const j = await api('GET', '/api/v4/sites');
    siteList = j.sites;
    $('inboxPath').textContent = '자료함 위치: ' + j.inbox + ' — 사업지마다 폴더 하나, 사업수지는 각 폴더의 사업수지.json 에 자동 저장됩니다.';
    $('siteCount').hidden = !j.sites.length; $('siteCount').textContent = j.sites.length;
    $('curSiteSel').innerHTML = '<option value="">— 사업지 선택 —</option>' + j.sites.map(s => `<option ${s.name === curSite ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
    renderPortfolio(); loadTrash();
    if (document.getElementById('view-easy')?.classList.contains('active') && ezStep === 1) ezRender1();
  } catch (e) { notice('사업지 목록을 불러오지 못했습니다: ' + e.message, true); }
}
let pfFilter = 'all';
function renderPortfolio() {
  const S = { ok: ['적합', 'ok'], warn: ['조건부', 'warn'], bad: ['부적합', 'bad'] };
  let ok = 0, warn = 0, bad = 0, none = 0;
  siteList.forEach(s => { const r = s.result; if (!r) none++; else if (r.verdict === 'ok') ok++; else if (r.verdict === 'warn') warn++; else bad++; });
  const rows = siteList.filter(s => pfFilter === 'all' || (pfFilter === 'none' ? !s.result : s.result?.verdict === pfFilter));
  $('portfolio').tBodies[0].innerHTML = rows.map(s => {
    const r = s.result;
    const ratio = r ? (r.proportional_rate_pct != null ? `<span title="비례율">${pct(r.proportional_rate_pct)}</span>` : pct(r.margin_pct)) : '–';
    return `<tr class="clickrow" data-site="${esc(s.name)}" style="${s.name === curSite ? 'background:#eef6fd' : ''}">
      <td><b>${esc(s.name)}</b><div class="muted" style="font-size:12.5px">자료 ${s.files}개${s.scenarios ? ' · 시나리오 ' + s.scenarios : ''}${r && r.project_mode === 'redevelopment' ? ' · 정비사업' : ''}</div></td>
      <td style="font-size:14px">${esc(r?.location || '–')}<div class="muted" style="font-size:12.5px">${esc((r?.zones || []).join(', '))}</div></td>
      <td class="r">${r ? fmt(r.land_area_sqm, 0) + '㎡' : '–'}<div class="muted" style="font-size:12.5px">${r ? fmt(PY(r.land_area_sqm), 0) + '평' : ''}</div></td>
      <td class="r">${r ? fmt(r.units) : '–'}</td><td class="r">${r ? krw(r.revenue_net) : '–'}</td>
      <td class="r ${r && r.pbt < 0 ? 'minus' : 'money'}">${r ? krw(r.pbt) : '–'}</td><td class="r">${ratio}</td>
      <td class="r">${r && r.bep_sales_rate_pct != null ? pct(r.bep_sales_rate_pct) : '–'}</td><td class="r">${r && r.equity_irr_pct != null ? pct(r.equity_irr_pct) : '–'}</td>
      <td class="c">${r ? `<span class="chip ${S[r.verdict][1]}" title="${esc(r.verdict_label)}">${S[r.verdict][0]}</span>` : '<span class="chip gray">미분석</span>'}</td>
      <td class="muted" style="font-size:13px;white-space:nowrap">${r ? new Date(r.saved_at).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' }) : '–'}</td>
      <td class="r" style="white-space:nowrap"><button class="btn ghost" data-open="sites" data-site="${esc(s.name)}">자료</button> <button class="btn" data-open="proforma" data-site="${esc(s.name)}">수지</button>
        <button class="btn ghost del-site" data-del-site="${esc(s.name)}" title="사업지 삭제 (복원 가능)">삭제</button></td></tr>`;
  }).join('') || `<tr><td colspan="12"><div class="empty"><span class="ico">📁</span>${siteList.length ? '조건에 맞는 사업지가 없습니다.' : '사업지가 없습니다. 오른쪽 위에서 사업지를 추가하세요.'}</div></td></tr>`;
  $('pfCount').textContent = siteList.length + '곳'; $('pfOk').textContent = ok + '곳'; $('pfWarn').textContent = warn + '곳'; $('pfBad').textContent = bad + '곳'; $('pfNone').textContent = '미분석 ' + none;
}
$('pfFilter').onclick = e => { const b = e.target.closest('[data-f]'); if (!b) return; pfFilter = b.dataset.f; $('pfFilter').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); renderPortfolio(); };
/* 화면 내 확인창 (브라우저 기본 confirm 대신) */
function confirmBox(title, msg, yes = '삭제') {
  return new Promise(res => {
    $('cfmTitle').textContent = title; $('cfmMsg').innerHTML = msg; $('cfmYes').textContent = yes;
    $('cfmBack').classList.remove('hidden'); $('cfmNo').focus();
    const done = v => { $('cfmBack').classList.add('hidden'); document.removeEventListener('keydown', key); res(v); };
    const key = e => { if (e.key === 'Escape') done(false); };
    document.addEventListener('keydown', key);
    $('cfmYes').onclick = () => done(true); $('cfmNo').onclick = () => done(false);
    $('cfmBack').onclick = e => { if (e.target === $('cfmBack')) done(false); };
  });
}
async function loadTrash() {
  try {
    const t = (await api('GET', '/api/v4/sites-trash')).trash;
    $('trashCard').classList.toggle('hidden', !t.length);
    const S = { ok: ['적합', 'ok'], warn: ['조건부', 'warn'], bad: ['부적합', 'bad'] };
    const when = d => d.length >= 13 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)} ${d.slice(9, 11)}:${d.slice(11, 13)}` : d;
    $('trashTable').tBodies[0].innerHTML = t.map(x => `<tr><td><b>${esc(x.name)}</b></td><td class="muted">${esc(when(x.deleted))}</td>
      <td class="r">${x.result ? krw(x.result.pbt) : '–'}</td><td class="c">${x.result ? `<span class="chip ${S[x.result.verdict][1]}">${S[x.result.verdict][0]}</span>` : '<span class="chip gray">미분석</span>'}</td>
      <td class="r" style="white-space:nowrap"><button class="btn" data-restore="${esc(x.id)}">↩ 복원</button> <button class="btn ghost del-site purge" data-purge="${esc(x.id)}" data-purge-name="${esc(x.name)}">영구 삭제</button></td></tr>`).join('');
  } catch { /* 무시 */ }
}
$('trashTable').addEventListener('click', async e => {
  const pg = e.target.closest('[data-purge]');
  if (pg) {
    const ok = await confirmBox('영구 삭제하시겠습니까?', `<b>${esc(pg.dataset.purgeName)}</b> 사업지의 자료·사업수지·시나리오 파일을 <b style="color:#c0392b">완전히 삭제</b>합니다.<br><span class="muted" style="font-size:13px">영구 삭제하면 복원할 수 없습니다.</span>`, '영구 삭제');
    if (!ok) return;
    try { await api('DELETE', `/api/v4/sites-trash/${encodeURIComponent(pg.dataset.purge)}`); notice(`‘${pg.dataset.purgeName}’ 사업지를 영구 삭제했습니다.`); await loadTrash(); }
    catch (err) { notice(err.message, true); }
    return;
  }
  const b = e.target.closest('[data-restore]'); if (!b) return;
  try { const r = await api('POST', `/api/v4/sites-trash/${encodeURIComponent(b.dataset.restore)}/restore`); notice(`‘${r.name}’ 사업지를 복원했습니다.`); await loadSites(); }
  catch (err) { notice(err.message, true); }
});
$('portfolio').addEventListener('click', async e => {
  const del = e.target.closest('[data-del-site]');
  if (del) {
    e.stopPropagation();
    const n = del.dataset.delSite, r = siteList.find(s => s.name === n)?.result;
    const ok = await confirmBox('삭제하시겠습니까?', `<b>${esc(n)}</b> 사업지와 자료·사업수지를 삭제합니다.${r ? `<br><span class="muted">세전이익 ${krw(r.pbt)} · ${esc(r.verdict_label || '')}</span>` : ''}<br><span class="muted" style="font-size:13px">삭제된 사업지는 아래 「삭제된 사업지」에서 복원할 수 있습니다.</span>`);
    if (!ok) return;
    try {
      if (n === curSite) { clearTimeout(saveTimer); curSite = null; store.set('develogic.site', ''); }
      await api('DELETE', siteUrl(n));
      notice(`‘${n}’ 사업지를 삭제했습니다.`);
      await loadSites();
      if (!curSite && siteList.length) await selectSite(siteList[0].name);   // 현재 사업지를 지웠으면 첫 사업지로 전환
    } catch (err) { notice(err.message, true); }
    return;
  }
  const row = e.target.closest('[data-site]'); if (!row) return;
  await selectSite(row.dataset.site);
  go(e.target.dataset.open || 'proforma');
});
$('curSiteSel').onchange = e => { if (e.target.value) selectSite(e.target.value); };
$('siteCreate').onclick = async () => {
  const n = $('newSite').value.trim(); if (!n) { notice('사업지 이름을 입력하세요.', true); return; }
  const reg = pickRegion('newSiteProv', 'newSiteMuni', n); if (!reg) return;
  try { const r = await api('POST', '/api/v4/sites', { name: n }); $('newSite').value = ''; await loadSites(); await selectSite(r.name);
    applyRegion(reg); go('sites'); notice(`사업지 폴더를 만들었습니다 (${reg.province} ${reg.municipality} 조례 적용). 토지이용계획확인서·필지목록을 넣어 주세요.`); }
  catch (err) { notice(err.message, true); }
};
async function selectSite(name) {
  if (name === curSite && pf) return;
  clearTimeout(saveTimer);
  curSite = name; store.set('develogic.site', name); lastSite = null;
  $('curSiteSel').value = name; renderPortfolio();
  loadingSite = true;
  try {
    const j = await api('GET', siteUrl(name, '/proforma'));
    let p = j.proforma;
    if (!p) {   // 처음 여는 사업지: 템플릿 + 자료함 분석값으로 시작
      p = await api('GET', '/sample?name=proforma');
      p.project_name = name;
      try {
        const d = await api('GET', siteUrl(name)); lastSite = d; const s = d.summary;
        if (s.total_area_sqm) {
          // 템플릿 규모를 대지면적 비율로 맞춤 (연면적·세대수·자기자본·대출·정액 사업비) — 이후 실제 계획으로 수정 필요
          const k = s.total_area_sqm / p.land_area_sqm, r2 = v => Math.round(v * k * 100) / 100;
          p.above_gfa_sqm = r2(p.above_gfa_sqm); p.below_gfa_sqm = r2(p.below_gfa_sqm);
          p.units.forEach(u => { if (u.kind !== 'apartment' && u.kind !== 'officetel') { u.supply_sqm = r2(u.supply_sqm); u.exclusive_sqm = r2(u.exclusive_sqm); } else u.count = Math.max(1, Math.round(u.count * k)); });
          p.equity = Math.round(p.equity * k); p.loans.forEach(l => l.amount = Math.round(l.amount * k));
          p.costs.forEach(c => { if (c.basis === 'fixed') c.value = Math.round(c.value * k); });
          if (p.site?.building_area_sqm) p.site.building_area_sqm = r2(p.site.building_area_sqm);
          p.land_area_sqm = Math.round(s.total_area_sqm * 100) / 100;
          p.site = { ...p.site, province: s.province || p.site.province, municipality: s.municipality || p.site.municipality, flags: d.flags.map(f => f.name),
            zones: s.by_zone.filter(z => z.zone !== '미확인').map(z => ({ zone: z.zone, area_sqm: Math.round(z.area_sqm * 100) / 100 })) };
        }
      } catch { /* 자료 없음 */ }
      notice(`‘${name}’ 사업수지를 템플릿으로 시작합니다. 자료함 값(대지·용도지역)을 반영했습니다.`);
    }
    pfLoad(p, true); savedSnap = j.proforma ? JSON.stringify(pf) : null; loadOrdinance(!j.proforma);
  } catch (err) { notice(err.message, true); }
  loadingSite = false;
  $('saveState').className = 'chip gray'; $('saveState').textContent = '자동 저장 켜짐';
  renderScnSelect();
  if (document.getElementById('view-sites').classList.contains('active')) openSite(name);
  if (document.getElementById('view-easy')?.classList.contains('active') && ezStep === 1) ezRender1();
  if (VIEWS[location.hash.slice(1)]) show(location.hash.slice(1));
}
async function openSite(name) {
  if (!name) return;
  $('siteDetail').innerHTML = '<div class="card"><div class="empty">자료를 읽는 중…</div></div>';
  try { lastSite = await api('GET', '/api/v4/sites/' + encodeURIComponent(name)); renderSite(); }
  catch (err) { $('siteDetail').innerHTML = `<div class="card">${errBox(err)}</div>`; }
}
function renderSiteDesign(r) {
  const n = r.files.filter(f => f.kind === '설계도서').length;
  return n ? `<div class="alert info" style="display:inline-block;margin:0 0 12px;padding:6px 12px;font-size:13.5px">설계도서 PDF ${n}개가 있습니다. <a href="#" id="siteDesignGo">사업수지 › 분양 계획에 반영 →</a></div>` : '';
}
function renderSite() {
  const r = lastSite, s = r.summary;
  $('siteDetail').innerHTML = `
    <div class="site-top">
    <div class="card site-head">
      <div class="site-title"><h2>${esc(r.name)}</h2><span class="muted">${esc([s.province, s.municipality].filter(Boolean).join(' ') || '지역 미확인')} · 필지 ${s.parcel_count}개 · 자료 ${r.files.length}개</span></div>
      <div class="site-actions">
        <span class="grp"><button class="btn secondary" id="siteOpen">📂 폴더 열기</button><button class="btn secondary" id="siteReload">↻ 다시 읽기</button></span>
        <span class="grp"><button class="btn secondary" data-landuse-report title="사업수지에 입력된 필지의 토지이용계획을 조회해 열람본(참고용) PDF를 이 폴더에 저장">📄 토지이용계획 열람본 작성</button></span>
        <span class="grp"><button class="btn ghost" id="siteToFeas">법규 검토로 보내기</button><button class="btn" id="siteToPf">사업수지로 보내기 →</button></span>
      </div>
      <div id="dropZone" class="site-drop">📎 파일을 끌어다 놓거나 눌러서 추가 <span class="muted">토지이용계획확인서 PDF · 필지목록 엑셀 · 기타 자료</span><input type="file" id="siteFiles" multiple hidden></div></div>
    <div class="stats compact">
      <div class="stat hl"><small>대지면적 합계</small><strong>${fmt(s.total_area_sqm, 1)}㎡</strong><em>${fmt(s.total_area_py, 1)}평 · 필지 ${s.parcel_count}개</em>
        ${(s.by_jimok || []).length ? `<em>지목 ${(s.by_jimok || []).slice(0, 3).map(j => `${esc(j.jimok)} ${fmt(j.area_sqm, 0)}㎡`).join(' · ')}</em>` : ''}</div>
      <div class="stat"><small>주 용도지역</small><strong class="ink" style="font-size:16px">${esc(s.main_zone || '미확인')}</strong>
        <em>${esc([s.province, s.municipality].filter(Boolean).join(' ') || '소재지 미확인')}</em>
        ${(s.by_zone || []).length > 1 ? `<em class="neg">용도지역 ${s.by_zone.length}개 혼재 — ${s.by_zone.slice(1, 3).map(z => `${esc(z.zone.replace('지역', ''))} ${z.share != null ? pct(z.share * 100, 0) : ''}`).join(' · ')}</em>` : ''}</div>
      <div class="stat"><small>개별공시지가 합계</small><strong>${s.official_price_total ? krwW(s.official_price_total) : '–'}</strong>
        <em>㎡당 ${s.official_price_avg_sqm ? krw(s.official_price_avg_sqm) : '–'} · 평당 ${s.official_price_avg_sqm ? krw(s.official_price_avg_sqm * 3.305785) : '–'}</em>
        <em>반영 ${s.price_coverage != null ? pct(s.price_coverage * 100, 0) : '–'} · 매입가 아님</em></div>
      <div class="stat"><small>규제 사항</small><strong class="${r.flags.length ? 'neg' : 'pos'}">${r.flags.length ? r.flags.length + '건' : '없음'}</strong>
        <em>${r.flags.length ? esc(r.flags.slice(0, 3).map(f => f.name).join(' · ')) + (r.flags.length > 3 ? ' 외' : '') : '토지이용계획상 특이 규제 없음'}</em></div>
    </div></div>
    ${r.warnings.length ? `<div class="alert warn fit"><b>확인 필요</b><ul>${r.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}
    <div class="card"><h2>필지 현황</h2><div class="tablewrap"><table class="parcel-tbl"><colgroup><col style="width:28%"><col style="width:7%"><col style="width:10%"><col style="width:17%"><col style="width:13%"><col style="width:15%"><col style="width:10%"></colgroup><thead><tr><th>소재지·지번</th><th>지목</th><th class="r">면적 ㎡</th><th>용도지역</th><th class="r">공시지가 (원/㎡)</th><th>규제</th><th>출처</th></tr></thead><tbody>
      ${r.parcels.map(p => `<tr><td>${esc(p.address || '미확인')}</td><td>${esc(p.jimok || '–')}</td><td class="r">${fmt(p.area_sqm, 1)}</td><td>${esc(p.zones.join(', ') || '미확인')}</td><td class="r">${fmt(p.price_per_sqm)}</td><td>${p.flags.map(f => `<span class="chip warn" style="margin:1px">${esc(f)}</span>`).join('')}</td><td class="muted" style="font-size:12.5px">${esc(p.source)}</td></tr>`).join('') || '<tr><td colspan="7" class="c muted">인식된 필지가 없습니다.</td></tr>'}
      </tbody></table></div></div>
    <div class="grid2">
      <div class="card"><h2>용도지역별 면적</h2><table><tbody>${s.by_zone.map(z => `<tr><td>${esc(z.zone)}</td><td class="r">${fmt(z.area_sqm, 1)}㎡</td><td class="r">${z.share != null ? pct(z.share * 100) : ''}</td></tr>`).join('')}</tbody></table>
        <h3>지목별 면적</h3><table><tbody>${s.by_jimok.map(z => `<tr><td>${esc(z.jimok)}</td><td class="r">${fmt(z.area_sqm, 1)}㎡</td></tr>`).join('')}</tbody></table></div>
      <div class="card"><h2>규제 · 검토 사항</h2>${r.flags.map(f => `<div style="padding:8px 0;border-bottom:1px solid var(--line)"><span class="chip warn">${esc(f.name)}</span> <span style="font-size:14px">${esc(f.note)}</span><div class="muted" style="font-size:12.5px;margin-top:3px">${f.parcels.map(esc).join(', ')}</div></div>`).join('') || '<div class="empty">발견된 규제가 없습니다.</div>'}</div>
    </div>
    <div class="card" style="max-width:820px"><h2>자료 파일</h2><table><thead><tr><th>파일</th><th>인식</th><th class="r">필지</th><th class="r">크기</th></tr></thead><tbody>
      ${r.files.map(f => `<tr><td>${esc(f.name)}</td><td><span class="chip ${f.kind === '오류' ? 'bad' : f.parsed ? 'ok' : 'gray'}">${esc(f.kind)}</span></td><td class="r">${f.parsed || ''}</td><td class="r">${fmt(f.size / 1024, 0)} KB</td></tr>`).join('') || '<tr><td colspan="4" class="muted">파일이 없습니다.</td></tr>'}</tbody></table>
      <p class="muted" style="font-size:13px;margin:10px 0 0">${esc(r.notice)}</p></div>`;
  $('siteOpen').onclick = () => api('POST', `/api/v4/sites/${encodeURIComponent(r.name)}/open`).then(x => notice('폴더를 열었습니다: ' + x.path)).catch(err => notice(err.message, true));
  $('siteReload').onclick = () => openSite(r.name);
  $('siteDetail').insertAdjacentHTML('afterbegin', renderSiteDesign(r));
  $('siteDesignGo')?.addEventListener('click', async e => {
    e.preventDefault(); go('proforma'); document.querySelector('#pfTabs [data-tab="units"]').click();
    try { applyDesign(await api('GET', siteUrl(r.name, '/design'))); } catch (err) { $('designResult').innerHTML = errBox(err); }
  });
  const dz = $('dropZone'), fi = $('siteFiles');
  dz.onclick = () => fi.click();
  fi.onchange = () => uploadSite(fi.files);
  dz.ondragover = ev => { ev.preventDefault(); dz.style.borderColor = 'var(--brand-blue)'; };
  dz.ondragleave = () => dz.style.borderColor = '';
  dz.ondrop = ev => { ev.preventDefault(); dz.style.borderColor = ''; uploadSite(ev.dataTransfer.files); };
  $('siteToPf').onclick = () => sendSiteToPf();
  $('siteToFeas').onclick = () => {
    if (s.province) $('f_province').value = s.province; fillMuni('f_province', 'f_municipality', s.municipality || '');
    if (s.main_zone) $('f_zone').value = s.main_zone; $('f_site_area_sqm').value = fmt(s.total_area_sqm, 2); refreshHints(); go('feasibility');
  };
}
async function uploadSite(files) {
  if (!files || !files.length) return;
  const fd = new FormData(); [...files].forEach(f => fd.append('files', f));
  try {
    const r = await fetch(`/api/v4/sites/${encodeURIComponent(curSite)}/upload`, { method: 'POST', body: fd });
    if (!r.ok) throw new Error(errText(await r.json()));
    notice(`${(await r.json()).saved.length}개 파일을 추가했습니다.`); openSite(curSite);
  } catch (err) { notice(err.message, true); }
}
function sendSiteToPf() {
  const r = lastSite, s = r.summary; if (!pf) return;
  pf.project_name = r.name; pf.land_area_sqm = Math.round(s.total_area_sqm * 100) / 100;
  pf.site.province = s.province || pf.site.province; pf.site.municipality = s.municipality || pf.site.municipality;
  pf.site.address = r.parcels.find(p => p.address)?.address || pf.site.address;
  pf.site.zones = s.by_zone.filter(z => z.zone !== '미확인').map(z => ({ zone: z.zone, area_sqm: Math.round(z.area_sqm * 100) / 100 }));
  pf.site.flags = r.flags.map(f => f.name);
  pf.site.parcels = r.parcels.filter(x => x.area_sqm).map(x => ({ address: x.address || '', area_sqm: x.area_sqm, zone: (x.zones || [])[0] || '', jimok: x.jimok || '' }));
  const pn = (r.plan_notices || [])[0];
  if (pn) pf.site.plan = { ...pf.site.plan, kind: pn.kind, title: pn.title || pf.site.plan.title, notice_no: pn.notice_no || pf.site.plan.notice_no,
    notice_date: pn.notice_date || pf.site.plan.notice_date, base_far: pn.base_far, allowed_far: pn.allowed_far, max_far: pn.max_far, plan_bcr: pn.plan_bcr };
  else if (pf.site.plan.kind === 'none' && pf.site.flags.includes('지구단위계획구역')) pf.site.plan.kind = 'district';
  else if (pf.site.plan.kind === 'none' && pf.site.flags.some(f => f === '정비구역' || f === '재정비촉진지구')) pf.site.plan.kind = 'redevelopment';
  if (s.official_price_avg_sqm) {
    const land = pf.costs.find(c => c.category === 'land' && c.basis === 'per_land_py');
    if (land) land.note = `개별공시지가 평균 ${fmt(s.official_price_avg_sqm * 400 / 121)}원/평 (참고 — 매입가 아님)`;
  }
  pfLoad(pf, true); loadOrdinance(true); go('proforma'); pfTab('basic');
  notice('사업지 자료(대지면적·용도지역·소재지·규제)를 사업수지에 반영했습니다.');
}

/* ═════════════════════ 종합 현황 ═════════════════════ */
function renderOverview() { loadSites(); }

/* ═════════════════════ 사업지 법규 검토 ═════════════════════ */
const FEAS_TEXT = ['province', 'municipality', 'zone', 'project_type', 'as_of'];
const FEAS_NUM = ['site_area_sqm', 'incentive_far_pct', 'saleable_ratio', 'sale_price_krw_per_sqm', 'construction_cost_krw_per_sqm', 'contribution_cost_krw', 'other_cost_krw'];
const FEAS_CHK = ['verified_parcel_and_overlays', 'verified_district_or_renewal_plan', 'verified_incentive_and_contribution'];
let lastFeas = null;
$('feasBtn').onclick = e => busy(e.target, async () => {
  const o = {}; FEAS_TEXT.forEach(k => o[k] = $('f_' + k).value.trim()); FEAS_NUM.forEach(k => o[k] = num('f_' + k) ?? 0); FEAS_CHK.forEach(k => o[k] = $('f_' + k).checked);
  o.confirmed_buildable_site_sqm = num('f_confirmed_buildable_site_sqm');
  if (!o.municipality) { notice('시·군·구를 입력하세요.', true); $('f_municipality').focus(); return; }
  try { lastFeas = await api('POST', '/api/v2/feasibility', o); $('feasResult').innerHTML = renderFeas(lastFeas); }
  catch (err) { $('feasResult').innerHTML = errBox(err); }
});
function renderFeas(x) {
  let h = x.status === 'review_required'
    ? `<p><span class="chip warn">● 추가 검토 필요</span></p><div class="alert warn"><b>아래 항목 때문에 계산이 차단되었습니다.</b><ul>${x.blockers.map(b => `<li>${esc(b)}</li>`).join('')}</ul></div>${x.blockers.some(b => b.includes('조례')) ? '<button class="btn ghost" data-go="rules">조례 근거 등록하러 가기 →</button>' : ''}`
    : `<p><span class="chip ok">● 가정 기반 산출 완료</span></p>`;
  if (x.rule) { const r = x.rule; h += `<div class="alert info"><b>적용 조례</b> ${esc(r.legal_title)} ${esc(r.article)}<br>용적률 ${fmt(r.far_pct, 2)}% · 건폐율 ${fmt(r.bcr_pct, 2)}% · 시행 ${esc(r.valid_from)}${r.valid_to ? ' ~ ' + esc(r.valid_to) : ''} · <a href="${esc(r.source_url)}" target="_blank" rel="noopener">원문 ↗</a></div>`; }
  const c = x.calculation;
  if (c) {
    const m = Number(c.pre_financing_pre_tax_margin_krw);
    h += `<div class="stats"><div class="stat"><small>적용 용적률</small><strong>${fmt(c.far_pct, 2)}%</strong><em>건폐율 ${fmt(c.bcr_pct, 2)}%</em></div>
      <div class="stat"><small>용적률 대상 연면적</small><strong>${fmt(c.illustrative_far_floor_sqm, 0)}㎡</strong><em>≈ ${fmt(PY(c.illustrative_far_floor_sqm), 0)}평</em></div>
      <div class="stat"><small>분양 가능 면적</small><strong>${fmt(c.assumed_saleable_sqm, 0)}㎡</strong><em>건축면적 ${fmt(c.illustrative_footprint_sqm, 0)}㎡</em></div>
      <div class="stat"><small>단순 이익 (금융·세전)</small><strong class="${m < 0 ? 'neg' : ''}">${krwW(m)}</strong></div></div>
      <table><tbody><tr><td>분양수입</td><td class="r">${fmt(c.assumed_revenue_krw)} 원</td></tr><tr><td>공사비</td><td class="r">${fmt(c.assumed_construction_krw)} 원</td></tr><tr><td>공공기여</td><td class="r">${fmt(c.assumed_contribution_krw)} 원</td></tr><tr><td>기타 사업비</td><td class="r">${fmt(c.assumed_other_cost_krw)} 원</td></tr><tr class="total"><td>총 사업비</td><td class="r">${fmt(c.assumed_total_cost_krw)} 원</td></tr></tbody></table>
      <div class="toolbar" style="margin-top:14px"><button class="btn" id="toProforma">사업수지 분석으로 보내기 →</button><span class="muted" style="font-size:13.5px">대지면적·지상 연면적을 반영합니다</span></div>`;
  }
  return h + `<p class="muted" style="font-size:13px;margin-top:14px">${esc(x.notice)}</p>`;
}
document.addEventListener('click', e => {
  if (e.target.id !== 'toProforma' || !lastFeas?.calculation || !pf) return;
  pf.land_area_sqm = num('f_confirmed_buildable_site_sqm'); pf.above_gfa_sqm = Number(lastFeas.calculation.illustrative_far_floor_sqm);
  pfLoad(pf, true); go('proforma'); pfTab('basic'); notice('대지면적과 지상 연면적을 사업수지에 반영했습니다.');
});

/* ═════════════════════ 간이 조례 검토 ═════════════════════ */
$('quickBtn').onclick = e => busy(e.target, async () => {
  const out = $('quickResult');
  try {
    const x = await api('POST', '/api/v1/legal-review', {
      jurisdiction: $('q_region').value, zone: $('q_zone').value, project_type: $('q_type').value, site_area_sqm: num('q_area'),
      station_distance_m: $('q_dist').value === '' ? null : Number($('q_dist').value), district_plan_verified: $('q_district').checked, parcel_zoning_verified: $('q_parcel').checked,
    });
    const L = x.ordinance_limits || {};
    out.innerHTML = `<p><span class="chip ${x.issues.length ? 'warn' : ''}">● ${esc(x.status)}</span></p>
      <div class="stats"><div class="stat"><small>조례 용적률 상한</small><strong>${L.far != null ? L.far + '%' : '미확인'}</strong></div>
      <div class="stat"><small>조례 건폐율 상한</small><strong>${L.bcr != null ? L.bcr + '%' : '미확인'}</strong></div>
      <div class="stat"><small>단순 용적률 대상 면적</small><strong>${x.illustrative_max_far_floor_sqm ? fmt(x.illustrative_max_far_floor_sqm, 0) + '㎡' : '미산정'}</strong>${x.illustrative_max_far_floor_sqm ? `<em>≈ ${fmt(PY(x.illustrative_max_far_floor_sqm), 0)}평</em>` : ''}</div>
      <div class="stat"><small>단순 건축면적</small><strong>${x.illustrative_max_footprint_sqm ? fmt(x.illustrative_max_footprint_sqm, 0) + '㎡' : '미산정'}</strong></div></div>
      ${x.issues.length ? `<div class="alert warn"><b>확인 필요 사항</b><ul>${x.issues.map(i => `<li>${esc(i)}</li>`).join('')}</ul></div>` : ''}
      ${(x.sources || []).length ? `<div class="alert info"><b>근거</b>${x.sources.map(s => `<br><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)} (${esc(s.effective)} 시행) ↗</a>`).join('')}</div>` : ''}
      <p class="muted" style="font-size:13px">${esc(x.disclaimer || '')}</p>`;
  } catch (err) { out.innerHTML = errBox(err); }
});

/* ═════════════════════ 조례 근거 등록 ═════════════════════ */
const RULE_KEYS = ['province', 'municipality', 'zone', 'project_type', 'valid_from', 'valid_to', 'far_pct', 'bcr_pct', 'legal_title', 'article', 'source_url', 'reviewed_by', 'reviewed_on', 'notes'];
$('ruleBtn').onclick = e => busy(e.target, async () => {
  const o = {}; RULE_KEYS.forEach(k => o[k] = $('r_' + k).value.trim()); o.valid_to = o.valid_to || null;
  const missing = [['municipality', '시·군·구'], ['far_pct', '용적률'], ['bcr_pct', '건폐율'], ['valid_from', '시행 시작일'], ['legal_title', '조례·고시명'], ['article', '근거 조항'], ['source_url', '원문 URL'], ['reviewed_by', '검토자']].filter(([k]) => !o[k]).map(([, n]) => n);
  if (missing.length) { notice('필수 항목: ' + missing.join(', '), true); return; }
  try {
    const x = await api('POST', '/api/v2/ordinances', o);
    $('ruleResult').innerHTML = `<div class="alert ok"><b>등록 완료 (ID ${esc(x.id)})</b><br>${esc(x.notice)}<br><button class="btn ghost" style="margin-top:8px" data-go="feasibility">이 조례로 사업지 검토 →</button></div>`;
    ['province', 'zone', 'project_type'].forEach(k => $('f_' + k).value = o[k]); fillMuni('f_province', 'f_municipality', o.municipality);
    notice('조례 근거가 등록되었습니다.');
  } catch (err) { $('ruleResult').innerHTML = errBox(err); }
});
$('ruleReset').onclick = () => { ['municipality', 'valid_from', 'valid_to', 'far_pct', 'bcr_pct', 'legal_title', 'article', 'source_url', 'reviewed_by', 'notes'].forEach(k => $('r_' + k).value = ''); $('ruleResult').innerHTML = ''; };

/* ═════════════════════ Cash Flow · PF ═════════════════════ */
const EV_TYPES = { receipt: '사업수입 (분양 등)', cost: '사업비 지급', equity_in: 'Equity 투입', equity_out: 'Equity 회수', draw: '대출 실행', repay: '대출 상환' };
let cf = { loans: [], events: [] }, cfMode = 'form', cfUnit = 1e6, lastCf = null;
const loanOpts = sel => '<option value="">—</option>' + cf.loans.map(l => `<option ${l.id === sel ? 'selected' : ''}>${esc(l.id)}</option>`).join('');
function cfRenderLoans() {
  $('cfLoanRows').innerHTML = cf.loans.map((l, i) => `<tr>
    <td><input data-cl="${i}" data-k="id" value="${esc(l.id)}"></td>
    <td><input class="money-in" data-cl="${i}" data-k="limit" value="${fmt(l.limit)}"></td>
    <td><input type="number" step="0.01" style="text-align:right" data-cl="${i}" data-k="annual_rate" value="${+(l.annual_rate * 100).toFixed(4)}"></td>
    <td><select data-cl="${i}" data-k="day_basis">${[365, 360, 366].map(d => `<option ${l.day_basis == d ? 'selected' : ''}>${d}</option>`).join('')}</select></td>
    <td><input type="number" min="0" max="31" data-cl="${i}" data-k="payment_day" value="${l.payment_day ?? 0}" title="0 = 월말"></td>
    <td><button class="del" data-cdl="${i}">✕</button></td><td></td></tr>`).join('') || `<tr><td colspan="7" class="c muted">대출이 없습니다.</td></tr>`;
}
/* 자금 이벤트 필수 항목: Equity 투입·사업비 지급·사업수입은 항상, 대출 약정이 있으면 대출 실행·상환도 1건 이상 */
const evRequired = () => ['equity_in', 'cost', 'receipt', ...(cf.loans.length ? ['draw', 'repay'] : [])];
function ensureBaseEvents() {
  const start = $('c_start')?.value || cf.start || today, end = $('c_end')?.value || cf.end || start;
  const added = [], fresh = !cf.events.length;   // 빈 목록을 처음 채울 때는 알리지 않음
  evRequired().forEach(type => {
    if (cf.events.some(e => e.type === type)) return;
    const ev = { date: ['receipt', 'repay'].includes(type) ? end : start, type, amount: 0 };
    if (['draw', 'repay'].includes(type)) ev.loan_id = cf.loans[0]?.id;
    cf.events.push(ev); added.push(EV_TYPES[type]);
  });
  return fresh ? [] : added;
}
function cfRenderEvents() {
  const added = ensureBaseEvents(), req = evRequired();
  $('evRows').innerHTML = cf.events.map((e, i) => {
    const only = req.includes(e.type) && cf.events.filter(x => x.type === e.type).length === 1;   // 이 유형의 마지막 1건 → 삭제 불가
    return `<tr>
    <td><input type="date" data-ce="${i}" data-k="date" value="${esc(e.date)}"></td>
    <td><div style="display:flex;gap:6px;align-items:center"><select data-ce="${i}" data-k="type" ${only ? 'disabled title="필수 항목 — 유형을 바꾸려면 같은 유형을 하나 더 추가하세요"' : ''}>${Object.entries(EV_TYPES).map(([k, n]) => `<option value="${k}" ${e.type === k ? 'selected' : ''}>${n}</option>`).join('')}</select>${req.includes(e.type) ? '<span class="chip" title="기본 필수 항목">필수</span>' : ''}</div></td>
    <td><select data-ce="${i}" data-k="loan_id" ${['draw', 'repay'].includes(e.type) ? '' : 'disabled'}>${loanOpts(e.loan_id)}</select></td>
    <td><input class="money-in${req.includes(e.type) && !Number(e.amount) ? ' need' : ''}" data-ce="${i}" data-k="amount" value="${fmt(e.amount)}"></td>
    <td><button class="del" data-cde="${i}" ${only ? 'disabled title="필수 항목은 삭제할 수 없습니다"' : 'title="삭제"'}>✕</button></td><td></td></tr>`;
  }).join('');
  $('evCount').textContent = `${cf.events.length}건`;
  if (added.length) notice(`필수 자금 이벤트를 추가했습니다: ${added.join(', ')} — 날짜·금액을 입력하세요.`);
}
function cfSet(p) {
  cf = JSON.parse(JSON.stringify(p)); cf.loans = cf.loans || []; cf.events = cf.events || [];
  $('c_project_type').value = cf.project_type || 'general_housing'; $('c_start').value = cf.start || ''; $('c_end').value = cf.end || '';
  $('c_opening_cash').value = fmt(cf.opening_cash || 0); $('c_minimum_cash').value = fmt(cf.minimum_cash || 0);
  cfRenderLoans(); cfRenderEvents(); refreshHints(); $('cfJson').value = JSON.stringify(cf, null, 2);
}
function cfRead() {
  if (cfMode === 'json') return JSON.parse($('cfJson').value);
  return {
    ...cf, project_type: $('c_project_type').value, start: $('c_start').value, end: $('c_end').value, opening_cash: num('c_opening_cash') ?? 0, minimum_cash: num('c_minimum_cash') ?? 0,
    loans: cf.loans.map(l => ({ ...l })),
    events: cf.events.map(e => { const o = { date: e.date, type: e.type, amount: e.amount }; if (['draw', 'repay'].includes(e.type) && e.loan_id) o.loan_id = e.loan_id; return o; }),
  };
}
$('view-cashflow').addEventListener('change', e => {
  const t = e.target, k = t.dataset.k;
  if (t.dataset.cl !== undefined) {
    const l = cf.loans[t.dataset.cl], old = l.id;
    l[k] = k === 'id' ? t.value.trim() : k === 'annual_rate' ? Number(t.value) / 100 : k === 'day_basis' || k === 'payment_day' ? Number(t.value) : parseNum(t.value) ?? 0;
    if (k === 'id') { cf.events.forEach(ev => { if (ev.loan_id === old) ev.loan_id = l.id; }); cfRenderEvents(); }
  }
  if (t.dataset.ce !== undefined) {
    const ev = cf.events[t.dataset.ce];
    ev[k] = k === 'amount' ? parseNum(t.value) ?? 0 : t.value;
    if (k === 'amount') t.classList.toggle('need', evRequired().includes(ev.type) && !Number(ev.amount));
    if (k === 'type') { if (['draw', 'repay'].includes(ev.type)) { if (!ev.loan_id && cf.loans[0]) ev.loan_id = cf.loans[0].id; } else delete ev.loan_id; cfRenderEvents(); }
  }
});
$('view-cashflow').addEventListener('click', e => {
  const t = e.target;
  if (t.dataset.cdl !== undefined) { cf.loans.splice(t.dataset.cdl, 1); cfRenderLoans(); cfRenderEvents(); }
  if (t.dataset.cde !== undefined && !t.disabled) { cf.events.splice(t.dataset.cde, 1); cfRenderEvents(); }
});
$('cfAddLoan').onclick = () => { cf.loans.push({ id: 'PF-' + (cf.loans.length + 1), limit: 0, annual_rate: 0.08, day_basis: 365, payment_day: 0 }); cfRenderLoans(); cfRenderEvents(); };
$('addEv').onclick = () => { const last = cf.events[cf.events.length - 1]; cf.events.push({ date: last ? last.date : ($('c_start').value || today), type: 'cost', amount: 0 }); cfRenderEvents(); };
$('sortEv').onclick = () => { cf.events.sort((a, b) => a.date.localeCompare(b.date)); cfRenderEvents(); };
$('cfLoad').onclick = async () => { try { cfSet(await api('GET', '/sample?name=' + $('cfSample').value)); notice('샘플을 불러왔습니다.'); } catch (e) { notice(e.message, true); } };
document.querySelectorAll('#cfMode button').forEach(b => b.onclick = () => {
  const m = b.dataset.mode; if (m === cfMode) return;
  try { if (m === 'json') $('cfJson').value = JSON.stringify(cfRead(), null, 2); else cfSet(JSON.parse($('cfJson').value)); }
  catch (err) { notice('JSON 형식 오류: ' + err.message, true); return; }
  cfMode = m; document.querySelectorAll('#cfMode button').forEach(x => x.classList.toggle('on', x === b));
  $('cfForm').classList.toggle('hidden', m === 'json'); $('cfJsonWrap').classList.toggle('hidden', m !== 'json');
});
document.querySelectorAll('#cfUnit button').forEach(b => b.onclick = () => { cfUnit = Number(b.dataset.u); document.querySelectorAll('#cfUnit button').forEach(x => x.classList.toggle('on', x === b)); if (lastCf) $('cfResult').innerHTML = renderCf(lastCf); });
async function cfRun(btn) {
  await busy(btn, async () => {
    let p; try { p = cfRead(); } catch (err) { notice('JSON 형식 오류: ' + err.message, true); return; }
    if (cfMode === 'form') {   // 필수 항목 금액 확인
      const empty = evRequired().filter(type => !cf.events.some(e => e.type === type && Number(e.amount) > 0)).map(t => EV_TYPES[t]);
      if (empty.length) notice(`필수 자금 이벤트 금액이 비어 있습니다: ${empty.join(', ')} — 결과가 실제와 다를 수 있습니다.`, true);
    }
    try { lastCf = await api('POST', '/api/v1/cashflow', p); $('cfResult').innerHTML = renderCf(lastCf); }
    catch (err) { lastCf = null; $('cfResult').innerHTML = errBox(err); }
    $('cfOut').scrollIntoView({ behavior: 'smooth' });
  });
}
$('cfBtn').onclick = e => cfRun(e.target); $('cfBtnTop').onclick = e => cfRun(e.target);
function renderCf(x) {
  const M = x.months.map(m => Object.fromEntries(Object.entries(m).map(([k, v]) => [k, k === 'month' ? v : Number(v)])));
  const sum = k => M.reduce((a, m) => a + m[k], 0), u = v => inUnit(v, cfUnit);
  const gaps = M.filter(m => m.funding_gap > 0), minCash = Math.min(...M.map(m => m.closing_cash)), maxLoan = Math.max(...M.map(m => m.loan_balance));
  const unpaid = Object.entries(x.unpaid_accrued_interest || {}).filter(([, v]) => Number(v) > 0);
  let h = gaps.length ? `<div class="alert bad"><b>자금 부족 ${gaps.length}개월</b> — ${gaps.map(m => `${m.month} (${krwW(m.funding_gap)})`).join(', ')}</div>`
    : `<div class="alert ok"><b>전 기간 자금 부족 없음</b> — 최소 유지 현금 조건을 충족합니다.</div>`;
  if (unpaid.length) h += `<div class="alert warn"><b>사업 종료 시 미지급 이자</b> ${unpaid.map(([k, v]) => `${esc(k)}: ${krwW(v)}`).join(', ')}</div>`;
  h += `<div class="stats"><div class="stat hl"><small>종료 시 현금</small><strong>${krwW(M.at(-1)?.closing_cash)}</strong><em>대출잔액 ${krwW(M.at(-1)?.loan_balance)}</em></div>
    <div class="stat"><small>총 사업수입</small><strong>${krwW(sum('receipt'))}</strong></div><div class="stat"><small>총 사업비</small><strong class="ink">${krwW(sum('cost'))}</strong></div>
    <div class="stat"><small>총 이자비용</small><strong class="ink">${krwW(sum('interest'))}</strong></div><div class="stat"><small>최대 대출잔액</small><strong class="ink">${krwW(maxLoan)}</strong></div>
    <div class="stat"><small>최저 월말 현금</small><strong class="${minCash < 0 ? 'neg' : ''}">${krwW(minCash)}</strong></div></div>`;
  h += cfChart(M);
  const cols = [['month', '월'], ['receipt', '사업수입'], ['cost', '사업비'], ['equity_in', 'Equity 투입'], ['equity_out', 'Equity 회수'], ['draw', '대출 실행'], ['repay', '대출 상환'], ['interest', '이자'], ['closing_cash', '월말 현금'], ['loan_balance', '대출 잔액'], ['funding_gap', '자금 부족']];
  h += `<div class="card-head" style="margin-top:8px"><span class="muted">단위: ${{ 1: '원', 1000000: '백만원', 100000000: '억원' }[cfUnit]}</span><button class="btn ghost" id="cfCsv">CSV 다운로드</button></div>
    <div class="tablewrap"><table><thead><tr>${cols.map((c, i) => `<th class="${i ? 'r' : ''}">${c[1]}</th>`).join('')}</tr></thead><tbody>
    ${M.map(m => `<tr>${cols.map(([k]) => k === 'month' ? `<td><b>${m.month}</b></td>` : `<td class="r ${(k === 'funding_gap' && m[k] > 0) || (k === 'closing_cash' && m[k] < 0) ? 'minus' : ''}">${m[k] ? u(m[k]) : '<span class="muted">–</span>'}</td>`).join('')}</tr>`).join('')}
    </tbody><tfoot><tr class="total">${cols.map(([k]) => k === 'month' ? '<td>합계</td>' : ['closing_cash', 'loan_balance'].includes(k) ? '<td></td>' : `<td class="r">${u(sum(k))}</td>`).join('')}</tr></tfoot></table></div>`;
  return h;
}
document.addEventListener('click', e => {
  if (e.target.id !== 'cfCsv' || !lastCf) return;
  const keys = Object.keys(lastCf.months[0] || {});
  download('cashflow_' + today + '.csv', '﻿' + [keys.join(','), ...lastCf.months.map(m => keys.map(k => m[k]).join(','))].join('\n'), 'text/csv');
});
function cfChart(M) {
  if (!M.length) return '';
  const W = 900, H = 230, P = { l: 60, r: 14, t: 12, b: 28 }, iw = W - P.l - P.r, ih = H - P.t - P.b;
  const vals = M.flatMap(m => [m.closing_cash, m.loan_balance, 0]), max = Math.max(...vals), min = Math.min(...vals), span = (max - min) || 1;
  const y = v => P.t + ih - (v - min) / span * ih, bw = iw / M.length, x = i => P.l + bw * i + bw / 2;
  let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block" role="img" aria-label="월말 현금 및 대출잔액 추이">`;
  [0, 1, 2, 3, 4].map(i => min + span * i / 4).forEach(t => s += `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" stroke="#e6edf1"/><text x="${P.l - 8}" y="${y(t) + 4}" text-anchor="end" font-size="9" fill="#627887">${Math.round(t / 1e8).toLocaleString('ko-KR')}억</text>`);
  s += `<line x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}" stroke="#b5c2cb"/>`;
  M.forEach((m, i) => {
    const v = m.closing_cash, top = Math.min(y(v), y(0)), hh = Math.max(1, Math.abs(y(v) - y(0))), w = Math.min(56, bw * .6);
    s += `<rect x="${x(i) - w / 2}" y="${top}" width="${w}" height="${hh}" rx="3" fill="${v < 0 ? '#b3261e' : '#1e88d6'}"><title>${m.month} 월말 현금 ${krwW(v)}</title></rect><text x="${x(i)}" y="${H - 8}" text-anchor="middle" font-size="9" fill="#627887">${m.month}</text>`;
  });
  s += `<polyline fill="none" stroke="#111a2e" stroke-width="2.5" points="${M.map((m, i) => x(i) + ',' + y(m.loan_balance)).join(' ')}"/>`;
  M.forEach((m, i) => s += `<circle cx="${x(i)}" cy="${y(m.loan_balance)}" r="4" fill="#fff" stroke="#111a2e" stroke-width="2"><title>${m.month} 대출잔액 ${krwW(m.loan_balance)}</title></circle>`);
  return `<div class="legend" style="margin-bottom:6px"><span><i style="background:#1e88d6"></i>월말 현금</span><span><i style="background:#111a2e"></i>대출 잔액</span></div>` + s + '</svg>';
}

/* ═════════════════════ CI 가이드: 색상 견본 ═════════════════════ */
(function swatches() {
  const cs = getComputedStyle(document.documentElement);
  const list = [['--brand-navy', '메인 네이비', '메뉴·심볼 바탕'], ['--brand-navy-2', '네이비 활성', '메뉴 선택'], ['--brand-blue', '포인트 블루', '활성선·차트·포커스'], ['--brand-sky', '스카이', '아이콘 강조'],
    ['--action', '액션 블루', '버튼·링크'], ['--figure', '딥 블루', '금액·핵심 수치'], ['--ink', '본문', '텍스트'], ['--muted', '보조 텍스트', '설명·주석'],
    ['--line', '구분선', '카드 테두리'], ['--surface', '배경', '본문 바탕'], ['--pos', '이익·정상', '긍정 상태'], ['--caution', '주의', '검토 필요'], ['--neg', '손실·위험', '음수·차단']];
  $('swatches').innerHTML = list.map(([v, n, d]) => { const hex = cs.getPropertyValue(v).trim(); return `<div style="border:1px solid var(--line);border-radius:10px;overflow:hidden"><div style="height:54px;background:${hex}"></div><div style="padding:8px 10px;font-size:13px"><b>${n}</b><div class="muted">${hex} · ${d}</div><code style="font-size:11.5px;color:var(--muted-2)">${v}</code></div></div>`; }).join('');
})();

/* ═════════════════════ 시작 ═════════════════════ */
(async () => {
  await loadSites();
  const pref = store.get('develogic.site', null);
  if (pref && siteList.some(s => s.name === pref)) await selectSite(pref);
  else {   // 사업지 미선택: 템플릿으로 화면만 구성 (저장 안 됨)
    try { pfLoad(await api('GET', '/sample?name=proforma'), true); loadOrdinance(false); } catch { notice('템플릿을 불러오지 못했습니다.', true); }
  }
  try { cfSet(await api('GET', '/sample?name=general')); } catch { cfSet({ project_type: 'general_housing', start: today, end: today, loans: [], events: [] }); }
})();
refreshHints();
/* ═════════════════════ 간편 분석 (4단계) ═════════════════════ */
var ezStep = 1, ezTpls = null;
const EZ_ICON = { apartment: '🏘️', mixed_apt: '🏙️', officetel: '🏢', mixed_officetel: '🌆', retail: '🛍️', office: '💼', neighborhood: '🏪', knowledge: '🏭', datacenter: '🖥️', garoju: '🔨', rental: '🔑' };
const ezNum = v => { const n = Number(String(v ?? '').replace(/[^\d.\-]/g, '')); return Number.isFinite(n) ? n : 0; };
function ezRecommend(zone) {
  const z = zone || '';
  if (/전용주거|제1종일반주거/.test(z)) return ['neighborhood', 'apartment'];
  if (/일반주거/.test(z)) return ['apartment', 'neighborhood'];
  if (/준주거/.test(z)) return ['officetel', 'mixed_officetel', 'apartment'];
  if (/상업/.test(z)) return ['mixed_apt', 'mixed_officetel', 'office', 'retail'];
  if (/준공업/.test(z)) return ['knowledge', 'datacenter', 'mixed_apt'];
  if (/공업/.test(z)) return ['knowledge', 'datacenter'];
  return [];
}
function ezGo(n) {
  if (n > 1 && !curSite) { notice('먼저 사업지를 고르거나 만드세요.', true); n = 1; }
  if (n > 1 && !(Number(pf?.land_area_sqm) > 0)) { notice('주소를 조회해 대지면적을 먼저 확인하세요.', true); n = 1; }
  ezStep = n;
  document.querySelectorAll('#view-easy .ez-panel').forEach(p => p.classList.toggle('hidden', Number(p.dataset.ez) !== n));
  document.querySelectorAll('#ezSteps li').forEach(li => { const k = Number(li.dataset.ez); li.classList.toggle('on', k === n); li.classList.toggle('done', k < n); });
  if (n === 1) ezRender1(); if (n === 2) ezRender2(); if (n === 3) ezRender3(); if (n === 4) ezRender4();
  window.scrollTo(0, 0);
}
function easyEnter() { ezGo(ezStep || 1); }
document.addEventListener('click', e => { const b = e.target.closest('[data-ez-go]'); if (b) ezGo(Number(b.dataset.ezGo)); const s = e.target.closest('#ezSteps li'); if (s && Number(s.dataset.ez) <= ezStep + 1) ezGo(Number(s.dataset.ez)); });

/* 1단계 */
function ezRender1() {
  $('ezSite').innerHTML = '<option value="">— 사업지 선택 —</option>' + siteList.map(s => `<option ${s.name === curSite ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
  const ps = (pf?.site?.parcels || []).filter(x => String(x.address || '').trim() || Number(x.area_sqm) > 0);
  if (!curSite) { $('ezParcels').innerHTML = ''; return; }
  const tot = ps.reduce((a, x) => a + Number(x.area_sqm || 0), 0);
  const priced = ps.filter(x => Number(x.price_per_sqm) > 0 && Number(x.area_sqm) > 0);
  const ptot = priced.reduce((a, x) => a + x.price_per_sqm * x.area_sqm, 0);
  const zs = (pf.site.zones || []).slice().sort((a, b) => b.area_sqm - a.area_sqm);
  const munis = [...new Set(ps.map(x => (parseAddress(x.address) || {}).municipality).filter(Boolean))];
  const uses = [...new Set(ps.flatMap(x => (x.uses || []).filter(u => /지구단위|정비|개발제한|군사|문화|고도|경관|토지거래|과밀|저촉/.test(u.name) || u.relation === '저촉').map(u => u.name)))];
  $('ezParcels').innerHTML = ps.length ? `<div class="ez-plist"><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:14px"><b style="font-size:15px">필지 목록</b><span class="muted" style="font-size:13px;margin-right:auto">면적·용도지역·지목·공시지가는 직접 고칠 수 있습니다 — 대지면적과 용도지역별 면적에 바로 반영</span><button type="button" class="btn secondary" data-landuse-report title="모든 필지의 토지이용계획을 최신으로 조회해 반영하고, 열람본(참고용) PDF를 자료함에 저장">📄 토지이용계획 열람본 작성·반영</button><button type="button" class="btn secondary" data-parcel-map title="모든 필지를 한 지도에 경계선으로 표시">🗺 필지 통합 지도 (${ps.length}필지)</button></div><div class="tablewrap" style="margin-top:8px"><table class="edit" id="ezPTable"><thead><tr><th style="width:36px">#</th><th>소재지·지번</th><th class="r">면적 (㎡)</th><th>용도지역</th><th>지목</th><th class="r">공시지가 (원/㎡)</th><th class="r">공시지가 총액</th><th></th><th>자동 조회</th></tr></thead><tbody>
      ${ps.map((x, n) => { const i = pf.site.parcels.indexOf(x), A = k => isAuto(x, k) ? ' auto-val' : ''; return `<tr>
        <td class="c muted">${n + 1}</td>
        <td><div class="ez-addr"><span title="${esc(x.address)}">${esc(x.address)}</span>${x.manual ? '<span class="chip warn" title="지번 미확정 — 직접 입력한 면적">지번 미확정</span>' : mapLinks(x.address)}</div></td>
        <td><input class="money-in${A('area_sqm')}" data-ezp="${i}" data-k="area_sqm" value="${x.area_sqm ? moneyVal(x.area_sqm) : ''}" placeholder="0" style="text-align:right"></td>
        <td><select class="${A('zone')}" data-ezp="${i}" data-k="zone"><option value="">용도지역</option>${ZONE_LIST.map(z => `<option ${z === x.zone ? 'selected' : ''}>${z}</option>`).join('')}</select></td>
        <td><input class="${A('jimok')}" data-ezp="${i}" data-k="jimok" value="${esc(x.jimok || '')}" placeholder="대"></td>
        <td><input class="money-in${A('price_per_sqm')}" data-ezp="${i}" data-k="price_per_sqm" value="${x.price_per_sqm ? fmt(x.price_per_sqm) : ''}" placeholder="자동" style="text-align:right"></td>
        <td class="r money">${x.price_per_sqm && x.area_sqm ? krw(x.price_per_sqm * x.area_sqm) : '–'}</td>
        <td><button class="del" data-ez-del="${i}" title="삭제">✕</button></td>
        <td>${x.manual ? '<span class="muted" style="font-size:12.5px">직접 입력</span>' : `<button type="button" class="btn ghost" data-ez-land="${i}" title="이 필지 다시 조회" style="padding:4px 9px">↻ 조회</button>`}</td></tr>`; }).join('')}</tbody>
      <tfoot><tr class="total"><td></td><td>합계 ${ps.length}필지</td><td class="r">${fmt(tot, 2)}</td><td class="muted">${fmt(PY(tot), 1)}평</td><td></td>
        <td class="r muted" style="font-size:13px">${priced.length ? '평균 ' + fmt(ptot / priced.reduce((a, x) => a + Number(x.area_sqm), 0)) + '원/㎡' : ''}</td><td class="r money">${ptot ? krw(ptot) : '–'}</td>
        <td colspan="2" class="muted" style="font-size:13px">${priced.length ? '평당 ' + fmt(ptot / PY(priced.reduce((a, x) => a + Number(x.area_sqm), 0))) + '원' : ''}</td></tr></tfoot></table></div>
    <div class="ez-sum">
      <div><small>대지면적</small><b>${fmt(tot, 1)}㎡</b><em>${fmt(PY(tot), 1)}평 · ${ps.length}필지</em></div>
      <div><small>용도지역</small><b>${esc(zs.length > 1 ? `${zs.length}개 혼재` : (zs[0]?.zone || '–'))}</b><em>${zs.length > 1 ? zs.map(z => `${esc(z.zone.replace('지역', ''))} ${fmt(z.area_sqm, 0)}㎡(${Math.round(z.area_sqm / tot * 100)}%)`).join(' · ') : esc([pf.site.province, pf.site.municipality].filter(Boolean).join(' '))}</em></div>
      <div><small>공시지가 합계</small><b>${ptot ? krw(ptot) : '–'}</b><em>${ptot ? '평당 ' + fmt(ptot / PY(tot)) + '원 (매입가 아님)' : ''}</em></div>
      <div><small>확인할 규제</small><b class="${uses.length ? 'neg' : ''}">${uses.length ? uses.length + '건' : '없음'}</b><em>${esc(uses.slice(0, 3).join(' · '))}${uses.length > 3 ? ' 외' : ''}</em></div>
    </div></div>${zs.length > 1 ? `<div class="alert info" style="margin:10px 0 0;font-size:13.5px">용도지역이 ${zs.length}개 걸쳐 있어 <b>용도지역별 면적으로 가중한 용적률·건폐율</b>을 적용합니다 (국토계획법 제84조). 가장 넓은 용도지역(${esc(zs[0].zone)}) 기준으로 건물 용도를 추천합니다.</div>` : ''}${munis.length > 1 ? `<div class="alert warn" style="margin:10px 0 0;font-size:13.5px">필지가 서로 다른 시·군·구(${munis.map(esc).join(', ')})에 있습니다. 조례는 첫 필지(${esc(munis[0])}) 기준으로 적용되니 확인하세요.</div>` : ''}` : `<div class="empty ez-hint" style="margin-top:14px;padding:14px 22px">${curSite ? '필지 주소(지번까지)를 입력하고 「＋ 필지 추가」를 누르세요. 필지가 여러 개면 하나씩 이어서 추가합니다.' : ''}</div>`;
}
$('ezSite').onchange = async e => { if (e.target.value) { await selectSite(e.target.value); ezRender1(); } };
function ezNewShow(on) {
  $('ezNewBox').hidden = !on; $('ezNewToggle').hidden = on; $('ezNewToggle').setAttribute('aria-expanded', on);
  if (on) $('ezNewName').focus(); else $('ezNewName').value = '';
}
$('ezNewToggle').onclick = () => ezNewShow(true);
$('ezNewCancel').onclick = () => ezNewShow(false);
$('ezCreate').onclick = async () => {
  const n = $('ezNewName').value.trim(); if (!n) { notice('새 사업지 이름을 입력하세요.', true); return; }
  const reg = pickRegion('ezNewProv', 'ezNewMuni', n); if (!reg) return;
  try { const r = await api('POST', '/api/v4/sites', { name: n }); $('ezNewName').value = ''; await loadSites(); await selectSite(r.name);
    pf.site.parcels = []; pf.site.address = ''; applyRegion(reg); ezRender1(); ezNewShow(false);
    notice(`‘${r.name}’ 사업지를 만들었습니다 — ${reg.province} ${reg.municipality} 조례(용적률·건폐율·주차)를 적용합니다. 주소를 조회하거나 지번 미확정 토지 면적을 입력하세요.`); $('ezAddr').focus(); }
  catch (err) { notice(err.message, true); }
};
/* 여러 필지 주소 펼치기: 줄바꿈·세미콜론으로 나누고, '관양동 1591, 1592-3, 산12'처럼 지번만 이어 쓴 것은 앞 주소를 붙인다 */
function expandAddrs(text) {
  const out = [], JIBUN = /^(?:산\s*)?\d+(?:-\d+)?\s*(?:번지)?$/;
  let prefix = '';   // 앞 줄의 '…동' 까지 — 다음 줄에 지번만 적어도 이어 붙인다
  String(text || '').split(/[\n;]+/).map(x => x.trim()).filter(Boolean).forEach(line => {
    line.split(/\s*[,，、]\s*/).filter(Boolean).forEach(p => {
      if (JIBUN.test(p) && prefix) { out.push(`${prefix} ${p.replace(/\s*번지$/, '')}`); return; }
      out.push(p);
      const m = p.match(/^(.*?)\s*(?:산\s*)?\d+(?:-\d+)?\s*(?:번지)?$/);
      if (m && m[1].trim()) prefix = m[1].trim();
    });
  });
  return [...new Set(out.map(x => x.replace(/\s+/g, ' ').replace(/\s*번지$/, '')))];
}
/* 지도 바로가기: 네이버 지도·카카오맵 검색 링크 (새 탭) */
const mapUrl = (svc, a) => svc === 'naver' ? 'https://map.naver.com/p/search/' + encodeURIComponent(a) : 'https://map.kakao.com/link/search/' + encodeURIComponent(a);
function mapLinks(addr) {
  const a = String(addr || '').trim();
  if (!a) return '';
  return `<span class="map-links"><a class="map-btn naver" href="${esc(mapUrl('naver', a))}" target="_blank" rel="noopener" title="네이버 지도에서 보기">N 지도</a><a class="map-btn kakao" href="${esc(mapUrl('kakao', a))}" target="_blank" rel="noopener" title="카카오맵에서 보기">K 지도</a></span>`;
}
const normAddr = a => String(a || '').replace(/\s+/g, '').replace(/번지$/, '');
async function ezLookup(addr) {
  if (!curSite) { notice('먼저 사업지를 고르거나 만드세요.', true); return; }
  const one = String(addr || $('ezAddr').value).trim();
  if (!one) { notice('필지 주소(지번까지)를 입력하세요.', true); $('ezAddr').focus(); return; }
  if (/[\n;]|,\s*(산\s*)?\d/.test(one)) { notice('한 번에 한 필지만 추가합니다 — 지번 하나를 입력하고 「＋ 필지 추가」를 누른 뒤 다음 필지를 이어서 추가하세요.', true); $('ezAddr').focus(); return; }
  const list = [one];
  if (!pf.site.parcels.some(x => String(x.address || '').trim())) pf.site.parcels = [];
  const have = new Set(pf.site.parcels.map(x => normAddr(x.address)));
  const todo = list.filter(a => !have.has(normAddr(a))), skipped = list.length - todo.length;
  const fails = [], dups = [];
  $('ezLookup').disabled = true;
  try {
    for (const [n, a] of todo.entries()) {
      $('ezParcels').querySelector('.ez-progress')?.remove();
      $('ezParcels').insertAdjacentHTML('afterbegin', `<div class="alert info ez-progress" style="margin:14px 0 0">조회 중… ${todo.length > 1 ? `(${n + 1}/${todo.length}) ` : ''}${esc(a)}</div>`);
      pf.site.parcels.push({ address: a, area_sqm: 0, zone: '', jimok: '' });
      if (!pf.site.address) pf.site.address = a;
      const i = pf.site.parcels.length - 1;
      renderParcels();
      if (await fetchLand(i) === 'dup') { dups.push(a); continue; }
      if (!(Number(pf.site.parcels[i]?.area_sqm) > 0)) { fails.push(a); pf.site.parcels.splice(i, 1); renderParcels(); }
    }
  } finally { $('ezLookup').disabled = false; }
  applyParcels();
  $('ezAddr').value = fails.join('');   // 못 찾으면 그대로 남겨 고쳐서 다시 추가, 성공하면 비워 다음 필지 입력
  $('ezAddr').focus();
  ezRender1();
  const ok = todo.length - fails.length - dups.length;
  if (fails.length) $('ezParcels').insertAdjacentHTML('afterbegin', `<div class="alert warn" style="margin:14px 0 0"><b>${fails.length}필지를 찾지 못했습니다</b> — 지번까지 정확한지 확인해 고친 뒤 다시 「조회」하세요 (입력칸에 남겨 두었습니다).<br>${fails.map(esc).join(' · ')}</div>`);
  notice([ok ? `${ok}필지를 추가했습니다.` : '', skipped + dups.length ? `이미 있는 ${skipped + dups.length}필지는 중복이라 건너뛰었습니다.` : '', fails.length ? `${fails.length}필지 실패.` : ''].filter(Boolean).join(' ') || '추가할 필지가 없습니다.', !!fails.length && !ok);
}
$('ezLookup').onclick = () => ezLookup();
$('ezAddr').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); ezLookup(); } });
$('ezSearch').onclick = () => {
  openAddressSearch(picked => ezLookup(Array.isArray(picked) ? picked[0] : picked), $('ezAddr').value.trim());
};
$('ezParcels').addEventListener('click', e => {
  const d = e.target.closest('[data-ez-del]'); if (!d) return;
  pf.site.parcels.splice(Number(d.dataset.ezDel), 1); renderParcels(); applyParcels(); ezRender1();
});

/* 2단계 */
async function ezRender2() {
  if (!ezTpls) ezTpls = await api('GET', '/api/v4/templates');
  const zone = (pf.site.zones || []).slice().sort((a, b) => b.area_sqm - a.area_sqm)[0]?.zone || '', rec = ezRecommend(zone);   // 여러 용도지역이면 가장 넓은 것 기준
  const cur = pf._tplKey;
  $('ezTiles').innerHTML = ezTpls.map(t => `<button type="button" class="ez-tile${rec.includes(t.key) ? ' rec' : ''}${cur === t.key ? ' sel' : ''}" data-tpl="${esc(t.key)}">
      <span class="ico">${EZ_ICON[t.key] || '🏗'}</span><b>${esc(t.title)}${rec.includes(t.key) ? ' <span class="chip ok">추천</span>' : ''}${cur === t.key ? ' <span class="chip">선택됨</span>' : ''}</b><small>${esc(t.desc)}</small></button>`).join('');
}
function scaleBy(t, k) {
  const r2 = v => Math.round(v * k * 100) / 100;
  t.above_gfa_sqm = r2(t.above_gfa_sqm); t.below_gfa_sqm = r2(t.below_gfa_sqm);
  t.units.forEach(u => {
    if (u.count > 1 || u.kind === 'apartment' || u.kind === 'officetel') u.count = Math.max(1, Math.round(u.count * k));
    else { u.supply_sqm = r2(u.supply_sqm); u.exclusive_sqm = r2(u.exclusive_sqm); }
  });
  t.equity = Math.round(t.equity * k); (t.loans || []).forEach(l => l.amount = Math.round(l.amount * k));
  t.costs.forEach(c => { if (c.basis === 'fixed') c.value = Math.round(c.value * k); });
  return t;
}
$('ezTiles').addEventListener('click', async e => {
  const b = e.target.closest('[data-tpl]'); if (!b) return;
  const key = b.dataset.tpl, info = ezTpls.find(x => x.key === key);
  await busy(b, async () => {
    try {
      const sample = key === 'garoju' || key === 'rental' ? key : 'tpl_' + key;
      const t = await api('GET', '/sample?name=' + sample); delete t._template;
      const saved = siteList.find(s => s.name === curSite)?.result;
      if (saved && pf._tplKey !== key)   // 이미 분석한 사업지는 바꾸기 전 자동 보관
        await api('PUT', siteUrl(curSite, `/proforma?scenario=${encodeURIComponent(today + ' 용도 변경 전 백업')}&memo=${encodeURIComponent('간편 분석에서 「' + info.title + '」 선택 전 자동 보관')}`), pf);
      t.project_name = pf.project_name || curSite; t.site = { ...t.site, ...pf.site, building_area_sqm: null, plan_parking: null };   // 이전 용도의 건축면적·주차 계획은 무효
      scaleTemplate(t, Number(pf.land_area_sqm));
      // 이 땅의 허용 용적률(조례·도시계획)에 맞춰 규모 조정
      const chk = await api('POST', '/api/v3/proforma', t);
      const allowed = chk.compliance?.plan?.gfa ?? chk.compliance?.allowed_gfa_sqm;
      let msg = '';
      if (allowed > 0 && t.above_gfa_sqm > 0 && Math.abs(allowed / t.above_gfa_sqm - 1) > 0.01) {
        scaleBy(t, allowed / t.above_gfa_sqm);
        msg = ` 허용 용적률 ${fmt(allowed / t.land_area_sqm * 100, 0)}%에 맞춰 지상 연면적 ${fmt(t.above_gfa_sqm, 0)}㎡로 조정했습니다.`;
      }
      t.template_key = sample; pfLoad(t, false); pf._tplKey = key; loadOrdinance(false); renderScnSelect();
      notice(`「${info.title}」으로 구성했습니다.${msg}`);
      ezGo(3);
    } catch (err) { notice(err.message, true); }
  });
});

/* 3단계 */
function ezCost(cat, basis) { return pf.costs.find(c => c.category === cat && c.basis === basis); }
function ezField(label, val, key, unit, hint) {
  return `<label class="ez-f"><span>${label}</span><div class="unit"><input class="money-in" data-ezk="${key}" value="${val ? fmt(val) : ''}" inputmode="numeric"><span>${unit}</span></div>${hint ? `<small>${hint}</small>` : ''}</label>`;
}
function ezRender3() {
  const land = ezCost('land', 'per_land_py'), ca = ezCost('construction', 'per_above_py'), cb = ezCost('construction', 'per_below_py');
  const pub = pf.site.parcels.filter(x => x.price_per_sqm && x.area_sqm), pubPy = pub.length ? pub.reduce((a, x) => a + x.price_per_sqm * x.area_sqm, 0) / PY(pub.reduce((a, x) => a + Number(x.area_sqm), 0)) : 0;
  $('ezLand').innerHTML = land ? ezField('토지 매입가 (평당)', land.value, 'land', '원/평', pubPy ? `공시지가 평당 ${fmt(pubPy)}원 → 매입가는 공시지가의 <b>${fmt(land.value / pubPy, 1)}배</b>` : `대지 ${fmt(PY(pf.land_area_sqm), 1)}평 × 평당가`) : '<span class="muted">토지비 항목 없음 (상세 화면)</span>';
  $('ezCons').innerHTML = (ca ? ezField('지상 공사비 (평당)', ca.value, 'ca', '원/평', `지상 ${fmt(PY(pf.above_gfa_sqm), 0)}평`) : '') + (cb ? ezField('지하 공사비 (평당)', cb.value, 'cb', '원/평', `지하 ${fmt(PY(pf.below_gfa_sqm), 0)}평`) : '');
  $('ezFin').innerHTML = ezField('자기자본', pf.equity, 'equity', '원', '내가 넣는 돈 (대출 제외)') + `<label class="ez-f"><span>총 사업기간</span><div class="unit"><input data-ezk="months" value="${pf.duration_months}" inputmode="numeric"><span>개월</span></div><small>토지 계약 ~ 입주·정산</small></label>`;
  $('ezUnits').innerHTML = `<div class="tablewrap"><table class="ez-units"><thead><tr><th style="width:150px">타입</th><th style="width:120px">용도</th><th class="r" style="width:90px">세대·호</th><th class="r" style="width:170px">공급면적</th><th class="r" style="width:200px">평당 분양가</th><th class="r" style="width:160px">타입 매출</th><th></th></tr></thead><tbody>
    ${pf.units.map((u, i) => `<tr><td><b>${esc(u.name)}</b></td><td class="muted">${esc(KINDS[u.kind] || u.kind)}</td><td class="r">${fmt(u.count)}</td><td class="r">${fmt(u.supply_sqm, 1)}㎡ <span class="muted">${fmt(PY(u.supply_sqm), 1)}평</span></td>
      <td class="r"><div class="unit"><input class="money-in" data-ezu="${i}" value="${fmt(u.price_per_py)}" inputmode="numeric"><span>원</span></div></td><td class="r money" data-ezut="${i}">${krw(PY(u.supply_sqm) * u.price_per_py * u.count)}</td><td></td></tr>`).join('')}</tbody></table></div>
    <div class="ez-adj"><span>분양가 한꺼번에 조정</span>${[-10, -5, 5, 10].map(p => `<button type="button" class="btn ghost" data-ezadj="${p}">${p > 0 ? '+' : ''}${p}%</button>`).join('')}<small class="muted">세대수·면적은 상세 화면 › 분양 계획에서 바꿀 수 있습니다</small></div>`;
  fitUnitPaddingIn($('view-easy'));
  ezLive(); pfRecalc(true);
}
function fitUnitPaddingIn(root) {
  const ctx = document.createElement('canvas').getContext('2d');
  root.querySelectorAll('.unit').forEach(u => { const sp = u.querySelector(':scope > span'), inp = u.querySelector('input'); if (!sp || !inp) return;
    const cs = getComputedStyle(sp); ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`; inp.style.paddingRight = Math.ceil(ctx.measureText(sp.textContent).width + 18) + 'px'; });
}
$('view-easy').addEventListener('input', e => {
  const t = e.target, v = ezNum(t.value);
  if (t.dataset.ezk) {
    const k = t.dataset.ezk;
    if (k === 'land') ezCost('land', 'per_land_py').value = v;
    if (k === 'ca') ezCost('construction', 'per_above_py').value = v;
    if (k === 'cb') ezCost('construction', 'per_below_py').value = v;
    if (k === 'equity') pf.equity = v;
    if (k === 'months') pf.duration_months = Math.max(1, Math.round(v));
  } else if (t.dataset.ezu !== undefined) {
    const u = pf.units[Number(t.dataset.ezu)]; u.price_per_py = v;
    const c = document.querySelector(`[data-ezut="${t.dataset.ezu}"]`); if (c) c.textContent = krw(PY(u.supply_sqm) * v * u.count);
  } else return;
  fillFields(); renderUnits(); pfRecalc();
});
$('view-easy').addEventListener('focusout', e => { const t = e.target; if (t.classList?.contains('money-in') && (t.dataset.ezk || t.dataset.ezu !== undefined)) t.value = ezNum(t.value) ? fmt(ezNum(t.value)) : ''; });
$('view-easy').addEventListener('click', e => {
  const b = e.target.closest('[data-ezadj]'); if (!b) return;
  const k = 1 + Number(b.dataset.ezadj) / 100;
  pf.units.forEach(u => { u.price_per_py = Math.round(u.price_per_py * k / 10000) * 10000; });
  renderUnits(); ezRender3();
});
function ezLive() {
  if (!document.getElementById('view-easy')?.classList.contains('active') || !lastPf) return;
  const s = lastPf.summary, v = lastPf.verdict, tone = { ok: 'ok', warn: 'warn', bad: 'bad' }[v.overall];
  $('ezLive').innerHTML = `<div><small>총매출</small><b>${krw(s.revenue_net)}</b></div><div><small>총사업비</small><b>${krw(s.total_cost)}</b></div>
    <div><small>세전이익</small><b class="${s.pbt < 0 ? 'neg' : 'pos'}">${krw(s.pbt)}</b></div><div><small>매출이익률</small><b>${pct(s.margin_pct)}</b></div>
    <div><small>판정</small><span class="chip ${tone}">${esc(v.label.split(' — ')[0].split(' (')[0])}</span></div>`;
  if (ezStep === 4) ezRender4(true);
}

/* 4단계 */
let ezStress = null;
async function ezRender4(liveOnly) {
  if (!lastPf) { pfRecalc(true); return; }
  const s = lastPf.summary, v = lastPf.verdict, tone = { ok: 'ok', warn: 'warn', bad: 'bad' }[v.overall];
  const bad = (v.reasons || []).filter(x => x.status === 'bad'), warn = (v.reasons || []).filter(x => x.status === 'warn');
  const say = v.overall === 'ok' ? '판정 기준을 모두 충족합니다. 사업을 추진해 볼 만합니다.' : v.overall === 'warn' ? '추진은 가능하지만 아래 확인 사항을 해소해야 합니다.' : '지금 숫자로는 추진하기 어렵습니다. 아래 사유를 먼저 해결하세요.';
  $('ezResult').innerHTML = `<div class="ez-verdict ${tone}"><div><small>${esc(curSite || '')}</small><h2>${esc(v.label)}</h2><p>${say}</p></div></div>
    <div class="ez-kpis">
      <div><small>세전이익</small><b class="${s.pbt < 0 ? 'neg' : 'pos'}">${krw(s.pbt)}</b><em>총매출 ${krw(s.revenue_net)} − 총사업비 ${krw(s.total_cost)}</em></div>
      <div><small>매출이익률 <span class="qhelp" title="세전이익 ÷ 총매출 — 보통 10% 이상이면 양호">?</span></small><b>${pct(s.margin_pct)}</b><em>기준 ${fmt(pf.criteria?.margin_min_pct ?? 10)}% 이상</em></div>
      <div><small>BEP 분양률 <span class="qhelp" title="이만큼만 팔려도 손해가 없음 — 낮을수록 안전">?</span></small><b>${s.bep_sales_rate_pct != null ? pct(s.bep_sales_rate_pct) : '–'}</b><em>이만큼 팔리면 본전</em></div>
      <div><small>자기자본 수익률 (IRR) <span class="qhelp" title="내가 넣은 돈의 연 수익률 (세후)">?</span></small><b>${s.equity_irr_pct != null ? pct(s.equity_irr_pct) : '–'}</b><em>자기자본 ${krw(pf.equity)}</em></div>
    </div>
    ${bad.length || warn.length ? `<div class="ez-why"><h3>${bad.length ? `해결해야 할 사유 ${bad.length}건` : `확인할 사항 ${warn.length}건`}</h3><ol>${(bad.length ? bad : warn).slice(0, 6).map(x => `<li><span class="chip gray">${x.area}</span> ${esc(x.text)}</li>`).join('')}</ol>
      ${bad.length && warn.length ? `<small class="muted">그 밖에 확인할 사항 ${warn.length}건은 상세 화면 › 수지표·판정에 있습니다.</small>` : ''}</div>` : ''}
    <div class="ez-why"><h3>나쁜 일이 생기면? <small class="muted">위험 점검</small></h3><div id="ezStress"><span class="muted">계산 중…</span></div></div>`;
  if (liveOnly && ezStress) return ezStressRender();
  try { ezStress = (await api('POST', '/api/v4/proforma/stress', pf)).cases; ezStressRender(); }
  catch (err) { $('ezStress').innerHTML = errBox(err); }
}
function ezStressRender() {
  const el = document.getElementById('ezStress'); if (!el || !ezStress) return;
  const b = ezStress[0].kpi;
  el.innerHTML = `<div class="ez-stress">${ezStress.slice(1).filter(c => !c.error).map(c => { const d = c.kpi.pbt - b.pbt;
    return `<div class="${c.kpi.pbt < 0 ? 'bad' : d < -Math.abs(b.pbt) * 0.3 ? 'warn' : ''}"><b>${esc(c.label)}</b><span>${c.kpi.pbt < 0 ? '손실 ' + krw(-c.kpi.pbt) : '이익 ' + krw(c.kpi.pbt)}</span><small>${Math.abs(d) < 1e4 ? '변화 없음' : (d < 0 ? '▼ ' : '▲ ') + krw(Math.abs(d))}</small></div>`; }).join('')}</div>`;
}
$('ezSave').onclick = () => saveScenario(pf);
$('ezExcel').onclick = () => $('pfExcel').click();

show(location.hash.slice(1) || PATH_DEFAULT[location.pathname] || 'easy');

/* ═════════════════════ 날짜 칸 공통 달력 (청우종합관리 통합관리웹과 동일) ═════════════════════
   type=date / type=month 입력칸을 큰 달력 팝업으로 바꾼다. 나중에 표에 추가되는 칸도 자동 적용. */
(function datePicker() {
  const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const mk = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag); Object.entries(attrs).forEach(([k, v]) => k === 'onclick' ? e.onclick = v : e.setAttribute(k, v)); e.append(...kids); return e; };
  const close = () => document.getElementById('dpop')?.remove();
  function open(input) {
    close();
    const month = input.dataset.dp === 'month';
    const re = month ? /^\d{4}-\d{2}$/ : /^\d{4}-\d{2}-\d{2}$/;
    const cur = re.test(input.value) ? new Date(input.value + (month ? '-01' : '') + 'T00:00:00') : new Date();
    let y = cur.getFullYear(), m = cur.getMonth();
    const box = mk('div', { class: 'dpop', id: 'dpop' });
    const pick = v => { input.value = v; close(); input.focus(); input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true })); };
    const draw = () => {
      const today = ymd(new Date());
      let grid, title, mv;
      if (month) {
        grid = mk('div', { class: 'dp-grid months' });
        for (let i = 0; i < 12; i++) {
          const v = `${y}-${String(i + 1).padStart(2, '0')}`;
          grid.append(mk('button', { type: 'button', class: (v === input.value ? 'sel ' : '') + (v === today.slice(0, 7) ? 'td' : ''), onclick: () => pick(v) }, `${i + 1}월`));
        }
        title = `${y}년`; mv = n => { y += n; draw(); };
      } else {
        const first = new Date(y, m, 1), start = new Date(y, m, 1 - first.getDay());
        grid = mk('div', { class: 'dp-grid' }, ...['일', '월', '화', '수', '목', '금', '토'].map(w => mk('b', {}, w)));
        for (let i = 0; i < 42; i++) {
          const d = new Date(start); d.setDate(start.getDate() + i); const ds = ymd(d);
          grid.append(mk('button', { type: 'button', class: (d.getMonth() !== m ? 'o ' : '') + (ds === input.value ? 'sel ' : '') + (ds === today ? 'td' : ''), onclick: () => pick(ds) }, String(d.getDate())));
        }
        title = `${y}년 ${m + 1}월`; mv = n => { m += n; if (m < 0) { m = 11; y--; } if (m > 11) { m = 0; y++; } draw(); };
      }
      box.replaceChildren(
        mk('div', { class: 'dp-head' }, mk('b', {}, title), mk('span', {}, mk('button', { type: 'button', title: month ? '이전 해' : '이전 달', onclick: () => mv(-1) }, '↑'), mk('button', { type: 'button', title: month ? '다음 해' : '다음 달', onclick: () => mv(1) }, '↓'))),
        grid,
        mk('div', { class: 'dp-foot' }, mk('button', { type: 'button', onclick: () => pick('') }, '지우기'), mk('button', { type: 'button', onclick: () => pick(month ? today.slice(0, 7) : today) }, month ? '이번 달' : '오늘')));
    };
    draw(); document.body.append(box);
    const r = input.getBoundingClientRect();
    const left = Math.min(r.left + scrollX, scrollX + innerWidth - box.offsetWidth - 8);
    const below = r.bottom + box.offsetHeight + 8 < innerHeight;
    box.style.left = Math.max(8, left) + 'px';
    box.style.top = (below ? r.bottom + scrollY + 4 : r.top + scrollY - box.offsetHeight - 4) + 'px';
  }
  function enhance(root) {
    root.querySelectorAll?.('input[type=date], input[type=month]').forEach(input => {
      input.dataset.dp = input.type; input.type = 'text'; input.autocomplete = 'off'; input.classList.add('dpin');
      input.placeholder = input.dataset.dp === 'month' ? '연도-월' : '연도-월-일'; input.inputMode = 'numeric';
    });
  }
  enhance(document);
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => n.nodeType === 1 && enhance(n.parentNode || n)))).observe(document.body, { childList: true, subtree: true });
  document.addEventListener('click', e => { const t = e.target; if (t.classList?.contains('dpin')) open(t); });
  document.addEventListener('keydown', e => {
    const t = e.target;
    if (t.classList?.contains('dpin')) { if (e.key === 'ArrowDown' || e.key === 'Enter') { e.preventDefault(); open(t); } if (e.key === 'Escape' || e.key === 'Tab') close(); }
  });
  addEventListener('mousedown', e => { const p = document.getElementById('dpop'); if (p && !p.contains(e.target) && !e.target.classList?.contains('dpin')) close(); });
  addEventListener('scroll', () => close(), { passive: true });
})();

/* ═════════════════════ 주소 검색 (Kakao·Daum 우편번호 서비스, 무료·키 불필요) ═════════════════════
   선택한 주소의 지번 주소를 사업지 주소에 넣고 → 시·도/시·군·구 인식 → 조례 자동 적용 */
(function addressSearch() {
  const SRC = 'https://t1.kakaocdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js';   // 2026-11-30 daumcdn 종료 → kakaocdn
  let loading = null;
  const load = () => loading || (loading = new Promise((ok, fail) => {
    if (window.daum?.Postcode) return ok();
    const s = document.createElement('script'); s.src = SRC; s.onload = ok; s.onerror = () => { loading = null; fail(new Error('주소 검색 서비스를 불러오지 못했습니다 (인터넷 연결 확인)')); };
    document.head.appendChild(s);
  }));
  function close() {
    const l = document.getElementById('addrLayer'); if (!l) return;
    l.classList.remove('show'); setTimeout(() => l.remove(), 160);
    document.removeEventListener('keydown', onKey);
  }
  const onKey = ev => { if (ev.key === 'Escape') close(); };
  // opts.multi: 고를 때마다 목록에 쌓고 계속 검색 → 「선택한 N필지 추가」로 한꺼번에 onPick(목록) (간편 분석 여러 필지)
  async function open(onPick, query, opts = {}) {
    const picked = [];
    try { await load(); } catch (err) { notice(err.message, true); return; }
    document.getElementById('addrLayer')?.remove();
    const layer = document.createElement('div');
    layer.id = 'addrLayer'; layer.className = 'addr-modal';
    layer.innerHTML = `<div class="addr-dialog" role="dialog" aria-modal="true" aria-labelledby="addrTitle">
        <div class="addr-head">
          <div class="addr-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-6 8-12a8 8 0 0 0-16 0c0 6 8 12 8 12z"/><circle cx="12" cy="10" r="3"/></svg></div>
          <div class="addr-title"><b id="addrTitle">사업지 주소 검색</b><small>도로명·건물명·지번으로 검색 → 선택하면 지번 주소가 입력되고 해당 지역 조례가 자동 적용됩니다</small></div>
          <button type="button" class="addr-x" id="addrClose" aria-label="닫기">✕</button>
        </div>
        <div id="addrBox" class="addr-body"></div>
        ${opts.multi ? `<div class="addr-picked" id="addrPicked"><span class="muted">검색해서 고를 때마다 여기에 쌓입니다 (여러 필지 선택 가능)</span></div>` : ''}
        <div class="addr-foot"><span>예) 서초동 1376 · 서초대로 219 · 서초 ○○아파트</span><span>주소 데이터: 카카오 우편번호 서비스</span></div>
      </div>`;
    document.body.appendChild(layer);
    requestAnimationFrame(() => layer.classList.add('show'));
    layer.addEventListener('click', ev => { if (ev.target === layer || ev.target.closest('#addrClose')) close(); });
    document.addEventListener('keydown', onKey);
    const renderPicked = () => {
      const box = document.getElementById('addrPicked'); if (!box) return;
      box.innerHTML = picked.length ? `<div class="addr-chips">${picked.map((a, i) => `<span class="chip">${esc(a)} <button type="button" data-unpick="${i}" title="빼기">✕</button></span>`).join('')}</div>
        <button type="button" class="btn" id="addrDone">선택한 ${picked.length}필지 추가</button>` : '<span class="muted">검색해서 고를 때마다 여기에 쌓입니다 (여러 필지 선택 가능)</span>';
    };
    layer.addEventListener('click', ev => {
      const u = ev.target.closest('[data-unpick]'); if (u) { picked.splice(Number(u.dataset.unpick), 1); renderPicked(); return; }
      if (ev.target.closest('#addrDone')) { close(); onPick(picked.slice()); }
    });
    const embed = q => new window.daum.Postcode({
      width: '100%', height: '100%', animation: true, hideMapBtn: true, hideEngBtn: true, focusInput: true,
      theme: { bgColor: '#F2F7FC', searchBgColor: '#111A2E', queryTextColor: '#FFFFFF', contentBgColor: '#FFFFFF', pageBgColor: '#F4F8FA',
        textColor: '#142638', postcodeTextColor: '#0B78C2', emphTextColor: '#1E88D6', outlineColor: '#E1E9ED' },
      oncomplete: data => {
        // 지번 주소 우선 (토지이용계획·조례 판정 기준). 지번이 없으면 자동 지번 → 도로명
        const jibun = data.jibunAddress || data.autoJibunAddress || data.address;
        if (opts.multi) {   // 목록에 쌓고 새 검색창으로 계속
          if (!picked.some(a => addrKey(a) === addrKey(jibun))) picked.push(jibun); else notice('이미 고른 주소입니다: ' + jibun, true);
          renderPicked(); document.getElementById('addrBox').innerHTML = ''; embed('');
          return;
        }
        close();
        onPick(jibun, data);
      },
    }).embed(document.getElementById('addrBox'), { q: (q || '').trim(), autoClose: false });
    embed(query);
  }
  window.openAddressSearch = open;
  document.addEventListener('click', e => {
    if (e.target.closest?.('#addrSearch') == null) return;
    open((jibun, data) => {
      pf.site.address = jibun;
      $('s_address').value = jibun;
      $('addrHint').textContent = data.roadAddress ? '도로명: ' + data.roadAddress : '';
      applyAddress();
      // 필지 목록: 비어 있으면 1행을 만들고, 빈 행에 주소를 넣은 뒤 면적·지목·용도지역 자동 조회
      let row = pf.site.parcels.findIndex(x => !String(x.address || '').trim());
      if (!pf.site.parcels.length) { pf.site.parcels.push({ address: '', area_sqm: 0, zone: '', jimok: '' }); row = 0; }
      if (row >= 0) {
        pf.site.parcels[row].address = jibun;
        renderParcels(); applyParcels();
        fetchLand(row);
      } else notice('주소를 선택했습니다: ' + jibun);
    }, $('s_address').value);
  });
})();

/* 직접 입력한 주소도 조회: 필지 주소 칸 입력 완료(change) → 자동 조회 */
document.addEventListener('change', e => {
  const t = e.target;
  if (t.dataset?.pl !== undefined && t.dataset.k === 'address' && String(t.value).trim()) fetchLand(Number(t.dataset.pl));
  if (t.id === 's_address' && String(t.value).trim() && pf) {
    let row = pf.site.parcels.findIndex(x => !String(x.address || '').trim());
    if (!pf.site.parcels.length) { pf.site.parcels.push({ address: '', area_sqm: 0, zone: '', jimok: '' }); row = 0; }
    if (row >= 0) { pf.site.parcels[row].address = t.value.trim(); renderParcels(); fetchLand(row); }
  }
});

/* 단위 붙은 입력칸: 숫자를 오른쪽 정렬하고 단위 글자 바로 앞(8px 띄움)에 붙임 — 단위 길이(대·㎡/대·%p)에 맞춰 여백 계산 */
(function fitUnitPadding() {
  const ctx = document.createElement('canvas').getContext('2d');
  document.querySelectorAll('.unit').forEach(u => {
    if (u.closest('.edit')) return;
    const sp = u.querySelector(':scope > span'), inp = u.querySelector('input');
    if (!sp || !inp) return;
    const cs = getComputedStyle(sp);
    ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    inp.style.paddingRight = Math.ceil(ctx.measureText(sp.textContent).width + 10 + 8) + 'px';
  });
})();


/* ═════════════════════ 필지 통합 지도 (브이월드 연속지적도 · 일반/위성) ═════════════════════ */
let leafletReady = null, pmap = null, pmapBase = null, pmapLayer = 'Base', pmapShapes = null;
function loadLeaflet() {
  if (window.L && window.L.map) return Promise.resolve();
  if (leafletReady) return leafletReady;
  leafletReady = new Promise((ok, fail) => {
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'; document.head.appendChild(css);
    const js = document.createElement('script'); js.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'; js.onload = ok;
    js.onerror = () => { leafletReady = null; fail(new Error('지도 라이브러리를 불러오지 못했습니다 (인터넷 연결 확인)')); };
    document.head.appendChild(js);
  });
  return leafletReady;
}
const ZONE_COLOR = z => /상업/.test(z) ? '#d9480f' : /준주거/.test(z) ? '#e67700' : /제3종/.test(z) ? '#a61e4d' : /제2종/.test(z) ? '#c2255c' : /제1종|전용/.test(z) ? '#e64980'
  : /공업/.test(z) ? '#5f3dc4' : /녹지/.test(z) ? '#2b8a3e' : /관리|농림|보전/.test(z) ? '#5c940d' : '#1e88d6';
function setMapLayer(layer) {
  pmapLayer = layer;
  document.querySelectorAll('#mapLayer button').forEach(b => b.classList.toggle('on', b.dataset.layer === layer));
  if (!pmap) return;
  if (pmapBase) pmap.removeLayer(pmapBase);
  const tiles = [L.tileLayer(`/api/v4/maptile/${layer}/{z}/{y}/{x}`, { maxZoom: 19, maxNativeZoom: layer === 'white' ? 18 : 19, minZoom: 6, attribution: '© 국토교통부 브이월드' })];   // 라이트 지도는 18레벨까지 → 19는 확대 표시
  if (layer === 'Satellite') tiles.push(L.tileLayer('/api/v4/maptile/Hybrid/{z}/{y}/{x}', { maxZoom: 19, minZoom: 6 }));   // 위성 + 지명·도로
  pmapBase = L.layerGroup(tiles).addTo(pmap);
  if (pmapShapes) pmapShapes.bringToFront();
}
async function openParcelMap() {
  pickMode = false; $('mapCanvas').classList.remove('picking'); if (pickSel && pmap) { pmap.removeLayer(pickSel); pickSel = null; }
  const ps = (pf?.site?.parcels || []).filter(x => !x.manual && (String(x.address || '').trim() || x.pnu));
  if (!ps.length) { notice('지도에 표시할 필지가 없습니다. 주소를 먼저 조회하세요.', true); return; }
  $('mapBack').classList.remove('hidden');
  $('mapTitle').textContent = `필지 통합 지도 · ${curSite || ''}`;
  $('mapSide').innerHTML = '<div class="muted" style="padding:6px">필지 경계를 불러오는 중…</div>'; $('mapExt').innerHTML = '';
  try {
    await loadLeaflet();
    if (!pmap) { pmap = L.map('mapCanvas', { zoomControl: true }); setMapLayer(pmapLayer); pmap.setView([36.5, 127.8], 7); }
    setTimeout(() => pmap.invalidateSize(), 60);
    const r = await api('POST', '/api/v4/land/shapes', { items: ps.map(x => ({ address: String(x.address || ''), pnu: String(x.pnu || '') })) });
    if (pmapShapes) pmap.removeLayer(pmapShapes);
    pmapShapes = L.featureGroup().addTo(pmap);
    const ok = [], fail = [];
    r.features.forEach(f => {
      const i = f.properties.idx, x = ps[i], n = i + 1;
      if (!f.geometry) { fail.push(`${n}. ${x.address} — ${f.properties.error || '경계 없음'}`); return; }
      const c = ZONE_COLOR(x.zone || '');
      const base = { color: c, weight: 2.5, opacity: .95, fillColor: c, fillOpacity: .16, lineJoin: 'round' };
      const lay = L.geoJSON(f, { style: base, onEachFeature: (_, l) => l.on({ mouseover: () => l.setStyle({ weight: 3.5, fillOpacity: .32 }), mouseout: () => l.setStyle(base) }) })
        .bindTooltip(String(n), { permanent: true, direction: 'center', className: 'pmap-num' })
        .bindPopup(`<b>${n}. ${esc(x.address)}</b><br>${fmt(x.area_sqm, 1)}㎡ (${fmt(PY(x.area_sqm), 1)}평) · ${esc(x.zone || '용도지역 미확인')}${x.price_per_sqm ? `<br>공시지가 ${fmt(x.price_per_sqm)}원/㎡` : ''}<div style="margin-top:6px">${mapLinks(x.address)}</div>`);
      lay._pmapIdx = i;
      lay.addTo(pmapShapes); ok.push(x);
    });
    if (ok.length) pmap.fitBounds(pmapShapes.getBounds(), { padding: [60, 60], maxZoom: 18 });
    const tot = ok.reduce((a, x) => a + Number(x.area_sqm || 0), 0), zones = {};
    ok.forEach(x => { const z = x.zone || '미확인'; zones[z] = (zones[z] || 0) + Number(x.area_sqm || 0); });
    const ctr = ok.length ? pmapShapes.getBounds().getCenter() : null;
    if (ctr) $('mapExt').innerHTML = `<span class="map-links"><a class="map-btn kakao" target="_blank" rel="noopener" href="https://map.kakao.com/link/map/${encodeURIComponent((curSite || '사업지') + ' 중심')},${ctr.lat.toFixed(6)},${ctr.lng.toFixed(6)}" title="필지들의 중심을 카카오맵에서">K 지도(중심)</a><a class="map-btn naver" target="_blank" rel="noopener" href="${esc(mapUrl('naver', ok[0].address))}" title="첫 필지를 네이버 지도에서">N 지도</a></span>`;
    $('mapSide').innerHTML = `<div class="pmap-sum"><small>표시 필지</small><b>${ok.length}필지${fail.length ? ` <span class="neg" style="font-size:13px">(${fail.length} 실패)</span>` : ''}</b>
        <small>합계 면적</small><b>${fmt(tot, 1)}㎡</b><em>${fmt(PY(tot), 1)}평</em>
        <small>용도지역</small>${Object.entries(zones).sort((a, b) => b[1] - a[1]).map(([z, a]) => `<div class="pmap-zone"><i style="background:${ZONE_COLOR(z)}"></i>${esc(z)} <span class="muted">${fmt(a, 0)}㎡ · ${tot ? Math.round(a / tot * 100) : 0}%</span></div>`).join('')}</div>
      <ol class="pmap-list">${ps.map((x, i) => `<li data-pmap-i="${i}" class="${ok.includes(x) ? '' : 'muted'}" title="이 필지로 이동"><b>${esc(String(x.address).replace(/^.*?(\S+[동리가]\s)/, '$1'))}</b> <span class="muted">${fmt(x.area_sqm, 0)}㎡</span></li>`).join('')}</ol>
      ${fail.length ? `<div class="alert warn" style="font-size:12.5px;margin:8px 0 0">${fail.map(esc).join('<br>')}</div>` : ''}
      <p class="muted" style="font-size:12px;margin:8px 0 0">경계: 국토교통부 연속지적도(브이월드) · 참고용이며 측량 성과가 아닙니다.</p>`;
  } catch (err) { $('mapSide').innerHTML = errBox(err); }
}
document.addEventListener('click', e => {
  if (e.target.closest('[data-parcel-map]')) { openParcelMap(); return; }
  const lb = e.target.closest('#mapLayer [data-layer]'); if (lb) { setMapLayer(lb.dataset.layer); return; }
  const li = e.target.closest('[data-pmap-i]');
  if (li && pmapShapes) {   // 목록에서 필지를 누르면 그 필지로 이동
    const lay = pmapShapes.getLayers().find(l => l._pmapIdx === Number(li.dataset.pmapI));
    if (lay) { pmap.fitBounds(lay.getBounds(), { maxZoom: 19, padding: [60, 60] }); lay.openPopup(); }
  }
});
$('mapClose').onclick = () => { $('mapBack').classList.add('hidden'); pickMode = false; $('mapCanvas').classList.remove('picking'); if (pickSel) { pmap.removeLayer(pickSel); pickSel = null; } };

/* 지도에서 필지 선택: 지도를 누르면 그 자리의 필지(연속지적도)를 보여 주고 「＋ 이 필지 추가」로 간편 분석에 추가 */
let pickMode = false, pickSel = null, pickAdded = [];
async function openParcelPicker() {
  if (!curSite) { notice('먼저 사업지를 고르거나 만드세요.', true); return; }
  pickAdded = [];
  $('mapBack').classList.remove('hidden');
  $('mapTitle').textContent = `지도에서 필지 선택 · ${curSite}`;
  $('mapExt').innerHTML = '';
  pickSide('<div class="muted">지도를 불러오는 중…</div>');
  try {
    await loadLeaflet();
    if (!pmap) { pmap = L.map('mapCanvas', { zoomControl: true }); setMapLayer(pmapLayer); pmap.setView([36.5, 127.8], 7); }
    pickMode = true; $('mapCanvas').classList.add('picking');
    if (!pmap._pickBound) { pmap.on('click', e => { if (pickMode) pickAt(e.latlng); }); pmap._pickBound = true; }
    setTimeout(() => pmap.invalidateSize(), 60);
    if (pmapShapes) { pmap.removeLayer(pmapShapes); pmapShapes = null; }
    if (pickSel) { pmap.removeLayer(pickSel); pickSel = null; }
    const ps = (pf?.site?.parcels || []).filter(x => !x.manual && (String(x.address || '').trim() || x.pnu));
    let placed = false;
    if (ps.length) {
      const r = await api('POST', '/api/v4/land/shapes', { items: ps.map(x => ({ address: String(x.address || ''), pnu: String(x.pnu || '') })) });
      pmapShapes = L.featureGroup().addTo(pmap);
      r.features.forEach(f => { if (f.geometry) L.geoJSON(f, { style: { color: '#1e7b3a', weight: 2, fillColor: '#1e7b3a', fillOpacity: .25 }, interactive: false })
        .bindTooltip(String(f.properties.idx + 1), { permanent: true, direction: 'center', className: 'pmap-num' }).addTo(pmapShapes); });
      if (pmapShapes.getLayers().length) { pmap.fitBounds(pmapShapes.getBounds(), { padding: [60, 60], maxZoom: 18 }); placed = true; }
    }
    if (!placed) {
      const q = [pf?.site?.province, pf?.site?.municipality].filter(Boolean).join(' ') || guessRegion(curSite) && Object.values(guessRegion(curSite)).join(' ') || '';
      const c = q ? await api('GET', '/api/v4/land/center?q=' + encodeURIComponent(q)).catch(() => ({})) : {};
      if (c.lat) pmap.setView([c.lat, c.lon], 17); else pmap.setView([37.5663, 126.9779], 16);
    }
    pickSide();
  } catch (err) { pickSide(errBox(err)); }
}
function pickSide(extra = '') {
  const ps = (pf?.site?.parcels || []).filter(x => String(x.address || '').trim());
  $('mapSide').innerHTML = `<div class="pick-help"><b>필지를 누르세요</b><span>누른 자리의 필지 경계·지번이 표시되면 「＋ 이 필지 추가」로 넣습니다. 확대해서 필지 안쪽을 누르면 정확합니다.</span></div>
    ${extra}
    <small class="muted">이 사업지 필지 (${ps.length})</small>
    <ol class="pmap-list">${ps.map(x => `<li class="${pickAdded.includes(normAddr(x.address)) ? 'pick-new' : ''}"><b>${esc(String(x.address).replace(/^.*?(\S+[동리가]\s)/, '$1'))}</b> <span class="muted">${fmt(x.area_sqm, 1)}㎡</span></li>`).join('') || '<li class="muted">아직 없음</li>'}</ol>
    <p class="muted" style="font-size:12px;margin:8px 0 0">경계: 국토교통부 연속지적도(브이월드) · 참고용이며 측량 성과가 아닙니다.</p>`;
}
async function pickAt(ll) {
  if (pickSel) { pmap.removeLayer(pickSel); pickSel = null; }
  const tip = L.popup({ closeButton: false }).setLatLng(ll).setContent('<span class="muted">필지 찾는 중…</span>').openOn(pmap);
  try {
    const f = await api('GET', `/api/v4/land/at?lat=${ll.lat.toFixed(7)}&lon=${ll.lng.toFixed(7)}`);
    const addr = f.properties.addr || '', have = (pf?.site?.parcels || []).some(x => normAddr(x.address) === normAddr(addr));
    pickSel = L.geoJSON(f, { style: { color: '#1e88d6', weight: 3, fillColor: '#1e88d6', fillOpacity: .3 }, interactive: false }).addTo(pmap);
    const jiga = Number(f.properties.jiga) || 0;
    tip.setContent(`<div class="pick-pop"><b>${esc(addr)}</b>${jiga ? `<small>공시지가 ${fmt(jiga)}원/㎡</small>` : ''}
      ${have ? '<div class="muted" style="margin-top:6px">이미 추가된 필지입니다</div>' : `<button type="button" class="btn" data-pick-add="${esc(addr)}" style="margin-top:8px;width:100%">＋ 이 필지 추가</button>`}</div>`);
  } catch (err) { tip.setContent(`<div class="neg" style="max-width:240px">${esc(err.message)}</div>`); }
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-pick-add]'); if (!b) return;
  const addr = b.dataset.pickAdd; b.disabled = true; b.textContent = '추가 중…';
  await ezLookup(addr);
  const ok = (pf?.site?.parcels || []).some(x => normAddr(x.address) === normAddr(addr));
  if (ok) { pickAdded.push(normAddr(addr)); pmap.closePopup(); if (pickSel) { pmap.removeLayer(pickSel); pickSel = null; } }
  else { b.disabled = false; b.textContent = '＋ 이 필지 추가'; }
  // 추가한 필지를 초록 경계로 다시 표시
  try {
    const r = await api('POST', '/api/v4/land/shapes', { items: [{ address: addr, pnu: '' }] });
    const f = r.features[0]; if (ok && f?.geometry) { if (!pmapShapes) pmapShapes = L.featureGroup().addTo(pmap);
      L.geoJSON(f, { style: { color: '#1e7b3a', weight: 2, fillColor: '#1e7b3a', fillOpacity: .25 }, interactive: false }).addTo(pmapShapes); }
  } catch { /* 경계 표시는 참고용 */ }
  pickSide();
});
$('ezMapPick').onclick = () => openParcelPicker();
$('mapBack').addEventListener('click', e => { if (e.target === $('mapBack')) $('mapBack').classList.add('hidden'); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('mapBack').classList.contains('hidden')) $('mapBack').classList.add('hidden'); });


/* 일정의 '사업 개시 후 N개월' 항목(토지 잔금·착공·분양 개시)을 연·월로 고르게 한다. 저장은 기존처럼 개월 수(오프셋) */
const ymAdd = (ym, n) => { const [y, m] = String(ym || today.slice(0, 7)).split('-').map(Number); const t = y * 12 + (m - 1) + Number(n || 0); return `${Math.floor(t / 12)}-${String(t % 12 + 1).padStart(2, '0')}`; };
const ymDiff = (a, b) => { const [y1, m1] = String(a).split('-').map(Number), [y2, m2] = String(b).split('-').map(Number); return (y2 * 12 + m2) - (y1 * 12 + m1); };
let ofsStart = null;   // 마지막으로 화면에 반영한 사업 개시월 (개시월을 바꿔도 이미 고른 달력상의 월은 유지)
function fillOffsets() {
  const sc = pf?.schedule; if (!sc) return;
  ofsStart = sc.start_month;
  document.querySelectorAll('[data-ofs]').forEach(el => {
    const k = el.dataset.ofs; el.value = ymAdd(sc.start_month, sc[k]);
    const h = document.querySelector(`[data-ofs-hint="${k}"]`);
    if (h) h.textContent = `사업 개시 후 ${Number(sc[k] || 0)}개월`;
  });
}
function onStartMonthChange() {
  const sc = pf?.schedule; if (!sc || !/^\d{4}-\d{2}$/.test(sc.start_month || '')) return;
  if (ofsStart && /^\d{4}-\d{2}$/.test(ofsStart)) {
    let moved = false;
    document.querySelectorAll('[data-ofs]').forEach(el => {
      const k = el.dataset.ofs, keep = ymAdd(ofsStart, sc[k]), n = ymDiff(sc.start_month, keep);
      if (n >= 0) sc[k] = n; else { sc[k] = 0; moved = true; }
    });
    if (moved) notice('사업 개시월보다 앞선 일정은 사업 개시월로 맞췄습니다.', true);
  }
  fillOffsets(); pfRecalc();
}
document.addEventListener('change', e => {
  const el = e.target.closest?.('[data-ofs]'); if (!el || !pf?.schedule) return;
  const sc = pf.schedule, k = el.dataset.ofs;
  if (!/^\d{4}-\d{2}$/.test(el.value)) { fillOffsets(); return; }
  const n = ymDiff(sc.start_month, el.value);
  if (n < 0) { notice(`사업 개시월(${sc.start_month})보다 앞선 달은 고를 수 없습니다.`, true); fillOffsets(); return; }
  sc[k] = n; fillOffsets(); pfRecalc();
});


/* 지번 미확정 토지 (도시개발·택지 블록 등): 시·군·구 + 블록명 + 면적·용도지역 직접 입력 */
(function manualLand() {
  const box = $('ezManualBox'); if (!box) return;
  const init = () => {
    if ($('ezMProv').options.length < 2) $('ezMProv').innerHTML = '<option value="">선택</option>' + PROVINCES.map(p => `<option>${esc(p)}</option>`).join('');
    if ($('ezMZone').options.length < 2) $('ezMZone').innerHTML = '<option value="">선택</option>' + ZONE_LIST.map(z => `<option>${z}</option>`).join('');
    const p = pf?.site?.province || '', m = pf?.site?.municipality || '';
    if (p && !$('ezMProv').value) { $('ezMProv').value = p; fillMuni('ezMProv', 'ezMMuni', m); }
  };
  box.addEventListener('toggle', () => { if (box.open) init(); });
  $('ezMProv').onchange = () => fillMuni('ezMProv', 'ezMMuni', '');
  $('ezMAdd').onclick = () => {
    if (!curSite) { notice('먼저 사업지를 고르거나 만드세요.', true); return; }
    const prov = $('ezMProv').value, muni = $('ezMMuni').value, name = $('ezMName').value.trim();
    const area = parseNum($('ezMArea').value), zone = $('ezMZone').value, price = parseNum($('ezMPrice').value);
    const miss = [!prov && '광역지자체', !muni && prov !== '세종특별자치시' && '시·군·구', !name && '구역·블록명', !(area > 0) && '면적', !zone && '용도지역'].filter(Boolean);
    if (miss.length) { notice('입력하세요: ' + miss.join(', '), true); return; }
    const label = `${prov} ${muni ? muni + ' ' : ''}${name} (지번 미확정)`;
    if (!pf.site.parcels.some(x => String(x.address || '').trim())) pf.site.parcels = [];
    const dup = pf.site.parcels.findIndex(x => addrKey(x.address) === addrKey(label));
    if (dup >= 0) { notice(`이미 ${dup + 1}번으로 입력된 토지입니다. 면적은 표에서 고치세요.`, true); return; }
    pf.site.parcels.push({ address: label, area_sqm: area, zone, jimok: '대', price_per_sqm: price > 0 ? price : null, manual: true, uses: [] });
    pf.site.province = prov; pf.site.municipality = muni;
    $('ezMName').value = ''; $('ezMArea').value = ''; $('ezMPrice').value = '';
    renderParcels(); applyParcels(); loadOrdinance(true); ezRender1();
    notice(`‘${name}’ ${fmt(area, 1)}㎡ (${zone})를 추가했습니다. 대지면적·용적률이 자동 반영됩니다.`);
  };
  // 간편 분석 필지 목록: 면적·용도지역·지목·공시지가 직접 수정 → 대지면적·용도지역별 면적·사업비 다시 계산
  $('ezParcels').addEventListener('change', e => {
    const t = e.target.closest('[data-ezp]'); if (!t) return;
    const x = pf.site.parcels[Number(t.dataset.ezp)], k = t.dataset.k; if (!x) return;
    if (k === 'area_sqm' || k === 'price_per_sqm') {
      const v = parseNum(t.value);
      if (k === 'area_sqm' && !(v > 0)) { notice('면적을 0보다 크게 입력하세요.', true); t.value = moneyVal(x.area_sqm); return; }
      x[k] = v > 0 ? v : null;
    } else x[k] = t.value;
    renderParcels(); applyParcels(); ezRender1();
  });
  $('ezParcels').addEventListener('click', async e => {
    const b = e.target.closest('[data-ez-land]'); if (!b) return;
    b.disabled = true; b.textContent = '조회 중…';
    try { await fetchLand(Number(b.dataset.ezLand)); applyParcels(); } finally { ezRender1(); }
  });
  // 간편 분석 표에서 미확정 토지 면적 바로 수정 → 대지면적·용적률·사업비 다시 계산
  $('ezParcels').addEventListener('change', e => {
    const t = e.target.closest('[data-ez-area]'); if (!t) return;
    const x = pf.site.parcels[Number(t.dataset.ezArea)]; if (!x) return;
    const v = parseNum(t.value);
    if (!(v > 0)) { notice('면적을 0보다 크게 입력하세요.', true); t.value = moneyVal(x.area_sqm); return; }
    x.area_sqm = v; renderParcels(); applyParcels(); ezRender1();
  });
})();


/* 새 사업지의 지역(시·도·시·군·구): 고르면 그 지역 조례로 용적률·건폐율·주차·부담금을 계산 */
// 사업지 이름에서 지역 추정: '과천시 복합개발' → 경기도 과천시 · '서울시_서초구' → 서울특별시 서초구 (여러 곳에 같은 이름이면 시·도 단서가 있어야 함)
function guessRegion(name) {
  const n = (name || '').replace(/[_\s·,()-]+/g, ' ');
  const provs = PROVINCES.filter(pv => n.includes(pv) || Object.entries(PROV_ALIAS).some(([a, full]) => full === pv && new RegExp('(^|\\s)' + a).test(n)));
  const hits = [];
  for (const pv of PROVINCES) for (const m of (SIGUNGU[pv] || [])) {
    const stem = m.length > 2 ? m.replace(/[시군구]$/, '') : m;
    if (n.includes(m) || (stem.length >= 2 && new RegExp('(^|\\s)' + stem + '(\\s|$)').test(n))) hits.push({ province: pv, municipality: m });
  }
  const scoped = provs.length ? hits.filter(h => provs.includes(h.province)) : hits;
  const uniq = [...new Set(scoped.map(h => h.province + '|' + h.municipality))];
  if (uniq.length === 1) return scoped[0];
  if (!uniq.length && provs.length === 1 && !(SIGUNGU[provs[0]] || []).length) return { province: provs[0], municipality: '' };
  return null;
}
function regionNeed(provId, muniId, msg) {
  [provId, muniId].forEach(id => $(id).classList.add('need'));
  const box = $(provId).parentElement; let tip = box.querySelector('.region-tip');
  if (!tip) { tip = document.createElement('div'); tip.className = 'region-tip'; box.appendChild(tip); }
  tip.textContent = '⚠ ' + msg; notice(msg, true);
  const clear = () => { [provId, muniId].forEach(id => $(id).classList.remove('need')); tip.remove(); };
  $(provId).addEventListener('change', clear, { once: true }); $(muniId).addEventListener('change', clear, { once: true });
}
function pickRegion(provId, muniId, name) {
  if (!$(provId).value && name) {
    const g = guessRegion(name);
    if (g) { $(provId).value = g.province; fillMuni(provId, muniId, g.municipality); if ($(muniId).options[0]) $(muniId).options[0].textContent = '시·군·구'; }
  }
  const province = $(provId).value, municipality = $(muniId).value;
  if (!province) { regionNeed(provId, muniId, '지역(시·도·시·군·구)을 선택하세요 — 그 지역 조례로 사업수지를 계산합니다.'); $(provId).focus(); return null; }
  if (!municipality && province !== '세종특별자치시' && $(muniId).options.length > 1) { regionNeed(provId, muniId, '시·군·구를 선택하세요.'); $(muniId).focus(); return null; }
  return { province, municipality };
}
function applyRegion({ province, municipality }) {
  pf.site.province = province; pf.site.municipality = municipality || '';
  if ($('s_province')) { $('s_province').value = province; fillMuni('s_province', 's_municipality', municipality || ''); }
  loadOrdinance(true); pfRecalc();
}
function initRegionSelects() {
  [['ezNewProv', 'ezNewMuni'], ['newSiteProv', 'newSiteMuni']].forEach(([p, m]) => {
    if (!$(p) || $(p).options.length > 1) return;
    $(p).innerHTML = '<option value="">시·도 선택</option>' + PROVINCES.map(x => `<option>${esc(x)}</option>`).join('');
    $(m).innerHTML = '<option value="">시·군·구</option>';
    $(p).onchange = () => { fillMuni(p, m, ''); if ($(m).options[0]) $(m).options[0].textContent = '시·군·구'; };
  });
}
initRegionSelects(); setTimeout(initRegionSelects, 1500);   // 광역지자체 목록을 서버에서 받은 뒤 한 번 더


/* ═════════════════════ 법정 기준 초기화 ═════════════════════
   고친 숫자를 버리고, 사업지 정보(필지·대지면적·지역·용도지역·도시계획 결정고시)는 유지한 채
   용도 템플릿 구성 + 조례 허용 용적률에 맞춘 규모 + 법정 자동 부담금·세금으로 다시 만든다. */
function guessTemplate(p) {
  const k = new Set((p.units || []).filter(u => u.count).map(u => u.kind));
  if (p.project_mode === 'rental') return 'rental';
  if (p.project_mode === 'redevelopment') return 'garoju';
  if (k.has('apartment')) return k.has('retail') || k.has('office') ? 'tpl_mixed_apt' : 'tpl_apartment';
  if (k.has('officetel')) return k.has('retail') || k.has('office') ? 'tpl_mixed_officetel' : 'tpl_officetel';
  if (k.has('knowledge')) return 'tpl_knowledge';
  if (k.has('datacenter')) return 'tpl_datacenter';
  if (k.has('office')) return 'tpl_office';
  if (k.has('retail')) return 'tpl_retail';
  return 'tpl_apartment';
}
async function legalBaseline(sample) {
  const t = await api('GET', '/sample?name=' + sample); delete t._template;
  t.project_name = pf.project_name || curSite; t.template_key = sample;
  t.site = { ...t.site, ...pf.site, building_area_sqm: null, plan_parking: null, auto_far: true, incentive_far_pct: 0 };
  if (Number(pf.land_area_sqm) > 0) scaleTemplate(t, Number(pf.land_area_sqm));
  // 이 땅의 허용 용적률(조례·도시계획 결정고시)에 맞춰 규모 조정
  const chk = await api('POST', '/api/v3/proforma', t);
  const allowed = chk.compliance?.plan?.gfa ?? chk.compliance?.allowed_gfa_sqm;
  let msg = '';
  if (allowed > 0 && t.above_gfa_sqm > 0 && Math.abs(allowed / t.above_gfa_sqm - 1) > 0.01) {
    scaleBy(t, allowed / t.above_gfa_sqm);
    msg = ` 허용 용적률 ${fmt(allowed / t.land_area_sqm * 100, 0)}%에 맞춰 지상 연면적 ${fmt(t.above_gfa_sqm, 0)}㎡로 조정했습니다.`;
  }
  return { t, msg };
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-legal-reset]'); if (!b || !pf) return;
  if (!curSite) { notice('사업지를 먼저 선택하세요.', true); return; }
  const cur = pf.template_key || guessTemplate(pf);
  const opts = [...$('pfSampleSel').options].map(o => `<option value="${esc(o.value)}" ${o.value === cur ? 'selected' : ''}>${esc(o.text.replace('템플릿: ', ''))}</option>`).join('');
  const ok = await confirmBox('법정 기준으로 초기화할까요?',
    `직접 고친 <b>분양가·사업비·일정·금융 숫자를 버리고</b>, 법령·조례를 반영한 처음 사업수지로 되돌립니다.<br>
     <span class="muted" style="font-size:13px">유지: 필지·대지면적 ${fmt(pf.land_area_sqm, 1)}㎡ · ${esc([pf.site.province, pf.site.municipality].filter(Boolean).join(' ') || '지역 미입력')} · 용도지역 · 도시계획 결정고시<br>
     다시 계산: 조례 허용 용적률에 맞춘 규모 · 법정 자동 부담금·세금 · 조례 주차</span>
     <label style="display:block;margin-top:10px;font-size:14px">용도 <select id="rstTpl" class="ctl" style="width:auto;margin-left:6px">${opts}</select></label>
     <label style="display:flex;gap:6px;align-items:center;margin-top:8px;font-size:14px"><input type="checkbox" id="rstBackup" checked> 초기화 전에 지금 숫자를 시나리오로 보관 (「${today} 초기화 전 백업」)</label>`, '초기화');
  if (!ok) return;
  const sample = document.getElementById('rstTpl')?.value || cur, backup = document.getElementById('rstBackup')?.checked;
  await busy(b, async () => {
    try {
      if (backup) await api('PUT', siteUrl(curSite, `/proforma?scenario=${encodeURIComponent(today + ' 초기화 전 백업')}&memo=${encodeURIComponent('법정 기준 초기화 전 자동 보관')}`), pf);
      const { t, msg } = await legalBaseline(sample);
      pfLoad(t, false); pf._tplKey = sample.replace(/^tpl_/, ''); loadOrdinance(false); renderScnSelect();
      if (document.getElementById('view-easy')?.classList.contains('active')) ezGo(ezStep || 3);
      notice(`법정 기준으로 초기화했습니다.${msg}${backup ? ' 이전 숫자는 시나리오로 보관했습니다.' : ''}`);
    } catch (err) { notice(err.message, true); }
  });
});


/* 토지이용계획 열람본(참고용) 자동 작성·반영 — 정식 확인서 발급은 정부24(본인 인증·수수료) */
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-landuse-report]'); if (!b || !pf) return;
  if (!curSite) { notice('사업지를 먼저 선택하세요.', true); return; }
  const ps = (pf.site.parcels || []).filter(x => !x.manual && (String(x.address || '').trim() || x.pnu));
  if (!ps.length) { notice('조회할 필지가 없습니다. 주소(지번)를 먼저 조회하세요. 지번 미확정 토지는 열람본을 만들 수 없습니다.', true); return; }
  await busy(b, async () => {
    try {
      const r = await api('POST', siteUrl(curSite, '/landuse-report'), { items: ps.map(x => ({ address: x.address || '', pnu: x.pnu || '' })) });
      let changed = 0;
      r.parcels.forEach(L => {   // 최신 조회값을 필지에 반영 (면적·지목·용도지역·공시지가·규제)
        const x = pf.site.parcels.find(y => (y.pnu && y.pnu === L.pnu) || addrKey(y.address) === addrKey(`${L.address} ${L.jibun}`) || addrKey(y.address) === addrKey(L.input_address));
        if (!x) return;
        const before = JSON.stringify([x.area_sqm, x.zone, x.price_per_sqm, x.jimok, (x.uses || []).length]);
        if (L.area_sqm) x.area_sqm = L.area_sqm; if (L.jimok) x.jimok = L.jimok;
        if (L.zone && ZONE_LIST.includes(L.zone)) x.zone = L.zone;
        if (L.price_per_sqm) x.price_per_sqm = L.price_per_sqm; x.pnu = L.pnu; x.uses = L.uses || [];
        if (before !== JSON.stringify([x.area_sqm, x.zone, x.price_per_sqm, x.jimok, x.uses.length])) changed++;
      });
      renderParcels(); applyParcels(); applyLandUse();
      if (document.getElementById('view-easy')?.classList.contains('active') && ezStep === 1) ezRender1();
      if (document.getElementById('view-sites')?.classList.contains('active')) openSite(curSite);
      notice(`토지이용계획 열람본을 자료함에 저장했습니다 (${r.file}) — ${r.parcels.length}필지 최신 조회${changed ? `, ${changed}필지 값 갱신` : ', 변경 없음'}${r.failed.length ? ` · ${r.failed.length}필지 조회 실패` : ''}. ${r.notice}`, !!r.failed.length);
    } catch (err) { notice(err.message, true); }
  });
});
