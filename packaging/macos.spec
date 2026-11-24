# -*- mode: python ; coding: utf-8 -*-
"""
MarkEase macOS PyInstaller spec（.app bundle）。

构建（在对应架构的 runner 上原生构建）：
    MK_TARGET_ARCH=arm64 python -m PyInstaller --clean --noconfirm packaging/macos.spec
    MK_TARGET_ARCH=x86_64 python -m PyInstaller --clean --noconfirm packaging/macos.spec

产物：dist/MarkEase.app
分发：packaging/package.py --target macos-arm64|x64 生成 dmg
"""

import os
import sys

SPEC_DIR = os.path.abspath(SPECPATH)
sys.path.insert(0, SPEC_DIR)

from common import (  # noqa: E402
    COMMON_EXCLUDES, build_icons, common_datas, common_hiddenimports,
    project_root, read_version,
)

ROOT = project_root(SPEC_DIR)
VERSION = read_version(ROOT)
TARGET_ARCH = os.environ.get('MK_TARGET_ARCH') or None

datas, binaries, hiddenimports = common_hiddenimports()
datas += common_datas(ROOT)

# macOS 后端 + PyObjC（平台层会按需 import AppKit / WebKit）
hiddenimports += [
    'webview.platforms.cocoa',
    'objc',
    'AppKit',
    'Foundation',
    'WebKit',
    'Quartz',
    'UniformTypeIdentifiers',
]

icons = build_icons(ROOT, os.path.join(workpath, 'icons'))

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
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
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon=icons.get('icns') or 'NONE',
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

info_plist = {
    'CFBundleName': 'MarkEase',
    'CFBundleDisplayName': 'MarkEase',
    'CFBundleIdentifier': 'com.zbtstudio.markease',
    'CFBundleVersion': VERSION,
    'CFBundleShortVersionString': VERSION,
    'CFBundleExecutable': 'MarkEase',
    'CFBundlePackageType': 'APPL',
    'CFBundleSignature': '????',
    'NSHighResolutionCapable': True,
    'NSSupportsAutomaticGraphicsSwitching': True,
    'LSMinimumSystemVersion': '11.0',
    'NSHumanReadableCopyright':
        'Copyright © 2026 zbt00123. MIT License.',
    # 允许访问 127.0.0.1 的本地 HTTP asset server
    'NSAppTransportSecurity': {
        'NSAllowsLocalNetworking': True,
    },
    # 双击 .md / .markdown 打开（LaunchServices）
    'CFBundleDocumentTypes': [
        {
            'CFBundleTypeName': 'Markdown Document',
            'CFBundleTypeRole': 'Editor',
            'LSHandlerRank': 'Alternate',
            'LSItemContentTypes': [
                'net.daringfireball.markdown',
            ],
            'CFBundleTypeExtensions': ['md', 'markdown'],
        },
        {
            'CFBundleTypeName': 'PDF Document',
            'CFBundleTypeRole': 'Viewer',
            'LSHandlerRank': 'Alternate',
            'LSItemContentTypes': ['com.adobe.pdf'],
            'CFBundleTypeExtensions': ['pdf'],
        },
    ],
}

bundle_kwargs = dict(
    coll,
    name='MarkEase.app',
    bundle_identifier='com.zbtstudio.markease',
    info_plist=info_plist,
)
if icons.get('icns'):
    bundle_kwargs['icon'] = icons['icns']

app = BUNDLE(**bundle_kwargs)
