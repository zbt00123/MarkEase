# -*- coding: utf-8 -*-
"""
MarkEase 本地资源 HTTP 服务（阶段 12 收尾 修订 5）

路由：
    GET /web/<relpath>           → <web_dir>/<relpath>（index.html、CSS、JS、字体等全部前端资源）
    GET /fs/<urlencoded_abspath> → 任意绝对路径（白名单扩展名，用于本地图片/字体）
    GET / 或 /index.html         → 302 到 /web/index.html

特性：
- 监听 127.0.0.1 随机端口
- 所有响应带 CORS 头（允许从 file:// 跨 origin 访问）
- 只读，无写入接口
"""

import os
import threading
import mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote


ALLOWED_FS_EXTS = {
    # 图片
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico',
    # 字体
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
    # 前端资源（兜底）
    '.js', '.mjs', '.css', '.json', '.html',
}

MIME_OVERRIDES = {
    '.mjs': 'application/javascript; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
    '.eot': 'application/vnd.ms-fontobject',
    '.ico': 'image/x-icon',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
}


def _mime_for(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    guess, _ = mimetypes.guess_type(path)
    return guess or 'application/octet-stream'


class AssetServer:
    def __init__(self, web_dir):
        self._web_dir = os.path.abspath(web_dir)
        self._port = None
        self._server = None
        self._thread = None

    def start(self):
        web_dir = self._web_dir

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    self._handle_get()
                except Exception:
                    import traceback
                    traceback.print_exc()
                    try:
                        self.send_error(500)
                    except Exception:
                        pass

            def do_OPTIONS(self):
                try:
                    self.send_response(204)
                    self._cors_headers()
                    self.end_headers()
                except Exception:
                    pass

            def _cors_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', '*')

            def _handle_get(self):
                parsed = urlparse(self.path)
                path = parsed.path or '/'

                # ---------- /web/* ----------
                if path.startswith('/web/') or path == '/web':
                    rel = unquote(path[4:]) if path != '/web' else '/index.html'
                    rel = rel.lstrip('/') or 'index.html'
                    abs_path = os.path.normpath(os.path.join(web_dir, rel))
                    web_root = web_dir + os.sep
                    if not (abs_path == web_dir or abs_path.startswith(web_root)):
                        self.send_error(403, 'Forbidden')
                        return
                    self._serve_file(abs_path)
                    return

                # ---------- /fs/* ----------
                if path.startswith('/fs/'):
                    raw = unquote(path[4:])
                    abs_path = os.path.abspath(raw)
                    ext = os.path.splitext(abs_path)[1].lower()
                    if ext not in ALLOWED_FS_EXTS:
                        self.send_error(403, 'Extension not allowed')
                        return
                    self._serve_file(abs_path)
                    return

                # ---------- 根路径重定向 ----------
                if path == '/' or path == '/index.html':
                    self.send_response(302)
                    self._cors_headers()
                    self.send_header('Location', '/web/index.html')
                    self.end_headers()
                    return

                self.send_error(404)

            def _serve_file(self, abs_path):
                if not os.path.isfile(abs_path):
                    self.send_error(404, 'Not found')
                    return
                try:
                    with open(abs_path, 'rb') as f:
                        data = f.read()
                except Exception:
                    self.send_error(500)
                    return
                self.send_response(200)
                self.send_header('Content-Type', _mime_for(abs_path))
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-cache')
                self._cors_headers()
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt, *args):
                pass  # 静默日志

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self._port

    def stop(self):
        try:
            if self._server:
                self._server.shutdown()
                self._server.server_close()
        except Exception:
            pass