# -*- coding: utf-8 -*-
"""用本机 Chrome / Chromium 无头模式把预览 HTML 打印成 PDF。

Linux 的 WebKit2.PrintOperation 不是 Gtk.PrintOperation 子类，无法
set_export_file；macOS 的 NSPrintOperation 在部分版本会卡在保存面板。
统一改为：把预览 DOM 导出成自包含 HTML，再交给 Chrome/Chromium 打印。
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time


_BROWSER_NAMES = (
    'google-chrome',
    'google-chrome-stable',
    'chromium',
    'chromium-browser',
    'microsoft-edge',
    'microsoft-edge-stable',
    'brave-browser',
)

_MAC_BROWSERS = (
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
)


def find_browser():
    for name in _BROWSER_NAMES:
        path = shutil.which(name)
        if path:
            return path
    for path in _MAC_BROWSERS:
        if os.path.isfile(path):
            return path
    return None


def export_with_browser(window, pdf_path, app_root):
    """返回 True 表示已写出 PDF；False 表示没有可用浏览器/打印失败。"""
    browser = find_browser()
    if not browser:
        print('[MarkEase][pdf] no Chrome/Chromium found')
        return False

    try:
        html = window.evaluate_js(
            "(document.getElementById('preview') || {}).innerHTML || ''")
    except Exception as e:
        print(f'[MarkEase][pdf] read preview HTML failed: {e}')
        return False
    if not html:
        return False

    try:
        from converters.html_exporter import export_html
    except Exception as e:
        print(f'[MarkEase][pdf] html exporter unavailable: {e}')
        return False

    work = tempfile.mkdtemp(prefix='markease_pdf_')
    html_path = os.path.join(work, 'print.html')
    try:
        result = export_html(html, '', html_path, title='MarkEase',
                             doc_dir='', app_root=app_root)
        if not (result and result.get('ok')):
            print(f'[MarkEase][pdf] export_html failed: {result}')
            return False

        url = 'file://' + html_path.replace('\\', '/')
        profile = os.path.join(work, 'profile')

        def _run_headless(headless):
            args = [
                browser,
                headless,
                '--disable-gpu',
                '--no-pdf-header-footer',
                '--user-data-dir=' + profile,
                '--print-to-pdf=' + pdf_path,
                url,
            ]
            try:
                proc = subprocess.Popen(
                    args, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
            except Exception as e:
                print(f'[MarkEase][pdf] browser launch failed: {e}')
                return False

            deadline = time.time() + 30.0
            last_size = -1
            stable = 0
            try:
                while time.time() < deadline:
                    if os.path.exists(pdf_path):
                        size = os.path.getsize(pdf_path)
                        if size > 100:
                            stable = stable + 1 if size == last_size else 0
                            last_size = size
                            if stable >= 2:
                                return True
                    if proc.poll() is not None:
                        break
                    time.sleep(0.2)
                return (os.path.exists(pdf_path) and
                        os.path.getsize(pdf_path) > 100)
            finally:
                if proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except Exception:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except Exception:
                            pass

        for headless in ('--headless=new', '--headless'):
            if _run_headless(headless):
                print(f'[MarkEase][pdf] browser wrote PDF ({headless}): '
                      f'{pdf_path}')
                return True
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass
        print('[MarkEase][pdf] browser did not write PDF')
        return False
    except Exception as e:
        print(f'[MarkEase][pdf] browser export failed: {e}')
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def app_root():
    root = getattr(sys, '_MEIPASS', None)
    if root:
        return root
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
