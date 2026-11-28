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

# ============================================================
#  ★ 不打包发行版自带的系统库
#
#  PyInstaller 在 Linux 上会把构建机（CI 上是 ubuntu-22.04）的 GTK / GLib /
#  libstdc++ 等一起拷进 _internal，启动时它们会先于目标系统的同名库被加载。
#  在比构建机新的发行版上，系统的 WebKitGTK 反过来要求更新的符号版本：
#  Ubuntu 26.04 的 libicui18n.so.78 需要 CXXABI_1.3.15（GCC 14+），而 22.04 的
#  libstdc++.so.6 只到 CXXABI_1.3.13，于是 WebKit 的 typelib 加载失败，
#  应用在创建窗口之前就退出（从图标启动时看不到任何报错）。
#
#  这些库本来就该由 .deb 的 Depends 交给发行版提供，这里只保留：
#    - libpython*  ：Python 运行时
#    - libmupdf*   ：PyMuPDF 自带（顶层那几个是 COLLECT 生成的软链接，
#                    保留它们不影响 RUNPATH=$ORIGIN 的解析）
#  包内子目录（Python 扩展模块、pillow.libs 里 auditwheel 修补过的库）一律
#  保留：Pillow / PyMuPDF 的扩展模块自带 RPATH，靠目录内的库自洽运行，
#  已经用 DT_NEEDED/RPATH 逐项核对过，不依赖下面被剔除的这些系统库。
#
#  ★ MK_LINUX_LEGACY=1（legacy 构建，给 UOS 20 / 麒麟 V10 / Debian 10-11）：
#    老系统的 libffi 只有 6/7、OpenSSL 只有 1.1，而 Python 3.14 的 ctypes 要
#    libffi.so.8、ssl 要 libssl.so.3。这几个库 ABI 稳定、不会被系统的图形栈
#    加载，所以 legacy 产物把它们一起带上（soname 不同，不会顶掉系统库）。
# ============================================================
_ROOT_LIB_KEEP_PREFIXES = ('libpython', 'libmupdf')

_LEGACY_BUILD = os.environ.get('MK_LINUX_LEGACY') == '1'
if _LEGACY_BUILD:
    _ROOT_LIB_KEEP_PREFIXES += ('libffi', 'libssl', 'libcrypto')
    print('[linux.spec] legacy build: keeping bundled '
          + ', '.join(_ROOT_LIB_KEEP_PREFIXES))


def _is_bundled_system_lib(dest):
    """dest 是 _internal 内的相对路径；根目录下的系统 .so 判定为需剔除。"""
    path = str(dest).replace('\\', '/')
    while path.startswith('./'):
        path = path[2:]
    if '/' in path:              # 包内子目录：扩展模块 / wheel 自带库
        return False
    name = path.lower()
    if '.cpython-' in name or not name.startswith('lib'):
        return False
    return not name.startswith(_ROOT_LIB_KEEP_PREFIXES)


bundled_binaries = [b for b in a.binaries if not _is_bundled_system_lib(b[0])]
_dropped = len(a.binaries) - len(bundled_binaries)
if _dropped:
    print(f'[linux.spec] dropped {_dropped} system libraries '
          f'(provided by the target distro)')

coll = COLLECT(
    exe,
    bundled_binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MarkEase',
)
