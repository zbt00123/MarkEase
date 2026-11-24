# -*- coding: utf-8 -*-
"""
MarkEase 三平台打包公共配置（PyInstaller spec 共用）。

- 数据文件：web/、resources/、version_info.txt
- 版本号唯一来源：version_info.txt
- 图标：Windows 用 .ico；macOS / Linux 在构建时从 .ico 生成 .icns / .png
  （不把生成的二进制文件提交到仓库）
"""

import os
import re

from PyInstaller.utils.hooks import collect_all, collect_submodules


def project_root(specpath):
    return os.path.abspath(os.path.join(specpath, os.pardir))


def read_version(root):
    """从 version_info.txt 的 FileVersion 读取 X.Y.Z。"""
    path = os.path.join(root, 'version_info.txt')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            m = re.search(r"StringStruct\(u'FileVersion',\s*u'([^']+)'\)",
                          f.read())
        if m:
            return m.group(1)
    except Exception:
        pass
    return '0.0.0'


def common_datas(root):
    return [
        (os.path.join(root, 'web'), 'web'),
        (os.path.join(root, 'resources'), 'resources'),
        (os.path.join(root, 'version_info.txt'), '.'),
    ]


def _collect_pkg(datas, binaries, hiddenimports, name):
    try:
        d, b, h = collect_all(name)
        datas += d
        binaries += b
        hiddenimports += h
        print(f'[spec] collect_all({name}) ok')
    except Exception as e:
        print(f'[spec] collect_all({name}) failed: {e}')


def common_hiddenimports():
    """三平台共用的隐式导入（PyInstaller 静态分析找不到的）。"""
    hiddenimports = []
    datas = []
    binaries = []

    for pkg in ('fitz', 'pymupdf', 'docx', 'PIL'):
        _collect_pkg(datas, binaries, hiddenimports, pkg)

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
        'PIL', 'PIL.Image', 'PIL.ImageFile', 'PIL.ImageMode',
        'PIL.ImageColor', 'PIL.ImagePalette', 'PIL.PngImagePlugin',
        'PIL.JpegImagePlugin', 'PIL.GifImagePlugin', 'PIL.WebPImagePlugin',
        'PIL.BmpImagePlugin', 'PIL.TiffImagePlugin', 'PIL.IcoImagePlugin',
        'PIL.ImageSequence',
    ]
    return datas, binaries, hiddenimports


COMMON_EXCLUDES = [
    'tkinter', 'unittest', 'pydoc', 'test', 'tests',
    'PySide6', 'shiboken6', 'PySide2', 'shiboken2',
    'PyQt5', 'PyQt6', 'sip', 'PyQt5.sip', 'PyQt6.sip',
    'matplotlib', 'scipy', 'pandas', 'IPython', 'jupyter',
    'notebook', 'pytest', 'html2text', 'bs4', 'beautifulsoup4',
    'soupsieve', 'pythonnet', 'clr',
]


def build_icons(root, work_dir):
    """从 resources/icons/图标.ico 生成 macOS .icns 与 Linux .png。

    返回 {'png': path, 'icns': path}；Pillow 不可用时返回空字符串。
    """
    result = {'png': '', 'icns': ''}
    try:
        from PIL import Image
    except Exception as e:
        print(f'[spec] Pillow unavailable, skip icon conversion: {e}')
        return result

    candidates = [
        os.path.join(root, 'resources', 'icons', '图标.ico'),
        os.path.join(root, 'resources', 'icons', 'icon.ico'),
    ]
    src = next((p for p in candidates if os.path.isfile(p)), None)
    if not src:
        print('[spec] source .ico not found, skip icon conversion')
        return result

    try:
        os.makedirs(work_dir, exist_ok=True)
        img = Image.open(src)
        img.load()
        # ICO 里取最大的一帧
        try:
            sizes = sorted(img.info.get('sizes') or [img.size],
                           key=lambda s: s[0] * s[1])
            if sizes:
                img.size = sizes[-1]
                img.load()
        except Exception:
            pass
        img = img.convert('RGBA')

        png_path = os.path.join(work_dir, 'markease.png')
        img.resize((256, 256), Image.LANCZOS).save(png_path, format='PNG')
        result['png'] = png_path

        icns_path = os.path.join(work_dir, 'markease.icns')
        # 原始图标只有 256px，这里放大到 1024 以满足 Retina Dock / Finder
        img.resize((1024, 1024), Image.LANCZOS).save(icns_path,
                                                     format='ICNS')
        result['icns'] = icns_path
        print(f'[spec] icons: {png_path} / {icns_path}')
    except Exception as e:
        print(f'[spec] icon conversion failed: {e}')
    return result
