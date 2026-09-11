# -*- coding: utf-8 -*-
"""
ShellNew 管理器
负责在 Windows 系统的“新建”菜单中添加/移除 Markdown 文档项
菜单名称自动跟随系统语言
"""

import sys
import os
import winreg
import ctypes
from ctypes import wintypes


# ---------- 获取系统语言 ----------
def get_system_language_id() -> int:
    """获取系统默认 UI 语言 ID (LANGID)"""
    try:
        kernel32 = ctypes.windll.kernel32
        lang_id = kernel32.GetSystemDefaultUILanguage()
        return lang_id
    except Exception:
        return 0x0409  # 默认英语（美国）


def get_system_locale_name() -> str:
    """获取系统区域设置名称，如 'zh_CN', 'en_US', 'ja_JP'"""
    try:
        lang_id = get_system_language_id()
        # 主语言 ID（低 10 位）
        primary_lang = lang_id & 0x3FF
        # 子语言 ID
        sub_lang = (lang_id >> 10) & 0x3F

        lang_map = {
            0x04: {  # 中文
                0x01: "zh_CN",
                0x02: "zh_TW",
                0x03: "zh_HK",
            },
            0x09: {0x01: "en_US", 0x02: "en_GB"},  # 英语
            0x11: {0x01: "ja_JP"},                  # 日语
            0x12: {0x01: "ko_KR"},                  # 韩语
        }
        return lang_map.get(primary_lang, {}).get(sub_lang, "en_US")
    except Exception:
        return "en_US"


# ---------- 多语言菜单名称 ----------
SHELL_NEW_NAMES = {
    "zh_CN": "Markdown 文档",
    "zh_TW": "Markdown 文件",
    "en_US": "Markdown Document",
    "ko_KR": "Markdown 문서",
    "ja_JP": "Markdown ドキュメント",
}


def get_localized_name() -> str:
    """根据系统语言获取本地化的菜单项名称"""
    locale = get_system_locale_name()
    return SHELL_NEW_NAMES.get(locale, "Markdown Document")


# ---------- ShellNew 注册表操作 ----------
SHELL_NEW_KEY = r"Software\Classes\.md\ShellNew"
MD_EXT_KEY = r"Software\Classes\.md"
PROG_ID = "MarkEase.md"
PROG_ID_KEY = r"Software\Classes\MarkEase.md"


def _create_or_open_key(root, path, sub_key, access=winreg.KEY_WRITE):
    """安全地创建或打开注册表键"""
    try:
        key = winreg.OpenKey(root, path, 0, access)
    except FileNotFoundError:
        key = winreg.CreateKey(root, path)
    return key


def _set_value(root, path, name, value, value_type=winreg.REG_SZ):
    """设置注册表值"""
    key = _create_or_open_key(root, path)
    try:
        winreg.SetValueEx(key, name, 0, value_type, value)
    finally:
        winreg.CloseKey(key)


def _check_value_exists(root, path, name) -> bool:
    """检查注册表值是否存在"""
    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, name)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False


def _check_key_exists(root, path) -> bool:
    """检查注册表键是否存在"""
    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_READ)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False


def is_shell_new_registered() -> bool:
    """检查 ShellNew 是否已注册"""
    hkcr = winreg.HKEY_CURRENT_USER
    return (_check_key_exists(hkcr, SHELL_NEW_KEY) and
            _check_value_exists(hkcr, SHELL_NEW_KEY, "NullFile"))


def register_shell_new(force: bool = False) -> bool:
    """
    注册 ShellNew 项，使“新建”菜单中出现 Markdown 文档选项
    - force=True 时强制覆盖已有配置
    - 返回 True 表示成功
    """
    hkcr = winreg.HKEY_CURRENT_USER

    if is_shell_new_registered() and not force:
        print("[ShellNew] 已注册，跳过")
        return True

    try:
        # 1. 确保 .md 扩展名存在，并关联到 ProgID
        _set_value(hkcr, MD_EXT_KEY, "", PROG_ID)
        _set_value(hkcr, MD_EXT_KEY, "Content Type", "text/markdown")

        # 2. 创建 ProgID 并设置本地化友好名称
        localized_name = get_localized_name()
        _set_value(hkcr, PROG_ID_KEY, "", localized_name)
        _set_value(hkcr, PROG_ID_KEY, "FriendlyTypeName", localized_name)
        # 设置图标（使用 MarkEase 自己的图标）
        _set_value(hkcr, PROG_ID_KEY + r"\DefaultIcon", "",
                   get_exe_path() + ",0")

        # 3. 创建 ShellNew 键
        _set_value(hkcr, SHELL_NEW_KEY, "NullFile", "")

        # 4. 刷新资源管理器，让菜单立即生效
        _refresh_shell()

        print(f"[ShellNew] 注册成功，菜单名称：{localized_name}")
        return True

    except Exception as e:
        print(f"[ShellNew] 注册失败: {e}")
        return False


def unregister_shell_new() -> bool:
    """移除 ShellNew 项（用于卸载或调试）"""
    hkcr = winreg.HKEY_CURRENT_USER
    try:
        winreg.DeleteKey(hkcr, SHELL_NEW_KEY)
        _refresh_shell()
        print("[ShellNew] 已移除")
        return True
    except FileNotFoundError:
        print("[ShellNew] 不存在，无需移除")
        return True
    except Exception as e:
        print(f"[ShellNew] 移除失败: {e}")
        return False


def get_exe_path() -> str:
    """获取当前可执行文件路径"""
    if getattr(sys, 'frozen', False):
        return sys.executable
    else:
        # 开发模式：返回项目根目录下的虚拟路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, "MarkEase.exe")


def _refresh_shell():
    """通知资源管理器刷新，使注册表修改立即生效"""
    try:
        ctypes.windll.shell32.SHChangeNotify(
            0x08000000,  # SHCNE_ASSOCCHANGED
            0x0000,      # SHCNF_IDLIST
            None, None
        )
    except Exception:
        pass


def ensure_shell_new_on_startup():
    """
    在软件启动时调用：检查并按需注册 ShellNew
    静默执行，失败不影响主流程
    """
    try:
        if not is_shell_new_registered():
            register_shell_new()
    except Exception as e:
        print(f"[ShellNew] 启动检查失败: {e}")