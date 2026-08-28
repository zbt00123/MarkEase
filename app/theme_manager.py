# -*- coding: utf-8 -*-
"""
主题管理器
支持跟随系统、深色、浅色三种主题，通过 QPalette 和 QSS 全局应用
使用 Fusion 样式保证 QSS 滚动条生效，并检测系统深色模式
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

class ThemeManager:
    """管理应用主题"""

    THEME_SYSTEM = "system"
    THEME_LIGHT = "light"
    THEME_DARK = "dark"

    # 浅色调色板
    LIGHT_PALETTE = QPalette()
    LIGHT_PALETTE.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.WindowText, QColor(30, 30, 30))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.ToolTipText, QColor(30, 30, 30))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.Text, QColor(30, 30, 30))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.ButtonText, QColor(30, 30, 30))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    LIGHT_PALETTE.setColor(QPalette.ColorRole.PlaceholderText, QColor(150, 150, 150))

    # 深色调色板
    DARK_PALETTE = QPalette()
    DARK_PALETTE.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    DARK_PALETTE.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    DARK_PALETTE.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    DARK_PALETTE.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
    DARK_PALETTE.setColor(QPalette.ColorRole.ToolTipBase, QColor(60, 60, 60))
    DARK_PALETTE.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    DARK_PALETTE.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    DARK_PALETTE.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    DARK_PALETTE.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    DARK_PALETTE.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    DARK_PALETTE.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    DARK_PALETTE.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))

    # 全局样式表（浅色）
    LIGHT_QSS = """
    QToolTip {
        background-color: #ffffff;
        color: #1e1e1e;
        border: 1px solid #cccccc;
    }
    QScrollBar:vertical {
        border: none;
        background: #f0f0f0;
        width: 12px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #c0c0c0;
        min-height: 20px;
        border-radius: 6px;
    }
    QScrollBar::handle:vertical:hover {
        background: #a0a0a0;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar:horizontal {
        border: none;
        background: #f0f0f0;
        height: 12px;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: #c0c0c0;
        min-width: 20px;
        border-radius: 6px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #a0a0a0;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    """

    # 全局样式表（深色）
    DARK_QSS = """
    QToolTip {
        background-color: #3c3c3c;
        color: #dcdcdc;
        border: 1px solid #555555;
    }
    QScrollBar:vertical {
        border: none;
        background: #353535;
        width: 12px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #606060;
        min-height: 20px;
        border-radius: 6px;
    }
    QScrollBar::handle:vertical:hover {
        background: #808080;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar:horizontal {
        border: none;
        background: #353535;
        height: 12px;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: #606060;
        min-width: 20px;
        border-radius: 6px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #808080;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    """

    def __init__(self):
        self.current_theme = self.THEME_SYSTEM

    def apply_theme(self, theme: str):
        """应用指定主题（system/light/dark）"""
        self.current_theme = theme
        app = QApplication.instance()
        if not app:
            return

        # 统一使用 Fusion 样式，确保 QSS 生效
        app.setStyle("Fusion")

        if theme == self.THEME_SYSTEM:
            # 检测系统深色模式
            if self._is_system_dark():
                self._apply_dark()
            else:
                self._apply_light()
        elif theme == self.THEME_LIGHT:
            self._apply_light()
        elif theme == self.THEME_DARK:
            self._apply_dark()

    def _apply_light(self):
        app = QApplication.instance()
        app.setPalette(self.LIGHT_PALETTE)
        app.setStyleSheet(self.LIGHT_QSS)
        self.current_theme = self.THEME_LIGHT  # 实际应用为浅色

    def _apply_dark(self):
        app = QApplication.instance()
        app.setPalette(self.DARK_PALETTE)
        app.setStyleSheet(self.DARK_QSS)
        self.current_theme = self.THEME_DARK  # 实际应用为深色

    def _is_system_dark(self) -> bool:
        """检测系统是否为深色模式（Qt 6.5+ 支持）"""
        app = QApplication.instance()
        if hasattr(app.styleHints(), 'colorScheme'):
            scheme = app.styleHints().colorScheme()
            return scheme == Qt.ColorScheme.Dark
        # 回退：默认浅色
        return False

    def get_current_theme(self) -> str:
        return self.current_theme