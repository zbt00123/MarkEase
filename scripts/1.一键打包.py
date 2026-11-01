# -*- coding: utf-8 -*-
"""
MarkEase 一键打包脚本（整合版 · 阶段 15 修订）

流程（5 阶段）：
  1/5  预检查      Python / PyInstaller / 7-Zip / MarkEase.spec / version_info.txt
  2/5  清理        缓存 / 垃圾 / 旧依赖残留 / build / dist / release 旧版本
  3/5  vendor 验证 外链扫描 + 依赖完整性
  4/5  打包        PyInstaller（基于 MarkEase.spec）
  5/5  压缩        7z 到 <项目根>\\release

特点：
  - 阶段化进度显示，只输出关键信息和错误
  - PyInstaller 详细日志隐藏，失败时打印末尾 30 行
  - 7z 显示真实百分比进度条 + 压缩比
  - 彩色终端输出（可用 --no-color 关闭）
  - vendor 验证失败 → 立即中止（避免打出坏包）
  - 自动清理：缓存 / 垃圾 / 旧依赖 / build / dist / 旧版本压缩包
  - ★ 旧依赖扫描跳过 scripts/ 目录（构建脚本自身包含大量关键词，避免误报）
  - ★ 打包后自动补齐 MarkEase.exe.config（修复中文/网络路径下 pythonnet 加载失败）
  - ★ 发布目录使用项目内相对路径 release/，不写死本机绝对路径

用法：
  python scripts/1.一键打包.py                     # 完整流程
  python scripts/1.一键打包.py --skip-7z           # 跳过 7z 压缩
  python scripts/1.一键打包.py --skip-clean        # 跳过清理
  python scripts/1.一键打包.py --keep-build        # 保留 build/ dist/
  python scripts/1.一键打包.py --keep-old-releases # 保留 release 里的旧版本压缩包
  python scripts/1.一键打包.py --no-color          # 禁用彩色输出
  python scripts/1.一键打包.py --yes               # 覆盖压缩包时不询问
"""

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------- Windows 启用 ANSI ----------
if os.name == 'nt':
    os.system('')


# ============================================================
#  配置
# ============================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

SPEC_FILE = PROJECT_ROOT / 'MarkEase.spec'
VERSION_FILE = PROJECT_ROOT / 'version_info.txt'
VENDOR_DIR = PROJECT_ROOT / 'web' / 'js' / 'vendor'
DIST_DIR = PROJECT_ROOT / 'dist' / 'MarkEase'
BUILD_DIR = PROJECT_ROOT / 'build'

# 7z 输出目录：项目根下的 release/ 目录（相对路径，不暴露本机绝对路径）
#   打包完成后，压缩包会放到：
#     <项目根>\release\MarkEase_v<版本>_Windows_x64_portable.7z
RELEASE_DIR = PROJECT_ROOT / 'release'

# 保护路径（相对项目根，正斜杠分隔；清理时跳过）
SKIP_PATH_PREFIXES = (
    'web/js/vendor',
    'resources/icons',
    'resources/translations',
    'resources/themes',
    'Pic',
    '开发手册',
    '.git',
    '.venv', 'venv',
    'node_modules',
)

# ★ 旧依赖扫描时跳过的顶层目录（构建工具，不参与 PyInstaller 打包）
#   原因：scripts/*.py 内部包含 PySide6 / PyQt5 等字符串（模式定义、注释、提示），
#        直接扫描会产生大量误报。
OLD_DEP_SCAN_SKIP_DIRS = {'scripts'}

# 清理目标
CACHE_DIR_NAMES = ('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache')
JUNK_FILE_GLOBS = (
    '*.pyc', '*.pyo',
    '.DS_Store', 'Thumbs.db', 'desktop.ini',
    '*.swp', '*.swo', '*~',           # 编辑器临时/备份文件
    '*.spec~',
)
OLD_DEP_DIR_NAMES = ('PySide6', 'PySide2', 'PyQt5', 'PyQt6', 'shiboken6', 'shiboken2', 'sip')

