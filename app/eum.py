"""토지이음(eum.go.kr) 도시계획 고시 자동 검색 · 첨부(HWP/HWPX/PDF) 용적률 추출.

1) 검색: 고시정보 목록(gvGosiList.jsp)을 동 이름·계획 종류로 조회 → 시·군·구 일치, 제목 키워드, 날짜로 순위
2) 상세: gvGosiDet.jsp → 고시번호·고시일·담당기관·대상지 본문
3) 첨부: DownloadZip.jsp(일괄 ZIP) → HWP(5.0)·HWPX·PDF 글자 추출 → 기준·허용·상한 용적률·건폐율 추출 (원문 대조 필요)
"""
import io
import re
import struct
import urllib.parse
import urllib.request
import zipfile
import zlib

BASE = 'https://www.eum.go.kr/web/gs/gv/'
UA = {'User-Agent': 'Mozilla/5.0'}
KIND_WORDS = {
    'district': ['지구단위계획'],
    'redevelopment': ['정비구역', '재개발', '정비계획', '재정비촉진'],
    'reconstruction': ['재건축', '정비구역', '정비계획'],
    'small': ['가로주택', '소규모재건축', '소규모주택정비', '자율주택'],
}


def _get(url: str, data: bytes | None = None) -> bytes:
    req = urllib.request.Request(url, headers=UA, data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _text(b: bytes) -> str:
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode('utf-8', 'replace')


def _strip(h: str) -> str:
    h = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', h, flags=re.S | re.I)
    h = re.sub(r'<[^>]+>', ' ', h)
    h = h.replace('&nbsp;', ' ').replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
    return re.sub(r'\s+', ' ', h).strip()


def search(keyword: str, size: int = 50) -> list[dict]:
    q = urllib.parse.urlencode({'zonenm': keyword, 'listSize': size, 'pageNo': 1}, encoding='euc-kr')
    h = _text(_get(BASE + 'gvGosiList.jsp?' + q))
    rows = []
    for m in re.finditer(r'(\d{4}-\d{2}-\d{2})\s*</td>\s*<td[^>]*>\s*([^<]*고시[^<]*)</td>.*?href=["\']([^"\']*gvGosiDet\.jsp\?seq=(\d+)[^"\']*)["\'][^>]*>\s*(.*?)</a>',
                         h, flags=re.S):
        title = _strip(m.group(5))
        rows.append({'date': m.group(1), 'notice_no': m.group(2).strip(), 'title': title, 'seq': m.group(4),
                     'url': BASE + 'gvGosiDet.jsp?seq=' + m.group(4)})
    seen, out = set(), []
    for r in rows:   # 같은 고시가 중복 게시되는 경우 하나로
        k = (r['notice_no'], r['title'])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def find_candidates(address: str, kind: str, municipality: str = '', registered: str = '') -> list[dict]:
    """주소의 동 이름 + 계획 종류 키워드로 검색, 시·군·구 일치·결정 고시·지정일 근접 순으로 정렬."""
    tokens = (address or '').split()
    dong = next((t for t in tokens if re.search(r'(동|리|가|읍|면)$', t) and not t.endswith(('시', '군', '구'))), '')
    words = KIND_WORDS.get(kind, ['지구단위계획'])
    queries = [w for w in ([dong[:-1] if dong.endswith('동') and len(dong) > 2 else dong] if dong else [])] + [f'{municipality} {words[0]}'.strip()]
    cands = {}
    for q in queries:
        if not q:
            continue
        try:
            for r in search(q):
                cands.setdefault(r['seq'], r)
        except OSError:
            continue
    muni_core = municipality[:-1] if municipality.endswith(('시', '군', '구')) else municipality
    out = []
    for r in cands.values():
        t = r['title']
        score = 0
        if any(w in t for w in words):
            score += 50
        if muni_core and muni_core in r['notice_no']:
            score += 30
        elif municipality:
            continue   # 다른 지자체 고시 제외
        if dong and (dong in t or (dong[:-1] and dong[:-1] in t)):
            score += 15
        if '결정' in t:
            score += 10
        if '폐지' in t:
            score -= 20
        if registered and r['date'] and abs(_days(r['date']) - _days(registered)) <= 60:
            score += 25   # 토지이용계획 지정일과 고시일이 가까움
        r = {**r, 'score': score}
        if score >= 50:
            out.append(r)
    out = sorted(out, key=lambda x: (x['score'], x['date']), reverse=True)[:12]   # 점수 높은 순, 같으면 최신
    # 대상지 확인: 고시 본문의 위치(○○동 ○○번지 일원)에 사업지 지번이 있으면 '지번 일치'
    jibun = (re.search(r'(산\s*)?(\d+(?:-\d+)?)\s*$', (address or '').strip()) or [None, None, ''])[2]
    main_no = jibun.split('-')[0] if jibun else ''
    from concurrent.futures import ThreadPoolExecutor
    def loc(c):
        try:
            body = detail(c['seq'])['body']
        except OSError:
            body = ''
        m = re.search(r'([가-힣]+[동리가])\s*((?:산\s*)?\d+(?:\s*-\s*\d+)?(?:\s*[,·및외]\s*(?:산\s*)?\d+(?:\s*-\s*\d+)?)*)\s*(?:번지)?\s*(일원|일대|외\s*\d+\s*필지)?', body)
        c['location'] = re.sub(r'\s+', ' ', f"{m.group(1)} {m.group(2)}번지 {m.group(3) or ''}").strip() if m else ''
        nums = [re.sub(r'\s', '', n) for n in re.findall(r'\d+(?:\s*-\s*\d+)?', m.group(2))] if m else []
        c['match'] = bool(main_no) and (jibun in nums or main_no in [n.split('-')[0] for n in nums]) and (not dong or dong[:-1] in c['location'])
        return c
    with ThreadPoolExecutor(max_workers=6) as ex:
        out = list(ex.map(loc, out))
    return sorted(out, key=lambda x: (x['match'], x['score'], x['date']), reverse=True)


def _days(d: str) -> int:
    y, m, dd = (int(x) for x in d[:10].split('-'))
    return y * 372 + m * 31 + dd


def detail(seq: str) -> dict:
    seq = re.sub(r'\D', '', seq)
    h = _text(_get(BASE + 'gvGosiDet.jsp?seq=' + seq))
    cap = re.search(r'<caption>\s*(.*?)\s*-\s*고시번호', h, flags=re.S)
    def cell(label):
        m = re.search(r'<th[^>]*>\s*' + label + r'\s*</th>\s*<td[^>]*>(.*?)</td>', h, flags=re.S)
        return _strip(m.group(1)) if m else ''
    t = _strip(h)
    body = (re.search(r'(1\.\s.*?)(?:목록으로|원문출처)', t) or [None, ''])[1][:1500]
    files = re.findall(r"download\('/web/FileDownload\.do',\s*'[^']*/([^'/]+)'\)", h)
    return {'seq': seq, 'title': _strip(cap.group(1)) if cap else '', 'notice_no': cell('고시번호'), 'org': cell('담당기관'),
            'date': (re.search(r'\d{4}-\d{2}-\d{2}', cell('고시일')) or [''])[0], 'body': body, 'files': files,
            'url': BASE + 'gvGosiDet.jsp?seq=' + seq}


# ───────── 첨부 글자 추출 ─────────
def _msvc_rand(seed: int):
    while True:
        seed = (seed * 214013 + 2531011) & 0xFFFFFFFF
        yield (seed >> 16) & 0x7FFF


def _distribution_key(payload: bytes) -> bytes:
    """배포용 문서 데이터(256바이트) → AES-128 키 (HWP 5.0 배포용 문서 규격)."""
    seed = struct.unpack_from('<I', payload, 0)[0]
    rnd, dec, n, key = _msvc_rand(seed), bytearray(payload), 0, 0
    for i in range(256):
        if n == 0:
            key = next(rnd) & 0xFF
            n = (next(rnd) & 0x0F) + 1
        if i >= 4:
            dec[i] = payload[i] ^ key
        n -= 1
    off = 4 + (seed & 0x0F)
    return bytes(dec[off:off + 16])


def _view_text(raw: bytes) -> bytes:
    """배포용 ViewText 섹션 복호화: 첫 레코드(배포용 문서 데이터 256바이트) → 키 → 나머지 AES-128 ECB."""
    from Crypto.Cipher import AES
    h = struct.unpack_from('<I', raw, 0)[0]
    size = (h >> 20) & 0xFFF
    payload = raw[4:4 + size]
    body = raw[4 + size:]
    body = body[:len(body) - len(body) % 16]
    return AES.new(_distribution_key(payload), AES.MODE_ECB).decrypt(body)


def hwp_text(data: bytes) -> str:
    """HWP 5.0 본문 글자 추출 (일반 BodyText / 배포용 ViewText 모두)."""
    import olefile
    ole = olefile.OleFileIO(io.BytesIO(data))
    header = ole.openstream('FileHeader').read()
    props = struct.unpack_from('<I', header, 36)[0]
    compressed, distribution = bool(props & 1), bool(props & 4)
    folder = 'ViewText' if distribution else 'BodyText'
    texts = []
    sections = sorted((e for e in ole.listdir() if e[0] == folder), key=lambda e: int(re.sub(r'\D', '', e[1]) or 0))
    for e in sections:
        raw = ole.openstream(e).read()
        if distribution:
            raw = _view_text(raw)
        if compressed:
            raw = zlib.decompressobj(-15).decompress(raw)
        i = 0
        while i + 4 <= len(raw):
            h = struct.unpack_from('<I', raw, i)[0]
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                size = struct.unpack_from('<I', raw, i)[0]
                i += 4
            if tag == 67:   # HWPTAG_PARA_TEXT
                texts.append(_para(raw[i:i + size]))
            i += size
    return '\n'.join(texts)


def _para(b: bytes) -> str:
    out, i = [], 0
    ext = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}   # 확장 컨트롤: 8 wchar 차지
    while i + 1 < len(b):
        c = struct.unpack_from('<H', b, i)[0]
        if c in ext or c in (4, 5, 6, 7, 8, 9, 19, 20):
            i += 16 if (c in ext or c in (4, 5, 6, 7, 8, 9, 19, 20)) else 2
            if c == 9:
                out.append('\t')
            continue
        if c in (10, 13):
            out.append('\n')
        elif c >= 32:
            out.append(chr(c))
        i += 2
    return ''.join(out)


