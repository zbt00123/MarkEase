# -*- coding: utf-8 -*-
"""
MarkEase Windows 平台实现。

这里只放"Windows 与其它系统做法不同"的代码：
- WebView2 用户数据目录 / 浏览器参数（必须在 import webview 之前设置）
- 窗口未响应看门狗（user32.IsHungAppWindow）
- Win32 剪贴板读取（CF_UNICODETEXT）
- PDF 导出（CoreWebView2.PrintToPdfAsync + pythonnet）
- 文件关联（winreg，委托 app/file_assoc.py）
- 文件管理器定位（explorer /select,）

★ 本模块只在 Windows 上被 import；macOS / Linux 不得依赖 pythonnet / winreg。
★ WebView2 进程崩溃自恢复仍在 main.py（v2.1.6 已稳定，暂不搬动）。
"""

import os
import re
import sys
import time
import ctypes
import shutil
import threading

from app import logging_setup as _logging

from .base import PlatformBase


# ============================================================
#  日志薄封装（语义与 main.py 的 _log_event / _log_error 一致）
# ============================================================
def _log_event(event, message=None, **context):
    if _logging is None:
        return
    try:
        _logging.record_event(event, message=message, **context)
    except Exception:
        pass


def _log_error(event, message=None, exception=None, **context):
    if _logging is None:
        return
    try:
        _logging.log_error(event, message=message,
                           exception=exception, **context)
    except Exception:
        pass


def _log_critical(event, message=None, exception=None, **context):
    if _logging is None:
        return
    try:
        _logging.log_critical(event, message=message,
                              exception=exception, **context)
    except Exception:
        pass


# ============================================================
#  WebView2 用户数据目录
#
#  背景（"打包后窗口空白"的根因，两层叠加）：
#    a) pywebview 在私有模式下把 WebView2 配置目录设为
#       tempfile.TemporaryDirectory()。若进程无法写 %TEMP%，
#       pywebview 会静默把 cache_dir 留成 None。
#    b) WebView2 回退到环境变量 / 默认目录；若该目录来自上次崩溃残留，
#       残留的 EBWebView 档案带锁，初始化直接抛 0x800700AA，窗口永久空白。
#
#  解决：
#    - 按优先级探测"确实可写"的目录；
#    - 每次启动用 run-<pid> 独立子目录，启动前清理已退出进程的残留；
#    - 同时设置 WEBVIEW2_USER_DATA_FOLDER 并传给 webview.start(storage_path=...)。
# ============================================================
_USER_DATA_DIR = None


def _pid_alive(pid):
    """判断 PID 是否仍存活（用于清理残留 profile）。"""
    try:
        import psutil
        return bool(psutil.pid_exists(pid))
    except Exception:
        pass
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return True  # 判断不了就保守处理，不删


