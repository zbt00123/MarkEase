# -*- coding: utf-8 -*-
"""
图片选择弹窗后端（阶段 10 修订 5）
- 单方法 API：select_local_image(path, action='probe')
- action: 'probe' | 'replace' | 'keep_both' | 'cancel'
"""

import os
import re
import json
import shutil
import string
import tempfile
import mimetypes
import urllib.request
import urllib.error
from urllib.parse import urlparse


IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}
MAX_IMAGE_SIZE = 20 * 1024 * 1024
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) MarkEase/2.0'


def _log(*args):
    try:
        print('[image_picker]', *args)
    except Exception:
        pass


def _list_drives():
    out = []
    for letter in string.ascii_uppercase:
        root = f'{letter}:\\'
        if os.path.exists(root):
            out.append({'name': f'{letter}:', 'path': root})
    return out


def _list_shortcuts():
    home = os.path.expanduser('~')
    out = []

    def add(name, path):
        if path and os.path.isdir(path):
            out.append({'name': name, 'path': path})

    add('桌面', os.path.join(home, 'Desktop'))
    add('下载', os.path.join(home, 'Downloads'))
    add('图片', os.path.join(home, 'Pictures'))
    add('文档', os.path.join(home, 'Documents'))
    add('视频', os.path.join(home, 'Videos'))
    add('音乐', os.path.join(home, 'Music'))
    onedrive = os.environ.get('OneDrive')
    if onedrive and os.path.isdir(onedrive):
        add('OneDrive', onedrive)
    return out


