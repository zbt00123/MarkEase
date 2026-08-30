# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent


class FloatingTocButton(QPushButton):
    mouse_entered = Signal()
    mouse_left = Signal()

    def __init__(self, parent=None):
        super().__init__("☰", parent)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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

    def enterEvent(self, event):
        self.mouse_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.mouse_left.emit()
        super().leaveEvent(event)