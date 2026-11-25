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
        """macOS 只保留系统应用菜单；业务菜单回到窗口内 HTML 菜单栏。"""
        self._window = window
        self._api = api
        try:
            import webview as _webview
            # 只保留 App 菜单（About/Hide/Quit），不创建 View/Edit 菜单
            _webview.settings['SHOW_DEFAULT_MENUS'] = False
        except Exception as e:
            print(f'[MarkEase][mac] cannot hide default menus: {e}')

        try:
            self._install_early_about_hook()
        except Exception as e:
            print(f'[MarkEase][mac] early About hook failed: {e}')

        print('[MarkEase][mac] in-window menubar enabled; app menu only')
        return None

    def _install_early_about_hook(self):
        """在 App 菜单创建的那一刻改写 About，保证点得再快也是自定义窗口。"""
        from webview.platforms import cocoa

        if getattr(cocoa.BrowserView, '_mk_about_hook', False):
            return

        original = cocoa.BrowserView._add_app_menu

        def _patched(self, main_menu, custom_items=None):
            original(self, main_menu, custom_items)
            try:
                from app.platform import platform as _platform
                _platform._rewire_about_menu(main_menu)
            except Exception as e:
                print(f'[MarkEase][mac] early About rewire failed: {e}')

        cocoa.BrowserView._add_app_menu = _patched
        cocoa.BrowserView._mk_about_hook = True

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

    def quit_immediately(self):
        """直接 os._exit，绕过 Python finalize 对 JS API 线程的 join。

        pywebview 的每个 JS API 调用都在非 daemon 线程里执行；从
        force_close() 里 window.destroy() 会让该线程停在 Cocoa 销毁流程，
        解释器退出时 wait_for_thread_shutdown 永久等待，表现为"关闭卡死"。
        """
        try:
            threading.Timer(0.15, lambda: os._exit(0),
                            ).start()
            return True
        except Exception as e:
            print(f'[MarkEase][mac] quit_immediately failed: {e}')
            return False

    def on_webview_started(self, window=None):
        """启动后兜底再改一次 About（正常应由 _add_app_menu hook 提前完成）。"""
        self._window = window
        try:
            threading.Thread(target=self._late_about_fix,
                             daemon=True,
                             name='MarkEaseAboutFix').start()
        except Exception as e:
            print(f'[MarkEase][mac] About fallback thread failed: {e}')

    def _late_about_fix(self):
        try:
            import AppKit
        except Exception:
            return
        for _ in range(50):
            try:
                main = AppKit.NSApplication.sharedApplication().mainMenu()
                if main is not None and main.numberOfItems() >= 1:
                    self._rewire_about_menu(main)
                    return
            except Exception:
                pass
            time.sleep(0.1)

    def _rewire_about_menu(self, main):
        """把系统 App 菜单的 About 改为打开 MarkEase 自己的关于窗口。"""
        if getattr(self, '_about_rewired', False):
            return
        try:
            import AppKit
            if main.numberOfItems() < 1:
                return
            sub = main.itemAtIndex_(0).submenu()
            if sub is None:
                return

            handler = getattr(self, '_about_handler', None)
            if handler is None:
                class _AboutHandler(AppKit.NSObject):
                    def showAbout_(self, sender):
                        try:
                            api = getattr(self, '_mk_api', None)
                            if api is not None:
                                # 直接开自定义关于窗口，不依赖前端是否已初始化
                                threading.Thread(
                                    target=api.open_about_window,
                                    daemon=True,
                                    name='MarkEaseAboutMenu',
                                ).start()
                                return
                            window = getattr(self, '_mk_window', None)
                            if window is None:
                                return
                            threading.Thread(
                                target=lambda: window.evaluate_js(
                                    "window.MKMenuAction && "
                                    "window.MKMenuAction('about')"),
                                daemon=True,
                                name='MarkEaseAboutMenu',
                            ).start()
                        except Exception as e:
                            print(f'[MarkEase][mac] About menu failed: {e}')

                handler = _AboutHandler.alloc().init()
                self._about_handler = handler

            handler._mk_window = getattr(self, '_window', None)
            handler._mk_api = getattr(self, '_api', None)
            for item in sub.itemArray():
                title = str(item.title() or '')
                try:
                    action = str(item.action() or '')
                except Exception:
                    action = ''
                if ('About' in title or '关于' in title or
                        'orderFrontStandardAboutPanel' in action):
                    item.setTarget_(handler)
                    item.setAction_(b'showAbout:')
                    self._about_rewired = True
                    print('[MarkEase][mac] About menu rewired')
                    return
        except Exception as e:
            print(f'[MarkEase][mac] rewire About menu failed: {e}')

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

        # 真正让 macOS 的「双击 .md」生效的是 NSApplicationDelegate 的
        # application:openFile:/openFiles:。旧版只注册 AppleEvent handler，
        # LaunchServices 仍会走 delegate，delegate 不实现就弹
        # “MarkEase cannot open files in the Markdown Document format”。
        try:
            from webview.platforms import cocoa

            class _MarkEaseAppDelegate(cocoa.BrowserView.AppDelegate):
                def application_openFile_(self, sender, filename):
                    try:
                        _queue_file(str(filename))
                    except Exception as exc:
                        print(f'[MarkEase][mac] openFile failed: {exc}')
                    return True

                def application_openFiles_(self, sender, filenames):
                    try:
                        for path in filenames:
                            _queue_file(str(path))
                    except Exception as exc:
                        print(f'[MarkEase][mac] openFiles failed: {exc}')

                def application_openURLs_(self, sender, urls):
                    try:
                        for url in urls:
                            if url is not None and url.isFileURL():
                                _queue_file(str(url.path()))
                    except Exception as exc:
                        print(f'[MarkEase][mac] openURLs failed: {exc}')

            cocoa.BrowserView.AppDelegate = _MarkEaseAppDelegate
            cocoa.BrowserView._shared_app_delegate = None
            print('[MarkEase][mac] open-file application delegate installed')
        except Exception as e:
            print(f'[MarkEase][mac] cannot install open-file delegate: {e}')

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
        wv = self._wkwebview(window)
        if wv is None:
            return {'ok': False, 'error': '无法获取 WKWebView'}

        # NSPrintOperation 在 macOS 上会卡在保存面板，已弃用。
        # createPDF 先按浅色打印版式截取，再按 Letter 页切片。
        if self._fallback_create_pdf(window, wv, pdf_path):
            return {'ok': True}
        return {'ok': False, 'error': 'PDF 导出失败'}

    def _fallback_create_pdf(self, window, wv, pdf_path):
        """createPDF 兜底：先截取浅色长图，再按 Letter 页切片。"""
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
            time.sleep(0.6)

            width, height = self._pdf_page_size(window)
            if width <= 0:
                width = 720.0
            if height <= 0:
                height = 1600.0

            # PDF 单页最大 200in；超长文档分块捕获
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

            if not parts:
                return False

            source = parts[0]
            if len(parts) > 1:
                import pymupdf
                fd, merged = tempfile.mkstemp(suffix='.pdf')
                os.close(fd)
                out = pymupdf.open()
                try:
                    for part in parts:
                        src_doc = pymupdf.open(part)
                        out.insert_pdf(src_doc)
                        src_doc.close()
                    out.save(merged)
                finally:
                    out.close()
                source = merged

            self._paginate_pdf(source, pdf_path)
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

    def _paginate_pdf(self, source_path, pdf_path):
        """把 createPDF 的长页按 Letter 尺寸切片，尽量避开文字行。"""
        import pymupdf

        page_w, page_h = 612.0, 792.0
        margin = 28.8
        content_w = page_w - margin * 2
        content_h = page_h - margin * 2

        src = pymupdf.open(source_path)
        out = pymupdf.open()
        try:
            for src_page in src:
                width = float(src_page.rect.width)
                height = float(src_page.rect.height)
                if width <= 1 or height <= 1:
                    continue
                scale = content_w / width
                step = content_h / scale

                obstacles = []
                try:
                    text = src_page.get_text('dict')
                    for block in text.get('blocks', []):
                        if block.get('type') == 0:
                            for line in block.get('lines', []):
                                bbox = line.get('bbox')
                                if bbox:
                                    obstacles.append((bbox[1], bbox[3]))
                        else:
                            bbox = block.get('bbox')
                            if bbox:
                                obstacles.append((bbox[1], bbox[3]))
                    for image in src_page.get_image_info():
                        bbox = image.get('bbox')
                        if bbox:
                            obstacles.append((bbox[1], bbox[3]))
                except Exception:
                    obstacles = []

                def safe_break(target, min_y):
                    candidate = target
                    for _ in range(20):
                        hit = None
                        for y0, y1 in obstacles:
                            if y0 < candidate - 1 < y1:
                                hit = (y0, y1)
                                break
                        if hit is None:
                            return candidate
                        new_y = hit[0] - 2
                        if new_y <= min_y:
                            new_y = hit[1] + 2
                        if new_y <= min_y or new_y >= target:
                            return target
                        candidate = new_y
                    return target

                y = 0.0
                while y < height - 1:
                    target = min(y + step, height)
                    if target < height:
                        target = safe_break(target, y + step * 0.5)
                    if target <= y + 10:
                        target = min(y + step, height)
                    slice_h = target - y
                    dest_h = slice_h * scale
                    page = out.new_page(width=page_w, height=page_h)
                    dest = pymupdf.Rect(
                        margin, margin, margin + content_w,
                        margin + min(dest_h, content_h))
                    clip = pymupdf.Rect(0, y, width, target)
                    page.show_pdf_page(dest, src, src_page.number, clip=clip)
                    y = target

            out.save(pdf_path, garbage=4, deflate=True)
        finally:
            out.close()
            src.close()

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

    def _pdf_page_size(self, window):
        """用打印版式的 preview 宽高（CSS 像素）作为 createPDF 的 rect。"""
        try:
            width = float(window.evaluate_js(
                "(document.getElementById('preview') || {})."
                "getBoundingClientRect().width || 720"))
            height = float(window.evaluate_js(
                "Math.max((document.getElementById('preview') || {})."
                "scrollHeight || 0, document.body.scrollHeight) || 1600"))
            return max(width, 320.0), max(height, 600.0)
        except Exception as e:
            print(f'[MarkEase][mac] PDF size probe failed: {e}')
            return (720.0, 1600.0)

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
