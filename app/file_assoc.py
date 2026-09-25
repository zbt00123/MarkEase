# -*- coding: utf-8 -*-
"""
MarkEase 文件关联模块（阶段 15 修订 2）

本次修订要点：
    1. ShellNew 只对 .md 注册（不再注册 .markdown，避免右键出现两项）
    2. 主动清理历史上误注册的 .markdown\\ShellNew
    3. 图标复制到 %LOCALAPPDATA%\\MarkEase\\MarkEase.ico（无中文路径），
       三处同写图标关联，彻底修复「白色图标」：
           - .md\\ShellNew\\IconPath
           - .md\\DefaultIcon
           - MarkEase.md\\DefaultIcon

功能：
    set_as_default_program()   注册 .md / .markdown 的默认打开程序
    register_shell_new()       右键 → 新建 里添加「Markdown 文件」（只 .md）
    is_default_program()       查询是否为默认程序
    setup_shell_new_on_first_run()
                              首次启动时自动注册（仅打包版）

设计原则：
    - 全部写 HKCU\\Software\\Classes，无需管理员权限
    - 不主动抢占默认程序，除非用户显式点击菜单项
    - 显示名跟随系统 UI 语言
"""

import os
import sys
import shutil
import ctypes

try:
    import winreg
    WINREG_OK = True
except ImportError:
    WINREG_OK = False


PROGID = 'MarkEase.md'

# 默认程序关联：.md 和 .markdown 都关联
ASSOC_EXTS = ('.md', '.markdown')

# ShellNew 只对 .md 注册（.markdown 不注册，避免右键出现两项）
SHELL_NEW_EXTS = ('.md',)


# ============================================================
#  系统语言 → 显示名
# ============================================================
def _get_display_name():
    try:
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except Exception:
        lcid = 0x0804

    if lcid in (0x0804, 0x1004, 0x0004):
        return 'Markdown 文件'
    if lcid in (0x0404, 0x0C04, 0x1404):
        return 'Markdown 檔案'
    if lcid == 0x0409:
        return 'Markdown File'
    if lcid in (0x0809, 0x0C09, 0x1009, 0x1409):
        return 'Markdown File'
    if lcid == 0x0411:
        return 'Markdown ファイル'
    if lcid == 0x0412:
        return 'Markdown 파일'

    primary = lcid & 0x3FF
    fallback = {
        0x04: 'Markdown 文件',
        0x09: 'Markdown File',
        0x11: 'Markdown ファイル',
        0x12: 'Markdown 파일',
    }
    return fallback.get(primary, 'Markdown File')


# ============================================================
#  路径工具
# ============================================================
def _get_exe_path():
    return os.path.abspath(sys.executable)


def _find_source_icon():
    """在打包目录 / 项目根目录中找图标源文件。"""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    names = ('图标.ico', 'icon.ico', 'MarkEase.ico')
    for name in names:
        p = os.path.join(base, 'resources', 'icons', name)
        if os.path.exists(p):
            return p
    return None


def _ensure_local_icon():
    """
    把 ico 复制到 %LOCALAPPDATA%\\MarkEase\\MarkEase.ico，返回绝对路径。

    为什么复制：
        源路径含中文「图标.ico」，某些 Windows 组件（iconcache 服务等）
        读取注册表中的图标路径时对中文路径处理不稳，会导致图标显示为空白。
        复制到纯 ASCII 路径（%LOCALAPPDATA%\\MarkEase\\）后，图标能稳定加载。

    失败时回退到源路径。
    """
    src = _find_source_icon()
    if not src:
        return None

    try:
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        dst_dir = os.path.join(base, 'MarkEase')
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, 'MarkEase.ico')

        need_copy = True
        if os.path.exists(dst):
            try:
                if os.path.getmtime(dst) >= os.path.getmtime(src) and \
                   os.path.getsize(dst) == os.path.getsize(src):
                    need_copy = False
            except Exception:
                pass

        if need_copy:
            shutil.copy2(src, dst)

        return dst
    except Exception:
        # 复制失败就退回源路径（虽然可能是中文路径，但聊胜于无）
        return src


