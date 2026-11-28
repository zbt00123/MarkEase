# -*- coding: utf-8 -*-
"""
MarkEase Linux / macOS 产物打包脚本（在对应系统的 runner 上执行）。

用法：
    python packaging/package.py --target linux-x64  --dist dist --out out
    python packaging/package.py --target macos-x64  --dist dist --out out
    python packaging/package.py --target macos-arm64 --dist dist --out out

产物：
    Linux : MarkEase_v<版本>_Linux_x64.tar.gz + .deb
    macOS : MarkEase_v<版本>_macOS_<arch>.dmg

可选环境变量（macOS 签名 / 公证）：
    MK_CODESIGN_IDENTITY   Developer ID Application 证书名；缺省为 ad-hoc "-"
    MK_NOTARIZE=1          对 dmg 执行 notarytool 公证并 staple
    APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time


def log(msg):
    print(f'[package] {msg}', flush=True)


def run(cmd, **kwargs):
    log('+ ' + ' '.join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kwargs)


def read_version(root):
    import re
    path = os.path.join(root, 'version_info.txt')
    with open(path, 'r', encoding='utf-8') as f:
        m = re.search(r"StringStruct\(u'FileVersion',\s*u'([^']+)'\)",
                      f.read())
    if not m:
        raise SystemExit('cannot read FileVersion from version_info.txt')
    return m.group(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def clean_runtime_artifacts(app_dir, is_mac=False):
    """删除构建/冒烟测试在产物目录里留下的运行期文件。

    CI 会在打包前启动一次应用并执行 --self-test，日志系统会把 `logs/`
    写进 frozen 目录；这些文件不能进入分发产物。
    """
    roots = [app_dir]
    if is_mac:
        roots.append(os.path.join(app_dir, 'Contents', 'MacOS'))
    for root in roots:
        for name in ('logs', 'webview2'):
            target = os.path.join(root, name)
            if os.path.isdir(target):
                log(f'clean runtime artifact: {target}')
                shutil.rmtree(target, ignore_errors=True)


# macOS 原生对话框（打开/保存面板、菜单）的语言由 bundle 支持的本地化决定。
BUNDLE_LANGUAGES = ('zh_CN', 'zh_TW', 'en', 'ja', 'ko')


def ensure_bundle_localizations(app_path):
    """给 .app 补上 .lproj 目录。

    PyInstaller 生成的 bundle 里一个 .lproj 都没有，macOS 会认为这个 App
    只支持开发语言，于是中文系统下 NSOpenPanel / NSAlert（"打开"文件
    对话框）仍然显示英文。补上空目录即可让 AppKit 选中对应语言。
    """
    resources = os.path.join(app_path, 'Contents', 'Resources')
    os.makedirs(resources, exist_ok=True)
    for lang in BUNDLE_LANGUAGES:
        lproj = os.path.join(resources, f'{lang}.lproj')
        os.makedirs(lproj, exist_ok=True)
        log(f'bundle localization: {lang}.lproj')


def ensure_icon_png(root, work_dir):
    """生成 Linux .desktop 用的 256px PNG。"""
    os.makedirs(work_dir, exist_ok=True)
    target = os.path.join(work_dir, 'markease.png')
    if os.path.isfile(target):
        return target
    try:
        from PIL import Image
        src = os.path.join(root, 'resources', 'icons', '图标.ico')
        if not os.path.isfile(src):
            src = os.path.join(root, 'resources', 'icons', 'icon.ico')
        img = Image.open(src).convert('RGBA')
        img.resize((256, 256), Image.LANCZOS).save(target, format='PNG')
        return target
    except Exception as e:
        log(f'WARNING: cannot generate icon: {e}')
        return ''


# ============================================================
#  Linux
# ============================================================
DEB_CONTROL = """Package: markease
Version: {version}
Section: editors
Priority: optional
Architecture: {arch}
Depends: libgtk-3-0 | libgtk-3-0t64, libglib2.0-0 | libglib2.0-0t64, libwebkit2gtk-4.1-0 | libwebkit2gtk-4.0-37, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, gir1.2-gtk-3.0, libcairo2, libpango-1.0-0, libgdk-pixbuf-2.0-0 | libgdk-pixbuf2.0-0
Recommends: chromium | google-chrome-stable | microsoft-edge-stable
Installed-Size: {installed_size}
Maintainer: ZBT Studio <zbt00123@users.noreply.github.com>
Homepage: https://github.com/zbt00123/MarkEase
Description: MarkEase - Markdown editor with live preview
 MarkEase is a lightweight Markdown editor with a live preview,
 KaTeX math, Mermaid-free architecture, PDF/HTML import and export.
