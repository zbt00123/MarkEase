# -*- coding: utf-8 -*-
"""
MarkEase HTML 导出器（阶段 16 第 8 批 + 本轮修订）

本批修复：
  1. 清理 CSS 里所有 @media (prefers-color-scheme: dark) {...} 块
  2. 检测图片真实文件头（AVIF/HEIC/WebP...），不安全格式用 Pillow 转码
  3. <meta name="color-scheme" content="light only"> + :root color-scheme
  4. <meta name="markease-source-doc-dir" content="base64(doc_dir)">
  5. <meta name="markease-source-md"> 里嵌入的 Markdown 原文，
     图片相对路径先绝对化（assets/x.png → D:/path/to/assets/x.png）

★ 本轮修订：
  - 导出 HTML 视觉层时，把本机 /proxy 代理 URL 还原为原始网络 URL
    （http://127.0.0.1:PORT/proxy?url=https%3A%2F%2F... → https://...）
    这样重新导入 HTML 时，图片走原始网络 URL，不再依赖本机代理
  - 保证网络图片 URL 完全不落盘、不改写

职责：
  - 接收前端渲染好的 HTML 片段 + 原始 Markdown
  - 套完整 HTML 模板（浅色主题，内联样式）
  - 图片 base64 内联（本地图片）；网络图片保留原始 URL
  - KaTeX 字体按需 base64 内联
  - 原始 Markdown + 原始 doc_dir 用 base64 嵌入 <meta>
"""

import os
import re
import base64
import mimetypes
from io import BytesIO

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


# ============================================================
#  常量
# ============================================================

IMAGE_COMPRESS_THRESHOLD = 200 * 1024   # 200 KB
IMAGE_MAX_WIDTH = 1600

SAFE_IMAGE_MIMES = {
    'image/png', 'image/jpeg', 'image/gif',
    'image/webp', 'image/bmp', 'image/x-icon',
    'image/svg+xml',
}

# Markdown 图片语法：![alt](url) 或 ![alt](<url>)
_MD_IMG_RE = re.compile(
    r'(!\[[^\]]*\]\()(\s*)(<[^>]*>|[^)\s]+)([^)]*)(\))'
)

# HTML <img src="...">
_HTML_IMG_SRC_RE = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])([^"\']*)(\2[^>]*>)',
    re.IGNORECASE
)

# 本机 /proxy 代理 URL 匹配
_PROXY_URL_RE = re.compile(
    r'^https?://127\.0\.0\.1:\d+/proxy\?url=(.+)$',
    re.IGNORECASE
)


# ============================================================
#  ★ 图片路径绝对化（阶段 16 第 8 批）
# ============================================================

def _absolutize_one_url(url, norm_dir):
    """
    把单个 URL 从相对转绝对。
    - 空 / data: / blob: / file: / http(s): / Windows 盘符 / Unix 根路径 → 原样
    - 其他（相对路径）→ norm_dir + '/' + url
    - URL 里含空格/括号 → 用 <...> 包裹
    """
    if not url:
        return url

    stripped = url.strip()
    was_angle = False
    if stripped.startswith('<') and stripped.endswith('>'):
        was_angle = True
        stripped = stripped[1:-1]

    if not stripped:
        return url

    # 保持原样
    if re.match(r'^(https?:|data:|blob:|file:)', stripped, re.IGNORECASE):
        return url
    if re.match(r'^[A-Za-z]:[\\/]', stripped):
        return url
    if stripped.startswith('/'):
        return url

    new_path = norm_dir + '/' + stripped.lstrip('/')

    if was_angle:
        return '<' + new_path + '>'
    if re.search(r'[\s()]', new_path):
        return '<' + new_path + '>'
    return new_path


def absolutize_image_paths_in_markdown(md_text, doc_dir):
    """
    把 Markdown 里所有图片的相对路径转成绝对路径。

    用于 PDF / HTML 导出时嵌入的 Markdown 原文：
    这样重新导入后，即使没有 doc_dir 上下文，图片也能通过绝对路径加载。

    - Markdown 图片语法：![alt](path) 和 ![alt](<path>)
    - HTML <img src="path">
    - 不改动：http(s)://、data:、blob:、file:、Windows 盘符、Unix 根路径
    """
    if not md_text:
        return ''
    if not doc_dir:
        return md_text

    norm_dir = str(doc_dir).replace('\\', '/').rstrip('/')
    if not norm_dir:
        return md_text

    result = md_text

    # 1) Markdown 图片语法
    def repl_md(match):
        head = match.group(1)
        space1 = match.group(2)
        url = match.group(3)
        rest = match.group(4) or ''
        tail = match.group(5)
        new_url = _absolutize_one_url(url, norm_dir)
        return f'{head}{space1}{new_url}{rest}{tail}'

    result = _MD_IMG_RE.sub(repl_md, result)

    # 2) HTML <img src="...">
    def repl_html(match):
        prefix = match.group(1)
        quote = match.group(2)
        url = match.group(3)
        rest = match.group(4)
        new_url = _absolutize_one_url(url, norm_dir)
        if new_url.startswith('<') and new_url.endswith('>'):
            new_url = new_url[1:-1]
        return f'{prefix}{quote}{new_url}{quote}{rest}'

    result = _HTML_IMG_SRC_RE.sub(repl_html, result)

    return result


# ============================================================
#  工具函数
# ============================================================

def _read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _read_binary(path):
    with open(path, 'rb') as f:
        return f.read()


def _guess_mime(path):
    mime, _ = mimetypes.guess_type(path)
    return mime or 'application/octet-stream'


def _to_data_url(path):
    if not os.path.isfile(path):
        return None
    try:
        data = _read_binary(path)
        mime = _guess_mime(path)
        b64 = base64.b64encode(data).decode('ascii')
        return f'data:{mime};base64,{b64}'
    except Exception:
        return None


def _html_escape(s):
    return (str(s)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))


