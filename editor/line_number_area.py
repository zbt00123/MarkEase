# -*- coding: utf-8 -*-
"""
行号区域控件
显示编辑器左侧的行号，自动跟随滚动
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QColor

class LineNumberArea(QWidget):
    """行号区域，用于显示编辑器行号"""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)