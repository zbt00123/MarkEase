# -*- mode: python ; coding: utf-8 -*-
"""
MarkEase v2.1 PyInstaller spec（阶段 16 第 1 批 · 含 Pillow）
"""

import os
import shutil
from PyInstaller.utils.hooks import (
    collect_dynamic_libs, collect_all, collect_submodules
)

# ---------- 项目根目录 ----------
try:
    project_root = os.path.abspath(SPECPATH)
except NameError:
    project_root = os.path.abspath(os.getcwd())

print(f'[spec] project_root = {project_root}')

# ---------- 数据文件 ----------
datas = [
    (os.path.join(project_root, 'web'), 'web'),
    (os.path.join(project_root, 'resources'), 'resources'),
    (os.path.join(project_root, 'version_info.txt'), '.'),
]

binaries = collect_dynamic_libs('webview')
hiddenimports = []

# ---------- PyMuPDF / fitz ----------
for pkg in ('fitz', 'pymupdf'):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
        print(f'[spec] collect_all({pkg}) ok')
    except Exception as e:
        print(f'[spec] collect_all({pkg}) failed: {e}')

# ---------- python-docx ----------
for pkg in ('docx',):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
        print(f'[spec] collect_all({pkg}) ok')
    except Exception as e:
        print(f'[spec] collect_all({pkg}) failed: {e}')

try:
    hiddenimports += collect_submodules('lxml')
except Exception as e:
    print(f'[spec] collect lxml failed: {e}')

hiddenimports += [
    'docx', 'docx.api', 'docx.document', 'docx.opc',
    'docx.opc.package', 'docx.parts', 'docx.parts.document',
    'docx.parts.image', 'docx.parts.styles', 'docx.oxml',
    'docx.oxml.ns', 'docx.shared', 'docx.enum', 'docx.enum.text',
    'docx.enum.style',
]

# ---------- Pillow ----------
for pkg in ('PIL',):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
        print(f'[spec] collect_all({pkg}) ok')
    except Exception as e:
        print(f'[spec] collect_all({pkg}) failed: {e}')

hiddenimports += [
    'PIL', 'PIL.Image', 'PIL.ImageFile', 'PIL.ImageMode',
    'PIL.ImageColor', 'PIL.ImagePalette', 'PIL.PngImagePlugin',
    'PIL.JpegImagePlugin', 'PIL.GifImagePlugin', 'PIL.WebPImagePlugin',
    'PIL.BmpImagePlugin', 'PIL.TiffImagePlugin', 'PIL.IcoImagePlugin',
    'PIL.ImageSequence',
]

# ---------- ★ pythonnet（必须显式收集 runtime 下的 DLL）----------
#   ★ 不要用 `import clr` 来探测！import clr 会真正初始化 .NET Framework，
#     在构建机上（无 .NET / 受限环境 / 沙箱）可能抛异常，从而静默跳过整个
#     pythonnet 收集，打出的包启动时才会报 pythonnet 相关错误。
#     这里只做"模块是否存在"的探测，不触发任何 .NET 初始化。
try:
    import importlib.util

    def _module_available(name):
        try:
            return importlib.util.find_spec(name) is not None
        except Exception:
            return False

    if _module_available('pythonnet') and _module_available('clr_loader'):
        hiddenimports += ['clr', 'pythonnet', 'clr_loader']
        print('[spec] pythonnet found, .NET (PDF/WebView) support enabled')

        # 显式收集 pythonnet 和 clr_loader 的数据
        for pkg in ('pythonnet', 'clr_loader'):
            tmp_ret = collect_all(pkg)
            datas += tmp_ret[0]
            binaries += tmp_ret[1]
            hiddenimports += tmp_ret[2]

        # 暴力确保 runtime 下的所有 dll 被塞进 pythonnet/runtime
        pythonnet_spec = importlib.util.find_spec('pythonnet')
        pythonnet_dir = os.path.dirname(pythonnet_spec.origin)
        runtime_dir = os.path.join(pythonnet_dir, 'runtime')
        if os.path.isdir(runtime_dir):
            for f in os.listdir(runtime_dir):
                if f.lower().endswith('.dll'):
                    src = os.path.join(runtime_dir, f)
                    datas.append((src, 'pythonnet/runtime'))
                    print(f'[spec] forced include dll: {f}')
    else:
        print('[spec] pythonnet not installed, .NET support disabled')
except Exception as e:
    print(f'[spec] collect pythonnet failed: {e}')

# ---------- Analysis ----------
a = Analysis(
    [os.path.join(project_root, 'main.py')],
    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    # ★ 引用新建的 runtime hook
    runtime_hooks=['pyi_rth_pythonnet.py'],
    excludes=[
        'tkinter', 'unittest', 'pydoc', 'test', 'tests',
        'PySide6', 'shiboken6', 'PySide2', 'shiboken2',
        'PyQt5', 'PyQt6', 'sip', 'PyQt5.sip', 'PyQt6.sip',
        'matplotlib', 'scipy', 'pandas', 'IPython', 'jupyter',
        'notebook', 'pytest', 'html2text', 'bs4', 'beautifulsoup4',
        'soupsieve',
    ],
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=os.path.join(project_root, 'version_info.txt'),
    uac_admin=False,
    icon=[os.path.join(project_root, 'resources', 'icons', '图标.ico')],
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

# ---------- ★ 关键修复：把 .NET Framework 运行时配置放到 exe 同目录 ----------
#   .NET Framework 按"程序集路径"计算安全区域；路径含中文时会被误判为
#   Internet 区域，AppDomain.Load 直接抛 NotSupportedException(0x80131515)，
#   导致 pythonnet 无法加载 Python.Runtime.dll（打包后启动即报
#   "Failed to resolve Python.Runtime.Loader.Initialize"）。
#   必须通过 <exe>.config 开启 loadFromRemoteSources 才能修复。
#   详见 MarkEase.exe.config 内的注释。
_app_config_src = os.path.join(project_root, 'MarkEase.exe.config')
_app_config_dst = os.path.join(DISTPATH, 'MarkEase', 'MarkEase.exe.config')
try:
    if not os.path.isfile(_app_config_src):
        print(f'[spec] WARNING: {_app_config_src} not found; '
              f'pythonnet may fail to load on non-ASCII paths')
    else:
        shutil.copyfile(_app_config_src, _app_config_dst)
        print(f'[spec] .NET runtime config -> {_app_config_dst}')
except Exception as e:
    print(f'[spec] WARNING: failed to copy .NET runtime config: {e}')