# -*- coding: utf-8 -*-
"""
MarkEase 主入口（阶段 15 修订：修复启动缓存导致的偶发空白问题）

- 忽略系统 VPN 对 127.0.0.1 的代理
- 禁用 WebView2 后台网络/组件更新/同步（降低 360「BITS 任务」告警概率）
- 前端从 asset server 的 HTTP 地址加载
- background_color 依据主题
- 支持双击 .md / .markdown / .pdf 启动（命令行参数）
- ★ 修复：显式指定 WebView2 user data folder，避免 pywebview 内部
        "删除失败 → 复用旧缓存" 导致的偶发空白
- ★ v2.1.1：closing 事件异步通知前端（避免 WebView2 死锁）
- ★ v2.1.1：新增看门狗，窗口未响应超时 → 强制退出
- ★ v2.1.2：新增日志系统（app/logging_setup.py），仅错误/崩溃落盘
"""

import os
import sys
import re
import time
import threading
import ctypes

# ============================================================
#  ★ v2.1.2：日志系统必须在最早期初始化
#     - faulthandler 需在解释器可能崩溃前开启
#     - sys.excepthook / threading.excepthook 需尽早安装
# ============================================================
try:
    from app import logging_setup
except Exception as _logging_import_err:
    logging_setup = None
    _LOGGING_IMPORT_ERROR = _logging_import_err
else:
    _LOGGING_IMPORT_ERROR = None


def _read_version_from_version_info():
    """
    从 version_info.txt 读取版本号（与 app/api.py 保持一致的解析逻辑）。
    读取失败返回 '0.0.0'。
    """
    try:
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        vi_path = os.path.join(base, 'version_info.txt')
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


# 前端 BUILD_TAG（与 web/js/render.js 保持一致；仅作日志标识）
_RENDER_BUILD_TAG = 'render-v23'


def _init_logging_early():
    """
    最早的日志初始化。放在 import webview 之前。
    """
    if logging_setup is None:
        # 回退：直接 print，至少终端能看到
        try:
            print('[MarkEase] logging_setup import failed: %s'
                  % _LOGGING_IMPORT_ERROR)
        except Exception:
            pass
        return None
    try:
        version = _read_version_from_version_info()
        log_dir = logging_setup.setup_logging(
            version=version, build_tag=_RENDER_BUILD_TAG)
        if log_dir:
            try:
                print('[MarkEase] log dir: %s' % log_dir)
            except Exception:
                pass
        else:
            try:
                print('[MarkEase] log dir unavailable, logging disabled')
            except Exception:
                pass
        return log_dir
    except Exception as e:
        try:
            print('[MarkEase] setup_logging failed: %s' % e)
        except Exception:
            pass
        return None


def _log_event(event, message=None, **context):
    """轻量封装：仅入内存环形缓冲。"""
    if logging_setup is None:
        return
    try:
        logging_setup.record_event(event, message=message, **context)
    except Exception:
        pass


def _log_error(event, message=None, exception=None, **context):
    """写 ERROR 到磁盘。"""
    if logging_setup is None:
        return
    try:
        logging_setup.log_error(event, message=message,
                                exception=exception, **context)
    except Exception:
        pass


def _log_critical(event, message=None, exception=None, **context):
    """写 CRITICAL 到磁盘，并 flush stdout/stderr。"""
    if logging_setup is None:
        return
    try:
        logging_setup.log_critical(event, message=message,
                                   exception=exception, **context)
    except Exception:
        pass


# 早期初始化（在 import webview 之前完成）
_LOG_DIR = _init_logging_early()
_log_event('app_boot_start',
           'MarkEase main entry reached; before importing webview',
           log_dir=str(_LOG_DIR) if _LOG_DIR else '')


# ★★★ 必须在 import webview 之前设置 ★★★

# ------------------------------------------------------------------
# 1) 显式指定 WebView2 user data folder（稳定路径，避免缓存冲突）
#
#    背景：pywebview 每次 webview.start() 会创建一个临时 user data folder，
#         退出时尝试删除。若删除失败（如 BrowserProcess 提前退出），
#         下次启动可能复用一个"半旧"的 folder，导致 JS 缓存与磁盘上的
#         app.js 不一致 → 打开文档时白屏。
#
#    解决：显式指定到一个固定路径，让 WebView2 始终用同一个 folder，
#         并让缓存自然老化（浏览器会自动淘汰）。
# ------------------------------------------------------------------
_USER_DATA_DIR = os.path.join(
    os.path.expanduser('~'), '.markease', 'webview2_data'
)
try:
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = _USER_DATA_DIR
    print(f'[MarkEase] webview2 user data: {_USER_DATA_DIR}')
    _log_event('webview2_user_data_set', 'WEBVIEW2_USER_DATA_FOLDER set',
               path=_USER_DATA_DIR)
