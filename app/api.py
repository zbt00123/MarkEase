# -*- coding: utf-8 -*-
"""
阶段 15 修订 9：
- 版本号唯一来源：version_info.txt（APP_INFO['version'] 动态读取）
- 兼容 pywebview 4.x / 5.x 的 FileDialog 常量
- 关于窗口：窗口标题本地化、on_top 置顶、notify_about_refresh 热刷新
- set_startup_file / get_startup_file（支持双击 .md 启动）

阶段 16：
- export_html / import_html_dialog / import_dropped_pdf / import_dropped_html
- 阶段 16 第 6 批：import_dropped_pdf_bytes（无 path 时的字节流导入）
- 阶段 16 第 7 批：_import_pdf_by_path 返回 doc_dir；import_dropped_pdf_bytes 走 data URL
- 阶段 16 第 8 批：_export_pdf_to_path 嵌入前绝对化图片路径
- 本轮：PDF 网络图片预加载 / proxy 代理

★ 本轮修订（图片自动迁移到 assets/）：
    1. _import_pdf_by_path：PDF 内图片落盘到 <pdf_dir>/assets/，
       MD 里用相对路径 assets/image_NNN.png；
       doc_dir 设为 <pdf_dir>
    2. save_file / save_file_as：保存前扫描 content 中所有本地图片
       （Temp 路径 / data URL），迁移到 <doc_dir>/assets/ 并改写为
       相对路径。返回新的 content 给前端刷新。
    3. 新增 finalize_imported_html(doc_dir, markdown_content)：
       第三方 HTML 转换后调用，把 data URL 图片落盘到
       <doc_dir>/assets/，返回改写后的 Markdown。
"""

import os
import sys
import json
import re
import base64
import hashlib
import shutil
import subprocess
import tempfile
import time
import webview
from converters.html_exporter import (
    export_html as _export_html_impl,
    absolutize_image_paths_in_markdown as _absolutize_md,
)
from converters.html_importer import import_html_file as _import_html_impl

try:
    _OPEN_DIALOG = webview.FileDialog.OPEN
    _SAVE_DIALOG = webview.FileDialog.SAVE
except AttributeError:
    _OPEN_DIALOG = webview.OPEN_DIALOG
    _SAVE_DIALOG = webview.SAVE_DIALOG

try:
    import clr
    import System
    CLR_AVAILABLE = True
except ImportError:
    CLR_AVAILABLE = False


SETTINGS_FILE = os.path.join(os.path.expanduser('~'), '.markease', 'settings.json')
EMBED_NAME = 'markease_source.md'
MAX_IMAGE_SIZE = 20 * 1024 * 1024
MAX_DROP_PDF_SIZE = 100 * 1024 * 1024
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}

GITHUB_REPO = 'zbt00123/MarkEase'
GITHUB_RELEASES_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
GITHUB_RELEASES_PAGE = f'https://github.com/{GITHUB_REPO}/releases'
UPDATE_CHECK_INTERVAL = 30 * 24 * 60 * 60

CURRENT_SHELL_NEW_VERSION = 2

DEFAULT_SETTINGS = {
    'theme': 'system',
    'language': 'system',
    'window_width': 1200,
    'window_height': 800,
    'sync_scroll': True,
    'zoom_percent': 100,
    'last_update_check': 0,
    'shell_new_registered': 0,
}


# ============================================================
#  图片迁移：正则和常量
# ============================================================

# Markdown 图片语法：![alt](url) 或 ![alt](<url>) 或 ![alt](url "title")
_MD_IMG_RE = re.compile(
    r'(!\[[^\]]*\]\()(\s*)(<[^>]*>|[^)\s]+)([^)]*)(\))'
)

