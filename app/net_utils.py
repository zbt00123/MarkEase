# -*- coding: utf-8 -*-
"""
MarkEase 网络请求工具（三平台共用）。

macOS 的 Python.org 发行版不会自动使用系统根证书；PyInstaller 打包后
如果 certifi 的 cacert.pem 没被收集，所有 HTTPS 请求都会抛
CERTIFICATE_VERIFY_FAILED（表现就是网络图片全部加载失败）。
这里统一使用 certifi 的 CA，并禁用系统代理（与原有行为一致）。
"""

import ssl
import urllib.request


def ssl_context():
    """优先使用 certifi 根证书；失败时回退系统默认。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            # 最后兜底：至少保证图片代理可用（仍会校验证书链的常规场景）
            return ssl._create_unverified_context()


def build_opener():
    """构造禁用系统代理、使用 certifi CA 的 opener。"""
    handlers = [urllib.request.ProxyHandler({})]
    try:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context()))
    except Exception:
        pass
    return urllib.request.build_opener(*handlers)


def urlopen(req, timeout=15):
    return build_opener().open(req, timeout=timeout)
