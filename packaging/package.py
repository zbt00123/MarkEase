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
Depends: libgtk-3-0, libwebkit2gtk-4.0-37 | libwebkit2gtk-4.1-0, gir1.2-gtk-3.0, gir1.2-webkit2-4.0 | gir1.2-webkit2-4.1, libglib2.0-0, libcairo2, libpango-1.0-0
Recommends: chromium | google-chrome-stable | microsoft-edge-stable
Installed-Size: {installed_size}
Maintainer: ZBT Studio <zbt00123@users.noreply.github.com>
Homepage: https://github.com/zbt00123/MarkEase
Description: MarkEase - Markdown editor with live preview
 MarkEase is a lightweight Markdown editor with a live preview,
 KaTeX math, Mermaid-free architecture, PDF/HTML import and export.
"""

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


def package_linux(root, dist, out, version):
    app_dir = os.path.join(dist, 'MarkEase')
    if not os.path.isdir(app_dir):
        raise SystemExit(f'missing build output: {app_dir}')

    clean_runtime_artifacts(app_dir, is_mac=False)

    os.makedirs(out, exist_ok=True)
    artifacts = []

    tar_name = f'MarkEase_v{version}_Linux_x64.tar.gz'
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

        deb_name = f'MarkEase_v{version}_Linux_x64.deb'
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


def package_macos(root, dist, out, version, arch):
    app_path = os.path.join(dist, 'MarkEase.app')
    if not os.path.isdir(app_path):
        raise SystemExit(f'missing build output: {app_path}')

    clean_runtime_artifacts(app_path, is_mac=True)

    os.makedirs(out, exist_ok=True)
    codesign_app(app_path)

    stage = tempfile.mkdtemp(prefix='markease_dmg_')
    try:
        shutil.copytree(app_path, os.path.join(stage, 'MarkEase.app'),
                        symlinks=True)
        os.symlink('/Applications', os.path.join(stage, 'Applications'))

        dmg_name = f'MarkEase_v{version}_macOS_{arch}.dmg'
        dmg_path = os.path.join(out, dmg_name)
        last_error = None
        for attempt in range(3):
            try:
                run(['hdiutil', 'create', '-volname', 'MarkEase',
                     '-srcfolder', stage, '-ov', '-format', 'UDZO', dmg_path])
                last_error = None
                break
            except subprocess.CalledProcessError as e:
                last_error = e
                log(f'hdiutil create failed (attempt {attempt + 1}): {e}')
                try:
                    if os.path.exists(dmg_path):
                        os.remove(dmg_path)
                except Exception:
                    pass
                time.sleep(3)
        if last_error is not None:
            raise last_error
        # hdiutil verify 偶尔在 CI 上报 "Resource temporarily unavailable"，重试
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
        shutil.rmtree(stage, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True,
                        choices=['linux-x64', 'macos-x64', 'macos-arm64'])
    parser.add_argument('--dist', default='dist')
    parser.add_argument('--out', default='out')
    args = parser.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    version = read_version(root)
    dist = os.path.abspath(args.dist)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    log(f'version={version} target={args.target}')
    if args.target == 'linux-x64':
        artifacts = package_linux(root, dist, out, version)
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
