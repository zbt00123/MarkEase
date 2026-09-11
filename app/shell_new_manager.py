# -*- coding: utf-8 -*-
"""
ShellNew 管理器
在 Windows 系统「新建」菜单中添加 Markdown 文档项。
菜单名称自动跟随系统语言。
"""

import ctypes
import winreg


# ---------- 系统语言识别 ----------
def get_system_locale_name() -> str:
    """获取系统 UI 语言，返回 'zh_CN' / 'en_US' 之类的字符串"""
    try:
        lang_id = ctypes.windll.kernel32.GetSystemDefaultUILanguage()
        primary = lang_id & 0x3FF
        sub = (lang_id >> 10) & 0x3F
        lang_map = {
            0x04: {0x01: "zh_CN", 0x02: "zh_TW", 0x03: "zh_HK"},
            0x09: {0x01: "en_US", 0x02: "en_GB"},
            0x11: {0x01: "ja_JP"},
            0x12: {0x01: "ko_KR"},
        }
        return lang_map.get(primary, {}).get(sub, "en_US")
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
    return SHELL_NEW_NAMES.get(get_system_locale_name(), "Markdown Document")


# ---------- 注册表路径 ----------
HKCU = winreg.HKEY_CURRENT_USER
MD_KEY = r"Software\Classes\.md"
SHELL_NEW_KEY = r"Software\Classes\.md\ShellNew"


# ---------- 状态检查 ----------
def is_shell_new_registered() -> bool:
    """检查「新建」菜单项是否已存在"""
    try:
        key = winreg.OpenKey(HKCU, SHELL_NEW_KEY, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return False

    try:
        winreg.QueryValueEx(key, "NullFile")
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)


# ---------- 注册 ----------
def register_shell_new(force: bool = False) -> bool:
    """
    注册 ShellNew 项。
    成功返回 True，失败返回 False（不抛异常）。
    """
    if is_shell_new_registered() and not force:
        return True

    try:
        # 1. 在 .md 下设置友好类型名（菜单显示名）
        name = get_localized_name()
        key = winreg.CreateKey(HKCU, MD_KEY)
        try:
            winreg.SetValueEx(key, "FriendlyTypeName", 0, winreg.REG_SZ, name)
        finally:
            winreg.CloseKey(key)

        # 2. 创建 ShellNew\NullFile（核心）
        key = winreg.CreateKey(HKCU, SHELL_NEW_KEY)
        try:
            winreg.SetValueEx(key, "NullFile", 0, winreg.REG_SZ, "")
        finally:
            winreg.CloseKey(key)

        # 3. 通知 Shell 刷新
        _refresh_shell()
        print(f"[ShellNew] 已注册，菜单名：{name}")
        return True

    except Exception as e:
        print(f"[ShellNew] 注册失败: {e}")
        return False


# ---------- 卸载（调试用） ----------
def unregister_shell_new() -> bool:
    """移除 ShellNew 项（不删除 .md 的其他关联）"""
    try:
        winreg.DeleteKey(HKCU, SHELL_NEW_KEY)
        _refresh_shell()
        print("[ShellNew] 已移除")
        return True
    except FileNotFoundError:
        return True
    except Exception as e:
        print(f"[ShellNew] 移除失败: {e}")
        return False


# ---------- 通知系统刷新 ----------
def _refresh_shell():
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


# ---------- 启动时调用 ----------
def ensure_shell_new_on_startup():
    """软件启动时调用：不存在则注册，已存在则跳过"""
    try:
        if not is_shell_new_registered():
            register_shell_new()
    except Exception as e:
        print(f"[ShellNew] 启动检查异常: {e}")