def _is_writable_dir(path):
    """能否在 path 下创建目录并写入文件。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, '.mk_write_test')
        with open(probe, 'wb') as f:
            f.write(b'ok')
        os.remove(probe)
        return True
    except Exception:
        return False


def _webview_profile_bases():
    """按优先级返回候选 profile 根目录（第一个可写的会被采用）。"""
    bases = []

    # 1) 程序目录（仅打包版：受限环境里往往只有这里可写）
    try:
        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(os.path.abspath(sys.executable))
            bases.append(os.path.join(app_dir, 'webview2'))
    except Exception:
        pass

    # 2) Windows 用户本地数据
    local = os.environ.get('LOCALAPPDATA')
    if local:
        bases.append(os.path.join(local, 'MarkEase', 'webview2'))

    # 3) 用户目录（与 settings.json 同级的 .markease）
    try:
        bases.append(os.path.join(os.path.expanduser('~'), '.markease',
                                  'webview2'))
    except Exception:
        pass

    # 4) 临时目录（最后兜底）
    tmp = os.environ.get('TEMP') or os.environ.get('TMP')
    if tmp:
        bases.append(os.path.join(tmp, 'MarkEase', 'webview2'))

    return bases


def _prepare_webview_user_data_dir():
    """创建本次启动专用的 WebView2 目录，并清理已退出进程的残留目录。"""
    base = None
    for candidate in _webview_profile_bases():
        if _is_writable_dir(candidate):
            base = candidate
            break
    if base is None:
        print('[MarkEase] no writable webview2 profile dir found')
        return None

    try:
        for name in os.listdir(base):
            m = re.match(r'^run-(\d+)$', name)
            if not m:
                continue
            pid = int(m.group(1))
            if pid == os.getpid() or _pid_alive(pid):
                continue
            try:
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass

    run_dir = os.path.join(base, 'run-%d' % os.getpid())
    if not _is_writable_dir(run_dir):
        print(f'[MarkEase] cannot create webview2 run dir: {run_dir}')
        return None
    return run_dir


_EXTRA_BROWSER_ARGS = [
    '--proxy-bypass-list="127.0.0.1;localhost;<local>"',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-sync',
    '--disable-default-apps',
    '--disable-client-side-phishing-detection',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-features=Translate,OptimizationHints,MediaRouter,msEdgeUpdateCheck',
    # ★ 关闭 HTTP 磁盘缓存（开发期必开；发布后可去掉以加快启动）
    '--disk-cache-size=1',
]


def _setup_windows_webview_env():
    """设置 WEBVIEW2_USER_DATA_FOLDER / WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS。

    ★ 必须在 ``import webview`` 之前调用（main.py 已保证）。
    """
    global _USER_DATA_DIR

    _USER_DATA_DIR = _prepare_webview_user_data_dir()
    try:
        if _USER_DATA_DIR:
            os.environ['WEBVIEW2_USER_DATA_FOLDER'] = _USER_DATA_DIR
            print(f'[MarkEase] webview2 user data: {_USER_DATA_DIR}')
            _log_event('webview2_user_data_set',
                       'WEBVIEW2_USER_DATA_FOLDER set',
                       path=_USER_DATA_DIR)
        else:
            _log_error('webview2_user_data_unavailable',
                       'No writable WebView2 profile dir; relying on defaults')
    except Exception as e:
        print(f'[MarkEase] cannot set user data dir: {e}')
        _log_error('webview2_user_data_failed',
                   'Failed to set webview2 user data dir',
                   exception=e, path=_USER_DATA_DIR)

    existing = os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '')
    for arg in _EXTRA_BROWSER_ARGS:
        flag = arg.split('=')[0]
        if flag not in existing:
            existing = (existing + ' ' if existing else '') + arg
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = existing
    _log_event('webview2_args_set',
               'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS configured',
               args=existing)
    return _USER_DATA_DIR


# ============================================================
#  剪贴板：CF_UNICODETEXT
#  WebView2 下 document.execCommand('paste') 会被 Chromium 直接拒绝，
#  navigator.clipboard.readText() 又依赖 clipboard-read 权限，均不可靠。
# ============================================================
def _read_clipboard_text_windows():
    """读取 Windows 剪贴板中的 Unicode 文本（CF_UNICODETEXT）。"""
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    CF_UNICODETEXT = 13

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    last_error = None
    opened = False
    for _ in range(6):
        if user32.OpenClipboard(None):
            opened = True
            break
        last_error = ctypes.get_last_error()
        time.sleep(0.05)

    if not opened:
        raise OSError(
            '无法打开系统剪贴板（可能被其他程序占用）'
            + (f'，错误码 {last_error}' if last_error else '')
        )

    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ''

        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ''

        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ''
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


# ============================================================
#  看门狗：窗口连续 timeout_sec 秒未响应 → 强制退出
# ============================================================
def start_hang_watchdog(window, timeout_sec=10, check_interval=2):
    def _resolve_hwnd():
        try:
            native = window.native
            if native is not None and hasattr(native, 'Handle'):
                return int(native.Handle)
        except Exception:
            pass
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, 'MarkEase')
            return int(hwnd) if hwnd else 0
        except Exception:
            return 0

    def _watch():
        try:
            user32 = ctypes.windll.user32
        except Exception as e:
            _log_error('watchdog_user32_failed',
                       'Failed to load user32',
                       exception=e)
            return

        hwnd = 0
        for _ in range(30):
            hwnd = _resolve_hwnd()
            if hwnd:
                break
            time.sleep(1)

        if not hwnd:
            print('[MarkEase][watchdog] 未找到主窗口，看门狗退出')
            _log_event('watchdog_no_window',
                       'Watchdog could not find main window; exiting thread')
            return

        print('[MarkEase][watchdog] 开始监控 hwnd=%s timeout=%ss interval=%ss'
              % (hwnd, timeout_sec, check_interval))
        _log_event('watchdog_started', 'Watchdog monitoring started',
                   hwnd=hwnd, timeout_sec=timeout_sec,
                   check_interval=check_interval)

        hung_since = None
        while True:
            time.sleep(check_interval)
            try:
                is_hung = bool(user32.IsHungAppWindow(hwnd))
            except Exception as e:
                _log_error('watchdog_is_hung_check_failed',
                           'IsHungAppWindow raised',
                           exception=e, hwnd=hwnd)
                is_hung = False

            if is_hung:
                if hung_since is None:
                    hung_since = time.time()
                    print('[MarkEase][watchdog] 检测到窗口未响应，开始计时')
                    _log_event('watchdog_hung_detected',
                               'Window is not responding; starting timer',
                               hwnd=hwnd)
                elif time.time() - hung_since >= timeout_sec:
                    elapsed = time.time() - hung_since
                    print('[MarkEase][watchdog] 窗口未响应超过 %ss，强制退出'
                          % timeout_sec)
                    _log_critical(
                        'watchdog_timeout_force_exit',
                        'Main window did not respond within timeout; '
                        'forcing process exit.',
                        hwnd=hwnd, timeout_sec=timeout_sec,
                        check_interval=check_interval,
                        hung_duration_sec=round(elapsed, 3),
                        action='os._exit(1)',
                    )
                    try:
                        sys.stdout.flush()
                        sys.stderr.flush()
                    except Exception:
                        pass
                    os._exit(1)
            else:
                if hung_since is not None:
                    print('[MarkEase][watchdog] 窗口已恢复响应')
                    _log_event('watchdog_recovered',
                               'Window recovered; resetting hung timer',
                               hwnd=hwnd)
                hung_since = None

    t = threading.Thread(target=_watch, daemon=True, name='MarkEaseWatchdog')
    t.start()
    print('[MarkEase][watchdog] 看门狗线程已启动')
    _log_event('watchdog_thread_started',
               'Watchdog daemon thread started',
               thread_name='MarkEaseWatchdog')


class WindowsPlatform(PlatformBase):
    name = 'Windows'
    is_windows = True

    # ---------- 启动 / 窗口 ----------
    def prepare_webview_env(self):
        try:
            self._storage_path = _setup_windows_webview_env()
        except Exception as e:
            print(f'[MarkEase] prepare_webview_env failed: {e}')
            _log_error('webview_env_failed',
                       'prepare_webview_env raised',
                       exception=e)
            self._storage_path = None
        return self._storage_path

    def webview_gui(self):
        return 'edgechromium'

    def get_icon_path(self, base_dir):
        for name in ('图标.ico', 'icon.ico'):
            path = os.path.join(base_dir, 'resources', 'icons', name)
            if os.path.exists(path):
                return path
        return None

    def start_hang_watchdog(self, window):
        try:
            start_hang_watchdog(window)
        except Exception as e:
            print('[MarkEase][watchdog] 启动失败: %s' % e)
            _log_error('watchdog_start_failed',
                       'Failed to start hang watchdog',
                       exception=e)

    # ---------- 剪贴板 ----------
    def read_clipboard_text(self):
        return _read_clipboard_text_windows()

    # ---------- 文件管理器 ----------
    def open_directory(self, path, select_path=None):
        import subprocess
        try:
            if select_path and os.path.exists(select_path):
                subprocess.Popen(['explorer', '/select,', select_path])
            else:
                subprocess.Popen(['explorer', path])
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def reveal(self, path):
        path = os.path.abspath(path or '')
        if not os.path.exists(path):
            return {'ok': False, 'error': '文件不存在：' + path}
        return self.open_directory(os.path.dirname(path), select_path=path)

    # ---------- PDF ----------
    def supports_pdf_export(self):
        # ★ 不 import clr：真正的 .NET 初始化只在导出 PDF 时发生。
        #   在受限环境里 import clr 可能直接让进程崩溃，不能用于能力探测。
        import importlib.util
        try:
            return (importlib.util.find_spec('pythonnet') is not None and
                    importlib.util.find_spec('clr') is not None)
        except Exception:
            return False

    def export_pdf(self, window, pdf_path):
        try:
            import clr  # noqa: F401
            import System
        except Exception as e:
            return {'ok': False,
                    'error': f'未安装 pythonnet，无法导出 PDF: {e}'}

        if window is None:
            return {'ok': False, 'error': '窗口未就绪'}

        task_holder = [None]
        error_holder = [None]

        def start_on_ui():
            try:
                native_window = window.native
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
            window.native.Invoke(System.Action(start_on_ui))
        except Exception as e:
            _log_error('pdf_ui_dispatch_failed',
                       'native.Invoke failed', exception=e)
            return {'ok': False, 'error': f'UI 线程调度失败: {e}'}

        if error_holder[0]:
            _log_error('pdf_export_start_failed',
                       'PrintToPdfAsync start failed',
                       message=error_holder[0])
            return {'ok': False, 'error': f'导出启动失败: {error_holder[0]}'}

        task = task_holder[0]
        if task is None:
            return {'ok': False, 'error': '未获取到导出任务'}

        try:
            task.Wait()
        except Exception as e:
            _log_error('pdf_export_wait_failed',
                       'PrintToPdfAsync task.Wait failed', exception=e)
            return {'ok': False, 'error': f'等待导出失败: {e}'}

        if not os.path.exists(pdf_path):
            return {'ok': False, 'error': '未生成 PDF 文件'}
        return {'ok': True}

    # ---------- 文件关联 ----------
    def setup_file_associations_on_first_run(self):
        try:
            from app import file_assoc
            return file_assoc.setup_shell_new_on_first_run()
        except Exception as e:
            return {'ok': False, 'skipped': True, 'reason': str(e)}

    def register_shell_new(self):
        try:
            from app import file_assoc
            return file_assoc.register_shell_new()
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def set_as_default_program(self):
        try:
            from app import file_assoc
            return file_assoc.set_as_default_program()
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def is_default_program(self):
        try:
            from app import file_assoc
            return bool(file_assoc.is_default_program())
        except Exception:
            return False

    def get_default_program_name(self):
        try:
            from app import file_assoc
            return file_assoc._get_display_name()
        except Exception:
            return 'Markdown File'
