# -*- coding: utf-8 -*-
"""
阶段 15 修订 6：
- 关于窗口：窗口标题本地化、on_top 置顶、notify_about_refresh 热刷新
- set_startup_file / get_startup_file（支持双击 .md 启动）
- APP_INFO['version'] = '2.0.0'
- 保留文件关联接口
"""

import os
import sys
import json
import re
import shutil
import subprocess
import tempfile
import time
import webview

try:
    import clr
    import System
    CLR_AVAILABLE = True
except ImportError:
    CLR_AVAILABLE = False


SETTINGS_FILE = os.path.join(os.path.expanduser('~'), '.markease', 'settings.json')
EMBED_NAME = 'markease_source.md'
MAX_IMAGE_SIZE = 20 * 1024 * 1024
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}

GITHUB_REPO = 'zbt00123/MarkEase'
GITHUB_RELEASES_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
GITHUB_RELEASES_PAGE = f'https://github.com/{GITHUB_REPO}/releases'
UPDATE_CHECK_INTERVAL = 30 * 24 * 60 * 60

# ShellNew 注册逻辑版本号（改动注册表结构 / 图标策略时递增）
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

APP_INFO = {
    'name': 'MarkEase',
    'version': '2.0.0',
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
        'zh_cn': 'zh_CN',
        'zh_hans': 'zh_CN',
        'zh_sg': 'zh_CN',
        'zh_tw': 'zh_TW',
        'zh_hk': 'zh_TW',
        'zh_hant': 'zh_TW',
        'en': 'en_US',
        'en_us': 'en_US',
        'en_gb': 'en_US',
        'ja': 'ja_JP',
        'ja_jp': 'ja_JP',
        'ko': 'ko_KR',
        'ko_kr': 'ko_KR',
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

    # ★ 阶段 15 修订 6：运行时修改原生窗口标题
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
        try:
            vi_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'version_info.txt')
            if not os.path.exists(vi_path):
                if getattr(sys, 'frozen', False):
                    vi_path = os.path.join(sys._MEIPASS, 'version_info.txt')
            if os.path.exists(vi_path):
                with open(vi_path, 'r', encoding='utf-8') as f:
                    txt = f.read()
                m = re.search(
                    r"StringStruct\(u'FileVersion',\s*u'([^']+)'\)", txt)
                if m:
                    info['version'] = m.group(1)
        except Exception:
            pass
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
        self._window = None
        self._web_dir = web_dir
        self._settings = Settings()
        self._current_file = ''
        self._current_content = ''
        self._picker_windows = []

        # ★ 阶段 15 修订 6：关于窗口引用（用于热刷新）
        self._about_window = None

        # ★ 阶段 15 修订 4：启动文件（双击 .md 时由 main.py 注入）
        self._startup_file = ''

        from app.asset_server import AssetServer
        self._asset_server = AssetServer(web_dir=self._web_dir)
        self._asset_port = self._asset_server.start()
        print(f'[MarkEase] asset server: http://127.0.0.1:{self._asset_port}')

        # 首次启动 / 版本升级时重写 ShellNew 注册
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

    # ---------- ★ 阶段 15 修订 4：启动文件 ----------
    def set_startup_file(self, path):
        """由 main.py 调用，记录启动时要打开的文件路径。"""
        self._startup_file = path or ''
        return {'ok': True}

    def get_startup_file(self):
        """
        由前端在初始化完成后调用。
        返回启动时传入的文件内容（读一次后清空，避免重复加载）。
        """
        if not self._startup_file:
            return {'ok': False}

        path = self._startup_file
        self._startup_file = ''  # 读一次即清空

        try:
            ext = os.path.splitext(path)[1].lower()

            # PDF：走导入逻辑
            if ext == '.pdf':
                result = self._import_pdf_by_path(path)
                return result

            # 其他文本文件：直接读
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
        try:
            vi_path = os.path.join(self._get_base_dir(), 'version_info.txt')
            if os.path.exists(vi_path):
                with open(vi_path, 'r', encoding='utf-8') as f:
                    txt = f.read()
                m = re.search(
                    r"StringStruct\(u'FileVersion',\s*u'([^']+)'\)", txt)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return APP_INFO.get('version', '2.0.0')

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

    # ---------- 前端就绪通知 ----------
    def frontend_ready(self):
        return {'ok': True}

    # ---------- 资源 URL ----------
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
        """
        ★ 阶段 15 修订 6：强制直连，绕过系统代理。

        用户开启 VPN / 系统代理时，可能会拦截对 GitHub API 的请求。
        这里清除所有代理环境变量 + 使用空 ProxyHandler 强制直连。
        """
        import urllib.request

        # 清除代理环境变量
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
            import hashlib
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

    # ---------- ★ 阶段 15 修订 6：关于窗口 ----------
    def _get_about_window_title(self):
        """按当前语言返回关于窗口标题，兜底 '关于 MarkEase'。"""
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
        # 若已存在，先聚焦（不重复打开）
        if self._about_window is not None:
            try:
                self._about_window.restore()
                return {'ok': True, 'focused': True}
            except Exception:
                self._about_window = None

        # ★ 根据当前语言读取 about_title 作为初始标题
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
                on_top=True,   # ★ 置顶
            )
        except TypeError:
            # 兼容不支持 on_top 的旧版 pywebview
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

    # ★ 新增：通知关于窗口刷新（语言/主题变化时由主窗口调用）
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
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                'Markdown 文件 (*.md;*.markdown)',
                'PDF 文件 (*.pdf)',
                '所有文件 (*.*)'
            )
        )
        if not result:
            return {'ok': False, 'cancelled': True}

        path = result[0]
        ext = os.path.splitext(path)[1].lower()

        if ext == '.pdf':
            return self._import_pdf_by_path(path)

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
            with open(self._current_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self._current_content = content
            return {'ok': True, 'path': self._current_file}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def save_file_as(self, content):
        if self._window is None:
            return {'ok': False, 'error': '窗口未就绪'}

        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
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
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._current_file = path
            self._current_content = content
            return {'ok': True, 'path': path}
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
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('PDF 文件 (*.pdf)', '所有文件 (*.*)')
        )
        if not result:
            return {'ok': False, 'cancelled': True}

        return self._import_pdf_by_path(result[0])

    def _import_pdf_by_path(self, path: str):
        from converters.pdf_importer import PdfImporter
        if not PdfImporter.is_available():
            return {'ok': False, 'error': 'PyMuPDF 未安装，无法导入 PDF'}

        try:
            markdown_text = PdfImporter.convert(path, image_placeholder='[图片]')
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
            'imported': True,
        }

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

        embed_ok = embed_markdown_into_pdf(pdf_path, content)
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
            webview.SAVE_DIALOG,
            save_filename=default_name,
            file_types=('PDF 文件 (*.pdf)',)
        )
        if not result:
            return {'ok': False, 'cancelled': True}

        pdf_path = result if isinstance(result, str) else result[0]
        if not pdf_path.lower().endswith('.pdf'):
            pdf_path += '.pdf'

        return self._export_pdf_to_path(content, pdf_path)

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