# HTML <img src="...">
_HTML_IMG_RE = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])([^"\']*)(\2[^>]*>)',
    re.IGNORECASE
)

# data:image/xxx;base64,...
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


def _read_version_from_file():
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vi_path = os.path.join(base, 'version_info.txt')
        if not os.path.exists(vi_path) and getattr(sys, 'frozen', False):
            vi_path = os.path.join(sys._MEIPASS, 'version_info.txt')
        if os.path.exists(vi_path):
            with open(vi_path, 'r', encoding='utf-8') as f:
                txt = f.read()
            m = re.search(
                r"StringStruct\(u'FileVersion',\s*u'([^']+)'\)", txt)
            if m:
                return m.group(1)
    except Exception:
        pass
    return '0.0.0'


_APP_VERSION = _read_version_from_file()


APP_INFO = {
    'name': 'MarkEase',
    'version': _APP_VERSION,
    'author': 'ZBT Studio',
    'author_url': 'https://github.com/zbt00123/',
    'outline_by': 'ChatGPT',
    'outline_url': 'https://chatgpt.com/',
    'coded_by': 'DeepSeek',
    'coded_url': 'https://chat.deepseek.com/',
    'license': '仅供学习使用，可以任意修改、复制、发布代码，严禁商用。',
}


class Settings:
    def __init__(self):
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        self._data = dict(DEFAULT_SETTINGS)
        self._load()

    def _load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    self._data.update(json.load(f))
            except Exception:
                pass

    def save(self):
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def get_all(self):
        return dict(self._data)


def _get_fitz():
    try:
        import pymupdf as fitz
        return fitz
    except ImportError:
        try:
            import fitz
            return fitz
        except ImportError:
            return None


def embed_markdown_into_pdf(pdf_path: str, markdown_text: str) -> bool:
    fitz = _get_fitz()
    if fitz is None:
        return False

    try:
        md_bytes = markdown_text.encode('utf-8')
        doc = fitz.open(pdf_path)
        tmp_path = None
        try:
            try:
                names = doc.embfile_names()
                if EMBED_NAME in names:
                    doc.embfile_del(EMBED_NAME)
            except Exception:
                pass

            doc.embfile_add(
                EMBED_NAME,
                md_bytes,
                filename=EMBED_NAME,
                ufilename=EMBED_NAME,
                desc='MarkEase original markdown',
            )

            fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
            os.close(fd)
            doc.save(tmp_path, garbage=3, deflate=True)
        finally:
            doc.close()

        if tmp_path and os.path.exists(tmp_path):
            os.replace(tmp_path, pdf_path)
        return True
    except Exception:
        import traceback
        traceback.print_exc()
        return False


def _is_in_temp_dir(path):
    try:
        tmp_dir = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        p = os.path.normcase(os.path.abspath(path))
        return p.startswith(tmp_dir + os.sep)
    except Exception:
        return False


def _sanitize_image_name(name):
    name = (name or 'image').replace(' ', '_')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().strip('.') or 'image'
    base, ext = os.path.splitext(name)
    if ext.lower() not in IMAGE_EXTS:
        ext = '.png'
    return base, ext.lower()


def _normalize_lang_code(lang: str) -> str:
    if not lang:
        return 'zh_CN'
    s = str(lang).strip().replace('-', '_')
    low = s.lower()

    mapping = {
        'zh_cn': 'zh_CN', 'zh_hans': 'zh_CN', 'zh_sg': 'zh_CN',
        'zh_tw': 'zh_TW', 'zh_hk': 'zh_TW', 'zh_hant': 'zh_TW',
        'en': 'en_US', 'en_us': 'en_US', 'en_gb': 'en_US',
        'ja': 'ja_JP', 'ja_jp': 'ja_JP',
        'ko': 'ko_KR', 'ko_kr': 'ko_KR',
    }
    if low in mapping:
        return mapping[low]
    if low.startswith('zh'):
        return 'zh_CN'
    if low.startswith('en'):
        return 'en_US'
    if low.startswith('ja'):
        return 'ja_JP'
    if low.startswith('ko'):
        return 'ko_KR'
    return 'zh_CN'


def _parse_version(v: str):
    if not v:
        return (0, 0, 0)
    s = str(v).strip().lstrip('vV')
    parts = re.split(r'[.\-+]', s)
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            break
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


# ============================================================
#  AboutApi
# ============================================================
class AboutApi:
    def __init__(self, web_dir, main_api=None):
        self._window = None
        self._web_dir = web_dir
        self._main_api = main_api

    def set_window(self, window):
        self._window = window

    def close_window(self):
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
        return {'ok': True}

    def set_window_title(self, title):
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}
        try:
            t = str(title or '')
            if not t:
                return {'ok': False, 'error': '标题为空'}
            try:
                self._window.title = t
            except Exception:
                if hasattr(self._window, 'set_title'):
                    self._window.set_title(t)
                else:
                    raise
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def get_settings(self):
        if self._main_api is not None and hasattr(self._main_api, '_settings'):
            return self._main_api._settings.get_all()
        return {'theme': 'system', 'language': 'system'}

    def get_translations(self, lang=None):
        if self._main_api is not None and hasattr(self._main_api, 'get_translations'):
            return self._main_api.get_translations(lang)
        return {'ok': False, 'error': '主 Api 未就绪', 'lang': 'zh_CN', 'dict': {}}

    def get_version(self):
        info = dict(APP_INFO)
        info['ok'] = True
        info['version'] = _read_version_from_file()
        return info

    def _find_icon_path(self):
        candidates = []
        if getattr(sys, 'frozen', False):
            candidates.append(sys._MEIPASS)
        candidates.append(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))

        names = ('图标.ico', 'icon.ico', 'MarkEase.ico')
        for base in candidates:
            for name in names:
                p = os.path.join(base, 'resources', 'icons', name)
                if os.path.exists(p):
                    return p
        return None

    def get_icon_url(self):
        from urllib.parse import quote

        icon_path = self._find_icon_path()
        if not icon_path:
            return {'ok': False, 'error': '未找到图标文件'}

        if self._main_api is None or not hasattr(self._main_api, '_asset_port'):
            return {'ok': False, 'error': 'asset server 未就绪'}

        port = self._main_api._asset_port
        abs_norm = os.path.abspath(icon_path).replace('\\', '/')
        url = f'http://127.0.0.1:{port}/fs/{quote(abs_norm, safe="")}'
        return {'ok': True, 'url': url}

    def open_external_url(self, url):
        if not url:
            return {'ok': False, 'error': 'URL 为空'}
        try:
            import webbrowser
            webbrowser.open(url)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}