"""

# 图形栈由发行版提供（见 linux.spec 的说明）。24.04 起部分包名带 t64 后缀，
# 所以 Depends 里两种写法都要列，dpkg 会挑能装上的那个。
DEB_POSTINST = """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
"""

DEB_POSTRM = """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0
"""

# 不允许再被打进产物的系统库（构建机自己的 GTK / GLib / libstdc++ 等）。
# 一旦回潮，在比构建机新的发行版上会顶掉系统库，WebKit 直接加载失败。
FORBIDDEN_BUNDLED_LIBS = (
    'libgtk-3.so.0',
    'libgdk-3.so.0',
    'libglib-2.0.so.0',
    'libgio-2.0.so.0',
    'libgobject-2.0.so.0',
    'libgirepository-1.0.so.1',
    'libstdc++.so.6',
    'libpango-1.0.so.0',
    'libcairo.so.2',
    'libicu',
)

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=MarkEase
GenericName=Markdown Editor
Comment=Markdown editor with live preview
Exec=/opt/markease/MarkEase %f
Icon=markease
Terminal=false
Categories=Office;TextEditor;
MimeType=text/markdown;text/x-markdown;
Keywords=markdown;editor;notes;
StartupWMClass=MarkEase
"""


def assert_no_system_libs(app_dir):
    """构建产物里不能出现构建机的系统库（见 linux.spec 的说明）。

    PyInstaller 一旦把构建机的 GTK / GLib / libstdc++ 打进 _internal，
    在更新的发行版上就会顶掉系统同名库，导致 WebKit 无法加载、应用静默退出。
    """
    internal = os.path.join(app_dir, '_internal')
    if not os.path.isdir(internal):
        return
    leaked = []
    for name in sorted(os.listdir(internal)):
        path = os.path.join(internal, name)
        if not os.path.isfile(path) and not os.path.islink(path):
            continue
        for forbidden in FORBIDDEN_BUNDLED_LIBS:
            if name == forbidden or name.startswith(forbidden):
                leaked.append(name)
                break
    if leaked:
        raise SystemExit(
            'refusing to package: system libraries were bundled into '
            f'_internal: {", ".join(leaked)}')


