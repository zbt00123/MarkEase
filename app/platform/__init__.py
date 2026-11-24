# -*- coding: utf-8 -*-
"""
MarkEase 平台层入口。

业务代码（main.py / app/api.py）只 ``from app.platform import platform``，
再调用 ``platform.xxx()``；不要再写 ``if sys.platform == ...``。

- Windows  : app/platform/win.py   （WebView2 / pythonnet / winreg，行为与 v2.1.6 一致）
- macOS    : app/platform/mac.py   （WKWebView / pbpaste / open / NSPrintOperation）
- Linux    : app/platform/linux.py （WebKit2GTK / xclip / xdg-open / WebKit2.PrintOperation）
- 其他      : base.py 的安全默认实现
"""

import sys

from .base import PlatformBase

if sys.platform == 'win32':
    from .win import WindowsPlatform as _Impl
elif sys.platform == 'darwin':
    from .mac import MacPlatform as _Impl
elif sys.platform.startswith('linux'):
    from .linux import LinuxPlatform as _Impl
else:
    _Impl = PlatformBase

platform = _Impl()
# 兼容旧引用写法
Platform = PlatformBase

__all__ = ['platform', 'PlatformBase', 'Platform']
