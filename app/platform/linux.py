# -*- coding: utf-8 -*-
"""
MarkEase Linux 平台实现（GTK / WebKit2GTK）。

- 窗口后端：pywebview 的 gtk（WebKit2 4.1，回退 4.0）
- 剪贴板：wl-paste / xclip / xsel
- 文件管理器：xdg-open
- PDF：WebKit2.PrintOperation（GTK 打印管线，导出 PDF，打印媒体分页）
- 文件关联：~/.local/share/applications/markease.desktop + xdg-mime

★ 本模块只在 Linux 上被 import；gi / Gtk 相关 import 一律放在函数内部，
  避免 Windows / macOS 因为缺少 GI 而启动失败。
"""

import os
import sys
import time
import glob
import shutil
import tempfile
import threading

from .base import PlatformBase


DESKTOP_FILE_NAME = 'markease.desktop'


class LinuxPlatform(PlatformBase):
    name = 'Linux'
    is_linux = True

    # ---------- 启动 / 窗口 ----------
    def webview_gui(self):
        return 'gtk'

    def get_icon_path(self, base_dir):
        for name in ('icon-512.png', 'icon-256.png', 'icon.png',
                     'markease.png'):
            path = os.path.join(base_dir, 'resources', 'icons', name)
            if os.path.exists(path):
                return path
        # 打包版会把 png 放在数据目录根部附近，再兜底找一次
        for path in glob.glob(os.path.join(base_dir, 'resources', 'icons',
                                           '*.png')):
            return path
        return None

    def prepare_webview_env(self):
        # WebKitGTK 在某些虚拟机 / 无 GPU 环境下 DMA-BUF 渲染会崩溃。
        # 只在用户没有显式设置时关闭，保证 CI 与远程桌面可启动。
        os.environ.setdefault('WEBKIT_DISABLE_DMABUF_RENDERER', '1')
        return None

    # ---------- 剪贴板 ----------
    def read_clipboard_text(self):
        return self._read_clipboard_from_commands([
            ('wl-paste', '--no-newline'),
            ('xclip', '-selection', 'clipboard', '-o'),
            ('xsel', '--clipboard', '--output'),
        ])

    # ---------- 文件管理器 ----------
    def open_directory(self, path, select_path=None):
        import subprocess
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.Popen(['xdg-open', folder])
        return {'ok': True}

    # ---------- PDF ----------
    def supports_pdf_export(self):
        try:
            self._gtk_modules()
            return True
        except Exception:
            return False

    @staticmethod
    def _gtk_modules():
        """返回 (Gtk, GLib, webkit)，优先复用 pywebview 已加载的 WebKit2。"""
        from gi.repository import GLib, Gtk
        try:
            from webview.platforms import gtk as gtk_backend
            webkit = getattr(gtk_backend, 'webkit', None)
        except Exception:
            webkit = None
        if webkit is None:
            import gi
            for version in ('4.1', '4.0'):
                try:
                    gi.require_version('WebKit2', version)
                    break
                except Exception:
                    continue
            from gi.repository import WebKit2 as webkit
        return Gtk, GLib, webkit

    @staticmethod
    def _webkit_webview(window):
        gui = getattr(window, 'gui', None)
        wv = getattr(gui, 'webview', None)
        if wv is None:
            native = getattr(window, 'native', None)
            wv = getattr(native, 'webview', None)
        if wv is None:
            native = getattr(window, 'native', None)
            try:
                child = native.get_child() if native is not None else None
                while child is not None:
                    if hasattr(child, 'evaluate_javascript'):
                        wv = child
                        break
                    child = child.get_child() if hasattr(child, 'get_child') \
                        else None
            except Exception:
                pass
        return wv

    def export_pdf(self, window, pdf_path):
        try:
            Gtk, GLib, webkit = self._gtk_modules()
        except Exception as e:
            return {'ok': False,
                    'error': f'缺少 GTK / WebKit2 依赖，无法导出 PDF: {e}'}

        wv = self._webkit_webview(window)
        if wv is None:
            return {'ok': False, 'error': '无法获取 WebKit2 WebView'}

        parent = getattr(window, 'native', None)
        holder = {}
        done = threading.Event()

        def _do_export():
            try:
                op = webkit.PrintOperation.new(wv)
                try:
                    op.set_show_progress(False)
                except Exception:
                    pass

                # 与 Windows PrintToPdfAsync 默认一致：Letter + 0.4 inch
                paper = Gtk.PaperSize.new_custom(
                    'na_letter', 'Letter', 612, 792, Gtk.Unit.POINTS)
                setup = Gtk.PageSetup()
                setup.set_paper_size(paper)
                setup.set_top_margin(0.4, Gtk.Unit.INCH)
                setup.set_bottom_margin(0.4, Gtk.Unit.INCH)
                setup.set_left_margin(0.4, Gtk.Unit.INCH)
                setup.set_right_margin(0.4, Gtk.Unit.INCH)
                try:
                    op.set_page_setup(setup)
                except Exception:
                    try:
                        op.set_default_page_setup(setup)
                    except Exception:
                        pass

                # WebKit2.PrintOperation 不是 Gtk.PrintOperation 子类，没有
                # set_export_file；用 GTK 的 “Print to File” 打印机导出 PDF。
                from urllib.parse import quote
                settings = Gtk.PrintSettings()
                try:
                    settings.set_printer('Print to File')
                except Exception:
                    pass
                settings.set('output-file-format', 'pdf')
                settings.set('output-uri', 'file://' + quote(pdf_path))
                op.set_print_settings(settings)

                def _on_finished(*_args):
                    done.set()

                def _on_failed(_op, error):
                    holder['error'] = error
                    done.set()

                try:
                    op.connect('finished', _on_finished)
                    op.connect('failed', _on_failed)
                except Exception:
                    pass

                op.print_()

                # 某些 GTK 版本不会发 finished 信号，轮询目标文件兜底
                def _watch_file():
                    for _ in range(600):
                        if done.is_set():
                            return
                        try:
                            if (os.path.exists(pdf_path) and
                                    os.path.getsize(pdf_path) > 100):
                                done.set()
                                return
                        except Exception:
                            pass
                        time.sleep(0.1)
                    done.set()

                threading.Thread(target=_watch_file, daemon=True,
                                 name='MarkEasePdfWatch').start()
            except Exception as e:
                holder['error'] = e
                done.set()
            return False

        try:
            GLib.idle_add(_do_export)
        except Exception as e:
            return {'ok': False, 'error': f'GTK 主线程调度失败: {e}'}

        if not done.wait(180):
            return {'ok': False, 'error': '导出 PDF 超时（180 秒）'}

        if holder.get('error') is not None:
            return {'ok': False, 'error': str(holder['error'])}
        if not os.path.exists(pdf_path):
            return {'ok': False, 'error': '未生成 PDF 文件'}
        try:
            with open(pdf_path, 'rb') as f:
                if f.read(5) != b'%PDF-':
                    return {'ok': False, 'error': 'WebKit2 未输出有效 PDF'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        return {'ok': True}

    # ---------- 文件关联（.desktop + xdg-mime） ----------
    def _applications_dir(self):
        data_home = os.environ.get('XDG_DATA_HOME') or \
            os.path.join(os.path.expanduser('~'), '.local', 'share')
        return os.path.join(data_home, 'applications')

    def _icon_install_path(self):
        data_home = os.environ.get('XDG_DATA_HOME') or \
            os.path.join(os.path.expanduser('~'), '.local', 'share')
        return os.path.join(data_home, 'icons', 'hicolor', '256x256',
                            'apps', 'markease.png')

    def _exec_command(self):
        if getattr(sys, 'frozen', False):
            return sys.executable
        main_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), 'main.py')
        return f'{sys.executable} "{main_py}"'

    def ensure_desktop_entry(self):
        """写入用户级 .desktop 与图标（不修改默认程序）。"""
        try:
            apps_dir = self._applications_dir()
            os.makedirs(apps_dir, exist_ok=True)

            icon_path = self.get_icon_path(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))))
            icon_installed = ''
            if icon_path and os.path.isfile(icon_path):
                target = self._icon_install_path()
                os.makedirs(os.path.dirname(target), exist_ok=True)
                try:
                    shutil.copyfile(icon_path, target)
                    icon_installed = target
                except Exception:
                    icon_installed = ''

            icon_value = icon_installed or 'markease'
            content = (
                '[Desktop Entry]\n'
                'Type=Application\n'
                'Name=MarkEase\n'
                'GenericName=Markdown Editor\n'
                'Comment=Markdown editor with WYSIWYG preview\n'
                f'Exec={self._exec_command()} %f\n'
                f'Icon={icon_value}\n'
                'Terminal=false\n'
                'Categories=Office;TextEditor;\n'
                'MimeType=text/markdown;text/x-markdown;\n'
                'Keywords=markdown;editor;notes;\n'
                'StartupWMClass=MarkEase\n'
            )
            path = os.path.join(apps_dir, DESKTOP_FILE_NAME)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            try:
                os.chmod(path, 0o644)
            except Exception:
                pass

            # 刷新桌面数据库（命令不存在就跳过）
            for cmd in (['update-desktop-database', apps_dir],
                        ['gtk-update-icon-cache', '-f', '-t',
                         os.path.join(os.path.dirname(os.path.dirname(
                             os.path.dirname(self._icon_install_path()))))]):
                if shutil.which(cmd[0]):
                    try:
                        import subprocess
                        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=10)
                    except Exception:
                        pass

            return {'ok': True, 'path': path, 'icon': icon_installed}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def setup_file_associations_on_first_run(self):
        # 只在打包版自动写桌面条目；源码运行时跳过，避免污染开发机
        if not getattr(sys, 'frozen', False):
            return {'ok': False, 'skipped': True, 'reason': 'not frozen'}
        return self.ensure_desktop_entry()

    def register_shell_new(self):
        result = self.ensure_desktop_entry()
        if result.get('ok'):
            result['name'] = 'MarkEase'
        return result

    def set_as_default_program(self):
        result = self.ensure_desktop_entry()
        if not result.get('ok'):
            return result
        xdg_mime = shutil.which('xdg-mime')
        if not xdg_mime:
            return {'ok': False, 'error': '未找到 xdg-mime（请安装 xdg-utils）'}
        try:
            import subprocess
            for mime in ('text/markdown', 'text/x-markdown'):
                subprocess.run([xdg_mime, 'default', DESKTOP_FILE_NAME, mime],
                               check=True, timeout=15)
            return {'ok': True, 'progid': DESKTOP_FILE_NAME,
                    'exe': sys.executable}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def is_default_program(self):
        xdg_mime = shutil.which('xdg-mime')
        if not xdg_mime:
            return False
        try:
            import subprocess
            out = subprocess.run(
                [xdg_mime, 'query', 'default', 'text/markdown'],
                stdout=subprocess.PIPE, timeout=10)
            return out.stdout.decode('utf-8', 'replace').strip() == \
                DESKTOP_FILE_NAME
        except Exception:
            return False

    def get_default_program_name(self):
        return 'Markdown 文件'