except Exception as e:
    print(f'[MarkEase] cannot create user data dir: {e}')
    _log_error('webview2_user_data_failed',
               'Failed to create webview2 user data dir',
               exception=e, path=_USER_DATA_DIR)

# ------------------------------------------------------------------
# 2) 反 360 / VPN 绕过参数
# ------------------------------------------------------------------
_existing = os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '')

_EXTRA_ARGS = [
    '--proxy-bypass-list="127.0.0.1;localhost;<local>"',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-sync',
    '--disable-default-apps',
    '--disable-client-side-phishing-detection',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-features=Translate,OptimizationHints,MediaRouter,msEdgeUpdateCheck',
    # ★ 关键：关闭 HTTP 磁盘缓存（开发期必开；发布后可去掉以加快启动）
    #   若你希望保留缓存（加快启动），注释掉下面这一行即可
    '--disk-cache-size=1',
]

for _arg in _EXTRA_ARGS:
    _flag = _arg.split('=')[0]
    if _flag not in _existing:
        _existing = (_existing + ' ' if _existing else '') + _arg

os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = _existing
_log_event('webview2_args_set',
           'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS configured',
           args=_existing)


try:
    import webview
except Exception as _webview_import_err:
    _log_critical('webview_import_failed',
                  'Failed to import pywebview',
                  exception=_webview_import_err)
    raise


def get_base_dir():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_web_dir():
    return os.path.join(get_base_dir(), 'web')


def get_icon_path():
    path = os.path.join(get_base_dir(), 'resources', 'icons', '图标.ico')
    if os.path.exists(path):
        return path
    fallback = os.path.join(get_base_dir(), 'resources', 'icons', 'icon.ico')
    if os.path.exists(fallback):
        return fallback
    return None


def _bg_for_theme(theme):
    if theme == 'dark':
        return '#1e1e1e'
    return '#f7f7f7'


def _parse_startup_file():
    """
    从命令行参数中提取待打开的文件路径。

    场景：
      - 双击 .md 文件 → Windows 调用 MarkEase.exe "D:\\path\\file.md"
      - 用户命令行手输 → python main.py "D:\\path\\file.md"

    规则：
      - 跳过以 -- 开头的参数（pywebview 内部参数等）
      - 只取第一个存在的文件
      - 支持的扩展名：.md / .markdown / .txt / .pdf（其他也接受，交由前端判断）
    """
    if len(sys.argv) < 2:
        return ''

    for arg in sys.argv[1:]:
        if not arg or arg.startswith('--'):
            continue
        try:
            p = os.path.abspath(arg)
        except Exception:
            continue
        if os.path.isfile(p):
            return p
    return ''