# ============================================================
#  图片真实类型检测（读文件头）
# ============================================================

def _detect_real_image_mime(abs_path):
    try:
        with open(abs_path, 'rb') as f:
            head = f.read(32)
    except Exception:
        return None

    if not head:
        return None

    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith(b'GIF87a') or head.startswith(b'GIF89a'):
        return 'image/gif'
    if len(head) >= 12 and head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        return 'image/webp'
    if head.startswith(b'BM'):
        return 'image/bmp'
    if head[:4] == b'\x00\x00\x01\x00':
        return 'image/x-icon'
    if len(head) >= 12 and head[4:12] in (b'ftypavif', b'ftypavis'):
        return 'image/avif'
    if len(head) >= 12 and head[4:8] == b'ftyp' and head[8:12] in (
        b'heic', b'heix', b'hevc', b'hevx', b'mif1', b'msf1'
    ):
        return 'image/heic'
    stripped = head.lstrip()
    if stripped.startswith(b'<svg') or stripped.startswith(b'<?xml'):
        return 'image/svg+xml'

    return None


def _read_image_as_data_url(abs_path, force_compress=False):
    if not os.path.isfile(abs_path):
        return None

    real_mime = _detect_real_image_mime(abs_path)
    ext = os.path.splitext(abs_path)[1].lower()

    if real_mime == 'image/svg+xml':
        try:
            data = _read_binary(abs_path)
            b64 = base64.b64encode(data).decode('ascii')
            return f'data:image/svg+xml;base64,{b64}'
        except Exception:
            return None

    if real_mime in SAFE_IMAGE_MIMES:
        try:
            size = os.path.getsize(abs_path)
        except Exception:
            size = 0

        if _HAS_PIL and (force_compress or size > IMAGE_COMPRESS_THRESHOLD):
            compressed = _compress_with_pil(abs_path, real_mime)
            if compressed:
                mime, data = compressed
                b64 = base64.b64encode(data).decode('ascii')
                return f'data:{mime};base64,{b64}'

        try:
            data = _read_binary(abs_path)
            b64 = base64.b64encode(data).decode('ascii')
            return f'data:{real_mime};base64,{b64}'
        except Exception:
            return None

    if _HAS_PIL:
        result = _transcode_with_pil(abs_path)
        if result:
            mime, data = result
            b64 = base64.b64encode(data).decode('ascii')
            return f'data:{mime};base64,{b64}'

    print(f'[html_exporter] warning: cannot transcode {abs_path} '
          f'(real_mime={real_mime}, ext={ext})')
    return _to_data_url(abs_path)