class ImagePickerApi:
    def __init__(self, web_dir, doc_path='', main_api=None):
        self._window = None
        self._web_dir = web_dir
        self._doc_path = doc_path or ''
        self._main_api = main_api
        _log('初始化，文档路径:', self._doc_path or '(未保存)')

    def set_window(self, window):
        self._window = window

    # ---------- 窗口 ----------
    def close_window(self):
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
        return {'ok': True}

    # ---------- 主题 / asset ----------
    def get_settings(self):
        if self._main_api is not None and hasattr(self._main_api, '_settings'):
            return self._main_api._settings.get_all()
        return {'theme': 'system', 'language': 'system'}

    def _get_asset_base(self):
        if self._main_api is not None and hasattr(self._main_api, '_asset_port'):
            return f'http://127.0.0.1:{self._main_api._asset_port}'
        return ''

    def get_initial_state(self):
        return {
            'ok': True,
            'starting_folder': self._get_starting_folder(),
            'shortcuts': _list_shortcuts(),
            'drives': _list_drives(),
            'asset_base': self._get_asset_base(),
            'doc_saved': bool(self._doc_path),
        }

    def _get_starting_folder(self):
        if self._doc_path:
            d = os.path.dirname(os.path.abspath(self._doc_path))
            if os.path.isdir(d):
                return d
        home = os.path.expanduser('~')
        for name in ('Pictures', 'Desktop', 'Downloads', 'Documents'):
            p = os.path.join(home, name)
            if os.path.isdir(p):
                return p
        return home

    # ---------- 目录列表 ----------
    def list_directory(self, path):
        if not path:
            return {'ok': False, 'error': '空路径'}
        try:
            path = os.path.normpath(os.path.abspath(path))
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        if not os.path.isdir(path):
            return {'ok': False, 'error': '目录不存在'}

        folders, images, others = [], [], []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.name.startswith('.'):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            folders.append({
                                'name': entry.name,
                                'path': os.path.join(path, entry.name),
                            })
                        elif entry.is_file(follow_symlinks=False):
                            ext = os.path.splitext(entry.name)[1].lower()
                            fp = os.path.join(path, entry.name)
                            try:
                                size = entry.stat().st_size
                            except Exception:
                                size = 0
                            info = {
                                'name': entry.name,
                                'path': fp,
                                'ext': ext,
                                'size': size,
                            }
                            if ext in IMAGE_EXTS:
                                images.append(info)
                            else:
                                others.append(info)
                    except Exception:
                        continue

            folders.sort(key=lambda x: x['name'].lower())
            images.sort(key=lambda x: x['name'].lower())
            others.sort(key=lambda x: x['name'].lower())

            parent = os.path.dirname(path)
            if parent == path:
                parent = None

            return {
                'ok': True,
                'path': path,
                'parent': parent,
                'folders': folders,
                'images': images,
                'others': others,
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 本地图片：统一入口 ----------
    def select_local_image(self, path, action='probe'):
        """
        action:
            'probe'     —— 默认。检查冲突；无冲突直接确认；有冲突返回冲突信息
            'replace'   —— 覆盖同名
            'keep_both' —— 保留两者
            'cancel'    —— 取消
        """
        _log(f'select_local_image: path={path!r}, action={action!r}')

        if not path or not os.path.isfile(path):
            return {'ok': False, 'error': '文件不存在'}
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS:
            return {'ok': False, 'error': '不是支持的图片格式'}

        if action not in ('probe', 'replace', 'keep_both', 'cancel'):
            action = 'probe'

        if action == 'cancel':
            return {'ok': False, 'cancelled': True}

        # 文档未保存：直接返回绝对路径（probe 场景）
        if not self._doc_path:
            md_path = os.path.abspath(path).replace('\\', '/')
            alt = os.path.splitext(os.path.basename(path))[0]
            return self._confirm_pick(md_path, alt, unsaved=True)

        doc_dir = os.path.dirname(os.path.abspath(self._doc_path))
        assets_dir = os.path.join(doc_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)

        name = os.path.basename(path).replace(' ', '_')
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().strip('.') or 'image'
        base, ext_norm = os.path.splitext(name)
        if ext_norm.lower() not in IMAGE_EXTS:
            ext_norm = '.png'
        target = os.path.join(assets_dir, base + ext_norm)

        _log('target 目标路径:', target, '存在:', os.path.exists(target))

        exists = os.path.exists(target)

        # 同文件：直接确认
        if exists:
            try:
                if os.path.samefile(path, target):
                    md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
                    alt = os.path.splitext(os.path.basename(path))[0]
                    return self._confirm_pick(md_path, alt, unsaved=False)
            except Exception:
                pass

        # probe：无冲突则复制；有冲突返回信息
        if action == 'probe':
            if not exists:
                try:
                    shutil.copy2(path, target)
                except Exception as e:
                    return {'ok': False, 'error': str(e)}
                md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
                alt = os.path.splitext(os.path.basename(path))[0]
                return self._confirm_pick(md_path, alt, unsaved=False)

            # 冲突
            try:
                src_size = os.path.getsize(path)
                tgt_size = os.path.getsize(target)
            except Exception:
                src_size = tgt_size = 0
            _log('检测到冲突，返回 conflict=True')
            return {
                'ok': False,
                'conflict': True,
                'src_path': os.path.abspath(path),
                'src_name': os.path.basename(path),
                'src_size': src_size,
                'target_path': target,
                'target_name': os.path.basename(target),
                'target_size': tgt_size,
            }

        # replace / keep_both
        try:
            if action == 'replace':
                shutil.copy2(path, target)
                md_path = os.path.relpath(target, doc_dir).replace('\\', '/')
            else:  # keep_both
                counter = 1
                while True:
                    new_target = os.path.join(
                        assets_dir, f'{base}-{counter}{ext_norm}')
                    if not os.path.exists(new_target):
                        break
                    counter += 1
                shutil.copy2(path, new_target)
                md_path = os.path.relpath(new_target, doc_dir).replace('\\', '/')

            alt = os.path.splitext(os.path.basename(path))[0]
            return self._confirm_pick(md_path, alt, unsaved=False)
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 网络图片 ----------
    def import_network_image(self, url):
        if not url or not isinstance(url, str):
            return {'ok': False, 'error': '空 URL'}
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return {'ok': False, 'error': '仅支持 http/https 链接'}

        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            resp = urllib.request.urlopen(req, timeout=30)
            try:
                ctype = (resp.headers.get('Content-Type') or '').lower()
                data = resp.read(MAX_IMAGE_SIZE + 1)
            finally:
                resp.close()
        except urllib.error.HTTPError as e:
            return {'ok': False, 'error': f'HTTP {e.code}'}
        except urllib.error.URLError as e:
            return {'ok': False, 'error': f'网络错误: {e.reason}'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

        if len(data) > MAX_IMAGE_SIZE:
            return {'ok': False,
                    'error': f'图片超过 {MAX_IMAGE_SIZE // 1024 // 1024}MB'}

        head = data[:64].lstrip().lower()
        if head.startswith(b'<html') or head.startswith(b'<!doctype html'):
            return {'ok': False, 'error': '该链接是网页，不是图片'}

        is_image_ctype = ctype.startswith('image/')
        is_image_magic = (
            data[:8].startswith(b'\x89PNG') or
            data[:3] == b'\xff\xd8\xff' or
            data[:6] in (b'GIF87a', b'GIF89a') or
            data[:4] == b'RIFF' or
            data[:2] == b'BM'
        )
        if not is_image_ctype and not is_image_magic:
            return {'ok': False,
                    'error': f'该链接不是图片（Content-Type: {ctype or "unknown"}）'}

        ext = mimetypes.guess_extension(ctype.split(';')[0].strip()) or ''
        if ext == '.jpe':
            ext = '.jpg'
        if ext not in IMAGE_EXTS:
            ext = os.path.splitext(parsed.path)[1].lower()
        if ext not in IMAGE_EXTS:
            ext = '.png'

        base_name = os.path.splitext(os.path.basename(parsed.path))[0]
        base_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', base_name)[:50] or 'image'

        try:
            if self._doc_path:
                doc_dir = os.path.dirname(os.path.abspath(self._doc_path))
                assets_dir = os.path.join(doc_dir, 'assets')
                os.makedirs(assets_dir, exist_ok=True)

                candidate = os.path.join(assets_dir, base_name + ext)
                counter = 1
                while os.path.exists(candidate):
                    candidate = os.path.join(assets_dir, f'{base_name}-{counter}{ext}')
                    counter += 1

                with open(candidate, 'wb') as f:
                    f.write(data)
                md_path = os.path.relpath(candidate, doc_dir).replace('\\', '/')
                return self._confirm_pick(md_path, base_name, unsaved=False)
            else:
                fd, tmp = tempfile.mkstemp(suffix=ext)
                os.close(fd)
                with open(tmp, 'wb') as f:
                    f.write(data)
                return self._confirm_pick(tmp.replace('\\', '/'),
                                          base_name, unsaved=True)
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 结果回传 ----------
    def _confirm_pick(self, md_path, alt_text='', unsaved=False):
        md_path = (md_path or '').strip()
        if not md_path:
            return {'ok': False, 'error': '空路径'}

        src = md_path
        if re.search(r'[\s()<>]', src) and not src.startswith('<'):
            src = '<' + src + '>'
        md = f'![{alt_text or ""}]({src})'

        if self._main_api is not None and getattr(self._main_api, '_window', None) is not None:
            try:
                payload = json.dumps({'md': md, 'unsaved': bool(unsaved)},
                                     ensure_ascii=False)
                self._main_api._window.evaluate_js(
                    f'window.onImagePickerResult && window.onImagePickerResult({payload});'
                )
            except Exception as e:
                return {'ok': False, 'error': str(e)}

        self.close_window()
        return {'ok': True, 'unsaved': unsaved}