# ============================================================
#  注册表原语
# ============================================================
def _set_default(root, subkey, value):
    with winreg.CreateKeyEx(root, subkey, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, '', 0, winreg.REG_SZ, value)


def _set_value(root, subkey, name, value):
    with winreg.CreateKeyEx(root, subkey, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _get_default(root, subkey):
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, '')
            return val
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _delete_key_recursive(root, subkey):
    """递归删除子键（不存在则忽略）。"""
    try:
        # 先递归删子键
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_key_recursive(root, subkey + '\\' + sub)
    except FileNotFoundError:
        return
    except Exception:
        pass

    # 清空值
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    name, _, _ = winreg.EnumValue(k, 0)
                except OSError:
                    break
                try:
                    winreg.DeleteValue(k, name)
                except Exception:
                    break
    except FileNotFoundError:
        return
    except Exception:
        pass

    # 删键
    try:
        winreg.DeleteKey(root, subkey)
    except Exception:
        pass


def _has_user_choice(ext):
    """
    检测 ext 是否被用户在「设置 → 默认应用」里显式指定过。
    如指定过，Windows 会写 UserChoice，会忽略 HKCU\\Software\\Classes 层。
    """
    try:
        key = r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts' \
              + '\\' + ext + r'\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, 'ProgId')
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _notify_shell():
    """通知 shell 刷新关联与图标缓存。"""
    try:
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


def _write_icon_associations(icon_path, exts):
    """
    三处同写图标关联，确保「新建」菜单、文件图标、打开方式都正确显示：
        1. <ext>\\ShellNew\\IconPath   —— 桌面右键「新建」项的图标
        2. <ext>\\DefaultIcon          —— 文件本身图标（扩展名级）
        3. MarkEase.md\\DefaultIcon    —— ProgID 级图标（打开方式等场景）
    """
    if not icon_path:
        return

    # 1) ShellNew 项图标（只对 SHELL_NEW_EXTS 写）
    for ext in exts:
        # 只对配置了 ShellNew 的扩展名写 IconPath
        if ext not in SHELL_NEW_EXTS:
            continue
        shellnew = r'Software\Classes' + '\\' + ext + r'\ShellNew'
        # IconPath 值：纯路径，用引号包裹
        _set_value(winreg.HKEY_CURRENT_USER, shellnew,
                   'IconPath', f'"{icon_path}"')

    # 2) 扩展名级 DefaultIcon
    for ext in exts:
        _set_default(winreg.HKEY_CURRENT_USER,
                     r'Software\Classes' + '\\' + ext + r'\DefaultIcon',
                     f'"{icon_path}",0')

    # 3) ProgID 级 DefaultIcon
    _set_default(winreg.HKEY_CURRENT_USER,
                 r'Software\Classes' + '\\' + PROGID + r'\DefaultIcon',
                 f'"{icon_path}",0')


# ============================================================
#  公共接口
# ============================================================
def is_default_program():
    if not WINREG_OK:
        return False
    try:
        val = _get_default(winreg.HKEY_CURRENT_USER,
                           r'Software\Classes\.md')
        return val == PROGID
    except Exception:
        return False