# ============================================================
#  主 Api
# ============================================================
class Api:
    def __init__(self, web_dir):
        self._web_dir = web_dir or ''
        if self._web_dir:
            self._app_root = os.path.dirname(os.path.abspath(self._web_dir))
        else:
            self._app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._window = None
        self._settings = Settings()
        self._current_file = ''
        self._current_content = ''
        self._picker_windows = []

        self._about_window = None
        self._startup_file = ''

        from app.asset_server import AssetServer
        self._asset_server = AssetServer(web_dir=self._web_dir)
        self._asset_port = self._asset_server.start()
        print(f'[MarkEase] asset server: http://127.0.0.1:{self._asset_port}')

        try:
            from app import file_assoc
            try:
                reg_ver = int(self._settings.get('shell_new_registered', 0) or 0)
            except Exception:
                reg_ver = 0

            if reg_ver < CURRENT_SHELL_NEW_VERSION:
                r = file_assoc.setup_shell_new_on_first_run()
                if r and r.get('ok') and not r.get('skipped'):
                    self._settings.set('shell_new_registered',
                                       CURRENT_SHELL_NEW_VERSION)
                    print(f'[MarkEase] shell-new registered '
                          f'(v{CURRENT_SHELL_NEW_VERSION}): {r.get("name")}')
                elif r and r.get('skipped'):
                    print(f'[MarkEase] shell-new skipped: {r.get("reason")}')
        except Exception as e:
            print(f'[MarkEase] shell-new setup failed: {e}')

    def set_window(self, window):
        self._window = window

    # ============================================================
    #  图片迁移工具
    # ============================================================
    def _is_local_abs_path(self, s):
        if not s:
            return False
        if re.match(r'^[A-Za-z]:[\\/]', s):
            return True
        if s.startswith('/') and not s.startswith('//'):
            return True
        return False

    def _is_under_dir(self, path, dir_path):
        try:
            p = os.path.normcase(os.path.abspath(path))
            d = os.path.normcase(os.path.abspath(dir_path))
            return p.startswith(d + os.sep) or p == d
        except Exception:
            return False

    def _unique_target_path(self, assets_dir, base, ext, src_data=None):
        target = os.path.join(assets_dir, base + ext)
        if not os.path.exists(target):
            return target, False
        if src_data is not None:
            try:
                with open(target, 'rb') as f:
                    if f.read() == src_data:
                        return target, True
            except Exception:
                pass
        counter = 1
        while True:
            cand = os.path.join(assets_dir, f'{base}-{counter}{ext}')
            if not os.path.exists(cand):
                return cand, False
            counter += 1

    def _migrate_images_to_doc_dir(self, content, doc_dir):
        """
        扫描 content 中的图片引用（Markdown + HTML），把所有可迁移到
        <doc_dir>/assets/ 的图片落盘，并改写 content 为相对路径。

        迁移对象：
          - data:image/...;base64,...  （第三方 HTML 转换产物）
          - 本地绝对路径图片（含 Temp 目录、其他 assets/ 目录）

        保持不动：
          - http(s)://、blob:、file:
          - 已在 <doc_dir>/assets/ 下的图片（仅改写为相对路径）
          - 相对路径

        返回 (new_content, migrated_count, migrated_paths)
        """
        if not content or not doc_dir:
            return content, 0, []

        doc_dir_abs = os.path.abspath(doc_dir)
        assets_dir = os.path.join(doc_dir_abs, 'assets')

        migrated_count = [0]
        migrated_paths = []

        def ensure_assets_dir():
            os.makedirs(assets_dir, exist_ok=True)

        def migrate_one(url):
            if not url:
                return None
            raw = url
            if raw.startswith('<') and raw.endswith('>'):
                raw = raw[1:-1]

            # 1) data URL → 落盘
            m = _DATA_URL_RE.match(raw)
            if m:
                try:
                    mime_sub = m.group(1).lower()
                    b64 = m.group(2)
                    data = base64.b64decode(b64)
                except Exception:
                    return None
                ext = _DATA_URL_EXT.get(mime_sub, '.png')
                base = 'image_' + hashlib.md5(data).hexdigest()[:10]
                ensure_assets_dir()
                target, already = self._unique_target_path(
                    assets_dir, base, ext, src_data=data)
                if not already:
                    try:
                        with open(target, 'wb') as f:
                            f.write(data)
                    except Exception:
                        return None
                try:
                    rel = os.path.relpath(target, doc_dir_abs).replace('\\', '/')
                except Exception:
                    rel = 'assets/' + os.path.basename(target)
                migrated_count[0] += 1
                migrated_paths.append(rel)
                return rel

            # 2) 本地绝对路径
            if self._is_local_abs_path(raw):
                src_abs = os.path.abspath(raw)
                if not os.path.isfile(src_abs):
                    return None
                # 已在 <doc_dir>/assets/ 下 → 只改写为相对路径
                if self._is_under_dir(src_abs, assets_dir):
                    try:
                        rel = os.path.relpath(src_abs, doc_dir_abs).replace('\\', '/')
                        return rel
                    except Exception:
                        return None
                # 复制到 assets/
                try:
                    with open(src_abs, 'rb') as f:
                        data = f.read()
                except Exception:
                    return None
                base_name, ext = os.path.splitext(os.path.basename(src_abs))
                if not ext:
                    ext = '.png'
                ext = ext.lower()
                ensure_assets_dir()
                target, already = self._unique_target_path(
                    assets_dir, base_name, ext, src_data=data)
                if not already:
                    try:
                        with open(target, 'wb') as f:
                            f.write(data)
                    except Exception:
                        return None
                try:
                    rel = os.path.relpath(target, doc_dir_abs).replace('\\', '/')
                except Exception:
                    rel = 'assets/' + os.path.basename(target)
                migrated_count[0] += 1
                migrated_paths.append(rel)
                return rel

            return None

        # 1) Markdown 图片语法
        def repl_md(match):
            head = match.group(1)
            space1 = match.group(2)
            url = match.group(3)
            rest = match.group(4) or ''
            tail = match.group(5)
            new_url = migrate_one(url)
            if new_url is None:
                return match.group(0)
            return f'{head}{space1}{new_url}{rest}{tail}'

        new_content = _MD_IMG_RE.sub(repl_md, content)

        # 2) HTML <img src="...">
        def repl_html(match):
            prefix = match.group(1)
            quote = match.group(2)
            url = match.group(3)
            rest = match.group(4)
            new_url = migrate_one(url)
            if new_url is None:
                return match.group(0)
            if new_url.startswith('<') and new_url.endswith('>'):
                new_url = new_url[1:-1]
            return f'{prefix}{quote}{new_url}{quote}{rest}'

        new_content = _HTML_IMG_RE.sub(repl_html, new_content)

        return new_content, migrated_count[0], migrated_paths

    # ---------- 启动文件 ----------
    def set_startup_file(self, path):
        self._startup_file = path or ''
        return {'ok': True}

    def get_startup_file(self):
        if not self._startup_file:
            return {'ok': False}

        path = self._startup_file
        self._startup_file = ''

        try:
            ext = os.path.splitext(path)[1].lower()

            if ext == '.pdf':
                result = self._import_pdf_by_path(path)
                return result

            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._current_file = path
            self._current_content = content
            return {
                'ok': True,
                'path': path,
                'content': content,
                'imported': False,
            }
        except UnicodeDecodeError:
            try:
                with open(path, 'r', encoding='gbk', errors='replace') as f:
                    content = f.read()
                self._current_file = path
                self._current_content = content
                return {
                    'ok': True,
                    'path': path,
                    'content': content,
                    'imported': False,
                    'encoding': 'gbk',
                }
            except Exception as e:
                return {'ok': False, 'error': str(e), 'path': path}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e), 'path': path}

    # ---------- 路径工具 ----------
    def _get_base_dir(self):
        if getattr(sys, 'frozen', False):
            return sys._MEIPASS
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _get_translations_dir(self):
        return os.path.join(self._get_base_dir(), 'resources', 'translations')

    def _read_file_version(self):
        return _read_version_from_file()

    def _resolve_system_language(self):
        try:
            import locale
            lang = locale.getdefaultlocale()[0]
            if lang:
                return _normalize_lang_code(lang)
        except Exception:
            pass

        for env_key in ('LANG', 'LANGUAGE', 'LC_ALL', 'LC_MESSAGES'):
            val = os.environ.get(env_key)
            if val:
                return _normalize_lang_code(val.split('.')[0])

        return 'zh_CN'

    def frontend_ready(self):
        return {'ok': True}

    def get_asset_base_url(self):
        return {'ok': True, 'url': f'http://127.0.0.1:{self._asset_port}'}

    # ---------- 多语言 ----------
    def get_translations(self, lang=None):
        try:
            if not lang or lang == 'system':
                lang = self._resolve_system_language()
            lang = _normalize_lang_code(lang)

            trans_dir = self._get_translations_dir()
            path = os.path.join(trans_dir, f'{lang}.json')

            if not os.path.exists(path):
                fallback = os.path.join(trans_dir, 'zh_CN.json')
                if os.path.exists(fallback):
                    path = fallback
                    lang = 'zh_CN'
                else:
                    return {'ok': False, 'error': '未找到翻译文件', 'lang': lang, 'dict': {}}

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return {'ok': True, 'lang': lang, 'dict': data}
        except Exception as e:
            return {'ok': False, 'error': str(e), 'lang': 'zh_CN', 'dict': {}}

    def get_language(self):
        return self._settings.get('language', 'system')

    def set_language(self, language):
        self._settings.set('language', language)
        return True

    # ---------- 文件关联 ----------
    def set_as_default_program(self):
        try:
            from app import file_assoc
            return file_assoc.set_as_default_program()
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def register_shell_new(self):
        try:
            from app import file_assoc
            r = file_assoc.register_shell_new()
            if r and r.get('ok'):
                self._settings.set('shell_new_registered',
                                   CURRENT_SHELL_NEW_VERSION)
            return r
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def is_default_program(self):
        try:
            from app import file_assoc
            return {'ok': True, 'is_default': file_assoc.is_default_program()}
        except Exception as e:
            return {'ok': False, 'is_default': False, 'error': str(e)}

    def get_default_program_display_name(self):
        try:
            from app import file_assoc
            return {'ok': True, 'name': file_assoc._get_display_name()}
        except Exception as e:
            return {'ok': False, 'name': 'Markdown File', 'error': str(e)}

    # ---------- 检查更新 ----------
    def _fetch_latest_release(self):
        import urllib.request

        for env_key in (
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy',
            'NO_PROXY', 'no_proxy',
        ):
            os.environ.pop(env_key, None)

        current = self._read_file_version()
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={
                'User-Agent': f'MarkEase/{current}',
                'Accept': 'application/vnd.github+json',
            },
        )

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        with opener.open(req, timeout=15) as resp:
            raw = resp.read(1024 * 1024)
            data = json.loads(raw.decode('utf-8', errors='ignore'))
        return data

    def check_update(self, silent=False):
        now = int(time.time())
        try:
            current = self._read_file_version()
            data = self._fetch_latest_release()

            tag = data.get('tag_name') or data.get('name') or ''
            latest = str(tag).strip().lstrip('vV')
            if not latest:
                latest = current

            notes = data.get('body') or ''
            html_url = data.get('html_url') or GITHUB_RELEASES_PAGE
            name = data.get('name') or tag or f'v{latest}'
            published_at = data.get('published_at') or ''

            has_update = _parse_version(latest) > _parse_version(current)

            self._settings.set('last_update_check', now)

            return {
                'ok': True,
                'has_update': has_update,
                'current_version': current,
                'latest_version': latest,
                'notes': notes,
                'html_url': html_url,
                'name': name,
                'published_at': published_at,
                'silent': bool(silent),
            }
        except Exception as e:
            return {
                'ok': False,
                'has_update': False,
                'current_version': self._read_file_version(),
                'latest_version': '',
                'notes': '',
                'html_url': GITHUB_RELEASES_PAGE,
                'error': str(e),
                'silent': bool(silent),
            }

    def maybe_check_update(self):
        now = int(time.time())
        try:
            last = int(self._settings.get('last_update_check', 0) or 0)
        except Exception:
            last = 0

        if last > 0 and (now - last) < UPDATE_CHECK_INTERVAL:
            return {
                'ok': True,
                'skipped': True,
                'has_update': False,
                'current_version': self._read_file_version(),
                'latest_version': '',
                'notes': '',
                'html_url': GITHUB_RELEASES_PAGE,
            }

        result = self.check_update(silent=True)
        self._settings.set('last_update_check', now)
        return result

    # ---------- 下载图标 ----------
    def download_icon(self, url):
        if not url:
            return {'ok': False, 'error': 'URL 为空'}

        try:
            import urllib.request
            from urllib.parse import urlparse

            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read(10 * 1024 * 1024)
                content_type = resp.headers.get('Content-Type', '')

            ext = '.png'
            if 'jpeg' in content_type or 'jpg' in content_type:
                ext = '.jpg'
            elif 'gif' in content_type:
                ext = '.gif'
            elif 'webp' in content_type:
                ext = '.webp'
            elif 'svg' in content_type:
                ext = '.svg'
            elif 'icon' in content_type or 'ico' in content_type:
                ext = '.ico'

            parsed = urlparse(url)
            domain = parsed.hostname or 'icon'
            path_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            base_name = domain.replace('.', '_') + '_' + path_hash
            filename = base_name + ext

            if not self._current_file:
                fd, tmp = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                try:
                    with open(tmp, 'wb') as f:
                        f.write(data)
                except Exception as e:
                    return {'ok': False, 'error': str(e)}
                return {'ok': True, 'md_path': tmp.replace('\\', '/'),
                        'unsaved': True}

            doc_dir = os.path.dirname(os.path.abspath(self._current_file))
            assets_dir = os.path.join(doc_dir, 'assets')
            os.makedirs(assets_dir, exist_ok=True)
            target = os.path.join(assets_dir, filename)

            if os.path.exists(target):
                try:
                    with open(target, 'rb') as f:
                        existing = f.read()
                    if existing == data:
                        md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
                        return {'ok': True, 'md_path': md_path, 'unsaved': False}
                except Exception:
                    pass

                fd, tmp = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                try:
                    with open(tmp, 'wb') as f:
                        f.write(data)
                except Exception as e:
                    return {'ok': False, 'error': str(e)}

                try:
                    tgt_size = os.path.getsize(target)
                except Exception:
                    tgt_size = 0

                return {
                    'ok': False,
                    'conflict': True,
                    'src_path': tmp,
                    'src_name': filename,
                    'src_size': len(data),
                    'target_path': target,
                    'target_name': filename,
                    'target_size': tgt_size,
                    'is_temp': True,
                }

            try:
                with open(target, 'wb') as f:
                    f.write(data)
            except Exception as e:
                return {'ok': False, 'error': str(e)}

            md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
            return {'ok': True, 'md_path': md_path, 'unsaved': False}

        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 在文件管理器中打开并选中文件 ----------
    def reveal_in_explorer(self, path):
        if not path:
            return {'ok': False, 'error': '路径为空'}

        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {'ok': False, 'error': '文件不存在：' + path}

        try:
            if sys.platform == 'win32':
                subprocess.Popen(['explorer', '/select,', path])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', path])
            else:
                folder = path if os.path.isdir(path) else os.path.dirname(path)
                subprocess.Popen(['xdg-open', folder])
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 窗口控制 ----------
    def close_all_pickers(self):
        for w in list(self._picker_windows):
            try:
                w.destroy()
            except Exception:
                pass
        self._picker_windows.clear()
        self._about_window = None
        return {'ok': True}

    def close_window(self):
        self.close_all_pickers()
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}
        try:
            self._window.destroy()
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def open_external_url(self, url: str):
        if not url:
            return {'ok': False, 'error': 'URL 为空'}
        try:
            import webbrowser
            webbrowser.open(url)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 关于窗口 ----------
    def _get_about_window_title(self):
        fallback = '关于 MarkEase'
        try:
            lang = self._settings.get('language', 'system')
            if not lang or lang == 'system':
                lang = self._resolve_system_language()
            lang = _normalize_lang_code(lang)

            trans_dir = self._get_translations_dir()
            path = os.path.join(trans_dir, f'{lang}.json')
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                t = data.get('about_title')
                if t:
                    return str(t)
        except Exception:
            pass
        return fallback

    def open_about_window(self):
        if self._about_window is not None:
            try:
                self._about_window.restore()
                return {'ok': True, 'focused': True}
            except Exception:
                self._about_window = None

        title = self._get_about_window_title()

        about_api = AboutApi(web_dir=self._web_dir, main_api=self)
        url = f'http://127.0.0.1:{self._asset_port}/web/about.html'

        about_window = None
        try:
            about_window = webview.create_window(
                title=title,
                url=url,
                js_api=about_api,
                width=520,
                height=580,
                min_size=(460, 500),
                resizable=True,
                on_top=True,
            )
        except TypeError:
            try:
                about_window = webview.create_window(
                    title=title,
                    url=url,
                    js_api=about_api,
                    width=520,
                    height=580,
                    min_size=(460, 500),
                    resizable=True,
                )
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {'ok': False, 'error': str(e)}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

        about_api.set_window(about_window)
        self._about_window = about_window
        self._picker_windows.append(about_window)

        def _on_closed():
            if self._about_window is about_window:
                self._about_window = None
            try:
                if about_window in self._picker_windows:
                    self._picker_windows.remove(about_window)
            except Exception:
                pass

        try:
            about_window.events.closed += _on_closed
        except Exception:
            pass

        return {'ok': True}

    def notify_about_refresh(self):
        w = self._about_window
        if w is None:
            return {'ok': False, 'skipped': True, 'reason': 'no about window'}
        try:
            w.evaluate_js(
                'window.__refreshFromMain && window.__refreshFromMain();'
            )
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 图片选择弹窗 ----------
    def open_image_picker(self):
        from app.image_picker import ImagePickerApi

        self.close_all_pickers()

        picker_api = ImagePickerApi(
            web_dir=self._web_dir,
            doc_path=self._current_file or '',
            main_api=self,
        )

        html_path = os.path.join(self._web_dir, 'image_picker.html')
        if not os.path.exists(html_path):
            return {'ok': False, 'error': '缺少 web/image_picker.html'}

        try:
            picker_window = webview.create_window(
                title='插入图片',
                url=html_path,
                js_api=picker_api,
                width=960,
                height=640,
                min_size=(720, 480),
            )
            picker_api.set_window(picker_window)
            self._picker_windows.append(picker_window)
            return {'ok': True}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    # ---------- 拖拽导入 ----------
    def import_dropped_file(self, path):
        if not path:
            return {'ok': False, 'error': '空路径'}
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return {'ok': False, 'error': '文件不存在'}
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS:
            return {'ok': False, 'error': '不是支持的图片格式'}

        if not self._current_file:
            return {'ok': True, 'md_path': path.replace('\\', '/'),
                    'unsaved': True}

        doc_dir = os.path.dirname(os.path.abspath(self._current_file))
        assets_dir = os.path.join(doc_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)

        base, ext_norm = _sanitize_image_name(os.path.basename(path))
        target = os.path.join(assets_dir, base + ext_norm)

        if os.path.exists(target):
            try:
                if os.path.samefile(path, target):
                    md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
                    return {'ok': True, 'md_path': md_path, 'unsaved': False}
            except Exception:
                pass
            try:
                src_size = os.path.getsize(path)
                tgt_size = os.path.getsize(target)
            except Exception:
                src_size = tgt_size = 0
            return {
                'ok': False,
                'conflict': True,
                'src_path': path,
                'src_name': os.path.basename(path),
                'src_size': src_size,
                'target_path': target,
                'target_name': os.path.basename(target),
                'target_size': tgt_size,
            }

        try:
            shutil.copy2(path, target)
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
        return {'ok': True, 'md_path': md_path, 'unsaved': False}

    def import_dropped_bytes(self, filename, data_bytes):
        if not data_bytes:
            return {'ok': False, 'error': '空数据'}
        try:
            data = bytes(data_bytes)
        except Exception as e:
            return {'ok': False, 'error': f'数据转换失败: {e}'}

        if len(data) > MAX_IMAGE_SIZE:
            return {'ok': False,
                    'error': f'图片超过 {MAX_IMAGE_SIZE // 1024 // 1024}MB'}

        base, ext = _sanitize_image_name(os.path.basename(filename or 'image.png'))

        if not self._current_file:
            fd, tmp = tempfile.mkstemp(suffix=ext)
            os.close(fd)
            try:
                with open(tmp, 'wb') as f:
                    f.write(data)
            except Exception as e:
                return {'ok': False, 'error': str(e)}
            return {'ok': True, 'md_path': tmp.replace('\\', '/'),
                    'unsaved': True}

        doc_dir = os.path.dirname(os.path.abspath(self._current_file))
        assets_dir = os.path.join(doc_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        target = os.path.join(assets_dir, base + ext)

        if os.path.exists(target):
            try:
                with open(target, 'rb') as f:
                    existing = f.read()
                if existing == data:
                    md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
                    return {'ok': True, 'md_path': md_path, 'unsaved': False}
            except Exception:
                pass

            fd, tmp = tempfile.mkstemp(suffix=ext)
            os.close(fd)
            try:
                with open(tmp, 'wb') as f:
                    f.write(data)
            except Exception as e:
                return {'ok': False, 'error': str(e)}
            try:
                tgt_size = os.path.getsize(target)
            except Exception:
                tgt_size = 0
            return {
                'ok': False,
                'conflict': True,
                'src_path': tmp,
                'src_name': os.path.basename(filename or 'image' + ext),
                'src_size': len(data),
                'target_path': target,
                'target_name': os.path.basename(target),
                'target_size': tgt_size,
                'is_temp': True,
            }

        try:
            with open(target, 'wb') as f:
                f.write(data)
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
        return {'ok': True, 'md_path': md_path, 'unsaved': False}

    def resolve_dropped_conflict(self, src_path, action):
        if not src_path or not os.path.isfile(src_path):
            return {'ok': False, 'error': '文件不存在'}
        if action not in ('replace', 'keep_both', 'cancel'):
            return {'ok': False, 'error': '未知操作'}
        if action == 'cancel':
            if _is_in_temp_dir(src_path):
                try:
                    os.remove(src_path)
                except Exception:
                    pass
            return {'ok': False, 'cancelled': True}

        if not self._current_file:
            return {'ok': False, 'error': '文档未保存'}

        doc_dir = os.path.dirname(os.path.abspath(self._current_file))
        assets_dir = os.path.join(doc_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)

        base, ext = _sanitize_image_name(os.path.basename(src_path))
        target = os.path.join(assets_dir, base + ext)

        try:
            if action == 'replace':
                shutil.copy2(src_path, target)
                md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
            else:
                counter = 1
                while True:
                    new_target = os.path.join(
                        assets_dir, f'{base}-{counter}{ext}')
                    if not os.path.exists(new_target):
                        break
                    counter += 1
                shutil.copy2(src_path, new_target)
                md_path = os.path.relpath(new_target, doc_dir).replace('\\', '/')

            if _is_in_temp_dir(src_path):
                try:
                    os.remove(src_path)
                except Exception:
                    pass

            return {'ok': True, 'md_path': md_path, 'unsaved': False}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def import_dropped_url(self, url):
        if not url:
            return {'ok': False, 'error': '空 URL'}
        from app.image_picker import ImagePickerApi
        picker = ImagePickerApi(
            web_dir=self._web_dir,
            doc_path=self._current_file or '',
            main_api=self,
        )
        return picker.import_network_image(url)

    # ---------- 当前文件同步 ----------
    def set_current_file(self, path):
        self._current_file = path or ''
        return {'ok': True}

    # ---------- 文件 ----------
    def open_file_dialog(self):
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}

        result = self._window.create_file_dialog(
            _OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                'Markdown 文件 (*.md;*.markdown)',
                'PDF 文件 (*.pdf)',
                'HTML 文件 (*.html;*.htm)',
                '所有文件 (*.*)'
            )
        )
        if not result:
            return {'ok': False, 'cancelled': True}

        path = result[0]
        ext = os.path.splitext(path)[1].lower()

        if ext == '.pdf':
            return self._import_pdf_by_path(path)

        if ext in ('.html', '.htm'):
            r = _import_html_impl(path)
            if r and r.get('ok'):
                r['path'] = path
                r['imported'] = True
            return r

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._current_file = path
            self._current_content = content
            return {'ok': True, 'path': path, 'content': content}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def save_file(self, content):
        if not self._current_file:
            return self.save_file_as(content)
        try:
            doc_dir = os.path.dirname(os.path.abspath(self._current_file))
            new_content, migrated, _ = self._migrate_images_to_doc_dir(
                content, doc_dir)
            with open(self._current_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            self._current_content = new_content
            return {
                'ok': True,
                'path': self._current_file,
                'content': new_content,
                'migrated_images': migrated,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def save_file_as(self, content):
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}

        result = self._window.create_file_dialog(
            _SAVE_DIALOG,
            save_filename='未命名.md',
            file_types=(
                'Markdown 文件 (*.md)',
                'PDF 文件 (*.pdf)',
                '所有文件 (*.*)'
            )
        )
        if not result:
            return {'ok': False, 'cancelled': True}

        path = result if isinstance(result, str) else result[0]
        ext = os.path.splitext(path)[1].lower()

        if ext == '.pdf':
            if not CLR_AVAILABLE:
                return {'ok': False, 'error': '未安装 pythonnet，无法导出 PDF'}
            return self._export_pdf_to_path(content, path)

        if not path.lower().endswith(('.md', '.markdown')):
            path += '.md'
        try:
            doc_dir = os.path.dirname(os.path.abspath(path))
            new_content, migrated, _ = self._migrate_images_to_doc_dir(
                content, doc_dir)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            self._current_file = path
            self._current_content = new_content
            return {
                'ok': True,
                'path': path,
                'content': new_content,
                'migrated_images': migrated,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def get_current_file(self):
        return self._current_file

    def update_content(self, content):
        self._current_content = content
        return True

    # ---------- PDF ----------
    def import_pdf_dialog(self):
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}

        result = self._window.create_file_dialog(
            _OPEN_DIALOG,
            allow_multiple=False,
            file_types=('PDF 文件 (*.pdf)', '所有文件 (*.*)')
        )
        if not result:
            return {'ok': False, 'cancelled': True}

        return self._import_pdf_by_path(result[0])

    def _import_pdf_by_path(self, path: str):
        """
        ★ 本轮修订：
          - PDF 内图片落盘到 <pdf_dir>/assets/
          - MD 里用相对路径 assets/image_NNN.png
          - doc_dir 设为 <pdf_dir>
        """
        from converters.pdf_importer import PdfImporter
        if not PdfImporter.is_available():
            return {'ok': False, 'error': 'PyMuPDF 未安装，无法导入 PDF'}

        try:
            pdf_dir = os.path.dirname(os.path.abspath(path))
            assets_dir = os.path.join(pdf_dir, 'assets')

            markdown_text = PdfImporter.convert(
                path,
                image_placeholder='[图片]',
                image_dir_override=assets_dir,   # ★ 图片落盘到 <pdf_dir>/assets/
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': f'PDF 解析失败: {e}'}

        if not markdown_text.strip():
            return {'ok': False, 'error': 'PDF 无可提取文本'}

        self._current_file = ''
        self._current_content = markdown_text
        return {
            'ok': True,
            'path': '',
            'content': markdown_text,
            'source_pdf': path,
            'doc_dir': pdf_dir,
            'imported': True,
        }

    # ============================================================
    #  图片加载等待（PDF 导出用）
    # ============================================================
    def _wait_images_loaded(self, timeout_sec=15.0):
        if self._window is None:
            return

        poll_js = (
            "(function(){ "
            "var imgs = document.querySelectorAll('#preview img[src]'); "
            "var total = 0; var loaded = 0; "
            "imgs.forEach(function(img){ "
            "  var s = img.getAttribute('src') || ''; "
            "  if (!s) return; "
            "  total++; "
            "  if (img.complete && img.naturalWidth > 0) loaded++; "
            "}); "
            "return JSON.stringify({ total: total, loaded: loaded }); "
            "})()"
        )

        time.sleep(0.3)
        elapsed = 0.3
        interval = 0.15

        while elapsed < timeout_sec:
            try:
                raw = self._window.evaluate_js(poll_js)
            except Exception as e:
                print(f'[MarkEase] _wait_images_loaded poll failed: {e}')
                break
            if not raw:
                break
            try:
                data = json.loads(raw)
            except Exception:
                break
            try:
                total = int(data.get('total', 0))
                loaded = int(data.get('loaded', 0))
            except Exception:
                break

            if total == 0 or loaded >= total:
                break

            time.sleep(interval)
            elapsed += interval

        time.sleep(0.2)

    def _export_pdf_to_path(self, content, pdf_path):
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}
        if not CLR_AVAILABLE:
            return {'ok': False, 'error': '未安装 pythonnet，无法导出 PDF'}

        pdf_path = os.path.abspath(pdf_path)
        if not pdf_path.lower().endswith('.pdf'):
            pdf_path += '.pdf'

        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass

        # 等待所有预览图片加载完成
        try:
            self._wait_images_loaded(timeout_sec=15.0)
        except Exception as e:
            print(f'[MarkEase] _wait_images_loaded failed: {e}')

        task_holder = [None]
        error_holder = [None]

        def start_on_ui():
            try:
                native_window = self._window.native
                webview_control = native_window.webview
                core = webview_control.CoreWebView2
                if core is None:
                    error_holder[0] = '无法获取 CoreWebView2'
                    return
                task_holder[0] = core.PrintToPdfAsync(pdf_path, None)
            except Exception as e:
                error_holder[0] = str(e)
                import traceback
                traceback.print_exc()

        try:
            self._window.native.Invoke(System.Action(start_on_ui))
        except Exception as e:
            return {'ok': False, 'error': f'UI 线程调度失败: {e}'}

        if error_holder[0]:
            return {'ok': False, 'error': f'导出启动失败: {error_holder[0]}'}

        task = task_holder[0]
        if task is None:
            return {'ok': False, 'error': '未获取到导出任务'}

        try:
            task.Wait()
        except Exception as e:
            return {'ok': False, 'error': f'等待导出失败: {e}'}

        if not os.path.exists(pdf_path):
            return {'ok': False, 'error': '未生成 PDF 文件'}

        try:
            doc_dir = ''
            if self._current_file:
                doc_dir = os.path.dirname(os.path.abspath(self._current_file))
            md_to_embed = _absolutize_md(content or '', doc_dir)
        except Exception:
            md_to_embed = content or ''

        embed_ok = embed_markdown_into_pdf(pdf_path, md_to_embed)

        size = os.path.getsize(pdf_path)
        return {
            'ok': True,
            'path': pdf_path,
            'size': size,
            'embedded': embed_ok,
        }

    def export_pdf(self, content: str):
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}
        if not CLR_AVAILABLE:
            return {'ok': False, 'error': '未安装 pythonnet，无法导出 PDF'}

        default_name = '未命名.pdf'
        if self._current_file:
            base = os.path.splitext(os.path.basename(self._current_file))[0]
            default_name = base + '.pdf'

        result = self._window.create_file_dialog(
            _SAVE_DIALOG,
            save_filename=default_name,
            file_types=('PDF 文件 (*.pdf)',)
        )
        if not result:
            return {'ok': False, 'cancelled': True}

        pdf_path = result if isinstance(result, str) else result[0]
        if not pdf_path.lower().endswith('.pdf'):
            pdf_path += '.pdf'

        return self._export_pdf_to_path(content, pdf_path)

    # ============================================================
    #  HTML 导入 / 导出
    # ============================================================

    def export_html(self, payload):
        try:
            html = (payload or {}).get('html') or ''
            markdown = (payload or {}).get('markdown') or ''
            title = (payload or {}).get('title') or 'MarkEase 导出'
            doc_dir = (payload or {}).get('doc_dir') or ''

            if not html:
                return {'ok': False, 'error': '无内容可导出'}

            default_name = 'document.html'
            if self._current_file:
                base = os.path.splitext(os.path.basename(self._current_file))[0]
                default_name = base + '.html'

            result = self._window.create_file_dialog(
                _SAVE_DIALOG,
                save_filename=default_name,
                file_types=('HTML 文件 (*.html;*.htm)', '所有文件 (*.*)')
            )
            if not result:
                return {'ok': False, 'cancelled': True}

            if isinstance(result, (list, tuple)):
                out_path = result[0] if result else ''
            else:
                out_path = result
            if not out_path:
                return {'ok': False, 'cancelled': True}

            if not out_path.lower().endswith(('.html', '.htm')):
                out_path += '.html'

            app_root = getattr(self, '_app_root', '') or ''
            if not app_root:
                app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            r = _export_html_impl(
                content_html=html,
                markdown_text=markdown,
                output_path=out_path,
                title=title,
                doc_dir=doc_dir,
                app_root=app_root,
            )
            return r
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def import_html_dialog(self):
        try:
            result = self._window.create_file_dialog(
                _OPEN_DIALOG,
                allow_multiple=False,
                file_types=('HTML 文件 (*.html;*.htm)', '所有文件 (*.*)')
            )
            if not result:
                return {'ok': False, 'cancelled': True}

            if isinstance(result, (list, tuple)):
                path = result[0] if result else ''
            else:
                path = result
            if not path:
                return {'ok': False, 'cancelled': True}

            r = _import_html_impl(path)
            return r
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ★ 新增：第三方 HTML 转换后落盘 data URL 图片
    def finalize_imported_html(self, doc_dir, markdown_content):
        """
        第三方 HTML 转换完成后，把 data URL 图片落盘到 <doc_dir>/assets/，
        MD 中改为相对路径。

        doc_dir 为空 → 不落盘，原样返回。
        """
        if not doc_dir or not markdown_content:
            return {'ok': True, 'content': markdown_content, 'migrated_images': 0}
        try:
            new_content, migrated, _ = self._migrate_images_to_doc_dir(
                markdown_content, doc_dir)
            return {
                'ok': True,
                'content': new_content,
                'migrated_images': migrated,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e), 'content': markdown_content}

    def import_dropped_pdf(self, path):
        try:
            if not path or not os.path.isfile(path):
                return {'ok': False, 'error': '文件不存在'}
            r = self._import_pdf_by_path(path)
            if not r or not r.get('ok'):
                return r or {'ok': False, 'error': 'PDF 解析失败'}
            r['source_pdf'] = path
            r['path'] = ''
            r['imported'] = True
            return r
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def import_dropped_pdf_bytes(self, filename, data_base64):
        import base64 as _b64

        if not data_base64:
            return {'ok': False, 'error': '空数据'}

        from converters.pdf_importer import PdfImporter
        if not PdfImporter.is_available():
            return {'ok': False, 'error': 'PyMuPDF 未安装，无法导入 PDF'}

        try:
            b64 = str(data_base64)
            if b64.startswith('data:'):
                comma = b64.find(',')
                if comma >= 0:
                    b64 = b64[comma + 1:]
            raw = _b64.b64decode(b64)
        except Exception as e:
            return {'ok': False, 'error': f'base64 解码失败: {e}'}

        if not raw:
            return {'ok': False, 'error': '解码后数据为空'}
        if len(raw) > MAX_DROP_PDF_SIZE:
            return {'ok': False,
                    'error': f'PDF 超过 {MAX_DROP_PDF_SIZE // 1024 // 1024}MB'}
        if not raw.startswith(b'%PDF-'):
            return {'ok': False, 'error': '文件不是有效的 PDF'}

        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix='markease_pdf_')
            tmp_pdf = os.path.join(tmp_dir, 'drop.pdf')
            with open(tmp_pdf, 'wb') as f:
                f.write(raw)

            try:
                markdown_text = PdfImporter.convert(
                    tmp_pdf,
                    image_placeholder='[图片]',
                    extract_images=False,
                    image_data_url_mode=True,
                    max_image_bytes=500 * 1024,
                    max_total_bytes=20 * 1024 * 1024,
                )
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {'ok': False, 'error': f'PDF 解析失败: {e}'}

            if not markdown_text.strip():
                return {'ok': False, 'error': 'PDF 无可提取文本'}

            self._current_file = ''
            self._current_content = markdown_text
            return {
                'ok': True,
                'path': '',
                'content': markdown_text,
                'source_pdf': filename or 'dropped.pdf',
                'doc_dir': '',
                'imported': True,
                'from_bytes': True,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        finally:
            if tmp_dir:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

    # ★ 本轮新增：从 HTML 视觉层恢复 Markdown 里缺失的本地图片
    def recover_missing_images(self, doc_dir, markdown_content, html_text):
        """
        拖拽无路径的 HTML 场景：
        前端拿到 HTML 文本后，调用此方法恢复 Markdown 里缺失的本地图片。

        参数：
            doc_dir            原始文档目录（HTML meta 里读取）
            markdown_content   Markdown 内容
            html_text          完整的 HTML 文本

        返回：
            {'ok': True, 'content': new_md, 'recovered': N}
        """
        try:
            from converters.html_importer import recover_images_in_markdown
            new_content, recovered = recover_images_in_markdown(
                markdown_content or '',
                doc_dir or '',
                html_text or '',
            )
            return {
                'ok': True,
                'content': new_content,
                'recovered': recovered,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                'ok': False,
                'error': str(e),
                'content': markdown_content,
                'recovered': 0,
            }

    def import_dropped_html(self, path):
        try:
            if not path or not os.path.isfile(path):
                return {'ok': False, 'error': '文件不存在'}
            r = _import_html_impl(path)
            if not r or not r.get('ok'):
                return r or {'ok': False, 'error': 'HTML 解析失败'}
            r['path'] = ''
            r['imported'] = True
            return r
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 设置 / 主题 / 语言 ----------
    def get_settings(self):
        return self._settings.get_all()

    def set_setting(self, key, value):
        self._settings.set(key, value)
        return True

    def fetch_url_title(self, url):
        if not url:
            return {'ok': False, 'error': 'URL 为空'}
        try:
            import urllib.request
            normalized = url.strip()
            if not re.match(r'^[a-z]+://', normalized, re.IGNORECASE):
                normalized = 'https://' + normalized

            req = urllib.request.Request(
                normalized,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                    'Accept': 'text/html,application/xhtml+xml',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read(200 * 1024)
                charset = resp.headers.get_content_charset() or 'utf-8'
                try:
                    html = raw.decode(charset, errors='ignore')
                except Exception:
                    html = raw.decode('utf-8', errors='ignore')

            m = re.search(
                r'<title[^>]*>([\s\S]*?)</title>',
                html, re.IGNORECASE)
            if not m:
                return {'ok': False, 'error': '页面中未找到标题'}
            title = m.group(1)
            title = re.sub(r'\s+', ' ', title).strip()
            title = (title
                     .replace('&amp;', '&')
                     .replace('&lt;', '<')
                     .replace('&gt;', '>')
                     .replace('&quot;', '"')
                     .replace('&#39;', "'")
                     .replace('&nbsp;', ' '))
            if not title:
                return {'ok': False, 'error': '标题为空'}
            return {'ok': True, 'title': title}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def fetch_favicon_url(self, url):
        if not url:
            return {'ok': False, 'error': 'URL 为空'}
        try:
            import urllib.request
            from urllib.parse import urljoin, urlparse

            normalized = url.strip()
            if not re.match(r'^[a-z]+://', normalized, re.IGNORECASE):
                normalized = 'https://' + normalized

            parsed = urlparse(normalized)
            if not parsed.scheme or not parsed.netloc:
                return {'ok': False, 'error': 'URL 格式无效'}

            base = f'{parsed.scheme}://{parsed.netloc}'
            default_favicon = base + '/favicon.ico'

            try:
                req = urllib.request.Request(
                    normalized,
                    headers={
                        'User-Agent': (
                            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) '
                            'Chrome/120.0.0.0 Safari/537.36'
                        ),
                        'Accept': 'text/html,application/xhtml+xml',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    raw = resp.read(300 * 1024)
                    charset = resp.headers.get_content_charset() or 'utf-8'
                    try:
                        html = raw.decode(charset, errors='ignore')
                    except Exception:
                        html = raw.decode('utf-8', errors='ignore')

                link_re = re.compile(r'<link\b[^>]*?>', re.IGNORECASE)
                href_re = re.compile(r'\bhref\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
                rel_re = re.compile(r'\brel\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)

                candidates = []
                for m in link_re.finditer(html):
                    tag = m.group(0)
                    rm = rel_re.search(tag)
                    if not rm:
                        continue
                    rel = rm.group(1).lower()
                    if ('icon' in rel) or ('apple-touch' in rel):
                        hm = href_re.search(tag)
                        if hm:
                            candidates.append(hm.group(1))

                for cand in candidates:
                    if cand.startswith(('http://', 'https://')):
                        return {'ok': True, 'url': cand, 'source': 'html-absolute'}
                for cand in candidates:
                    abs_url = urljoin(normalized, cand)
                    if abs_url.startswith(('http://', 'https://')):
                        return {'ok': True, 'url': abs_url, 'source': 'html-relative'}
            except Exception:
                pass

            return {'ok': True, 'url': default_favicon, 'source': 'default'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def get_theme(self):
        return self._settings.get('theme', 'system')

    def set_theme(self, theme):
        self._settings.set('theme', theme)
        return True