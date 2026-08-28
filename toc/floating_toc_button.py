# -*- coding: utf-8 -*-
"""
目录悬浮按钮（嵌入式）
作为主窗口的子控件，可上下拖动，点击切换目录显示
"""

from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QMouseEvent


class FloatingTocButton(QPushButton):
    """悬浮目录按钮"""

    # 自定义信号：按钮被拖动（请求移动），由主窗口处理位置约束
    dragged = Signal(QPoint)  # 新位置（全局坐标）

    def __init__(self, parent=None):
        super().__init__("☰", parent)
        self.setFixedSize(32, 32)
        # 悬停光标为手指
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 初始样式（浅色），深色模式由主窗口统一切换
        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(150, 150, 150, 100);
                border-radius: 16px;
                font-size: 16px;
                color: #333333;
                border: 1px solid rgba(0,0,0,30);
            }
            QPushButton:hover {
                background-color: rgba(150, 150, 150, 200);
            }
            QPushButton:pressed {
                background-color: rgba(120, 120, 120, 220);
            }
        """)
        self._press_pos = None      # 按下时的全局坐标
        self._drag_start = None     # 拖拽开始时的全局坐标
        self._dragging = False      # 是否正在拖拽

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._drag_start = self._press_pos
            self._dragging = False
            # 不阻止基类处理，以便点击事件正常触发
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton and self._press_pos is not None:
            current_pos = event.globalPosition().toPoint()
            # 移动超过 5 像素视为拖拽
            if (current_pos - self._press_pos).manhattanLength() > 5:
                self._dragging = True
                # 发射拖动信号，传递按钮新位置（全局）
                new_global = current_pos - (self._press_pos - self._drag_start)
                self.dragged.emit(new_global)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging:
            # 拖拽结束，忽略点击事件
            event.accept()
        else:
            # 非拖拽，正常触发点击
            super().mouseReleaseEvent(event)
        self._press_pos = None
        self._drag_start = None
        self._dragging = False