def _compress_with_pil(abs_path, real_mime):
    try:
        img = Image.open(abs_path)
        if img.width > IMAGE_MAX_WIDTH:
            ratio = IMAGE_MAX_WIDTH / float(img.width)
            new_h = max(1, int(img.height * ratio))
            img = img.resize((IMAGE_MAX_WIDTH, new_h), Image.LANCZOS)

        buf = BytesIO()
        has_alpha = img.mode in ('RGBA', 'LA', 'P')

        if real_mime == 'image/gif':
            try:
                if getattr(img, 'n_frames', 1) > 1:
                    return None
            except Exception:
                pass

        if has_alpha:
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            img.save(buf, format='PNG', optimize=True)
            return ('image/png', buf.getvalue())
        else:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(buf, format='JPEG', quality=85, optimize=True)
            return ('image/jpeg', buf.getvalue())
    except Exception:
        return None


def _transcode_with_pil(abs_path):
    try:
        img = Image.open(abs_path)
        try:
            img.seek(0)
        except Exception:
            pass

        if img.width > IMAGE_MAX_WIDTH:
            ratio = IMAGE_MAX_WIDTH / float(img.width)
            new_h = max(1, int(img.height * ratio))
            img = img.resize((IMAGE_MAX_WIDTH, new_h), Image.LANCZOS)

        buf = BytesIO()
        has_alpha = img.mode in ('RGBA', 'LA', 'P')
        if has_alpha:
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            img.save(buf, format='PNG', optimize=True)
            return ('image/png', buf.getvalue())
        else:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(buf, format='JPEG', quality=88, optimize=True)
            return ('image/jpeg', buf.getvalue())
    except Exception as e:
        print(f'[html_exporter] Pillow transcode failed: {e}')
        return None


# ============================================================
#  路径解析
# ============================================================

