# -*- coding: utf-8 -*-
"""
MarkEase HTML 导入器（阶段 16 第 4 批 + 本轮修订）

职责：
  - 读取 .html 文件
  - 优先检测 MarkEase 导出的 <meta name="markease-source-md">（100% 还原）
  - 检测 <meta name="markease-source-doc-dir">（还原 currentDocDir）
  - 第三方 HTML → 返回原始 HTML 字符串，由前端 DOM 转换

★ 本轮修订（导入图片缺失恢复）：
  1. 读取到 markease-source-md 后，检查 Markdown 里所有本地图片
     路径是否存在。
  2. 缺失的图片从 HTML 视觉层的 <img src="data:image/...;base64,...">
     按顺序提取，写入系统临时文件夹，替换 Markdown 里对应的路径。
  3. 网络图片（http/https）不参与恢复，原样保留。
  4. 导出 recover_images_in_markdown 公共函数供 app/api.py 调用
     （拖拽无路径的 HTML 场景）。
"""

import os
import re
import base64
import tempfile  # ★ 本轮新增

from .html_exporter import (
    extract_source_markdown,
    extract_source_doc_dir,
    _MD_IMG_RE,
    _HTML_IMG_SRC_RE,
)


# ★ 本轮新增：data URL 解析
_DATA_URL_RE = re.compile(
    r'^data:image/([a-zA-Z0-9.+-]+);base64,(.+)$',
    re.DOTALL
)

_DATA_URL_EXT = {
    'png': '.png',
    'jpeg': '.jpg',
    'jpg': '.jpg',
    'gif': '.gif',
    'webp': '.webp',
    'bmp': '.bmp',
    'svg+xml': '.svg',
    'x-icon': '.ico',
    'vnd.microsoft.icon': '.ico',
}

# ★ 本轮新增：HTML 视觉层的 base64 内联图片
_HTML_B64_IMG_RE = re.compile(
    r'<img\b[^>]*?\bsrc\s*=\s*["\'](data:image/[^"\']+)["\']',
    re.IGNORECASE
)


# 尝试的解码顺序
_DECODE_ENCODINGS = ('utf-8', 'utf-8-sig', 'gbk', 'gb18030', 'latin-1')


def _read_html_text(path):
    """按多种编码尝试读取 HTML 文本"""
    for enc in _DECODE_ENCODINGS:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            continue
    return None


# ============================================================
# ★ 本轮新增：从 HTML 视觉层恢复 Markdown 里缺失的本地图片
# ============================================================

def _is_local_and_missing(url, doc_dir_abs):
    """
    判断 URL 是否是「本地路径且文件不存在」。

    - http(s): / data: / blob: / file: → False（跳过，不处理）
    - Windows 盘符绝对路径 → 检查文件是否存在
    - Unix 绝对路径 → 检查文件是否存在
    - 相对路径 → 相对 doc_dir_abs 拼接后检查
    """
    if not url:
        return False

    raw = url
    if raw.startswith('<') and raw.endswith('>'):
        raw = raw[1:-1]

    if re.match(r'^(https?:|data:|blob:|file:)', raw, re.IGNORECASE):
        return False

    if re.match(r'^[A-Za-z]:[\\/]', raw):
        return not os.path.isfile(raw)

    if raw.startswith('/'):
        return not os.path.isfile(raw)

    if not doc_dir_abs:
        return False
    return not os.path.isfile(os.path.join(doc_dir_abs, raw))