# ============================================================
#  看门狗：监控主窗口是否"未响应"
#  连续 timeout_sec 秒未响应 → 强制退出进程，让用户可以重启
# ============================================================
def _start_hang_watchdog(window, timeout_sec=10, check_interval=2):
    if sys.platform != 'win32':
        _log_event('watchdog_skipped',
                   'Watchdog only runs on win32',
                   platform=sys.platform)
        return

    def _resolve_hwnd():
        try:
            native = window.native
            if native is not None and hasattr(native, 'Handle'):
                return int(native.Handle)
        except Exception:
            pass
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, 'MarkEase')
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
        _log_event('watchdog_started',
                   'Watchdog monitoring started',
                   hwnd=hwnd,
                   timeout_sec=timeout_sec,
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

                    # ★ v2.1.2：强制退出前写 CRITICAL 日志
                    _log_critical(
                        'watchdog_timeout_force_exit',
                        'Main window did not respond within timeout; '
                        'forcing process exit.',
                        hwnd=hwnd,
                        timeout_sec=timeout_sec,
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


def main():
    _log_event('main_enter', 'main() started',
               argv_count=len(sys.argv))

    web_dir = get_web_dir()
    index_path = os.path.join(web_dir, 'index.html')
    if not os.path.exists(index_path):
        print(f"错误：找不到 {index_path}")
        _log_critical('index_html_missing',
                      'web/index.html not found; cannot start',
                      index_path=index_path,
                      web_dir=web_dir)
        sys.exit(1)

    _log_event('web_dir_resolved', 'web directory resolved',
               web_dir=web_dir)

    try:
        from app.api import Api
    except Exception as e:
        _log_critical('api_import_failed',
                      'Failed to import app.api.Api',
                      exception=e)
        raise

    try:
        api = Api(web_dir)
    except Exception as e:
        _log_critical('api_init_failed',
                      'Failed to construct Api instance',
                      exception=e)
        raise

    # 解析命令行传入的文件（双击 .md 场景）
    startup_file = _parse_startup_file()
    if startup_file:
        print(f'[MarkEase] startup file: {startup_file}')
        _log_event('startup_file_detected',
                   'Startup file parsed from argv',
                   path=startup_file)
        try:
            api.set_startup_file(startup_file)
        except Exception as e:
            print(f'[MarkEase] set_startup_file failed: {e}')
            _log_error('startup_file_set_failed',
                       'api.set_startup_file raised',
                       exception=e, path=startup_file)

    try:
        theme = api._settings.get('theme', 'system')
    except Exception as e:
        theme = 'system'
        _log_error('theme_read_failed',
                   'Failed to read theme from settings',
                   exception=e)
    bg = _bg_for_theme(theme)

    url = f'http://127.0.0.1:{api._asset_port}/web/index.html'
    _log_event('asset_url_ready', 'asset server URL ready',
               url=url, port=api._asset_port)

    kwargs = dict(
        title='MarkEase',
        url=url,
        js_api=api,
        width=1200,
        height=800,
        min_size=(800, 600),
    )

    try:
        window = webview.create_window(background_color=bg, **kwargs)
    except TypeError:
        _log_event('create_window_retry',
                   'background_color kwarg not supported; retrying without it')
        try:
            window = webview.create_window(**kwargs)
        except Exception as e:
            _log_critical('create_window_failed',
                          'webview.create_window failed',
                          exception=e)
            raise
    except Exception as e:
        _log_critical('create_window_failed',
                      'webview.create_window failed',
                      exception=e)
        raise

    api.set_window(window)
    _log_event('window_created', 'pywebview window created')

    def on_closing():
        # ★ 修复死锁：不能在 closing 回调里同步调用 evaluate_js。
        #   改用独立线程 + 小延迟异步通知前端弹窗。
        try:
            if api._force_close:
                _log_event('closing_force',
                           'closing event: force_close=True; allow')
                return True
            if api._is_dirty:
                _log_event('closing_dirty',
                           'closing event: dirty=True; asking frontend')

                def _notify_frontend():
                    # 等主线程从 closing 回调返回后再通知前端
                    time.sleep(0.1)
                    try:
                        window.evaluate_js(
                            'window.onCloseRequested && window.onCloseRequested()'
                        )
                    except Exception as e:
                        print(f'[MarkEase] onCloseRequested failed: {e}')
                        _log_error('on_close_requested_failed',
                                   'window.evaluate_js raised in '
                                   'notify thread',
                                   exception=e)

                t = threading.Thread(target=_notify_frontend, daemon=True)
                t.start()
                return False  # 取消本次关闭
            _log_event('closing_clean',
                       'closing event: clean state; allow')
        except Exception as e:
            print(f'[MarkEase] on_closing error: {e}')
            _log_error('on_closing_error',
                       'Unexpected error inside on_closing',
                       exception=e)
        return True

    def on_closed():
        _log_event('window_closed', 'Window closed event received')
        try:
            api.close_all_pickers()
        except Exception as e:
            _log_error('close_pickers_failed',
                       'api.close_all_pickers raised',
                       exception=e)
        try:
            api._asset_server.stop()
        except Exception as e:
            _log_error('asset_server_stop_failed',
                       'api._asset_server.stop raised',
                       exception=e)

    window.events.closing += on_closing
    window.events.closed += on_closed

    # ★ 启动看门狗：窗口未响应超时 → 强制退出
    try:
        _start_hang_watchdog(window, timeout_sec=10, check_interval=2)
    except Exception as e:
        print('[MarkEase][watchdog] 启动失败: %s' % e)
        _log_error('watchdog_start_failed',
                   'Failed to start hang watchdog',
                   exception=e)

    icon_path = get_icon_path()
    if icon_path:
        print(f'[MarkEase] icon: {icon_path}')
    print(f'[MarkEase] url: {url}')

    _log_event('webview_start_called', 'Calling webview.start()',
               gui='edgechromium', debug=False,
               has_icon=bool(icon_path))

    try:
        webview.start(
            gui='edgechromium',
            debug=False,
            icon=icon_path if icon_path else None,
        )
    except Exception as e:
        _log_critical('webview_start_failed',
                      'webview.start raised',
                      exception=e)
        raise

    _log_event('webview_start_returned',
               'webview.start returned; main() is exiting')


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        # 顶层兜底：任何未捕获异常都写 CRITICAL
        try:
            _log_critical('main_unhandled_exception',
                          'Unhandled exception escaped main()',
                          exception=e)
        except Exception:
            pass
        raise