def set_as_default_program():
    """
    把 MarkEase 注册为 .md / .markdown 的默认打开程序。

    返回：
        {'ok': True, 'progid': ..., 'exe': ..., 'warnings': [...]}
        {'ok': False, 'error': ...}
    """
    if not WINREG_OK:
        return {'ok': False, 'error': '当前系统不支持注册表操作'}

    exe = _get_exe_path()
    icon = _ensure_local_icon()
    display_name = _get_display_name()
    warnings = []

    try:
        # ---- 1) 注册 ProgID ----
        base = r'Software\Classes' + '\\' + PROGID
        _set_default(winreg.HKEY_CURRENT_USER, base, display_name)
        _set_value(winreg.HKEY_CURRENT_USER, base,
                   'FriendlyTypeName', display_name)

        _set_default(winreg.HKEY_CURRENT_USER,
                     base + r'\shell\open\command',
                     f'"{exe}" "%1"')

        # ---- 2) 关联扩展名 ----
        for ext in ASSOC_EXTS:
            if _has_user_choice(ext):
                warnings.append(
                    f'{ext} 已被用户在「设置 → 默认应用」里指定过，'
                    f'请手动改选 MarkEase 才能生效'
                )
            _set_default(winreg.HKEY_CURRENT_USER,
                         r'Software\Classes' + '\\' + ext, PROGID)
            _set_value(winreg.HKEY_CURRENT_USER,
                       r'Software\Classes' + '\\' + ext + r'\OpenWithProgids',
                       PROGID, '')

        # ---- 3) 图标三处同写 ----
        _write_icon_associations(icon, ASSOC_EXTS)

        # ---- 4) 刷新系统 ----
        _notify_shell()

        return {
            'ok': True,
            'progid': PROGID,
            'exe': exe,
            'display_name': display_name,
            'warnings': warnings,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'ok': False, 'error': str(e)}


def register_shell_new():
    """
    在桌面右键 → 新建 里添加「Markdown 文件」（只对 .md）。

    本次修订：
        - 只对 .md 注册 ShellNew（不再对 .markdown 注册）
        - 主动清理历史上 .markdown\\ShellNew 遗留
        - 三处同写图标关联，修复白色图标

    返回：
        {'ok': True, 'name': 'Markdown 文件'}
        {'ok': False, 'error': ...}
    """
    if not WINREG_OK:
        return {'ok': False, 'error': '当前系统不支持注册表操作'}

    display_name = _get_display_name()
    icon = _ensure_local_icon()

    try:
        # ---- 1) 清理遗留（老版本曾给 .markdown 注册 ShellNew）----
        _delete_key_recursive(
            winreg.HKEY_CURRENT_USER,
            r'Software\Classes\.markdown\ShellNew')

        # ---- 2) 确保 ProgID 存在 ----
        base = r'Software\Classes' + '\\' + PROGID
        _set_default(winreg.HKEY_CURRENT_USER, base, display_name)
        _set_value(winreg.HKEY_CURRENT_USER, base,
                   'FriendlyTypeName', display_name)

        # ---- 3) 写 ShellNew（只对 .md）----
        for ext in SHELL_NEW_EXTS:
            shellnew_key = r'Software\Classes' + '\\' + ext + r'\ShellNew'
            # NullFile='' 表示创建一个 0 字节空文件
            _set_value(winreg.HKEY_CURRENT_USER, shellnew_key, 'NullFile', '')

        # ---- 4) 图标三处同写 ----
        _write_icon_associations(icon, ASSOC_EXTS)

        # ---- 5) 刷新系统 ----
        _notify_shell()

        return {'ok': True, 'name': display_name}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'ok': False, 'error': str(e)}


def setup_shell_new_on_first_run():
    """
    首次启动 / 版本升级时自动注册 ShellNew（仅打包版执行，源码运行跳过）。

    返回：
        {'ok': True,  'skipped': False, 'name': ...}
        {'ok': False, 'skipped': True,  'reason': ...}
    """
    if not getattr(sys, 'frozen', False):
        return {'ok': False, 'skipped': True, 'reason': 'not frozen'}

    if not WINREG_OK:
        return {'ok': False, 'skipped': True, 'reason': 'no winreg'}

    result = register_shell_new()
    if result.get('ok'):
        return {
            'ok': True,
            'skipped': False,
            'name': result.get('name', ''),
        }
    return {
        'ok': False,
        'skipped': False,
        'error': result.get('error', '未知错误'),
    }