def recover_images_in_markdown(md, doc_dir, html_text):
    """
    从 HTML 视觉层的 base64 数据中恢复 Markdown 里缺失的本地图片。

    参数：
        md           - Markdown 内容
        doc_dir      - Markdown 原始文档目录（用于判断相对路径是否存在）
        html_text    - 完整的 HTML 文本

    返回：
        (new_md, recovered_count)
    """
    if not md or not html_text:
        return md, 0

    # 1) 提取 HTML 视觉层里的 base64 内联图片（按文档顺序）
    html_images = []
    for m in _HTML_B64_IMG_RE.finditer(html_text):
        html_images.append(m.group(1))

    if not html_images:
        return md, 0

    doc_dir_abs = os.path.abspath(doc_dir) if doc_dir else ''

    # 2) 收集 Markdown 里所有图片引用（按位置排序）
    matches = []
    for m in _MD_IMG_RE.finditer(md):
        matches.append((m, 3))
    for m in _HTML_IMG_SRC_RE.finditer(md):
        matches.append((m, 3))
    matches.sort(key=lambda x: x[0].start())

    # 3) 过滤出「本地且缺失」的图片
    missing = [
        (m, g) for m, g in matches
        if _is_local_and_missing(m.group(g), doc_dir_abs)
    ]

    if not missing:
        return md, 0

    # 4) 把 HTML 里提取到的图片写入临时文件夹，替换 Markdown 路径
    temp_dir = tempfile.mkdtemp(prefix='markease_html_recovered_')
    result = md
    recovered = 0

    # 从后往前替换，避免位置偏移
    for i in range(len(missing) - 1, -1, -1):
        if i >= len(html_images):
            continue
        m, g = missing[i]
        data_url = html_images[i]
        dm = _DATA_URL_RE.match(data_url)
        if not dm:
            continue
        try:
            mime_sub = dm.group(1).lower()
            b64 = dm.group(2)
            data = base64.b64decode(b64)
        except Exception:
            continue
        ext = _DATA_URL_EXT.get(mime_sub, '.png')
        fname = f'recovered_{i:03d}{ext}'
        fpath = os.path.join(temp_dir, fname)
        try:
            with open(fpath, 'wb') as f:
                f.write(data)
        except Exception:
            continue

        new_path = fpath.replace('\\', '/')
        orig_url = m.group(g)
        was_angle = orig_url.startswith('<') and orig_url.endswith('>')
        if was_angle or re.search(r'[\s()]', new_path):
            new_url = '<' + new_path + '>'
        else:
            new_url = new_path

        start = m.start(g)
        end = m.end(g)
        result = result[:start] + new_url + result[end:]
        recovered += 1

    if recovered > 0:
        print(f'[html_importer] 从 HTML 恢复 {recovered} 张图片 '
              f'到 {temp_dir}')

    return result, recovered


# ============================================================
# 主入口
# ============================================================

def import_html_file(path):
    """
    读取 HTML 文件，返回：
      {
        'ok': True,
        'content': str,          # 若检测到 markease-source-md
        'source': 'markease',
        'path': path,
        'doc_dir': str,
        'recovered_images': int,  # ★ 本轮新增
      }
    或：
      {
        'ok': True,
        'html': str,             # 第三方 HTML
        'need_frontend_convert': True,
        'path': path,
        'doc_dir': '',
      }
    或：
      {
        'ok': False,
        'error': str,
      }
    """
    if not path or not os.path.isfile(path):
        return {'ok': False, 'error': '文件不存在'}

    try:
        text = _read_html_text(path)
        if text is None:
            return {'ok': False, 'error': '无法解码 HTML 文件'}

        # 解析 doc_dir（无论哪种 HTML 都试一下）
        doc_dir = extract_source_doc_dir(text)

        # 1) 优先检测 MarkEase 原始 Markdown
        md = extract_source_markdown(text)
        if md is not None:
            # ★ 本轮新增：检查缺失图片，从 HTML 视觉层恢复
            recovered = 0
            try:
                md, recovered = recover_images_in_markdown(
                    md, doc_dir, text)
            except Exception as e:
                print(f'[html_importer] recover failed: {e}')

            return {
                'ok': True,
                'content': md,
                'source': 'markease',
                'path': path,
                'doc_dir': doc_dir,
                'recovered_images': recovered,
            }

        # 2) 第三方 HTML → 交给前端
        return {
            'ok': True,
            'html': text,
            'need_frontend_convert': True,
            'path': path,
            'doc_dir': doc_dir,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}