# 旧依赖扫描（源码 import 报告）
OLD_DEP_PATTERNS = (
    ('PySide6',   re.compile(r'\bPySide6\b')),
    ('PySide2',   re.compile(r'\bPySide2\b')),
    ('PyQt5',     re.compile(r'\bPyQt5\b')),
    ('PyQt6',     re.compile(r'\bPyQt6\b')),
    ('shiboken6', re.compile(r'\bshiboken6\b')),
    ('shiboken2', re.compile(r'\bshiboken2\b')),
)
SOURCE_SUFFIXES = {'.py', '.js', '.mjs', '.html', '.htm', '.css'}

# dist/ 里需要额外清理的残留（PyInstaller 打包后常见）
DIST_JUNK_GLOBS = ('*.pdb', '*.exp', '*.lib', '*.ilk')
DIST_JUNK_DIR_NAMES = ('__pycache__',)

# vendor 扫描
IMPORT_RE = re.compile(
    r'''(?:\bfrom\s*|(?<![.\w])import\s*(?:\(\s*)?)'''
    r'''(?:['"]([^'"]+)['"])''',
    re.MULTILINE
)


# ============================================================
#  彩色输出
# ============================================================
class C:
    ENABLED = True

    @classmethod
    def _w(cls, code, s):
        return f'\033[{code}m{s}\033[0m' if cls.ENABLED else s

    @classmethod
    def red(cls, s):    return cls._w('31', s)
    @classmethod
    def green(cls, s):  return cls._w('32', s)
    @classmethod
    def yellow(cls, s): return cls._w('33', s)
    @classmethod
    def blue(cls, s):   return cls._w('34', s)
    @classmethod
    def cyan(cls, s):   return cls._w('36', s)
    @classmethod
    def gray(cls, s):   return cls._w('90', s)
    @classmethod
    def bold(cls, s):   return cls._w('1', s)


# ============================================================
#  工具函数
# ============================================================
def is_protected(path: Path) -> bool:
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return True
    parts = rel.parts
    if not parts:
        return False
    rel_str = '/'.join(parts)
    for prefix in SKIP_PATH_PREFIXES:
        if rel_str == prefix or rel_str.startswith(prefix + '/'):
            return True
    return False


