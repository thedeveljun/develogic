"""클라우드(여러 업체) 모드: 업체별 로그인, 자료함 분리, 운영자 전용 기능."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path


class Client:
    """원격 브라우저 하나 (쿠키 보관). Cloud Run 처럼 X-Forwarded-For 를 붙여 ASGI 로 직접 호출."""
    def __init__(self, app, ip='203.0.113.7'):
        self.app, self.ip, self.jar = app, ip, {}

    def __call__(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else b''
        ck = '; '.join(f'{k}={v}' for k, v in self.jar.items())
        headers = [(b'content-type', b'application/json'), (b'host', b'x'), (b'x-forwarded-for', self.ip.encode())]
        if ck:
            headers.append((b'cookie', ck.encode()))
        p, _, q = path.partition('?')
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'https',
                 'path': p, 'raw_path': p.encode(), 'query_string': q.encode(), 'root_path': '', 'headers': headers,
                 'client': ('169.254.1.1', 50000), 'server': ('x', 443)}
        out = {'status': None, 'headers': [], 'body': b''}
        sent = [False]

        async def receive():
            if not sent[0]:
                sent[0] = True
                return {'type': 'http.request', 'body': data, 'more_body': False}
            return {'type': 'http.disconnect'}

        async def send(m):
            if m['type'] == 'http.response.start':
                out['status'], out['headers'] = m['status'], m['headers']
            elif m['type'] == 'http.response.body':
                out['body'] += m.get('body', b'')
        asyncio.run(self.app(scope, receive, send))
        for k, v in out['headers']:
            if k == b'set-cookie':
                name, _, rest = v.decode().partition('=')
                val = rest.split(';')[0].strip('"')
                if val and 'Max-Age=0' not in v.decode():
                    self.jar[name] = val
                else:
                    self.jar.pop(name, None)
        try:
            j = json.loads(out['body'] or b'null')
        except ValueError:
            j = None
        return out['status'], j


class MultiTenantTests(unittest.TestCase):
    def setUp(self):
        from app import auth, config, landinfo
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = (config.MULTI, config.DATA, config.ACCOUNTS, landinfo.SETTINGS)
        config.MULTI, config.DATA, config.ACCOUNTS = True, d, d / 'accounts.json'
        landinfo.SETTINGS = d / 'settings.json'
        auth._fails.clear()
        os.environ['DEVELOGIC_OPERATOR_PW'] = 'operator-pass-1'
        auth.ensure_operator()

    def tearDown(self):
        from app import config, landinfo
        config.MULTI, config.DATA, config.ACCOUNTS, landinfo.SETTINGS = self.saved
        os.environ.pop('DEVELOGIC_OPERATOR_PW', None)
        self.tmp.cleanup()

    def test_isolation_and_roles(self):
        from app.main import app
        op, a, b, a2 = Client(app), Client(app, '198.51.100.1'), Client(app, '198.51.100.2'), Client(app, '198.51.100.3')

        self.assertEqual(op('GET', '/api/v4/sites')[0], 401)
        self.assertEqual(op('GET', '/api/v4/auth/mode'), (200, {'multi': True}))
        self.assertEqual(op('POST', '/api/v4/auth/login', {'username': 'develogic', 'password': 'wrong'})[0], 401)
        self.assertEqual(op('POST', '/api/v4/auth/login', {'username': 'develogic', 'password': 'operator-pass-1'})[0], 200)
        self.assertTrue(op('GET', '/api/v4/auth/me')[1]['operator'])

        # 운영자: 업체 2곳, 계정 발급
        self.assertEqual(op('POST', '/api/v4/accounts/companies', {'id': 'law-a', 'name': 'A 법률사무소'})[0], 200)
        self.assertEqual(op('POST', '/api/v4/accounts/companies', {'id': 'law-b', 'name': 'B 법률사무소'})[0], 200)
        self.assertEqual(op('PUT', '/api/v4/accounts/users', {'uid': 'a01', 'company': 'law-a', 'role': 'admin', 'password': 'a-pass-123'})[0], 200)
        self.assertEqual(op('PUT', '/api/v4/accounts/users', {'uid': 'a02', 'company': 'law-a', 'role': 'staff', 'password': 'a-staff-123'})[0], 200)
        self.assertEqual(op('PUT', '/api/v4/accounts/users', {'uid': 'b01', 'company': 'law-b', 'role': 'admin', 'password': 'b-pass-123'})[0], 200)
        self.assertEqual(op('PUT', '/api/v4/accounts/users', {'uid': 'b01', 'company': 'law-a', 'role': 'admin', 'password': 'x-pass-123'})[0], 422)  # 남의 아이디
        self.assertNotIn('a-pass-123', (Path(self.tmp.name) / 'accounts.json').read_text(encoding='utf-8'))

        self.assertEqual(a('POST', '/api/v4/auth/login', {'username': 'a01', 'password': 'a-pass-123'})[0], 200)
        self.assertEqual(b('POST', '/api/v4/auth/login', {'username': 'B01', 'password': 'b-pass-123'})[0], 200)   # 대소문자 무시
        self.assertEqual(a2('POST', '/api/v4/auth/login', {'username': 'a02', 'password': 'a-staff-123'})[0], 200)

        # 자료 분리: A 가 만든 사업지는 A 직원에게만 보이고 B 에게는 안 보인다
        self.assertEqual(a('POST', '/api/v4/sites', {'name': '서초 시범사업'})[0], 200)
        names = lambda c: [s['name'] for s in c('GET', '/api/v4/sites')[1]['sites']]
        self.assertEqual(names(a), ['서초 시범사업'])
        self.assertEqual(names(a2), ['서초 시범사업'])
        self.assertEqual(names(b), [])
        self.assertEqual(b('GET', '/api/v4/sites/' + '서초 시범사업')[0], 404)
        self.assertEqual(a('GET', '/api/v4/sites')[1]['inbox'], '')               # 서버 경로 숨김
        self.assertTrue((Path(self.tmp.name) / 'tenants' / 'law-a' / '자료함' / '서초 시범사업').is_dir())

        # 권한: 업체 관리자는 운영자 기능 불가, 직원은 삭제 불가
        self.assertEqual(a('GET', '/api/v4/accounts')[0], 403)
        self.assertEqual(a('PUT', '/api/v4/settings', {'vworld_key': 'x'})[0], 403)
        self.assertEqual(a('POST', '/api/v4/auth/passwords', {'admin': 'hijack-123'})[0], 403)
        self.assertEqual(a('POST', '/api/v4/sites/' + '서초 시범사업' + '/open')[0], 403)
        self.assertEqual(a2('DELETE', '/api/v4/sites/' + '서초 시범사업')[0], 403)
        self.assertEqual(b('DELETE', '/api/v4/sites/' + '서초 시범사업')[0], 404)    # B 는 A 자료를 지울 수 없음
        self.assertEqual(names(a), ['서초 시범사업'])

        # 비밀번호 변경 → 새 쿠키로 계속, 다른 브라우저의 예전 로그인은 끊김
        a_other = Client(app, '198.51.100.9')
        a_other('POST', '/api/v4/auth/login', {'username': 'a01', 'password': 'a-pass-123'})
        self.assertEqual(a('POST', '/api/v4/auth/my-password', {'current': 'a-pass-123', 'new': 'a-pass-456'})[0], 200)
        self.assertEqual(a('GET', '/api/v4/sites')[0], 200)
        self.assertEqual(a_other('GET', '/api/v4/sites')[0], 401)

        # 계정 삭제·업체 삭제 → 즉시 끊김
        self.assertEqual(op('DELETE', '/api/v4/accounts/users/a02')[0], 200)
        self.assertEqual(a2('GET', '/api/v4/sites')[0], 401)
        self.assertEqual(op('DELETE', '/api/v4/accounts/companies/law-b')[0], 200)
        self.assertEqual(b('GET', '/api/v4/sites')[0], 401)
        self.assertEqual(op('DELETE', '/api/v4/accounts/companies/develogic')[0], 422)   # 운영자 업체는 못 지움

    def test_no_tenant_no_inbox(self):
        from app import config
        with self.assertRaises(PermissionError):
            config.inbox()


if __name__ == '__main__':
    unittest.main()
