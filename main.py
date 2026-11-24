# -*- coding: utf-8 -*-
"""
MarkEase 主入口（阶段 15 修订：修复启动缓存导致的偶发空白问题）

- 忽略系统 VPN 对 127.0.0.1 的代理
- 禁用 WebView2 后台网络/组件更新/同步（降低 360「BITS 任务」告警概率）
- 前端从 asset server 的 HTTP 地址加载
- background_color 依据主题
- 支持双击 .md / .markdown / .pdf 启动（命令行参数）
- ★ v2.1.3 修订：每次启动使用独立、可写的 WebView2 数据目录
        （修复打包后 WebView2 报 0x800700AA、窗口空白的问题）
- ★ v2.1.1：closing 事件异步通知前端（避免 WebView2 死锁）
- ★ v2.1.1：新增看门狗，窗口未响应超时 → 强制退出
- ★ v2.1.2：新增日志系统（app/logging_setup.py），仅错误/崩溃落盘
- ★ 2026-11-23：WebView2 浏览器进程退出（BrowserProcessExited）后
        自动重建控件并恢复内容，不再整窗永久空白
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

# ★ 平台层：必须在 import webview 之前导入并初始化
#   Windows 会在这里设置 WEBVIEW2_* 环境变量；macOS / Linux 无操作。
from app.platform import platform


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
_RENDER_BUILD_TAG = 'render-v25'


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
#
#   Windows：WebView2 独立用户数据目录 + 反 360 / VPN 绕过参数；
#   macOS  ：WKWebView 自己管理数据目录；
#   Linux  ：WebKit2GTK 自己管理数据目录。
#   具体实现见 app/platform/{win,mac,linux}.py。
#
_USER_DATA_DIR = platform.prepare_webview_env()
if _USER_DATA_DIR:
    print(f'[MarkEase] webview storage: {_USER_DATA_DIR}')


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
    """按平台返回图标：Windows .ico / macOS .icns / Linux .png。"""
    return platform.get_icon_path(get_base_dir())


def _bg_for_theme(theme):
    if theme == 'dark':
        return '#1e1e1e'
    return '#f7f7f7'


def _parse_startup_file():
    """从命令行 / 系统打开事件中取待打开文件（平台相关）。"""
    return platform.parse_startup_file(sys.argv)


# 应用正在关闭时，忽略 WebView2 的进程退出事件（避免退出时误 reload / 误报错误）
_APP_SHUTTING_DOWN = False

# WebView2 进程崩溃恢复状态（模块级持有，避免 handler 被 GC）
_WEBVIEW2_RECOVERY_STATE = {
    'installing': False,
    'installed': False,
    'handler': None,
    'core': None,
    'generation': 0,
    'reloads': [],
    'rebuilds': [],
    'rebuilding': False,
    'rebuild_token': None,
}


def _enum_name(value, default='unknown'):
    """把 pythonnet 枚举转成短名称（'Crashed' 而不是全限定名）。"""
    try:
        if value is None:
            return default
        name = str(value)
        return name.rsplit('.', 1)[-1] or default
    except Exception:
        return default


def _webview2_failure_info(args):
    """
    收集 CoreWebView2ProcessFailedEventArgs 的诊断字段。

    WebView2 SDK 1.0.3856 提供：
      ProcessFailedKind / Reason / ExitCode / ProcessDescription /
      FailureSourceModulePath
    Reason 里 Crashed / Terminated / OutOfMemory / ProfileDeleted 等
    可以直接区分“原生崩溃”“被外部杀掉”“显存/内存不足”“profile 被删”。
    """
    info = {}
    try:
        info['kind'] = _enum_name(getattr(args, 'ProcessFailedKind', None))
    except Exception:
        info['kind'] = 'unknown'

    try:
        reason = getattr(args, 'Reason', None)
        if reason is not None:
            info['reason'] = _enum_name(reason)
    except Exception:
        pass

    try:
        code = getattr(args, 'ExitCode', None)
        if code is not None:
            code = int(code)
            info['exit_code'] = code
            info['exit_code_hex'] = '0x%08X' % (code & 0xFFFFFFFF)
    except Exception:
        pass

    try:
        desc = getattr(args, 'ProcessDescription', None)
        if desc:
            info['process_description'] = str(desc)
    except Exception:
        pass

    try:
        module = getattr(args, 'FailureSourceModulePath', None)
        if module:
            info['failure_source_module_path'] = str(module)
    except Exception:
        pass

    return info


def _show_webview2_fatal_dialog(detail=''):
    """WebView2 无法自动恢复时，用系统弹窗告诉用户怎么做（避免“静默空白”）。"""
    message = (
        '界面渲染组件（WebView2）已崩溃，自动恢复失败。\n\n'
        '请关闭本窗口后重新打开文档。已保存到磁盘的内容不会丢失。\n'
    )
    if detail:
        message += '\n' + str(detail) + '\n'
    try:
        import System.Windows.Forms as WinForms
        WinForms.MessageBox.Show(
            message, 'MarkEase',
            WinForms.MessageBoxButtons.OK,
            WinForms.MessageBoxIcon.Error,
        )
    except Exception:
        pass


def _show_webview2_fatal_dialog_async(detail=''):
    """在独立线程弹窗：ProcessFailed 处理器本身就在 UI 线程上，避免重入。"""
    try:
        threading.Thread(
            target=_show_webview2_fatal_dialog,
            args=(detail,),
            daemon=True,
            name='MarkEaseWebView2FatalDialog',
        ).start()
    except Exception:
        pass


def _read_creation_props(control):
    """读取旧 WebView2 控件的 CreationProperties 关键值（必须在 Dispose 之前调用）。"""
    values = {'args': '', 'exe': '', 'user_data': ''}
    if control is None:
        return values
    try:
        props = control.CreationProperties
    except Exception:
        return values
    try:
        values['args'] = str(props.AdditionalBrowserArguments or '')
    except Exception:
        pass
    try:
        values['exe'] = str(props.BrowserExecutableFolder or '')
    except Exception:
        pass
    try:
        values['user_data'] = str(props.UserDataFolder or '')
    except Exception:
        pass
    return values


def _create_rebuilt_webview2_control(window, old_args='', old_exe='',
                                     old_user_data=''):
    """
    按 pywebview 的初始化方式新建一个 WebView2 控件（必须在 UI 线程调用）。

    注意：同一个进程里 WebView2 会复用已经创建过的环境，
    给新控件换一个 UserDataFolder 实际不生效（实测浏览器进程仍用原 profile，
    新目录只会变成空目录）。因此这里沿用 `_USER_DATA_DIR` 原 profile，
    与 Edge 崩溃后重启浏览器进程的行为一致。
    """
    from Microsoft.Web.WebView2.WinForms import (
        CoreWebView2CreationProperties, WebView2,
    )
    from System.Drawing import Color

    props = CoreWebView2CreationProperties()

    user_data = _USER_DATA_DIR or old_user_data
    if user_data:
        try:
            props.UserDataFolder = user_data
        except Exception as e:
            _log_error('webview2_rebuild_profile_failed',
                       'Cannot set UserDataFolder for rebuilt WebView2',
                       exception=e, path=user_data)

    try:
        import webview as _pywebview
        private_mode = bool(_pywebview._state['private_mode'])
    except Exception:
        private_mode = True
    try:
        props.set_IsInPrivateModeEnabled(private_mode)
    except Exception as e:
        _log_event('webview2_rebuild_private_mode_failed',
                   'Cannot set private mode for rebuilt WebView2',
                   error=str(e))

    browser_args = old_args or '--disable-features=ElasticOverscroll'
    try:
        props.AdditionalBrowserArguments = browser_args
    except Exception as e:
        _log_error('webview2_rebuild_args_failed',
                   'Cannot copy AdditionalBrowserArguments',
                   exception=e)

    if old_exe:
        try:
            props.BrowserExecutableFolder = old_exe
        except Exception:
            pass

    control = WebView2()
    control.CreationProperties = props

    try:
        bg = str(getattr(window, 'background_color', '') or '')
        if len(bg) == 7 and bg.startswith('#'):
            control.DefaultBackgroundColor = Color.FromArgb(
                255, int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16))
    except Exception:
        pass

    return control


def _bind_process_failed_to_core(core):
    """
    给当前 CoreWebView2 绑定一个“这一代”的 ProcessFailed 处理器。

    每次重建都会递增 generation；旧 core 上残留的处理器在收到事件时
    会因 generation 不匹配而直接忽略，避免旧控件 Dispose 时再次触发
    一次多余的控件重建（曾导致 5 分钟内连续重建两次）。
    """
    state = _WEBVIEW2_RECOVERY_STATE
    if core is None:
        return False
    if state.get('core') is core:
        return True

    window = state.get('window')
    api = state.get('api')
    if window is None or api is None:
        return False

    generation = int(state.get('generation', 0)) + 1
    handler = _make_webview2_process_failed_handler(window, api, generation)

    try:
        core.ProcessFailed += handler
        state['core'] = core
        state['handler'] = handler
        state['generation'] = generation
        _log_event('webview2_recovery_bound',
                   'WebView2 ProcessFailed handler bound to core',
                   generation=generation)
        print('[MarkEase][webview2] ProcessFailed handler bound (generation=%d)'
              % generation)
        return True
    except Exception as e:
        _log_error('webview2_recovery_bind_failed',
                   'Failed to bind ProcessFailed to CoreWebView2',
                   exception=e)
        return False


def _rebuild_webview2_on_ui(window, api, reason='unknown'):
    """
    在现有窗口里重建 WebView2 控件。

    BrowserProcessExited 之后 CoreWebView2 已经不可用，Reload() 无法恢复，
    窗口会永久空白（v2.1.4 只记录了日志）。这里换一个新控件、重新挂上
    pywebview 的事件，再导航到同一个 URL；前端启动后会调用
    take_recovery_state() 把后端保存的内容恢复回来。
    """
    state = _WEBVIEW2_RECOVERY_STATE

    try:
        form = window.native
    except Exception:
        form = None

    try:
        if form is None:
            raise RuntimeError('window.native is gone')

        try:
            disposed = bool(form.IsDisposed)
        except Exception:
            disposed = False
        if disposed:
            raise RuntimeError('window is disposed')

        try:
            closed = bool(window.events.closed.is_set())
        except Exception:
            closed = False
        if closed:
            raise RuntimeError('window already closed')

        browser = getattr(form, 'browser', None)
        if browser is None:
            raise RuntimeError('pywebview EdgeChrome is not available')

        old_control = getattr(browser, 'webview', None)
        old_values = _read_creation_props(old_control)

        # 1) 先彻底摘掉、释放已失效的旧控件：
        #    同一进程里 WebView2 会复用已有环境，旧 core / 旧控件必须在本步
        #    释放干净，否则新控件会和“垂死”的旧环境共用同一个浏览器进程，
        #    可能刚恢复就再次 ProcessFailed。
        if old_control is not None:
            try:
                form.Controls.Remove(old_control)
            except Exception:
                pass
            try:
                old_control.Dispose()
            except Exception as e:
                _log_error('webview2_rebuild_old_dispose_failed',
                           'Disposing failed WebView2 control raised',
                           exception=e)
        try:
            state['core'] = None
        except Exception:
            pass

        # 2) 建新控件（沿用原 profile / 浏览器参数）
        new_control = _create_rebuilt_webview2_control(
            window, old_values.get('args', ''), old_values.get('exe', ''),
            old_values.get('user_data', ''))

        # 3) 新控件 + pywebview 的全部事件
        new_control.CoreWebView2InitializationCompleted += browser.on_webview_ready
        new_control.NavigationStarting += browser.on_navigation_start
        new_control.NavigationCompleted += browser.on_navigation_completed
        new_control.WebMessageReceived += browser.on_script_notify

        import System.Windows.Forms as WinForms
        new_control.Dock = WinForms.DockStyle.Fill
        form.Controls.Add(new_control)
        new_control.BringToFront()

        # 4) pywebview / 应用侧持有的引用全部指向新控件
        browser.webview = new_control
        form.webview = new_control

        def _on_init(sender, args):
            ok = False
            try:
                ok = bool(args.IsSuccess)
            except Exception:
                ok = False

            if not ok:
                state['rebuilding'] = False
                try:
                    init_exc = args.InitializationException
                except Exception:
                    init_exc = None
                print('[MarkEase][webview2] rebuilt control failed to initialize')
                _log_critical('webview2_rebuild_init_failed',
                              'Rebuilt WebView2 control failed to initialize',
                              reason=reason,
                              error=str(init_exc) if init_exc else '')
                _show_webview2_fatal_dialog_async(
                    '错误：' + str(init_exc) if init_exc else '')
                return

            try:
                if not _bind_process_failed_to_core(sender.CoreWebView2):
                    print('[MarkEase][webview2] rebuild: ProcessFailed NOT bound')
                    _log_error('webview2_rebuild_bind_not_bound',
                               'ProcessFailed handler was not bound after rebuild',
                               reason=reason)
            except Exception as e:
                _log_error('webview2_rebuild_bind_failed',
                           'Binding ProcessFailed after rebuild raised',
                           exception=e)

            state['rebuilding'] = False
            print('[MarkEase][webview2] control rebuilt; reloading page')
            _log_event('webview2_rebuild_init_ok',
                       'WebView2 control rebuilt; page reloading',
                       reason=reason)

        new_control.CoreWebView2InitializationCompleted += _on_init
        # 双保险：导航前确保恢复标记已置位（正常路径在 _schedule 里已置位）
        try:
            api._recovery_pending = True
        except Exception:
            pass

        print('[MarkEase][webview2] rebuilding control after %s' % reason)
        _log_event('webview2_rebuild_started',
                   'Rebuilding WebView2 control', reason=reason)
        new_control.EnsureCoreWebView2Async(None)
    except Exception as e:
        state['rebuilding'] = False
        print(f'[MarkEase][webview2] rebuild failed: {e}')
        _log_critical('webview2_rebuild_failed',
                      'Failed to rebuild WebView2 control',
                      exception=e, reason=reason)
        _show_webview2_fatal_dialog('错误：' + str(e))


def _schedule_webview2_rebuild(window, api, reason='unknown'):
    """安排一次控件重建（限频 3 次/5 分钟，且同一时间只允许一次）。"""
    if _APP_SHUTTING_DOWN:
        return False

    state = _WEBVIEW2_RECOVERY_STATE
    now = time.monotonic()
    state['rebuilds'] = [t for t in state['rebuilds'] if now - t < 300.0]

    if state.get('rebuilding'):
        _log_event('webview2_rebuild_skipped',
                   'WebView2 rebuild already in progress', reason=reason)
        return False

    if len(state['rebuilds']) >= 3:
        print('[MarkEase][webview2] too many rebuilds, stop')
        _log_error('webview2_rebuild_gave_up',
                   'WebView2 failed repeatedly; not rebuilding again',
                   reason=reason,
                   rebuilds_within_300s=len(state['rebuilds']))
        _show_webview2_fatal_dialog_async('界面组件多次崩溃。')
        return False

    state['rebuilding'] = True
    state['rebuild_token'] = now
    state['rebuilds'].append(now)

    # reload / 重建后前端都会调用 take_recovery_state 恢复最新内容
    try:
        api._recovery_pending = True
    except Exception:
        pass

    token = now

    def _watchdog():
        time.sleep(25.0)
        try:
            if (state.get('rebuilding') and
                    state.get('rebuild_token') == token):
                state['rebuilding'] = False
                print('[MarkEase][webview2] rebuild timed out')
                _log_critical('webview2_rebuild_timeout',
                              'WebView2 control rebuild timed out',
                              reason=reason)
                _show_webview2_fatal_dialog('界面组件初始化超时。')
        except Exception:
            pass

    def _worker():
        # 等浏览器进程及其子进程真正退出、profile 锁释放后再建新控件
        time.sleep(1.2)

        def _do_rebuild():
            _rebuild_webview2_on_ui(window, api, reason=reason)

        try:
            from System import Action
            window.native.Invoke(Action(_do_rebuild))
        except Exception as e:
            state['rebuilding'] = False
            print(f'[MarkEase][webview2] rebuild attach failed: {e}')
            _log_error('webview2_rebuild_attach_failed',
                       'Failed to marshal WebView2 rebuild to UI thread',
                       exception=e)
            _show_webview2_fatal_dialog('错误：' + str(e))

    threading.Thread(target=_worker, daemon=True,
                     name='MarkEaseWebView2Rebuild').start()
    threading.Thread(target=_watchdog, daemon=True,
                     name='MarkEaseWebView2RebuildWatchdog').start()

    print('[MarkEase][webview2] rebuild scheduled after %s' % reason)
    _log_event('webview2_rebuild_scheduled',
               'Scheduled WebView2 control rebuild', reason=reason)
    return True


def _make_webview2_process_failed_handler(window, api, generation=0):
    """构造某一代 CoreWebView2 的 ProcessFailed 处理器。"""

    def on_process_failed(sender, args):
        try:
            if _APP_SHUTTING_DOWN:
                return

            state = _WEBVIEW2_RECOVERY_STATE
            if generation != int(state.get('generation', 0)):
                # 旧 core（已被重建替换）迟到的 ProcessFailed：忽略
                print('[MarkEase][webview2] stale ProcessFailed ignored '
                      '(generation=%s, current=%s)'
                      % (generation, int(state.get('generation', 0))))
                _log_event('webview2_stale_process_failed',
                           'Ignoring ProcessFailed from a retired WebView2 core',
                           generation=generation,
                           current_generation=int(state.get('generation', 0)))
                return

            info = _webview2_failure_info(args)
            kind = info.get('kind', 'unknown')

            print('[MarkEase][webview2] process failed: %s reason=%s exit=%s'
                  % (kind, info.get('reason', '?'),
                     info.get('exit_code_hex', '?')))
            _log_error('webview2_process_failed',
                       'WebView2 process failed', **info)

            # ★ 浏览器进程退出：CoreWebView2 已不可用，Reload 无效，
            #   必须重建控件才能恢复（否则整窗永久空白）。
            if kind == 'BrowserProcessExited':
                _log_error('webview2_browser_process_exited',
                           'WebView2 browser process exited; rebuilding control',
                           **info)
                _schedule_webview2_rebuild(window, api, reason=kind)
                return

            # 只有真正会让内容区空白的进程类型才自动 reload
            recoverable = (
                'RenderProcessExited',
                'RenderProcessUnresponsive',
                'GpuProcessExited',
            )
            if kind not in recoverable:
                _log_event('webview2_process_failed_ignored',
                           'Non-recoverable WebView2 process failure kind',
                           **info)
                return

            now = time.monotonic()
            state = _WEBVIEW2_RECOVERY_STATE
            state['reloads'] = [
                t for t in state['reloads'] if now - t < 60.0
            ]
            if len(state['reloads']) >= 3:
                print('[MarkEase][webview2] recovery: too many reloads, '
                      'falling back to control rebuild')
                _log_error('webview2_recovery_gave_up',
                           'WebView2 crashed repeatedly; stop auto reload',
                           reloads_within_60s=len(state['reloads']),
                           **info)
                _schedule_webview2_rebuild(window, api, reason=kind)
                return
            state['reloads'].append(now)

            try:
                # 标记恢复：reload 后前端会调用 take_recovery_state 恢复内容
                try:
                    api._recovery_pending = True
                except Exception:
                    pass
                sender.Reload()
                print(f'[MarkEase][webview2] reloaded after {kind}')
                _log_event('webview2_reload_after_failure',
                           'WebView2 reloaded after process failure',
                           kind=kind,
                           reload_count=len(state['reloads']))
            except Exception as e:
                print(f'[MarkEase][webview2] reload failed: {e}')
                _log_error('webview2_reload_failed',
                           'Reload after WebView2 process failure raised',
                           exception=e, **info)
                # Reload 都失败了，说明控件已不可用，只能重建
                _schedule_webview2_rebuild(window, api, reason=kind)
        except Exception as e:
            _log_error('webview2_process_failed_handler_raised',
                       'ProcessFailed handler raised',
                       exception=e)

    return on_process_failed


def _install_webview2_process_failed_recovery(window, api):
    """
    监听 WebView2 的 ProcessFailed 事件。

    背景：WebView2 的 renderer / GPU 进程偶发崩溃时，WinForms 窗口仍然存在，
    但 WebView2 内容区会永久空白，Python 侧没有任何异常。用户关闭重开才恢复。
    - renderer / GPU 失效 → 自动 Reload（限频），并由前端恢复内容；
    - 浏览器进程退出（BrowserProcessExited）→ 重建 WebView2 控件；
    - 重建失败 → 系统弹窗提示，绝不留下“静默空白窗口”。
    """
    state = _WEBVIEW2_RECOVERY_STATE
    if state.get('installed') or state.get('installing'):
        return
    state['installing'] = True
    state['window'] = window
    state['api'] = api

    def _attach_on_ui():
        try:
            native = window.native
            wv = getattr(native, 'webview', None)
            core = getattr(wv, 'CoreWebView2', None) if wv is not None else None
        except Exception as e:
            state['installing'] = False
            print(f'[MarkEase][webview2] recovery: cannot access core: {e}')
            _log_error('webview2_recovery_core_failed',
                       'Cannot access WebView2 CoreWebView2',
                       exception=e)
            return

        if core is None:
            state['installing'] = False
            print('[MarkEase][webview2] recovery: CoreWebView2 is None')
            _log_error('webview2_recovery_core_none',
                       'CoreWebView2 is None; skip crash recovery')
            return

        try:
            if not _bind_process_failed_to_core(core):
                raise RuntimeError('bind returned False')
            state['installed'] = True
            state['installing'] = False
            print('[MarkEase][webview2] crash recovery installed')
            _log_event('webview2_recovery_installed',
                       'WebView2 ProcessFailed recovery installed')
        except Exception as e:
            state['installing'] = False
            print(f'[MarkEase][webview2] recovery install failed: {e}')
            _log_error('webview2_recovery_install_failed',
                       'Failed to subscribe WebView2 ProcessFailed',
                       exception=e)

    def _attach():
        try:
            from System import Action
            window.native.Invoke(Action(_attach_on_ui))
        except Exception as e:
            state['installing'] = False
            print(f'[MarkEase][webview2] recovery attach failed: {e}')
            _log_error('webview2_recovery_attach_failed',
                       'Failed to marshal recovery attach to UI thread',
                       exception=e)

    threading.Thread(target=_attach, daemon=True,
                     name='MarkEaseWebView2Recovery').start()


def _run_self_test():
    """无窗口自检：验证平台层、资源与业务模块可导入。

    供 CI 在三平台上执行 ``MarkEase --self-test``；不创建窗口、不启动服务。
    """
    import json

    result = {
        'ok': False,
        'platform': platform.name,
        'python': sys.version.split()[0],
        'version': _read_version_from_version_info(),
        'gui': platform.webview_gui(),
        'frozen': bool(getattr(sys, 'frozen', False)),
    }
    try:
        result['web_dir'] = get_web_dir()
        result['web_index'] = os.path.isfile(
            os.path.join(get_web_dir(), 'index.html'))
        result['icon'] = get_icon_path() or ''
        result['pdf_export'] = bool(platform.supports_pdf_export())

        # 业务模块导入检查（不构造 Api，避免启动 HTTP 服务）
        import app.api  # noqa: F401
        import app.asset_server  # noqa: F401
        import app.image_picker  # noqa: F401
        import converters.html_exporter  # noqa: F401
        import converters.html_importer  # noqa: F401
        import converters.pdf_importer  # noqa: F401
        import webview  # noqa: F401
        try:
            from importlib.metadata import version as _pkg_version
            result['webview_version'] = _pkg_version('pywebview')
        except Exception:
            result['webview_version'] = ''
        result['ok'] = bool(result['web_index'])
    except Exception as e:
        result['error'] = '%s: %s' % (type(e).__name__, e)

    print('[MarkEase][self-test] ' + json.dumps(result, ensure_ascii=False))
    return bool(result['ok'])


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
    startup_file = platform.parse_startup_file(sys.argv)
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

    platform.init_app_integration()

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
        global _APP_SHUTTING_DOWN
        try:
            if api._force_close:
                _APP_SHUTTING_DOWN = True
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
            _APP_SHUTTING_DOWN = True
            _log_event('closing_clean',
                       'closing event: clean state; allow')
        except Exception as e:
            _APP_SHUTTING_DOWN = True
            print(f'[MarkEase] on_closing error: {e}')
            _log_error('on_closing_error',
                       'Unexpected error inside on_closing',
                       exception=e)
        return True

    def on_closed():
        global _APP_SHUTTING_DOWN
        _APP_SHUTTING_DOWN = True
        try:
            platform.set_shutting_down(True)
        except Exception:
            pass
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

    def on_loaded():
        # Windows：WebView2 进程崩溃自恢复（macOS / Linux 无此机制）
        if platform.is_windows:
            try:
                _install_webview2_process_failed_recovery(window, api)
            except Exception as e:
                print(f'[MarkEase][webview2] recovery hook failed: {e}')
                _log_error('webview2_recovery_hook_failed',
                           'on_loaded recovery hook raised',
                           exception=e)
        # macOS：把 open-file Apple Event 转交前端
        try:
            platform.start_open_file_watcher(window, api)
        except Exception as e:
            _log_error('open_file_watcher_failed',
                       'start_open_file_watcher raised',
                       exception=e)

    window.events.loaded += on_loaded
    window.events.closing += on_closing
    window.events.closed += on_closed

    # ★ 启动看门狗：窗口未响应超时 → 强制退出
    try:
        platform.start_hang_watchdog(window)
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
               gui=platform.webview_gui(), debug=False,
               has_icon=bool(icon_path))

    try:
        webview.start(
            gui=platform.webview_gui(),
            debug=False,
            icon=icon_path if icon_path else None,
            # ★ 显式指定本次启动的 WebView2 目录：避免 pywebview 使用临时目录
            #   或上一次崩溃残留的坏档案，导致 0x800700AA 空白窗口。
            storage_path=_USER_DATA_DIR,
        )
    except Exception as e:
        _log_critical('webview_start_failed',
                      'webview.start raised',
                      exception=e)
        raise
    finally:
        # 退出时删除本次专用目录（失败也无妨，下次启动会清理）
        if _USER_DATA_DIR:
            try:
                import shutil
                shutil.rmtree(_USER_DATA_DIR, ignore_errors=True)
            except Exception:
                pass

    _log_event('webview_start_returned',
               'webview.start returned; main() is exiting')


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        sys.exit(0 if _run_self_test() else 1)
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