def dir_size(path: Path) -> int:
    total = 0
    try:
        if path.is_file():
            return path.stat().st_size
        for f in path.rglob('*'):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def fmt_size(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


def rel_display(p: Path) -> str:
    """把项目内路径显示为相对路径，避免在日志里暴露本机绝对路径。"""
    try:
        return str(p.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(p)


def rmtree(path: Path) -> bool:
    def on_err(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    try:
        shutil.rmtree(path, onerror=on_err)
        return True
    except Exception:
        return False


def safe_unlink(path: Path) -> bool:
    try:
        os.chmod(path, stat.S_IWRITE)
        path.unlink()
        return True
    except Exception:
        return False


def find_7z():
    p = shutil.which('7z')
    if p:
        return p
    # 通用安装路径兜底（所有 Windows 机器通用，不含用户特有信息）
    for c in (r'C:\Program Files\7-Zip\7z.exe',
              r'C:\Program Files (x86)\7-Zip\7z.exe'):
        if Path(c).exists():
            return c
    return None


def extract_version() -> str:
    if not VERSION_FILE.exists():
        return '0.0.0'
    try:
        text = VERSION_FILE.read_text(encoding='utf-8')
        m = re.search(r'filevers\s*=\s*\(\s*(\d+),\s*(\d+),\s*(\d+),\s*\d+\s*\)', text)
        if m:
            return f'{m.group(1)}.{m.group(2)}.{m.group(3)}'
    except Exception:
        pass
    return '0.0.0'


def phase_header(idx: int, total: int, title: str):
    print()
    print(C.bold(C.cyan(f'[{idx}/{total}] {title}')))
    print(C.gray('-' * 60))


def progress_bar(pct: int, width: int = 40) -> str:
    filled = int(width * pct / 100)
    return '█' * filled + '░' * (width - filled)


def clear_current_line(width: int = 80):
    """用空格覆盖当前行，避免残留上一帧内容（spinner / 进度条）。"""
    try:
        print('\r' + ' ' * width + '\r', end='', flush=True)
    except Exception:
        pass


# ============================================================
#  阶段 1：预检查
# ============================================================
def phase_precheck():
    """返回 info dict；失败返回 None。"""
    info = {}

    # Python
    py_ver = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
    print(f'  {C.green("✓")} Python {py_ver}')
    info['python'] = py_ver

    # PyInstaller
    try:
        import PyInstaller
        print(f'  {C.green("✓")} PyInstaller {PyInstaller.__version__}')
        info['pyinstaller'] = PyInstaller.__version__
    except ImportError:
        print(f'  {C.red("✗")} PyInstaller 未安装')
        print(f'      请执行: {C.yellow("pip install pyinstaller")}')
        return None

    # 关键文件
    ok = True
    for f, name in ((SPEC_FILE, 'MarkEase.spec'),
                    (VERSION_FILE, 'version_info.txt')):
        if f.exists():
            print(f'  {C.green("✓")} {name}')
        else:
            print(f'  {C.red("✗")} 缺少 {name}  ({rel_display(f)})')
            ok = False
    if not ok:
        return None

    # vendor 目录
    if VENDOR_DIR.is_dir():
        n = len([f for f in VENDOR_DIR.iterdir()
                 if f.is_file() and f.suffix in ('.mjs', '.js')])
        print(f'  {C.green("✓")} vendor ({n} 个文件)')
    else:
        print(f'  {C.red("✗")} vendor 目录不存在: {rel_display(VENDOR_DIR)}')
        return None

    # 7-Zip
    seven_zip = find_7z()
    if seven_zip:
        print(f'  {C.green("✓")} 7-Zip  {C.gray(seven_zip)}')
        info['7z'] = seven_zip
    else:
        print(f'  {C.yellow("⚠")} 未找到 7-Zip（将跳过压缩）')
        info['7z'] = None

    # 打印发布目录，便于确认
    print(f'  {C.green("✓")} 发布目录: {C.gray(rel_display(RELEASE_DIR))}')

    info['version'] = extract_version()
    return info


# ============================================================
#  阶段 2：清理（自动执行，无需确认）
# ============================================================
def phase_clean(keep_build: bool, keep_old_releases: bool):
    """自动清理所有残留文件。无需用户交互。"""

    # ============ 2.1 项目内缓存与垃圾 ============
    _clean_project_caches()

    # ============ 2.2 build / dist ============
    _clean_build_dist(keep_build)

    # ============ 2.3 release 旧版本压缩包 ============
    _clean_old_releases(keep_old_releases)

    # ============ 2.4 旧依赖残留报告（源码 import）============
    _report_old_imports()


def _clean_project_caches():
    """清理项目内 Python 缓存、垃圾文件、旧依赖残留目录。"""
    stats = {'dirs': 0, 'files': 0, 'bytes': 0}

    # 缓存目录
    cache_dirs = []
    for name in CACHE_DIR_NAMES:
        for p in PROJECT_ROOT.rglob(name):
            if p.is_dir() and not is_protected(p):
                cache_dirs.append(p)

    # 垃圾文件
    junk_files = []
    for pattern in JUNK_FILE_GLOBS:
        for p in PROJECT_ROOT.rglob(pattern):
            if p.is_file() and not is_protected(p):
                junk_files.append(p)

    # 旧依赖残留目录
    old_dep_dirs = []
    for name in OLD_DEP_DIR_NAMES:
        for p in PROJECT_ROOT.rglob(name):
            if p.is_dir() and not is_protected(p):
                old_dep_dirs.append(p)

    # 统计
    for p in cache_dirs + old_dep_dirs:
        stats['bytes'] += dir_size(p)
    for p in junk_files:
        stats['bytes'] += dir_size(p)

    # 删除
    for p in cache_dirs + old_dep_dirs:
        if rmtree(p):
            stats['dirs'] += 1
    for p in junk_files:
        if safe_unlink(p):
            stats['files'] += 1

    # 输出
    parts = []
    if stats['dirs']:
        parts.append(f'{stats["dirs"]} 目录')
    if stats['files']:
        parts.append(f'{stats["files"]} 文件')
    if parts:
        print(f'  {C.green("✓")} 项目缓存/垃圾: {", ".join(parts)} '
              f'({fmt_size(stats["bytes"])})')
    else:
        print(f'  {C.gray("·")} 项目缓存/垃圾: 无')


def _clean_build_dist(keep_build: bool):
    """清理 build/ 和 dist/（PyInstaller 中间产物）。"""
    if keep_build:
        print(f'  {C.gray("·")} build/ dist/: 已保留（--keep-build）')
        return

    for d, name in ((BUILD_DIR, 'build/'), (PROJECT_ROOT / 'dist', 'dist/')):
        if d.exists():
            sz = dir_size(d)
            if rmtree(d):
                print(f'  {C.green("✓")} {name} 已删除 ({fmt_size(sz)})')
            else:
                print(f'  {C.yellow("⚠")} {name} 删除失败')
        else:
            # 不打印"未找到"，保持输出简洁
            pass


def _clean_old_releases(keep_old: bool):
    """
    清理 release 目录里旧版本的 .7z 压缩包。

    保留：
      - 当前版本的压缩包（如有）
      - 用户手动放入的其他文件（非 .7z 或不符合命名规则的 .7z）
    """
    if not RELEASE_DIR.exists():
        print(f'  {C.gray("·")} release/: 目录不存在（将由 7z 阶段创建）')
        return

    # 查找所有匹配 MarkEase_v*.7z 的旧压缩包
    pattern_re = re.compile(r'^MarkEase_v(\d+\.\d+\.\d+)_Windows_x64_portable\.7z$')
    old_archives = []
    for f in RELEASE_DIR.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() != '.7z':
            continue
        m = pattern_re.match(f.name)
        if m:
            old_archives.append((f, m.group(1)))

    if not old_archives:
        print(f'  {C.gray("·")} release/: 无旧版本压缩包')
        return

    if keep_old:
        print(f'  {C.gray("·")} release/: 保留 {len(old_archives)} 个旧版本'
              f'（--keep-old-releases）')
        return

    # 删除所有旧版本（当前版本若存在，会被后续 7z 覆盖询问逻辑处理）
    total_size = 0
    deleted = 0
    for f, _ver in old_archives:
        try:
            total_size += f.stat().st_size
        except OSError:
            pass
        if safe_unlink(f):
            deleted += 1

    if deleted:
        print(f'  {C.green("✓")} release/: 清理 {deleted} 个旧版本压缩包'
              f' ({fmt_size(total_size)})')
    else:
        print(f'  {C.yellow("⚠")} release/: 清理失败')


def _report_old_imports():
    """
    扫描源码，报告残留的旧依赖 import（只报告，不自动删）。

    ★ 跳过 OLD_DEP_SCAN_SKIP_DIRS 中的目录（默认 scripts/），
      因为构建工具自身会包含 PySide6 / PyQt5 等字符串（模式定义 / 提示语），
      若参与扫描会产生大量误报。
    """
    hits = []
    for p in PROJECT_ROOT.rglob('*'):
        if not p.is_file():
            continue
        if p.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if is_protected(p):
            continue
        if p.name.endswith(('.min.js', '.min.css')):
            continue

        # ★ 跳过构建工具目录（scripts/ 等）
        try:
            rel_parts = p.relative_to(PROJECT_ROOT).parts
            if rel_parts and rel_parts[0] in OLD_DEP_SCAN_SKIP_DIRS:
                continue
        except ValueError:
            continue

        try:
            text = p.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            # 忽略纯注释行，进一步减少误报
            stripped = line.lstrip()
            if stripped.startswith(('#', '//', '/*', '*')):
                continue
            for dep_name, pat in OLD_DEP_PATTERNS:
                if pat.search(line):
                    hits.append((p, line_no, dep_name))
                    break

    if not hits:
        return
    print(f'  {C.yellow("⚠")} 源码中残留 {len(hits)} 处旧依赖引用：')
    for p, line_no, dep_name in hits[:5]:
        rel = str(p.relative_to(PROJECT_ROOT)).replace('\\', '/')
        print(f'      {C.yellow(dep_name)}  {rel}:{line_no}')
    if len(hits) > 5:
        print(f'      {C.gray(f"... 还有 {len(hits) - 5} 处")}')


def _clean_dist_junk():
    """清理 dist/ 里的 PyInstaller 残留（*.pdb / __pycache__ 等）。"""
    if not DIST_DIR.exists():
        return

    stats = {'files': 0, 'dirs': 0, 'bytes': 0}

    # 文件
    for pattern in DIST_JUNK_GLOBS:
        for p in DIST_DIR.rglob(pattern):
            if p.is_file():
                try:
                    stats['bytes'] += p.stat().st_size
                except OSError:
                    pass
                if safe_unlink(p):
                    stats['files'] += 1

    # 目录
    for name in DIST_JUNK_DIR_NAMES:
        for p in DIST_DIR.rglob(name):
            if p.is_dir():
                stats['bytes'] += dir_size(p)
                if rmtree(p):
                    stats['dirs'] += 1

    if stats['files'] or stats['dirs']:
        parts = []
        if stats['dirs']:
            parts.append(f'{stats["dirs"]} 目录')
        if stats['files']:
            parts.append(f'{stats["files"]} 文件')
        print(f'  {C.green("✓")} dist 残留: {", ".join(parts)} '
              f'({fmt_size(stats["bytes"])})')


def _ensure_dotnet_config() -> bool:
    """
    确保 MarkEase.exe.config 与 MarkEase.exe 位于同一目录。

    为什么必须要有：
      .NET Framework 会按程序集所在路径计算安全区域(Zone)。当路径包含中文
      （如包含中文字符的项目路径 <项目根>\\...）时，会被误判为 Internet
      区域，AppDomain.Load 直接抛 NotSupportedException(0x80131515)，
      pythonnet 的 clr_loader 捕获后静默返回 NULL，于是打包后的程序启动即报：
          Failed to resolve Python.Runtime.Loader.Initialize
      只有 <exe>.config 里开启 loadFromRemoteSources 才能修复。
    """
    src = PROJECT_ROOT / 'MarkEase.exe.config'
    dst = DIST_DIR / 'MarkEase.exe.config'

    if not src.is_file():
        print(f'  {C.red("✗")} 缺少 {src.name}'
              f'（.NET 程序集在中文/网络路径下将无法加载）')
        return False

    try:
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dst)
    except Exception as e:
        print(f'  {C.red("✗")} 复制 {src.name} 失败: {e}')
        return False

    print(f'  {C.green("✓")} .NET 运行时配置: {C.gray(src.name)}')
    return True


# ============================================================
#  阶段 3：vendor 验证
# ============================================================
def phase_verify_vendor() -> bool:
    if not VENDOR_DIR.is_dir():
        print(f'  {C.red("✗")} vendor 目录不存在: {rel_display(VENDOR_DIR)}')
        return False

    files = [f for f in VENDOR_DIR.iterdir()
             if f.is_file() and f.suffix in ('.mjs', '.js')]

    if len(files) < 20:
        print(f'  {C.yellow("⚠")} 只有 {len(files)} 个文件（预期 30+）')

    problems_http = []
    problems_missing = []

    for path in files:
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for m in IMPORT_RE.finditer(text):
            ref = m.group(1)
            if ref.startswith(('http://', 'https://')):
                problems_http.append((path.name, ref))
            elif ref.startswith(('./', '../')):
                target = (path.parent / ref).resolve()
                if not target.exists():
                    problems_missing.append((path.name, ref))

    if not problems_http and not problems_missing:
        print(f'  {C.green("✓")} {len(files)} 个文件，无外链，依赖完整')
        return True

    if problems_http:
        print(f'  {C.red("✗")} {len(problems_http)} 处残留外链：')
        for name, ref in problems_http[:5]:
            print(f'      {name}')
            print(f'        → {ref}')
        if len(problems_http) > 5:
            print(f'      {C.gray(f"... 还有 {len(problems_http) - 5} 处")}')

    if problems_missing:
        print(f'  {C.red("✗")} {len(problems_missing)} 处缺失依赖：')
        for name, ref in problems_missing[:5]:
            print(f'      {name}')
            print(f'        → {ref}')
        if len(problems_missing) > 5:
            print(f'      {C.gray(f"... 还有 {len(problems_missing) - 5} 处")}')

    return False


# ============================================================
#  阶段 4：PyInstaller 打包
# ============================================================
def phase_build() -> bool:
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean', '--noconfirm',
        str(SPEC_FILE),
    ]

    start = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
    )

    output_lines = []

    def reader():
        try:
            for line in proc.stdout:
                output_lines.append(line)
                if len(output_lines) > 300:
                    output_lines.pop(0)
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    spinner = ['|', '/', '-', '\\']
    idx = 0
    try:
        while proc.poll() is None:
            elapsed = int(time.time() - start)
            print(f'\r  {C.cyan(spinner[idx % 4])} 编译中 [{elapsed:>3}s]  ',
                  end='', flush=True)
            idx += 1
            time.sleep(0.15)
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        clear_current_line()
        print(f'  {C.yellow("✗")} 用户中止')
        return False
    finally:
        proc.wait()
        t.join(timeout=1.0)

    elapsed = time.time() - start

    # ★ 清空 spinner 行，避免与后续输出粘连
    clear_current_line(80)

    if proc.returncode != 0:
        print(f'  {C.red("✗")} 打包失败（{elapsed:.1f}s）\n')
        print(C.bold(C.red('--- PyInstaller 输出（末尾 30 行）---')))
        for line in output_lines[-30:]:
            print('  ' + line.rstrip())
        print(C.bold(C.red('--- 输出结束 ---')))
        return False

    # 检查产物
    exe = DIST_DIR / 'MarkEase.exe'
    if not exe.exists():
        print(f'  {C.red("✗")} 未找到产物 {rel_display(exe)}')
        return False

    # ★ 打包后自动清理 dist 残留
    _clean_dist_junk()

    # ★ 关键：补齐 exe 同目录的 .NET 运行时配置（否则中文路径下 pythonnet 无法加载）
    if not _ensure_dotnet_config():
        return False

    size = dir_size(DIST_DIR)
    print(f'  {C.green("✓")} 打包完成（{elapsed:.1f}s，{fmt_size(size)}）')
    return True


