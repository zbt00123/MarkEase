# -*- mode: python ; coding: utf-8 -*-
"""
MarkEase Linux PyInstaller spec（onedir）。

构建：
    python -m PyInstaller --clean --noconfirm packaging/linux.spec

产物：dist/MarkEase/（MarkEase 可执行文件 + _internal/）
分发：packaging/package.py --target linux-x64 生成 tar.gz 与 .deb
"""

import os
import sys

SPEC_DIR = os.path.abspath(SPECPATH)
sys.path.insert(0, SPEC_DIR)

from common import (  # noqa: E402
    COMMON_EXCLUDES, build_icons, common_datas, common_hiddenimports,
    project_root,
)

ROOT = project_root(SPEC_DIR)

datas, binaries, hiddenimports = common_hiddenimports()
datas += common_datas(ROOT)

# PyGObject / WebKit2：运行时由 pywebview 的 gtk 后端动态导入
hiddenimports += [
    'gi',
    'gi.repository.Gtk',
    'gi.repository.Gdk',
    'gi.repository.GLib',
    'gi.repository.Gio',
    'gi.repository.GObject',
    'gi.repository.Pango',
    'gi.repository.WebKit2',
    'webview.platforms.gtk',
]

icons = build_icons(ROOT, os.path.join(workpath, 'icons'))
if icons.get('png'):
    # 让 platform.get_icon_path() 在打包后也能找到窗口 / 桌面图标
    datas.append((icons['png'], os.path.join('resources', 'icons')))

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(SPEC_DIR, 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=COMMON_EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MarkEase',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=icons.get('png') or 'NONE',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MarkEase',
)