def hwpx_text(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    parts = sorted(n for n in z.namelist() if re.match(r'Contents/section\d+\.xml', n))
    return '\n'.join(re.sub(r'<[^>]+>', ' ', z.read(n).decode('utf-8', 'replace')) for n in parts)


def pdf_text(data: bytes) -> str:
    import pymupdf
    with pymupdf.open(stream=data, filetype='pdf') as d:
        return '\n'.join(p.get_text() for p in d)


def _download_all(seq: str) -> list[tuple[str, bytes]]:
    """상세 페이지 세션을 유지한 채 첨부파일을 하나씩 받는다 (FileDownload.do POST)."""
    import http.cookiejar
    seq = re.sub(r'\D', '', seq)
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.addheaders = list(UA.items())
    h = _text(op.open(BASE + 'gvGosiDet.jsp?seq=' + seq, timeout=30).read())
    paths = re.findall(r"download\('(/web/FileDownload\.do)',\s*'([^']+)'\)", h)
    out = []
    for url, path in paths:
        for enc in ('euc-kr', 'utf-8'):
            body = urllib.parse.urlencode({'file': path, 'gosi': 'Y', 'seq': seq, 'mobile_yn': ''}, encoding=enc).encode()
            try:
                data = op.open(urllib.request.Request('https://www.eum.go.kr' + url, data=body,
                                                      headers={'Referer': BASE + 'gvGosiDet.jsp?seq=' + seq}), timeout=60).read()
            except OSError:
                continue
            if len(data) > 200 and not data.lstrip()[:15].lower().startswith((b'<!doctype', b'<html', b'<script')):
                out.append((path.rsplit('/', 1)[-1], data))
                break
    return out


def attachments_text(seq: str) -> tuple[str, list[str]]:
    """첨부파일(HWP·HWPX·PDF, ZIP 포함) 글자 추출."""
    items = []
    for name, data in _download_all(seq):
        if data[:2] == b'PK' and not name.lower().endswith('.hwpx'):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
                items += [(_decode_name(n), z.read(n)) for n in z.namelist()]
                continue
            except zipfile.BadZipFile:
                pass
        items.append((name, data))
    texts, used = [], []
    for name, b in items:
        n = name.lower()
        try:
            if n.endswith('.hwp') or b[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
                texts.append(hwp_text(b)); used.append(name)
            elif n.endswith('.hwpx'):
                texts.append(hwpx_text(b)); used.append(name)
            elif n.endswith('.pdf') or b[:4] == b'%PDF':
                texts.append(pdf_text(b)); used.append(name)
        except Exception:
            continue
    return '\n'.join(texts), used


def _decode_name(n: str) -> str:
    try:
        return n.encode('cp437').decode('cp949')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return n


def extract_far(text: str) -> dict:
    """결정조서 글자에서 용적률·건폐율 추출 (여러 값이 있으면 첫 값, 원문 대조 필요)."""
    t = re.sub(r'\s+', ' ', text)
    def pct(label):
        m = re.search(label + r'[^0-9%]{0,30}?(\d{2,4}(?:\.\d+)?)\s*%', t)
        return float(m.group(1)) if m else None
    found = {'base_far': pct(r'기준\s*용적률'), 'allowed_far': pct(r'허용\s*용적률'), 'max_far': pct(r'상한\s*용적률'),
             'plan_bcr': pct(r'건폐율')}
    if found['base_far'] is None:
        found['base_far'] = pct(r'(?:계획|정비계획)\s*용적률') or pct(r'용적률')
    snippets = [t[max(0, m.start() - 60):m.end() + 80] for m in re.finditer(r'(기준|허용|상한)?\s*용적률', t)][:6]
    return {**found, 'snippets': snippets}


def extract(seq: str, address: str = '') -> dict:
    from . import plandoc
    d = detail(seq)
    text, used = attachments_text(seq)
    far = extract_far(text) if text else {'base_far': None, 'allowed_far': None, 'max_far': None, 'plan_bcr': None, 'snippets': []}
    blocks = plandoc.parse_blocks(text) if text else []
    if blocks:
        plandoc.locate(text, blocks)
    chosen = plandoc.match_address(blocks, address) if blocks else None
    if not chosen and len(blocks) == 1:
        chosen = blocks[0]['block']
    if chosen:   # 획지가 정해지면 그 획지 값(변경 조서 우선)을 기본값으로
        b = next(x for x in blocks if x['block'] == chosen)
        far = {**far, 'base_far': b.get('base_far') or b.get('far'), 'allowed_far': b.get('allowed_far'), 'max_far': b.get('max_far') or b.get('legal_max_far'),
               'plan_bcr': b.get('bcr') if b.get('bcr') is not None else far.get('plan_bcr')}
    elif len(blocks) > 1:   # 여러 획지인데 사업지 획지를 못 정하면 첫 값(기정일 수 있음)을 쓰지 않는다
        far = {**far, 'base_far': None, 'allowed_far': None, 'max_far': None, 'plan_bcr': None}
    return {**d, **far, 'blocks': blocks, 'block': chosen, 'parsed_files': [_decode_name(u) for u in used], 'text_length': len(text),
            'notice': '첨부 결정조서에서 자동 추출한 값입니다(기정·변경 조서가 함께 있으면 변경 값). 반드시 원문과 대조하세요.'
                      + ('' if chosen or len(blocks) <= 1 else ' 여러 획지가 있어 사업지 획지를 고르세요.')}