# ============================================================
#  阶段 5：7z 压缩
# ============================================================
def phase_compress(seven_zip: str, version: str, auto_yes: bool) -> bool:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    archive = RELEASE_DIR / f'MarkEase_v{version}_Windows_x64_portable.7z'

    # 覆盖询问（若 --yes 则跳过）
    if archive.exists() and not auto_yes:
        print(f'  {C.yellow("⚠")} 已存在: {archive.name}')
        prompt = '  ' + C.yellow('是否覆盖? (y/n): ')
        try:
            ans = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = 'n'
        if ans not in ('y', 'yes'):
            print(f'  {C.gray("·")} 已取消压缩')
            return False
        if not safe_unlink(archive):
            print(f'  {C.red("✗")} 无法删除旧文件')
            return False

    src_size = dir_size(DIST_DIR)

    cmd = [
        seven_zip, 'a', '-t7z',
        '-mx=9', '-mfb=273', '-ms=on', '-mmt=on',
        '-bsp1', '-bb1',
        str(archive), str(DIST_DIR),
    ]

    start = time.time()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
    )

    last_pct = -1
    for line in proc.stdout:
        m = re.search(r'(\d+)%', line)
        if not m:
            continue
        pct = int(m.group(1))
        if pct == last_pct:
            continue
        last_pct = pct
        bar = progress_bar(pct)
        print(f'\r  [{C.cyan(bar)}] {pct:>3}%', end='', flush=True)

    proc.wait()
    elapsed = time.time() - start

    # ★ 清空进度条行，避免残留 "]  97%" 之类的碎片
    clear_current_line(80)

    if proc.returncode != 0:
        print(f'  {C.red("✗")} 压缩失败（{elapsed:.1f}s）')
        return False

    dst_size = archive.stat().st_size
    ratio = dst_size / src_size * 100 if src_size > 0 else 0
    print(f'  {C.green("✓")} {archive.name}')
    print(f'      {fmt_size(src_size)} → {fmt_size(dst_size)} '
          f'({ratio:.1f}%，耗时 {elapsed:.1f}s)')
    return True


