# -*- coding: utf-8 -*-
"""
设置管理器
使用 QSettings 持久化保存用户设置
"""

from PySide6.QtCore import QSettings

class SettingsManager:
    """管理应用设置，提供默认值和读写接口"""

    def __init__(self):
        self.settings = QSettings("MarkEase", "MarkEase")
        self._init_defaults()

    def _init_defaults(self):
        """设置默认值（如果不存在）"""
        defaults = {
            "theme": "system",
            "language": "system",
            "window/width": 1200,
            "window/height": 800,
            "splitter_ratio": 0.5,
            "toc_visible": False,
            "toc_width": 200,
            "zoom_percent": 100,
            "sync_scroll": False,
        }
        for key, value in defaults.items():
            if not self.settings.contains(key):
                self.settings.setValue(key, value)

    # ====================== 通用读写 ======================

    def get(self, key: str, default=None):
        return self.settings.value(key, default)

    def set(self, key: str, value):
        self.settings.setValue(key, value)

    # ====================== 具体设置项 ======================

    @property
    def theme(self) -> str:
        return self.get("theme", "system")

    @theme.setter
    def theme(self, value: str):
        self.set("theme", value)

    @property
    def language(self) -> str:
        return self.get("language", "system")

    @language.setter
    def language(self, value: str):
        self.set("language", value)

    @property
    def window_size(self) -> tuple:
        width = int(self.get("window/width", 1200))
        height = int(self.get("window/height", 800))
        return width, height

    @window_size.setter
    def window_size(self, size: tuple):
        self.set("window/width", size[0])
        self.set("window/height", size[1])

    @property
    def splitter_ratio(self) -> float:
        return float(self.get("splitter_ratio", 0.5))

    @splitter_ratio.setter
    def splitter_ratio(self, value: float):
        self.set("splitter_ratio", value)

    @property
    def toc_visible(self) -> bool:
        return bool(self.get("toc_visible", False))

    @toc_visible.setter
    def toc_visible(self, value: bool):
        self.set("toc_visible", value)

    @property
    def toc_width(self) -> int:
        return int(self.get("toc_width", 200))

    @toc_width.setter
    def toc_width(self, value: int):
        self.set("toc_width", value)

    @property
    def zoom_percent(self) -> int:
        return int(self.get("zoom_percent", 100))

    @zoom_percent.setter
    def zoom_percent(self, value: int):
        self.set("zoom_percent", value)

    @property
    def sync_scroll(self) -> bool:
        return bool(self.get("sync_scroll", False))

    @sync_scroll.setter
    def sync_scroll(self, value: bool):
        self.set("sync_scroll", value)