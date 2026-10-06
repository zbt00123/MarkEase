# -*- coding: utf-8 -*-
"""
MarkEase 本地资源 HTTP 服务（阶段 16 修订）

路由：
    GET /web/<relpath>           → <web_dir>/<relpath>（前端资源）
    GET /fs/<urlencoded_abspath> → 任意绝对路径（白名单扩展名，用于本地图片/字体）
    GET /proxy?url=<encoded>     → ★ 新增：后端代理下载网络图片
    GET / 或 /index.html         → 302 到 /web/index.html

特性：
- 监听 127.0.0.1 随机端口
- 所有响应带 CORS 头（允许从 file:// 跨 origin 访问）
- ★ /proxy 路由通过后端下载网络图片：
    - 带浏览器 User-Agent + Referer 绕过防盗链
    - Accept 头包含 image/avif，避免服务器降级
    - 绕过系统代理
    - 限制单张 30MB、超时 20 秒
    - 响应带 Cache-Control: public, max-age=3600
"""

import os
import threading
import mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs


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
    '.avif': 'image/avif',
}


def _mime_for(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in MIME_OVERRIDES:
        return MIME_OVERRIDES[ext]
    guess, _ = mimetypes.guess_type(path)
    return guess or 'application/octet-stream'


# ============================================================
#  /proxy 后端代理下载网络图片
# ============================================================
_PROXY_MAX_BYTES = 30 * 1024 * 1024   # 单张上限 30MB
_PROXY_TIMEOUT = 20                    # 下载超时 20 秒
_PROXY_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)
_PROXY_ACCEPT = (
    'image/avif,image/webp,image/apng,image/svg+xml,image/*,'
    '*/*;q=0.8'
)


def _proxy_download(url):
    """
    后端下载 URL 内容。返回 (data: bytes, content_type: str)。
    失败时抛异常。
    """
    import urllib.request

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('unsupported scheme: ' + parsed.scheme)

    # 用 URL 的域名作为 Referer（很多图床 / CDN 用 Referer 防盗链）
    referer = f'{parsed.scheme}://{parsed.netloc}/'

    req = urllib.request.Request(url, headers={
        'User-Agent': _PROXY_UA,
        'Referer': referer,
        'Accept': _PROXY_ACCEPT,
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'identity',
    })

    # 显式禁用系统代理，避免 VPN 干扰
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )
    with opener.open(req, timeout=_PROXY_TIMEOUT) as resp:
        # 分块读取，限制最大字节数
        chunks = []
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _PROXY_MAX_BYTES:
                raise ValueError(
                    'image too large (>{:.0f}MB)'.format(
                        _PROXY_MAX_BYTES / 1024 / 1024))
            chunks.append(chunk)
        data = b''.join(chunks)
        ct = resp.headers.get('Content-Type', 'image/png')
        return data, ct


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

                # ---------- /proxy?url=xxx ----------
                if path == '/proxy' or path.startswith('/proxy'):
                    self._handle_proxy(parsed)
                    return

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

            def _handle_proxy(self, parsed):
                qs = parse_qs(parsed.query or '')
                url_list = qs.get('url', [])
                if not url_list:
                    self.send_error(400, 'Missing url parameter')
                    return
                url = url_list[0].strip()
                if not url:
                    self.send_error(400, 'Empty url parameter')
                    return

                try:
                    data, ct = _proxy_download(url)
                except Exception as e:
                    try:
                        self.send_error(502, 'Proxy failed: ' + str(e)[:200])
                    except Exception:
                        pass
                    return

                try:
                    self.send_response(200)
                    self.send_header('Content-Type', ct or 'image/png')
                    self.send_header('Content-Length', str(len(data)))
                    # 浏览器缓存 1 小时
                    self.send_header('Cache-Control', 'public, max-age=3600')
                    self._cors_headers()
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    pass

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