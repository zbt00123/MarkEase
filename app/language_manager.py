# -*- coding: utf-8 -*-
"""
语言管理器
加载翻译文件，提供翻译函数 tr()
支持跟随系统、简中、繁中、英、韩、日
"""

import json
import os
from PySide6.QtCore import QLocale, QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

class LanguageManager(QObject):
    """管理应用语言，提供翻译"""

    LANGUAGE_SYSTEM = "system"
    LANGUAGE_ZH_CN = "zh_CN"
    LANGUAGE_ZH_TW = "zh_TW"
    LANGUAGE_EN_US = "en_US"
    LANGUAGE_KO_KR = "ko_KR"
    LANGUAGE_JA_JP = "ja_JP"

    language_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_language = self.LANGUAGE_SYSTEM
        self.translations = {}
        self._load_translations(self._get_system_language_code())

    def _get_system_language_code(self) -> str:
        locale = QLocale.system()
        lang = locale.name()
        if lang.startswith("zh_CN"):
            return self.LANGUAGE_ZH_CN
        elif lang.startswith("zh_TW") or lang.startswith("zh_HK"):
            return self.LANGUAGE_ZH_TW
        elif lang.startswith("ko"):
            return self.LANGUAGE_KO_KR
        elif lang.startswith("ja"):
            return self.LANGUAGE_JA_JP
        else:
            return self.LANGUAGE_EN_US

    def _load_translations(self, lang_code: str):
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "translations")
        file_path = os.path.join(base_dir, f"{lang_code}.json")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.translations = json.load(f)
        except FileNotFoundError:
            # 回退到英文
            with open(os.path.join(base_dir, "en_US.json"), "r", encoding="utf-8") as f:
                self.translations = json.load(f)

    def set_language(self, lang_code: str):
        if lang_code == self.LANGUAGE_SYSTEM:
            lang_code = self._get_system_language_code()
        self._load_translations(lang_code)
        self.current_language = lang_code
        self._apply_font_for_language(lang_code)
        self.language_changed.emit(lang_code)

    def _apply_font_for_language(self, lang_code: str):
        """根据语言设置合适的字体（韩语使用 Malgun Gothic，避免过粗）"""
        app = QApplication.instance()
        if not app:
            return
        if lang_code == self.LANGUAGE_KO_KR:
            font = QFont("Malgun Gothic", 9)
            font.setWeight(QFont.Weight.Normal)
            app.setFont(font)
        else:
            # 恢复系统默认字体
            app.setFont(QFont())  # 默认字体

    def tr(self, key: str, default: str = "") -> str:
        return self.translations.get(key, default if default else key)

    def get_current_language(self) -> str:
        return self.current_language