def package_linux(root, dist, out, version, variant=''):
    app_dir = os.path.join(dist, 'MarkEase')
    if not os.path.isdir(app_dir):
        raise SystemExit(f'missing build output: {app_dir}')

    clean_runtime_artifacts(app_dir, is_mac=False)
    assert_no_system_libs(app_dir)

    suffix = f'_{variant}' if variant else ''
    os.makedirs(out, exist_ok=True)
    artifacts = []

    tar_name = f'MarkEase_v{version}_Linux_x64{suffix}.tar.gz'
    tar_path = os.path.join(out, tar_name)
    run(['tar', '-czf', tar_path, '-C', dist, 'MarkEase'])
    artifacts.append(tar_path)

    # ---- .deb ----
    stage = tempfile.mkdtemp(prefix='markease_deb_')
    try:
        opt = os.path.join(stage, 'opt', 'markease')
        shutil.copytree(app_dir, opt, symlinks=True)

        bin_dir = os.path.join(stage, 'usr', 'bin')
        os.makedirs(bin_dir, exist_ok=True)
        os.symlink('../opt/markease/MarkEase',
                   os.path.join(bin_dir, 'markease'))

        apps_dir = os.path.join(stage, 'usr', 'share', 'applications')
        os.makedirs(apps_dir, exist_ok=True)
        with open(os.path.join(apps_dir, 'markease.desktop'), 'w',
                  encoding='utf-8') as f:
            f.write(DESKTOP_ENTRY)

        icon = ensure_icon_png(root, os.path.join(out, '_icons'))
        if icon:
            icon_dir = os.path.join(stage, 'usr', 'share', 'icons',
                                    'hicolor', '256x256', 'apps')
            os.makedirs(icon_dir, exist_ok=True)
            shutil.copyfile(icon, os.path.join(icon_dir, 'markease.png'))

        installed_kb = 0
        for base, _dirs, files in os.walk(opt):
            for name in files:
                try:
                    installed_kb += os.path.getsize(os.path.join(base, name))
                except OSError:
                    pass
        installed_kb = max(1, installed_kb // 1024)

        control_dir = os.path.join(stage, 'DEBIAN')
        os.makedirs(control_dir, exist_ok=True)
        with open(os.path.join(control_dir, 'control'), 'w',
                  encoding='utf-8') as f:
            f.write(DEB_CONTROL.format(version=version, arch='amd64',
                                       installed_size=installed_kb))

        # 维护脚本：装/卸时刷新桌面数据库与图标缓存，避免 .md 关联
        # 和图标要等用户重新登录才出现。
        for name, body in (('postinst', DEB_POSTINST),
                           ('postrm', DEB_POSTRM)):
            path = os.path.join(control_dir, name)
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(body)
            os.chmod(path, 0o755)

        deb_name = f'MarkEase_v{version}_Linux_x64{suffix}.deb'
        deb_path = os.path.join(out, deb_name)
        run(['dpkg-deb', '--build', '--root-owner-group', stage, deb_path])
        artifacts.append(deb_path)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(os.path.join(out, '_icons'), ignore_errors=True)

    return artifacts


# ============================================================
#  macOS
# ============================================================
def codesign_app(app_path):
    identity = os.environ.get('MK_CODESIGN_IDENTITY') or '-'
    log(f'codesign identity: {identity}')
    # 清掉构建过程可能带上的扩展属性，避免 codesign 报 detritus 错误
    try:
        subprocess.run(['xattr', '-cr', app_path], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    cmd = ['codesign', '--force', '--deep', '--sign', identity]
    if identity == '-':
        cmd += ['--timestamp=none']
    else:
        cmd += ['--options', 'runtime', '--timestamp']
    run(cmd + [app_path])
    run(['codesign', '--verify', '--deep', '--strict', '--verbose=2',
         app_path])


def _load_font(size, cjk=False):
    from PIL import ImageFont
    candidates = []
    if cjk:
        candidates += [
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Medium.ttc',
            '/System/Library/Fonts/Hiragino Sans GB.ttc',
        ]
    candidates += [
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/Library/Fonts/Arial.ttf',
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


def build_dmg_background(path):
    """生成 DMG 的 Finder 背景：箭头 + 拖动到 Applications 的提示。"""
    from PIL import Image, ImageDraw

    width, height = 660, 420
    image = Image.new('RGB', (width, height), '#f5f5f7')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([(1, 1), (width - 2, height - 2)],
                           radius=18, outline='#d0d0d6', width=2)

    title_font = _load_font(24, cjk=True)
    text_font = _load_font(17, cjk=True)
    small_font = _load_font(13)

    draw.text((width / 2, 42), '安装 MarkEase', font=title_font,
              fill='#1d1d1f', anchor='mm')

    # 箭头：从 MarkEase 图标指向 Applications 快捷方式
    y = 215
    x1, x2 = 278, 382
    draw.line([(x1, y), (x2, y)], fill='#2f6feb', width=6)
    draw.polygon([(x2, y), (x2 - 18, y - 13), (x2 - 18, y + 13)],
                 fill='#2f6feb')

    draw.text((width / 2, 322),
              '拖动 MarkEase 到 Applications 文件夹',
              font=text_font, fill='#1d1d1f', anchor='mm')
    draw.text((width / 2, 352),
              'Drag MarkEase to the Applications folder',
              font=small_font, fill='#6e6e73', anchor='mm')
    image.save(path, format='PNG')
    return path


def package_macos(root, dist, out, version, arch):
    app_path = os.path.join(dist, 'MarkEase.app')
    if not os.path.isdir(app_path):
        raise SystemExit(f'missing build output: {app_path}')

    clean_runtime_artifacts(app_path, is_mac=True)
    ensure_bundle_localizations(app_path)
    os.makedirs(out, exist_ok=True)
    codesign_app(app_path)

    dmg_name = f'MarkEase_v{version}_macOS_{arch}.dmg'
    dmg_path = os.path.join(out, dmg_name)
    work = tempfile.mkdtemp(prefix='markease_dmg_')
    try:
        background = os.path.join(work, 'background.png')
        build_dmg_background(background)

        try:
            from dmgbuild import build_dmg
        except Exception as e:
            raise SystemExit(
                'dmgbuild is required for the styled macOS dmg: %s' % e)

        settings = {
            'volume_name': 'MarkEase',
            'format': 'UDZO',
            'files': [app_path],
            'symlinks': {'Applications': '/Applications'},
            'background': background,
            'window_rect': ((200, 120), (660, 420)),
            'icon_size': 128,
            'default_view': 'icon-view',
            'icon_locations': {
                'MarkEase.app': (190, 215),
                'Applications': (470, 215),
            },
            'show_status_bar': False,
            'show_tab_view': False,
            'show_toolbar': False,
            'show_pathbar': False,
            'show_sidebar': False,
            'arrange_by': None,
            'grid_spacing': 100,
            'label_pos': 'bottom',
        }
        log('building styled dmg with dmgbuild')
        build_dmg(dmg_path, 'MarkEase', settings=settings)

        last_error = None
        for attempt in range(3):
            try:
                run(['hdiutil', 'verify', dmg_path])
                last_error = None
                break
            except subprocess.CalledProcessError as e:
                last_error = e
                time.sleep(2)
        if last_error is not None:
            raise last_error

        if os.environ.get('MK_NOTARIZE') == '1':
            apple_id = os.environ.get('APPLE_ID', '')
            password = os.environ.get('APPLE_APP_SPECIFIC_PASSWORD', '')
            team_id = os.environ.get('APPLE_TEAM_ID', '')
            if not (apple_id and password and team_id):
                raise SystemExit('MK_NOTARIZE=1 but Apple credentials missing')
            run(['xcrun', 'notarytool', 'submit', dmg_path,
                 '--apple-id', apple_id, '--password', password,
                 '--team-id', team_id, '--wait'])
            run(['xcrun', 'stapler', 'staple', dmg_path])

        return [dmg_path]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True,
                        choices=['linux-x64', 'macos-x64', 'macos-arm64'])
    parser.add_argument('--dist', default='dist')
    parser.add_argument('--out', default='out')
    parser.add_argument('--variant', default='',
                        choices=['', 'legacy'],
                        help='linux-x64 only: "legacy" = Debian 10/11, '
                             'UOS 20, Kylin V10 build (glibc 2.28)')
    args = parser.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    version = read_version(root)
    dist = os.path.abspath(args.dist)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    log(f'version={version} target={args.target} variant={args.variant or "-"}')
    if args.target == 'linux-x64':
        artifacts = package_linux(root, dist, out, version, args.variant)
    elif args.target == 'macos-x64':
        artifacts = package_macos(root, dist, out, version, 'x64')
    else:
        artifacts = package_macos(root, dist, out, version, 'arm64')

    lines = []
    for path in artifacts:
        size = os.path.getsize(path)
        digest = sha256(path)
        log(f'artifact: {path} ({size / 1024 / 1024:.1f} MB) sha256={digest}')
        lines.append(f'{digest}  {os.path.basename(path)}')

    sums = os.path.join(out, 'SHA256SUMS.txt')
    with open(sums, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    log(f'checksums: {sums}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
