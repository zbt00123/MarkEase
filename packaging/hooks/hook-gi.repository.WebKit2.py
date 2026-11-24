# -*- coding: utf-8 -*-
"""PyInstaller 钩子：收集 WebKit2 的 typelib 与共享库。

PyInstaller 自带 Gtk/Gdk/GLib 等钩子，但没有 WebKit2；缺少它时
打包后的 Linux 版本会报 "Namespace WebKit2 not available"。
"""


def hook(hook_api):
    from PyInstaller.utils.hooks.gi import GiModuleInfo

    last_error = None
    for version in ('4.1', '4.0'):
        try:
            info = GiModuleInfo('WebKit2', version, hook_api=hook_api)
        except Exception as e:  # noqa: BLE001
            last_error = e
            continue
        if not info.available:
            continue
        try:
            binaries, datas, hiddenimports = info.collect_typelib_data()
        except Exception as e:  # noqa: BLE001
            last_error = e
            continue
        hook_api.add_binaries(binaries)
        hook_api.add_datas(datas)
        hook_api.add_imports(*hiddenimports)
        return

    if last_error is not None:
        raise RuntimeError(f'WebKit2 hook failed: {last_error}')