# ============================================================
#  主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='MarkEase 一键打包脚本（整合版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--skip-7z', action='store_true',
                        help='跳过 7z 压缩')
    parser.add_argument('--skip-clean', action='store_true',
                        help='跳过清理')
    parser.add_argument('--keep-build', action='store_true',
                        help='保留 build/ dist/')
    parser.add_argument('--keep-old-releases', action='store_true',
                        help='保留 release 里的旧版本压缩包')
    parser.add_argument('--no-color', action='store_true',
                        help='禁用彩色输出')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='覆盖压缩包时不询问')
    args = parser.parse_args()

    if args.no_color:
        C.ENABLED = False

    t0 = time.time()

    # ---------- 头部 ----------
    print(C.bold(C.blue('=' * 60)))
    print(C.bold(C.blue('  MarkEase 一键打包')))
    print(C.bold(C.blue('=' * 60)))
    print(f'  项目: {C.gray(str(PROJECT_ROOT))}')

    # ---------- 1/5 预检查 ----------
    phase_header(1, 5, '预检查')
    info = phase_precheck()
    if info is None:
        print()
        print(C.red('中止：预检查未通过。'))
        _pause_if_double_click()
        sys.exit(1)

    version = info['version']
    seven_zip = info.get('7z')
    print(f'  版本: {C.bold("v" + version)}')

    # ---------- 2/5 清理 ----------
    phase_header(2, 5, '清理（自动）')
    if args.skip_clean:
        print(f'  {C.gray("·")} 已跳过（--skip-clean）')
    else:
        phase_clean(
            keep_build=args.keep_build,
            keep_old_releases=args.keep_old_releases,
        )

    # ---------- 3/5 vendor 验证 ----------
    phase_header(3, 5, 'vendor 验证')
    if not phase_verify_vendor():
        print()
        print(C.red('中止：vendor 目录有问题。'))
        print(C.yellow('      请先运行: python scripts/fetch_vendor.py'))
        _pause_if_double_click()
        sys.exit(1)

    # ---------- 4/5 打包 ----------
    phase_header(4, 5, 'PyInstaller 打包')
    if not phase_build():
        _pause_if_double_click()
        sys.exit(1)

    # ---------- 5/5 压缩 ----------
    phase_header(5, 5, '7z 压缩')
    if args.skip_7z:
        print(f'  {C.gray("·")} 已跳过（--skip-7z）')
    elif not seven_zip:
        print(f'  {C.yellow("⚠")} 未找到 7-Zip，跳过压缩')
    else:
        phase_compress(seven_zip, version, auto_yes=args.yes)

    # ---------- 结尾 ----------
    elapsed = time.time() - t0
    print()
    print(C.bold(C.blue('=' * 60)))
    print(C.bold(C.green('  完成！')))
    print(C.bold(C.blue('=' * 60)))
    print(f'  版本:   {C.bold("v" + version)}')
    print(f'  产物:   {C.gray(rel_display(DIST_DIR))}')
    if not args.skip_7z and seven_zip:
        archive = RELEASE_DIR / f'MarkEase_v{version}_Windows_x64_portable.7z'
        if archive.exists():
            print(f'  发布:   {C.gray(rel_display(archive))}')
            print(f'           {C.gray(f"({fmt_size(archive.stat().st_size)})")}')
    print(f'  耗时:   {elapsed:.1f}s')

    _pause_if_double_click()


def _pause_if_double_click():
    """双击运行（无命令行参数）时，末尾暂停等待回车。"""
    if len(sys.argv) > 1:
        return
    if os.name != 'nt':
        return
    try:
        input('\n按回车键退出...')
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print()
        print(C.yellow('已中断'))
        sys.exit(130)
    except Exception as e:
        print()
        print(C.red(f'未捕获的异常: {e}'))
        import traceback
        traceback.print_exc()
        sys.exit(1)