# -*- coding: utf-8 -*-
"""
MarkEase 平台抽象层：默认实现 / 接口约定。

设计目标
--------
- **业务代码只依赖本模块的接口**，不出现 ``sys.platform`` 分支；
- Windows 的既有行为原样保留在 ``win.py``，保证 v2.1.6 行为不变；
- macOS / Linux 的差异全部收敛在 ``mac.py`` / ``linux.py``；
- 新增功能时：通用逻辑写在 ``app/`` / ``converters/``，只有
  "操作系统不同做法"的少数函数才加到平台层。

所有方法都必须**永不抛出未捕获异常**（返回 {'ok': False, ...} 或安全默认值），
避免因为某个平台缺少可选依赖导致整个应用无法启动。
"""

import os
import shutil
import subprocess


class PlatformBase:
    """平台默认实现（Unix 风格），子类按需覆盖。"""

    name = 'unknown'
    is_windows = False
    is_macos = False
    is_linux = False

    def __init__(self):
        self._storage_path = None
        self._shutting_down = False

    # ------------------------------------------------------------
    #  启动 / WebView
    # ------------------------------------------------------------
    def prepare_webview_env(self):
        """在 ``import webview`` **之前**调用，配置平台专用环境变量。

        返回本次启动使用的 webview storage/profile 目录（可为 None）。
        Windows 用它设置 WEBVIEW2_*；macOS / Linux 无此需要。
        """
        return None

    def webview_gui(self):
        """pywebview 后端名：edgechromium / cocoa / gtk。None = 自动选择。"""
        return None

    def get_icon_path(self, base_dir):
        """返回窗口 / 安装包图标路径；找不到返回 None。"""
        return None

    def get_storage_path(self):
        return self._storage_path

    def init_app_integration(self):
        """创建窗口前的系统集成（如 macOS 的 open-file Apple Event 监听）。"""
        return None

    def start_open_file_watcher(self, window, api):
        """窗口就绪后监听"系统再次要求打开文件"（如 macOS Apple Event）。"""
        return None

    def install_webview_recovery(self, window, api):
        """安装 WebView 崩溃自恢复（仅 Windows WebView2 有实现）。"""
        return None

    def start_hang_watchdog(self, window):
        """窗口未响应看门狗（仅 Windows 有实现）。"""
        return None

    def get_native_menu(self, window, api):
        """返回 pywebview 原生菜单列表；None 表示沿用应用内 HTML 菜单。"""
        return None

    def webview_localization(self):
        """pywebview 内置菜单（如 macOS 编辑菜单）的本地化文案。"""
        return {}

    def on_webview_started(self, window=None):
        """GUI 启动后的平台补充动作（macOS 用于调整菜单顺序）。"""
        return None

    def restart_app(self):
        """重启应用（macOS 切换语言刷新原生菜单用）。返回是否成功。"""
        return False

    def quit_immediately(self):
        """立即退出进程（绕过 Python 解释器 finalize / 线程 join）。"""
        return False

    def set_shutting_down(self, value):
        self._shutting_down = bool(value)

    def is_shutting_down(self):
        return bool(self._shutting_down)

    # ------------------------------------------------------------
    #  剪贴板
    # ------------------------------------------------------------
    def read_clipboard_text(self):
        """读取系统剪贴板纯文本；失败抛异常，由调用方转成 {'ok': False}。"""
        raise RuntimeError('当前平台暂不支持读取系统剪贴板')

    @staticmethod
    def _read_clipboard_from_commands(commands):
        """依次尝试若干外部命令，返回第一个成功命令的 stdout 文本。"""
        for cmd in commands:
            exe = shutil.which(cmd[0])
            if not exe:
                continue
            try:
                proc = subprocess.run(
                    [exe] + list(cmd[1:]),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:
                continue
            if proc.returncode != 0:
                continue
            try:
                return proc.stdout.decode('utf-8')
            except UnicodeDecodeError:
                return proc.stdout.decode('utf-8', errors='replace')
        raise RuntimeError('未找到可用的剪贴板读取工具（xclip / xsel / wl-paste / pbpaste）')

    # ------------------------------------------------------------
    #  文件管理器
    # ------------------------------------------------------------
    def open_directory(self, path, select_path=None):
        """在文件管理器中打开目录（可选选中其中的文件）。"""
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        opener = 'open' if self.is_macos else 'xdg-open'
        subprocess.Popen([opener, folder])
        return {'ok': True}

    def reveal(self, path):
        """在文件管理器中显示并选中文件。"""
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {'ok': False, 'error': '文件不存在：' + path}
        try:
            return self.open_directory(path)
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ------------------------------------------------------------
    #  PDF 导出
    # ------------------------------------------------------------
    def supports_pdf_export(self):
        return False

    def export_pdf(self, window, pdf_path):
        """把当前预览导出为 PDF（打印媒体）。"""
        return {'ok': False, 'error': '当前平台暂不支持导出 PDF'}

    # ------------------------------------------------------------
    #  文件关联
    # ------------------------------------------------------------
    def setup_file_associations_on_first_run(self):
        """首次启动时注册"新建 Markdown 文件"等系统级入口（可选）。"""
        return {'ok': False, 'skipped': True, 'reason': 'not supported'}

    def register_shell_new(self):
        """注册"右键 → 新建 Markdown 文件"（Windows ShellNew / Linux .desktop）。"""
        return {'ok': False, 'skipped': True, 'reason': 'not supported'}

    def set_as_default_program(self):
        return {'ok': False, 'error': '当前平台不支持自动注册默认程序'}

    def is_default_program(self):
        return False

    def get_default_program_name(self):
        return 'Markdown File'

    # ------------------------------------------------------------
    #  命令行 / 启动文件
    # ------------------------------------------------------------
    def parse_startup_file(self, argv):
        """从命令行参数取第一个存在的文件路径。"""
        found = []
        for arg in (argv or [])[1:]:
            if not arg or arg.startswith('--') or arg.startswith('-psn'):
                continue
            try:
                p = os.path.abspath(arg)
            except Exception:
                continue
            if os.path.isfile(p):
                found.append(p)
        return found[0] if found else ''
