# -*- coding: utf-8 -*-
"""
预览桥接模块
负责 Python 与 JavaScript 之间的通信（预留扩展接口）
"""

from PySide6.QtCore import QObject, Slot


class PreviewBridge(QObject):
    """处理预览页面的消息（例如点击链接、目录跳转等）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 预留信号，例如 linkClicked、scrollChanged 等