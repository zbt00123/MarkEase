# -*- coding: utf-8 -*-
"""
MarkEase macOS 平台实现（WKWebView / PyObjC）。

- 窗口后端：pywebview 的 cocoa（WKWebView）
- 剪贴板：pbpaste（不弹权限、不依赖 JS 剪贴板权限）
- 文件管理器：open / open -R
- PDF：WKWebView printOperationWithPrintInfo:（打印媒体，分页与 Windows 一致）
- 双击 .md 打开：CFBundleDocumentTypes（Info.plist）+ open-file Apple Event

★ 本模块只在 macOS 上被 import；PyObjC 相关 import 一律放在函数内部，
  避免 Linux / Windows 因为缺少 AppKit 而启动失败。
"""

import os
import sys
import time
import json
import threading

from .base import PlatformBase

# Apple Event 送进来的待打开文件（线程安全由 GIL + list 原子操作保证）
_pending_files = []
_handler = None


def _queue_file(path):
    try:
        path = os.path.abspath(path)
    except Exception:
        return
    if path and path not in _pending_files:
        _pending_files.append(path)


class MacPlatform(PlatformBase):
    name = 'macOS'
    is_macos = True

    # ---------- 启动 / 窗口 ----------
    def webview_gui(self):
        return 'cocoa'

    def get_icon_path(self, base_dir):
        for name in ('icon.icns', 'icon-512.png', 'icon-256.png'):
            path = os.path.join(base_dir, 'resources', 'icons', name)
            if os.path.exists(path):
                return path
        return None

    def _data_dir(self):
        return os.path.join(os.path.expanduser('~'),
                            'Library', 'Application Support', 'MarkEase')

    def prepare_webview_env(self):
        # macOS 的 WKWebView 数据目录由 WebKit 自己管理，
        # 这里只确保应用数据目录存在（日志 / 设置已由 logging_setup / api 处理）。
        try:
            os.makedirs(self._data_dir(), exist_ok=True)
        except Exception:
            pass
        return None

    # ---------- 原生菜单（macOS 系统菜单栏） ----------
    def get_native_menu(self, window, api):
        """构建 macOS 系统菜单栏；菜单项通过 MKMenuAction 调用前端统一动作。"""
        try:
            import webview as _webview
            from webview.menu import Menu, MenuAction, MenuSeparator
        except Exception as e:
            print(f'[MarkEase][mac] native menu unavailable: {e}')
            return None

        # 保留 pywebview 默认「编辑」菜单：macOS 的 Cmd+C/V/X/A 快捷键依赖它。
        # 只禁用默认「视图」菜单（里面只有全屏），改用 MarkEase 自己的「查看」。
        try:
            from webview.platforms import cocoa as _cocoa
            if not getattr(_cocoa.BrowserView,
                           '_mk_default_view_disabled', False):
                _cocoa.BrowserView._add_view_menu = \
                    lambda self, main_menu: None
                _cocoa.BrowserView._mk_default_view_disabled = True
        except Exception as e:
            print(f'[MarkEase][mac] cannot disable default view menu: {e}')

        labels = {}
        try:
            r = api.get_translations()
            if r and r.get('ok'):
                labels = r.get('dict') or {}
        except Exception as e:
            print(f'[MarkEase][mac] menu translations failed: {e}')

        def _t(key, fallback):
            value = labels.get(key)
            return str(value) if value else fallback

        # 默认「编辑」菜单的本地化（pywebview 自带 cut/copy/paste/selectAll）
        self._webview_localization = {
            'cocoa.menu.edit': _t('edit', '编辑'),
            'cocoa.menu.cut': _t('cut', '剪切'),
            'cocoa.menu.copy': _t('copy', '复制'),
            'cocoa.menu.paste': _t('paste', '粘贴'),
            'cocoa.menu.selectAll': _t('select_all', '全选'),
        }

        def _fullscreen():
            try:
                window.toggle_fullscreen()
            except Exception as exc:
                print(f'[MarkEase][mac] toggle_fullscreen failed: {exc}')

        _fullscreen.__name__ = 'mk_menu_toggle_fullscreen'

        def _action(action_id, title):
            def _run():
                try:
                    script = ('window.MKMenuAction && '
                              'window.MKMenuAction(%s);'
                              % json.dumps(action_id))
                    window.evaluate_js(script)
                except Exception as exc:
                    print(f'[MarkEase][mac] menu {action_id} failed: {exc}')

            _run.__name__ = 'mk_menu_' + action_id
            return MenuAction(title, _run)

        def item(action_id, key, fallback):
            return _action(action_id, _t(key, fallback))

        file_menu = Menu(_t('file', '文件'), [
            item('new', 'new', '新建'),
            item('open', 'open', '打开'),
            item('save', 'save', '保存'),
            item('save_as', 'save_as', '另存为'),
            MenuSeparator(),
            item('insert_image', 'insert_image', '插入图片'),
            MenuSeparator(),
            Menu(_t('import', '导入'), [
                item('import_pdf', 'import_pdf', '导入 PDF'),
                item('import_html', 'import_html', '导入 HTML'),
            ]),
            Menu(_t('export', '导出'), [
                item('export_pdf', 'export_pdf', '导出 PDF'),
                item('export_html', 'export_html', '导出 HTML'),
            ]),
            MenuSeparator(),
            item('exit', 'exit', '退出'),
        ])

        view_menu = Menu(_t('view', '查看'), [
            item('mode_edit', 'edit_mode', '编辑模式'),
            item('mode_split', 'split_mode', '分屏模式'),
            item('mode_preview', 'preview_mode', '预览模式'),
            MenuSeparator(),
            item('toggle_toc', 'show_toc', '显示/隐藏目录'),
            MenuSeparator(),
            item('zoom_in', 'zoom_in', '放大'),
            item('zoom_out', 'zoom_out', '缩小'),
            item('zoom_reset', 'reset_zoom', '重置缩放'),
            MenuSeparator(),
            item('toggle_theme', 'toggle_theme', '切换主题'),
            MenuSeparator(),
            MenuAction(_t('toggle_fullscreen', '切换全屏'), _fullscreen),
            MenuSeparator(),
            Menu(_t('language', '语言'), [
                item('lang_system', 'system', '跟随系统'),
                item('lang_zh_CN', 'zh_CN', '简体中文'),
                item('lang_zh_TW', 'zh_TW', '繁体中文'),
                item('lang_en_US', 'en_US', 'English'),
                item('lang_ja_JP', 'ja_JP', '日本語'),
                item('lang_ko_KR', 'ko_KR', '한국어'),
            ]),
        ])

        help_menu = Menu(_t('help', '帮助'), [
            item('about', 'about', '关于 MarkEase'),
            item('check_update', 'check_update', '检查更新'),
            MenuSeparator(),
            item('logs', 'logs', '日志'),
            MenuSeparator(),
            Menu(_t('settings', '设置'), [
                item('set_default_program', 'set_default_program',
                     '设为默认打开程序'),
                item('register_shell_new', 'register_shell_new',
                     '添加到「新建」菜单'),
            ]),
        ])

        print('[MarkEase][mac] native menu installed')
        return [file_menu, view_menu, help_menu]

    def webview_localization(self):
        return getattr(self, '_webview_localization', {})

    # ---------- 剪贴板 ----------
    def read_clipboard_text(self):
        return self._read_clipboard_from_commands([('pbpaste',)])

    # ---------- 文件管理器 ----------
    def open_directory(self, path, select_path=None):
        import subprocess
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.Popen(['open', folder])
        return {'ok': True}

    def reveal(self, path):
        import subprocess
        path = os.path.abspath(path or '')
        if not os.path.exists(path):
            return {'ok': False, 'error': '文件不存在：' + path}
        try:
            subprocess.Popen(['open', '-R', path])
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ---------- 系统集成：open-file Apple Event ----------
    def init_app_integration(self):
        """注册 open-file 处理器（必须在 NSApplication 运行前调用）。"""
        global _handler
        if _handler is not None:
            return
        try:
            import AppKit
            import Foundation
        except Exception as e:
            print(f'[MarkEase][mac] PyObjC unavailable: {e}')
            return

        try:
            class _OpenFileHandler(AppKit.NSObject):
                def handleOpenFile_event_(self, event, reply_event):
                    try:
                        key_direct = getattr(Foundation, 'keyDirectObject',
                                             0x2d2d2d2d)  # '----'
                        desc = event.paramDescriptorForKeyword_(key_direct)
                        if desc is None:
                            return
                        count = int(desc.numberOfItems())
                        for i in range(count):
                            item = desc.descriptorAtIndex_(i)
                            if item is None:
                                continue
                            raw = item.stringValue()
                            if not raw:
                                continue
                            url = Foundation.NSURL.URLWithString_(raw)
                            if url is not None and url.isFileURL():
                                _queue_file(str(url.path()))
                    except Exception as exc:
                        print(f'[MarkEase][mac] open-file parse failed: {exc}')

            handler = _OpenFileHandler.alloc().init()
            manager = AppKit.NSAppleEventManager.sharedAppleEventManager()
            selector = b'handleOpenFile:event:'
            event_class = getattr(AppKit, 'kCoreEventClass', 0x61657674)  # aevt
            event_id = getattr(AppKit, 'kAEOpenDocuments', 0x6f646f63)  # odoc
            registered = False
            for name in ('setEventHandler_selector_forEventClass_andEventID_',
                         'setEventHandler_andSelector_forEventClass_andEventID_'):
                fn = getattr(manager, name, None)
                if fn is None:
                    continue
                try:
                    fn(handler, selector, event_class, event_id)
                    registered = True
                    break
                except Exception:
                    continue
            if not registered:
                raise RuntimeError('NSAppleEventManager API not found')
            _handler = handler
            print('[MarkEase][mac] open-file Apple Event handler installed')
        except Exception as e:
            print(f'[MarkEase][mac] cannot install open-file handler: {e}')

    def start_open_file_watcher(self, window, api):
        """窗口加载后，把 Apple Event 送来的文件转交前端打开。"""
        def _watch():
            while True:
                try:
                    if self.is_shutting_down():
                        return
                    if not _pending_files:
                        time.sleep(0.5)
                        continue
                    path = _pending_files[0]
                    try:
                        api.set_startup_file(path)
                        window.evaluate_js(
                            'window.MKOpenStartupFile && window.MKOpenStartupFile()')
                        _pending_files.pop(0)
                    except Exception:
                        # 页面尚未就绪：保留在队列里，稍后重试
                        time.sleep(0.5)
                except Exception:
                    time.sleep(1.0)

        threading.Thread(target=_watch, daemon=True,
                         name='MarkEaseOpenFileWatcher').start()

    # ---------- PDF ----------
    def supports_pdf_export(self):
        try:
            import AppKit  # noqa: F401
            import WebKit  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _wkwebview(window):
        gui = getattr(window, 'gui', None)
        wv = getattr(gui, 'webview', None)
        if wv is None:
            wv = getattr(getattr(window, 'native', None), 'webview', None)
        return wv

    def export_pdf(self, window, pdf_path):
        try:
            import AppKit
            import Foundation
        except Exception as e:
            return {'ok': False, 'error': f'缺少 PyObjC，无法导出 PDF: {e}'}

        wv = self._wkwebview(window)
        if wv is None:
            return {'ok': False, 'error': '无法获取 WKWebView'}

        holder = {}
        done = threading.Event()

        def _do_print():
            try:
                info = AppKit.NSPrintInfo.alloc().init()
                # 与 Windows PrintToPdfAsync 默认一致：Letter + 0.4 inch 页边距
                info.setPaperSize_(Foundation.NSMakeSize(612.0, 792.0))
                info.setTopMargin_(28.8)
                info.setBottomMargin_(28.8)
                info.setLeftMargin_(28.8)
                info.setRightMargin_(28.8)
                info.setHorizontalPagination_(AppKit.NSFitPagination)
                info.setVerticalPagination_(AppKit.NSAutoPagination)
                info.setJobDisposition_(AppKit.NSPrintSaveJob)
                info.setJobSavingURL_(
                    Foundation.NSURL.fileURLWithPath_(pdf_path))

                op = wv.printOperationWithPrintInfo_(info)
                if op is None:
                    raise RuntimeError('WKWebView 不支持打印')
                op.setShowsPrintPanel_(False)
                op.setShowsProgressPanel_(False)
                if not bool(op.runOperation()):
                    raise RuntimeError('打印操作被取消或失败')
            except Exception as e:
                holder['error'] = e
            finally:
                done.set()

        if self._is_main_thread():
            _do_print()
        else:
            try:
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    _do_print)
            except Exception as e:
                return {'ok': False, 'error': f'主线程调度失败: {e}'}
            if not done.wait(180):
                return {'ok': False, 'error': '导出 PDF 超时（180 秒）'}

        if holder.get('error') is not None:
            return {'ok': False, 'error': str(holder['error'])}

        if not os.path.exists(pdf_path):
            return {'ok': False, 'error': '未生成 PDF 文件'}
        try:
            with open(pdf_path, 'rb') as f:
                if f.read(5) != b'%PDF-':
                    return {'ok': False,
                            'error': 'macOS 打印组件未输出有效 PDF'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

        # macOS 11 曾出现 NSPrintSaveJob 输出空白页的问题：
        # 页面数量正确但没有任何文字 / 图片。这里显式检测，避免"成功导出空白 PDF"。
        try:
            import pymupdf
            doc = pymupdf.open(pdf_path)
            try:
                if doc.page_count == 0:
                    return {'ok': False, 'error': '导出的 PDF 没有页面'}
                blank = True
                for page in doc:
                    if page.get_text().strip() or page.get_images():
                        blank = False
                        break
                if blank:
                    return {'ok': False,
                            'error': 'macOS 打印组件输出了空白 PDF，'
                                     '请改用“导出 HTML”或在真机上反馈该问题'}
            finally:
                doc.close()
        except ImportError:
            pass
        except Exception as e:
            print(f'[MarkEase][mac] PDF validation failed: {e}')

        return {'ok': True}

    @staticmethod
    def _is_main_thread():
        try:
            from Foundation import NSThread
            return bool(NSThread.isMainThread())
        except Exception:
            return False

    # ---------- 文件关联 ----------
    # macOS 的文档类型由 Info.plist 的 CFBundleDocumentTypes 声明；
    # 默认程序属于 LaunchServices，未签名的 .app 不适合在运行时强改，
    # 这里给出可执行的系统设置指引。
    def setup_file_associations_on_first_run(self):
        return {'ok': False, 'skipped': True,
                'reason': 'macOS uses Info.plist document types'}

    def register_shell_new(self):
        return {'ok': False, 'skipped': True,
                'reason': 'macOS does not support ShellNew'}

    def set_as_default_program(self):
        return {
            'ok': False,
            'error': 'macOS 请在 Finder 中右键 .md 文件 → 显示简介 → '
                     '“打开方式”选择 MarkEase → 点击“全部更改”',
            'hint': 'finder_open_with',
        }

    def is_default_program(self):
        return False

    def get_default_program_name(self):
        return 'Markdown Document'

    # ---------- 启动文件 ----------
    def parse_startup_file(self, argv):
        path = super().parse_startup_file(argv)
        if path:
            return path
        while _pending_files:
            candidate = _pending_files.pop(0)
            if os.path.isfile(candidate):
                return candidate
        return ''
