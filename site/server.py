# -*- coding: utf-8 -*-
"""婚礼邀请函抽签站点 · 零依赖 Python 服务
- 每位访客仅能抽 1 次（浏览器 token 记账，服务端落库）
- 已被抽走的邀请函不再进入抽签池（全局唯一）
运行：python3 server.py  (默认端口 52368，可用 PORT 环境变量覆盖)
"""
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(ROOT, 'public')
INVITE_DIR = os.path.join(ROOT, 'invites')
DATA_FILE = os.path.join(ROOT, 'data', 'claims.json')
PORT = int(os.environ.get('PORT', '52368'))
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'congjiang')

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
}
LOCK = threading.Lock()
CST = timezone(timedelta(hours=8))


def all_codes():
    if not os.path.isdir(INVITE_DIR):
        return []
    out = []
    for f in os.listdir(INVITE_DIR):
        m = re.match(r'^(\w+)\.(jpg|jpeg|png)$', f, re.I)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def code_path(code):
    for ext in ('.jpg', '.jpeg', '.png'):
        p = os.path.join(INVITE_DIR, code + ext)
        if os.path.exists(p):
            return p, ext
    return None, None


def read_store():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        return {'claims': {}}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        data.setdefault('claims', {})
        return data
    except Exception:
        return {'claims': {}}


def write_store(store):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(store, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def stat_payload(store=None):
    store = store or read_store()
    codes = all_codes()
    taken = {c['code'] for c in store['claims'].values()}
    return {'total': len(codes), 'remaining': max(0, len(codes) - len(taken))}


class Handler(BaseHTTPRequestHandler):
    server_version = 'InviteDraw/1.0'

    def log_message(self, fmt, *args):
        print('[%s] %s' % (datetime.now(CST).strftime('%H:%M:%S'), fmt % args))

    def _json(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _bytes(self, status, raw, ctype, cache='no-store'):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', cache)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        p = unquote(u.path)
        q = parse_qs(u.query)

        if p == '/api/status':
            return self._json(200, stat_payload())

        if p == '/api/me':
            token = (q.get('token') or [''])[0][:80]
            store = read_store()
            mine = store['claims'].get(token)
            body = {
                'claimed': bool(mine),
                'code': mine['code'] if mine else None,
                'image': '/invite/%s' % mine['code'] if mine else None,
                'name': mine.get('name', '') if mine else '',
            }
            body.update(stat_payload(store))
            return self._json(200, body)

        if p == '/api/admin/list':
            if (q.get('key') or [''])[0] != ADMIN_KEY:
                return self._json(403, {'error': 'forbidden'})
            store = read_store()
            rows = []
            for token, v in store['claims'].items():
                rows.append({'token': token[:10] + '…', 'code': v['code'],
                             'name': v.get('name', ''), 'at': v.get('at', '')})
            rows.sort(key=lambda r: r['at'], reverse=True)
            taken = {r['code'] for r in rows}
            body = {'rows': rows, 'unclaimed': [c for c in all_codes() if c not in taken]}
            body.update(stat_payload(store))
            return self._json(200, body)

        if p.startswith('/invite/'):
            code = re.sub(r'[^0-9A-Za-z]', '', p[len('/invite/'):])
            fp_, ext = code_path(code)
            if not fp_:
                return self._bytes(404, b'not found', 'text/plain; charset=utf-8')
            with open(fp_, 'rb') as f:
                raw = f.read()
            return self._bytes(200, raw, MIME.get(ext, 'application/octet-stream'),
                               'public, max-age=31536000')

        rel = '/index.html' if p == '/' else p
        if p == '/admin':
            rel = '/admin.html'
        safe = os.path.normpath(rel).lstrip('/')
        target = os.path.join(PUBLIC_DIR, safe)
        if os.path.isfile(target) and target.startswith(PUBLIC_DIR):
            ext = os.path.splitext(target)[1].lower()
            with open(target, 'rb') as f:
                raw = f.read()
            cache = 'no-store' if ext == '.html' else 'public, max-age=3600'
            return self._bytes(200, raw, MIME.get(ext, 'application/octet-stream'), cache)

        return self._bytes(404, b'404', 'text/plain; charset=utf-8')

    def do_POST(self):
        u = urlparse(self.path)
        if unquote(u.path) != '/api/draw':
            return self._json(404, {'error': 'not found'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(min(n, 100000)) or b'{}')
        except Exception:
            body = {}
        token = str(body.get('token', ''))[:80]
        name = str(body.get('name', ''))[:40]
        if not token:
            return self._json(400, {'error': 'missing token'})

        with LOCK:
            store = read_store()
            mine = store['claims'].get(token)
            if mine:
                res = {'repeat': True, 'code': mine['code'], 'name': mine.get('name', '')}
                res.update({'image': '/invite/%s' % mine['code']})
                res.update(stat_payload(store))
                return self._json(200, res)
            taken = {c['code'] for c in store['claims'].values()}
            pool = [c for c in all_codes() if c not in taken]
            if not pool:
                out = {'error': 'sold_out'}
                out.update(stat_payload(store))
                return self._json(410, out)
            pick = secrets.choice(pool)
            store['claims'][token] = {
                'code': pick,
                'name': name,
                'at': datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S'),
                'ip': self.headers.get('X-Forwarded-For') or self.client_address[0],
            }
            write_store(store)
            res = {'repeat': False, 'code': pick, 'name': name,
                   'image': '/invite/%s' % pick}
            res.update(stat_payload(store))
            return self._json(200, res)


if __name__ == '__main__':
    print('invites: %d, serving on http://0.0.0.0:%d' % (len(all_codes()), PORT))
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
