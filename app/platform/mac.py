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
import shutil
import tempfile
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

        self._file_menu_title = _t('file', '文件')
        file_menu = Menu(self._file_menu_title, [
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

    def restart_app(self):
        """重启当前 .app，让新的语言设置重新构建原生菜单。"""
        import subprocess
        try:
            if getattr(sys, 'frozen', False):
                exe = sys.executable
                marker = os.sep + 'Contents' + os.sep + 'MacOS' + os.sep
                if marker in exe:
                    bundle = exe.split(marker)[0]
                    args = ['open', '-n', bundle]
                else:
                    args = [exe]
            else:
                root = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))))
                args = [sys.executable, os.path.join(root, 'main.py')]
            subprocess.Popen(args, close_fds=True)
            threading.Timer(0.6, lambda: os._exit(0)).start()
            return True
        except Exception as e:
            print(f'[MarkEase][mac] restart failed: {e}')
            return False

    def on_webview_started(self, window=None):
        """GUI 启动后把「文件」菜单移到「编辑」左侧（macOS 标准顺序）。"""
        try:
            threading.Thread(target=self._wait_and_reorder_menus,
                             daemon=True,
                             name='MarkEaseMenuOrder').start()
        except Exception as e:
            print(f'[MarkEase][mac] menu order thread failed: {e}')

    def _wait_and_reorder_menus(self):
        try:
            import AppKit
            from PyObjCTools import AppHelper
        except Exception as e:
            print(f'[MarkEase][mac] PyObjC menu reorder unavailable: {e}')
            return
        wanted = getattr(self, '_file_menu_title', '文件')
        for _ in range(100):
            try:
                main = AppKit.NSApplication.sharedApplication().mainMenu()
                if main is not None:
                    titles = [str(i.title()) for i in main.itemArray()]
                    if wanted in titles:
                        break
            except Exception:
                pass
            time.sleep(0.1)
        AppHelper.callAfter(self._reorder_menus)

    def _reorder_menus(self):
        try:
            import AppKit
            main = AppKit.NSApplication.sharedApplication().mainMenu()
            if main is None:
                return
            wanted = getattr(self, '_file_menu_title', '文件')
            for item in list(main.itemArray()):
                try:
                    if str(item.title()) == wanted:
                        main.removeItem_(item)
                        main.insertItem_atIndex_(item, 1)
                        print('[MarkEase][mac] menu order fixed: '
                              'File before Edit')
                        return
                except Exception:
                    continue
        except Exception as e:
            print(f'[MarkEase][mac] reorder menus failed: {e}')

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
        # pywebview 的 Window.gui 是 GUI 模块，不是 BrowserView；
        # 真正的 WKWebView 在 cocoa.BrowserView.instances[uid].webview
        try:
            from webview.platforms import cocoa
            browser = cocoa.BrowserView.instances.get(
                getattr(window, 'uid', None))
            if browser is not None:
                wv = getattr(browser, 'webview', None)
                if wv is not None:
                    return wv
        except Exception:
            pass

        native = getattr(window, 'native', None)
        wv = getattr(native, 'webview', None)
        if wv is not None:
            return wv

        # 最后兜底：从 NSWindow.contentView 向下找 WKWebView
        try:
            root = native.contentView() if native is not None else None

            def _walk(view, depth=0):
                if view is None or depth > 6:
                    return None
                if hasattr(view,
                           'createPDFWithConfiguration_completionHandler_'):
                    return view
                try:
                    subs = view.subviews()
                except Exception:
                    subs = []
                for sub in subs:
                    found = _walk(sub, depth + 1)
                    if found is not None:
                        return found
                return None

            return _walk(root)
        except Exception:
            return None

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
                saving_url = Foundation.NSURL.fileURLWithPath_(pdf_path)
                info.setJobSavingURL_(saving_url)
                # 某些 macOS 版本只认 printInfo.dictionary 里的 jobSavingURL
                try:
                    info.dictionary().setObject_forKey_(
                        saving_url, AppKit.NSPrintJobSavingURL)
                except Exception:
                    pass

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
            print(f'[MarkEase][mac] print operation failed: {holder["error"]}')

        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 100:
            # NSPrintSaveJob 在部分 macOS 版本不会真正写文件 / 输出空白。
            # 兜底：用 WKWebView.createPDF 直接生成 PDF 数据并写盘。
            print('[MarkEase][mac] print-to-file produced nothing; '
                  'falling back to WKWebView.createPDF')
            if not self._fallback_create_pdf(window, wv, pdf_path):
                if holder.get('error') is not None:
                    return {'ok': False, 'error': str(holder['error'])}
                return {'ok': False, 'error': '未生成 PDF 文件'}

        if not os.path.exists(pdf_path):
            return {'ok': False, 'error': '未生成 PDF 文件'}
        try:
            with open(pdf_path, 'rb') as f:
                if f.read(5) != b'%PDF-':
                    return {'ok': False,
                            'error': 'macOS 打印组件未输出有效 PDF'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

        # macOS 11 曾出现 NSPrintSaveJob 输出空白页的问题。
        # 这里只检查文件有效性与页数，不因为"没有文字/图片"就判失败：
        # WKWebView 可能把文字转成路径，get_text() 为空但 PDF 是正常的。
        try:
            size = os.path.getsize(pdf_path)
            import pymupdf
            doc = pymupdf.open(pdf_path)
            try:
                pages = doc.page_count
                text_len = 0
                image_count = 0
                for page in doc:
                    text_len += len(page.get_text().strip())
                    image_count += len(page.get_images())
                print(f'[MarkEase][mac] pdf: size={size} pages={pages} '
                      f'text={text_len} images={image_count}')
                if pages == 0 or size < 100:
                    return {'ok': False,
                            'error': 'macOS 打印组件生成的 PDF 为空'}
                if text_len == 0 and image_count == 0:
                    print('[MarkEase][mac] WARNING: PDF has no extractable '
                          'text/images (may still render correctly)')
            finally:
                doc.close()
        except ImportError:
            if os.path.getsize(pdf_path) < 100:
                return {'ok': False, 'error': '生成的 PDF 文件过小'}
        except Exception as e:
            print(f'[MarkEase][mac] PDF validation failed: {e}')

        return {'ok': True}

    def _fallback_create_pdf(self, window, wv, pdf_path):
        """NSPrintSaveJob 不写文件时的兜底：WKWebView.createPDF。"""
        try:
            import Foundation
        except Exception as e:
            print(f'[MarkEase][mac] fallback createPDF unavailable: {e}')
            return False

        try:
            try:
                window.evaluate_js(
                    'window.MKSetPdfMode && window.MKSetPdfMode(true)')
            except Exception:
                pass
            time.sleep(0.3)

            width, height = self._wk_content_size(wv)
            if width <= 0:
                width = 1200.0
            if height <= 0:
                height = 1600.0

            # PDF 单页最大 200in；超长文档分块捕获后用 PyMuPDF 合并
            if height <= 18000.0:
                rects = [Foundation.NSMakeRect(0.0, 0.0, width, height)]
            else:
                rects = []
                y = 0.0
                while y < height:
                    h = min(8000.0, height - y)
                    rects.append(Foundation.NSMakeRect(0.0, y, width, h))
                    y += h

            parts = []
            for rect in rects:
                data = self._wk_create_pdf(wv, rect)
                if data is None:
                    return False
                fd, tmp = tempfile.mkstemp(suffix='.pdf')
                os.close(fd)
                if not bool(data.writeToFile_atomically_(tmp, True)):
                    return False
                parts.append(tmp)

            if len(parts) == 1:
                shutil.move(parts[0], pdf_path)
            else:
                import pymupdf
                out = pymupdf.open()
                try:
                    for part in parts:
                        src = pymupdf.open(part)
                        out.insert_pdf(src)
                        src.close()
                    out.save(pdf_path)
                finally:
                    out.close()
                    for part in parts:
                        try:
                            os.remove(part)
                        except Exception:
                            pass
            print(f'[MarkEase][mac] fallback createPDF wrote {pdf_path}')
            return True
        except Exception as e:
            print(f'[MarkEase][mac] fallback createPDF failed: {e}')
            return False
        finally:
            try:
                window.evaluate_js(
                    'window.MKSetPdfMode && window.MKSetPdfMode(false)')
            except Exception:
                pass

    def _wk_content_size(self, wv):
        """在主线程获取 WKWebView 可视宽度 / 全文高度。"""
        try:
            import AppKit
        except Exception:
            return (1200.0, 1600.0)

        holder = {}
        done = threading.Event()

        def _do():
            try:
                frame = wv.frame().size
                scroll = wv.scrollView()
                doc_view = scroll.documentView() if scroll is not None else None
                height = (doc_view.frame().size.height
                          if doc_view is not None else frame.height)
                holder['size'] = (frame.width, height)
            except Exception as e:
                holder['error'] = e
            finally:
                done.set()

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
        done.wait(10)
        if holder.get('error') is not None:
            print(f'[MarkEase][mac] content size failed: {holder["error"]}')
            return (1200.0, 1600.0)
        return holder.get('size') or (1200.0, 1600.0)

    def _wk_create_pdf(self, wv, rect):
        """在主线程调用 WKWebView.createPDF，返回 NSData 或 None。"""
        try:
            import AppKit
            import WebKit
        except Exception as e:
            print(f'[MarkEase][mac] WebKit createPDF unavailable: {e}')
            return None

        holder = {}
        done = threading.Event()

        def _do():
            try:
                cfg = WebKit.WKPDFConfiguration.alloc().init()
                cfg.setRect_(rect)

                def handler(data, error):
                    try:
                        if error is not None:
                            holder['error'] = error
                        else:
                            holder['data'] = data
                    finally:
                        done.set()

                wv.createPDFWithConfiguration_completionHandler_(cfg, handler)
            except Exception as e:
                holder['error'] = e
                done.set()

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_do)
        if not done.wait(120):
            print('[MarkEase][mac] createPDF timed out')
            return None
        if holder.get('error') is not None:
            print(f'[MarkEase][mac] createPDF failed: {holder["error"]}')
            return None
        return holder.get('data')

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