IMG_SRC_RE = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])([^"\']+)(\2)',
    re.IGNORECASE
)


def _resolve_local_path(src, doc_dir):
    if not src:
        return None

    m = re.match(r'^https?://127\.0\.0\.1:\d+/fs/(.+)$', src, re.IGNORECASE)
    if m:
        try:
            from urllib.parse import unquote
            return unquote(m.group(1))
        except Exception:
            return None

    if src.lower().startswith('file:///'):
        try:
            from urllib.parse import unquote
            p = unquote(src[8:])
            if re.match(r'^/[A-Za-z]:/', p):
                p = p[1:]
            return p
        except Exception:
            return None

    if re.match(r'^(data:|blob:|https?://)', src, re.IGNORECASE):
        return None

    if re.match(r'^[A-Za-z]:[\\/]', src):
        return src

    if src.startswith('/') and not src.startswith('//'):
        return src

    if not doc_dir:
        return None
    norm_dir = doc_dir.replace('\\', '/').rstrip('/')
    if not norm_dir:
        return None
    return norm_dir + '/' + src


def _embed_images_in_html(html, doc_dir, stats):
    """
    遍历 HTML 视觉层里的 <img src="...">：
      1) data: URL       → 原样
      2) 本机 /proxy URL → ★ 还原为原始网络 URL（不改写、不 base64）
      3) http(s)://      → 保留原样（除本机 fs）
      4) 本机 /fs/ URL   → base64 内联
      5) file:// 或相对路径 → base64 内联
    """
    def repl(match):
        prefix = match.group(1)
        quote = match.group(2)
        src = match.group(3)

        # 1) data: URL
        if src.startswith('data:'):
            stats['kept_data'] = stats.get('kept_data', 0) + 1
            return match.group(0)

        # ★ 2) 本机 /proxy 代理 URL → 还原为原始网络 URL
        proxy_match = _PROXY_URL_RE.match(src)
        if proxy_match:
            try:
                from urllib.parse import unquote
                original = unquote(proxy_match.group(1))
                stats['remote'] = stats.get('remote', 0) + 1
                print(f'[html_exporter] proxy → original: {original[:80]}')
                return f'{prefix}{quote}{original}{quote}'
            except Exception as e:
                print(f'[html_exporter] proxy decode failed: {e}')
                # 若解码失败，保持原样（避免丢失）

        # 3) 其他 http(s):// → 保留原样
        if re.match(r'^https?://', src, re.IGNORECASE):
            if not re.match(r'^https?://127\.0\.0\.1:\d+/fs/', src, re.IGNORECASE):
                stats['remote'] = stats.get('remote', 0) + 1
                return match.group(0)

        # 4/5) 本地图片 → base64 内联
        abs_path = _resolve_local_path(src, doc_dir)
        if not abs_path or not os.path.isfile(abs_path):
            stats['failed'] = stats.get('failed', 0) + 1
            return match.group(0)

        data_url = _read_image_as_data_url(abs_path)
        if data_url:
            stats['embedded'] = stats.get('embedded', 0) + 1
            ext = os.path.splitext(abs_path)[1].lower().lstrip('.')
            if 'data:image/' in data_url:
                mime = data_url.split(';')[0].replace('data:', '')
                if 'png' in mime and ext not in ('png',):
                    stats['transcoded'] = stats.get('transcoded', 0) + 1
                elif 'jpeg' in mime and ext not in ('jpg', 'jpeg'):
                    stats['transcoded'] = stats.get('transcoded', 0) + 1
            return f'{prefix}{quote}{data_url}{quote}'

        stats['failed'] = stats.get('failed', 0) + 1
        return match.group(0)

    return IMG_SRC_RE.sub(repl, html)


# ============================================================
#  CSS 深色模式清理
# ============================================================

def _strip_dark_media(css_text):
    if not css_text:
        return css_text

    result = []
    i = 0
    n = len(css_text)
    pattern = re.compile(
        r'@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)',
        re.IGNORECASE
    )

    while i < n:
        m = pattern.search(css_text, i)
        if not m:
            result.append(css_text[i:])
            break

        start = m.start()
        result.append(css_text[i:start])

        j = m.end()
        while j < n and css_text[j] in ' \t\n\r':
            j += 1

        if j >= n or css_text[j] != '{':
            i = m.end()
            continue

        depth = 1
        k = j + 1
        while k < n and depth > 0:
            if css_text[k] == '{':
                depth += 1
            elif css_text[k] == '}':
                depth -= 1
            k += 1

        i = k

    return ''.join(result)


# ============================================================
#  KaTeX 字体内联
# ============================================================

KATEX_FONT_FACE_RE = re.compile(
    r'@font-face\s*\{[^}]*?\}',
    re.IGNORECASE | re.DOTALL
)

FONT_URL_RE = re.compile(r'url\(\s*["\']?([^"\')]+\.woff2)["\']?\s*\)',
                         re.IGNORECASE)


def _inline_katex_fonts(css_text, fonts_dir):
    if not css_text:
        return css_text

    def block_repl(match):
        block = match.group(0)
        if not FONT_URL_RE.search(block):
            return block

        def url_repl(m):
            url = m.group(1)
            fname = os.path.basename(url)
            fpath = os.path.join(fonts_dir, fname)
            if not os.path.isfile(fpath):
                return m.group(0)
            try:
                data = _read_binary(fpath)
                b64 = base64.b64encode(data).decode('ascii')
                data_url = f'data:font/woff2;base64,{b64}'
                return f'url({data_url})'
            except Exception:
                return m.group(0)

        return FONT_URL_RE.sub(url_repl, block)

    return KATEX_FONT_FACE_RE.sub(block_repl, css_text)


# ============================================================
#  HTML 模板
# ============================================================

BASE_CSS = '''
* { box-sizing: border-box; }
img { max-width: 100%; height: auto; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 24px 0; }
'''


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="generator" content="MarkEase">
<meta name="color-scheme" content="light only">
<meta name="markease-source-md" content="{source_md_b64}">
<meta name="markease-source-doc-dir" content="{source_doc_dir_b64}">
<title>{title}</title>
<style>
{base_css}

{github_md_css}

{highlight_css}

{katex_css}

/* ===== MarkEase 导出补充样式（浅色强制） ===== */
:root {{
    color-scheme: light only !important;
}}
html, body {{
    background: #ffffff !important;
    color: #1f2328 !important;
    color-scheme: light only !important;
}}
body {{
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei",
                 "PingFang SC", "Hiragino Sans GB", "Helvetica Neue", Arial, sans-serif;
    font-size: 15px;
    line-height: 1.65;
}}
.markdown-body {{
    max-width: 900px;
    margin: 0 auto;
    padding: 32px 40px 64px;
    box-sizing: border-box;
    background: #ffffff !important;
    color: #1f2328 !important;
    color-scheme: light only !important;
}}
.markdown-body table,
.markdown-body table th,
.markdown-body table td {{
    background: #ffffff;
    color: #1f2328;
}}
.markdown-body table tr {{
    background: #ffffff;
}}
.markdown-body table tr:nth-child(2n) {{
    background: #f6f8fa;
}}
.markdown-body pre,
.markdown-body pre code {{
    background: #f6f8fa !important;
    color: #1f2328 !important;
}}
.markdown-body code {{
    background: rgba(27,31,35,0.06) !important;
    color: #1f2328 !important;
}}
details.md-details {{
    margin: 12px 0;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    background: #f6f8fa;
    padding: 0;
}}
details.md-details[open] {{ background: #ffffff; }}
details.md-details > summary.md-summary {{
    cursor: pointer;
    padding: 8px 12px 8px 30px;
    font-weight: 600;
    font-size: 14px;
    color: #24292f;
    list-style: none;
    position: relative;
    border-bottom: 1px solid transparent;
}}
details.md-details[open] > summary.md-summary {{
    border-bottom-color: #e1e4e8;
}}
details.md-details > summary.md-summary::before {{
    content: '\\25B6';
    position: absolute;
    left: 11px; top: 50%;
    transform: translateY(-50%);
    font-size: 10px; color: #57606a;
}}
details.md-details[open] > summary.md-summary::before {{
    content: '\\25BC'; color: #0969da;
}}
details.md-details > *:not(summary) {{
    padding-left: 12px; padding-right: 12px;
}}
li.task-list-item,
li.task-list-item::marker {{ list-style: none !important; }}
li.task-list-item::before {{ content: none !important; }}
ul.contains-task-list, ol.contains-task-list {{
    list-style: none; padding-left: 0;
}}
.task-list-bullet {{
    color: #8b949e;
    font-family: Consolas, "Courier New", monospace;
    display: inline;
    margin-right: 2px;
    user-select: text;
}}
.task-list-checkbox {{
    display: inline-block;
    width: 13px; height: 13px;
    border: 1.5px solid #6e7781;
    border-radius: 3px;
    vertical-align: -2px;
    margin-right: 6px;
    position: relative;
    background: #fff;
    font-size: 0;
    line-height: 0;
    color: transparent;
    overflow: hidden;
    text-indent: -9999px;
    box-sizing: border-box;
}}
.task-list-checkbox::after {{
    content: '';
    position: absolute;
    left: 3px; top: 0;
    width: 4px; height: 8px;
    border: solid #fff;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg) scale(0);
}}
.task-list-checkbox[data-md-task-checked="1"] {{
    background: #0969da;
    border-color: #0969da;
}}
.task-list-checkbox[data-md-task-checked="1"]::after {{
    transform: rotate(45deg) scale(1);
}}
.markdown-body li > p:only-child,
.markdown-body li > p:first-child:last-child {{
    display: inline;
    margin: 0;
    padding: 0;
}}
.katex-inline {{ display: inline; }}
.math-block {{ margin: 12px 0; text-align: center; }}
.katex-error {{ color: #d1242f; }}
@media (prefers-color-scheme: dark) {{
    html, body {{
        background: #ffffff !important;
        color: #1f2328 !important;
        color-scheme: light only !important;
    }}
    .markdown-body {{
        background: #ffffff !important;
        color: #1f2328 !important;
    }}
    .markdown-body table,
    .markdown-body table th,
    .markdown-body table td {{
        background: #ffffff !important;
        color: #1f2328 !important;
    }}
    .markdown-body table tr:nth-child(2n) {{
        background: #f6f8fa !important;
    }}
    .markdown-body pre,
    .markdown-body pre code {{
        background: #f6f8fa !important;
        color: #1f2328 !important;
    }}
    .markdown-body code {{
        background: rgba(27,31,35,0.06) !important;
        color: #1f2328 !important;
    }}
}}
</style>
</head>
<body>
<article class="markdown-body">
{content_html}
</article>
</body>
</html>
'''


# ============================================================
#  主入口
# ============================================================

def export_html(
    content_html,
    markdown_text,
    output_path,
    title='MarkEase 导出',
    doc_dir='',
    app_root='',
):
    """
    导出 HTML 文件。

    - content_html：预览 DOM 的 HTML 片段（img src 可能是本机 /proxy URL）
    - markdown_text：编辑器里的原始 Markdown
    - doc_dir：当前文档所在目录

    ★ 本轮修订：
      把 content_html 里的本机 /proxy 代理 URL 还原为原始网络 URL，
      这样重新导入 HTML 时，图片走原始网络 URL，不依赖本机代理。
    """
    stats = {
        'embedded': 0,
        'compressed': 0,
        'transcoded': 0,
        'remote': 0,
        'failed': 0,
        'kept_data': 0,
    }

    try:
        # 1) 图片处理（含 /proxy 还原）
        html_with_imgs = _embed_images_in_html(content_html or '', doc_dir, stats)

        # 2) Markdown 原文：图片路径绝对化
        md_absolute = absolutize_image_paths_in_markdown(
            markdown_text or '', doc_dir
        )
        md_bytes = md_absolute.encode('utf-8')
        md_b64 = base64.b64encode(md_bytes).decode('ascii')

        # 3) base64 编码原始 doc_dir
        doc_dir_str = str(doc_dir or '')
        if doc_dir_str:
            doc_dir_b64 = base64.b64encode(
                doc_dir_str.encode('utf-8')
            ).decode('ascii')
        else:
            doc_dir_b64 = ''

        # 4) 读取 CSS（app_root 存在时）
        github_md_css = ''
        highlight_css = ''
        katex_css = ''

        if app_root:
            css_dir = os.path.join(app_root, 'web', 'css')
            fonts_dir = os.path.join(css_dir, 'fonts')

            gm_path = os.path.join(css_dir, 'github-markdown.css')
            if os.path.isfile(gm_path):
                try:
                    raw = _read_text(gm_path)
                    github_md_css = _strip_dark_media(raw)
                except Exception:
                    github_md_css = ''

            hl_path = os.path.join(css_dir, 'highlight-github.min.css')
            if os.path.isfile(hl_path):
                try:
                    raw = _read_text(hl_path)
                    highlight_css = _strip_dark_media(raw)
                except Exception:
                    highlight_css = ''

            katex_path = os.path.join(css_dir, 'katex.min.css')
            if os.path.isfile(katex_path):
                try:
                    raw = _read_text(katex_path)
                    raw = _strip_dark_media(raw)
                    katex_css = _inline_katex_fonts(raw, fonts_dir)
                except Exception:
                    katex_css = ''

        # 5) 套模板
        full_html = HTML_TEMPLATE.format(
            source_md_b64=_html_escape(md_b64),
            source_doc_dir_b64=_html_escape(doc_dir_b64),
            title=_html_escape(title),
            base_css=BASE_CSS,
            github_md_css=github_md_css,
            highlight_css=highlight_css,
            katex_css=katex_css,
            content_html=html_with_imgs,
        )

        # 6) 写文件
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(full_html)

        size = os.path.getsize(output_path)
        return {
            'ok': True,
            'path': output_path,
            'size': size,
            'stats': stats,
        }
    except Exception as e:
        return {
            'ok': False,
            'error': str(e),
            'stats': stats,
        }


def extract_source_markdown(html_text):
    """从 MarkEase 导出的 HTML 中提取原始 Markdown。"""
    if not html_text:
        return None
    m = re.search(
        r'<meta\s+name\s*=\s*["\']markease-source-md["\']\s+'
        r'content\s*=\s*["\']([^"\']+)["\']',
        html_text,
        re.IGNORECASE
    )
    if not m:
        return None
    try:
        b64 = m.group(1)
        b64 = (b64.replace('&amp;', '&')
                    .replace('&lt;', '<')
                    .replace('&gt;', '>')
                    .replace('&quot;', '"')
                    .replace('&#39;', "'"))
        data = base64.b64decode(b64)
        return data.decode('utf-8')
    except Exception:
        return None


def extract_source_doc_dir(html_text):
    """
    从 MarkEase 导出的 HTML 中提取原始文档目录。
    返回 str（可能为空字符串），解析失败返回 ''。
    """
    if not html_text:
        return ''
    m = re.search(
        r'<meta\s+name\s*=\s*["\']markease-source-doc-dir["\']\s+'
        r'content\s*=\s*["\']([^"\']*)["\']',
        html_text,
        re.IGNORECASE
    )
    if not m:
        return ''
    try:
        b64 = m.group(1)
        b64 = (b64.replace('&amp;', '&')
                    .replace('&lt;', '<')
                    .replace('&gt;', '>')
                    .replace('&quot;', '"')
                    .replace('&#39;', "'"))
        if not b64:
            return ''
        data = base64.b64decode(b64)
        return data.decode('utf-8')
    except Exception:
        return ''