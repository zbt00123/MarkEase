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
"""

import os
import sys

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
except Exception as e:
    print(f'[MarkEase] cannot create user data dir: {e}')

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

import webview
from app.api import Api


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


def main():
    web_dir = get_web_dir()
    index_path = os.path.join(web_dir, 'index.html')
    if not os.path.exists(index_path):
        print(f"错误：找不到 {index_path}")
        sys.exit(1)

    api = Api(web_dir)

    # 解析命令行传入的文件（双击 .md 场景）
    startup_file = _parse_startup_file()
    if startup_file:
        print(f'[MarkEase] startup file: {startup_file}')
        try:
            api.set_startup_file(startup_file)
        except Exception as e:
            print(f'[MarkEase] set_startup_file failed: {e}')

    try:
        theme = api._settings.get('theme', 'system')
    except Exception:
        theme = 'system'
    bg = _bg_for_theme(theme)

    url = f'http://127.0.0.1:{api._asset_port}/web/index.html'

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
        window = webview.create_window(**kwargs)

    api.set_window(window)

    def on_closed():
        try:
            api.close_all_pickers()
        except Exception:
            pass
        try:
            api._asset_server.stop()
        except Exception:
            pass

    window.events.closed += on_closed

    icon_path = get_icon_path()
    if icon_path:
        print(f'[MarkEase] icon: {icon_path}')
    print(f'[MarkEase] url: {url}')

    webview.start(
        gui='edgechromium',
        debug=False,
        icon=icon_path if icon_path else None,
    )


if __name__ == '__main__':
    main()