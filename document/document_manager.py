# -*- coding: utf-8 -*-
"""
文档管理模块
管理当前打开文档的路径、内容、未保存状态等
"""

from PySide6.QtCore import QObject, Signal
from document.file_manager import FileManager


class DocumentManager(QObject):
    """文档管理器，负责维护当前文档状态"""

    # 信号：文档修改状态改变（bool: 是否有未保存修改）
    modification_changed = Signal(bool)
    # 信号：文件路径改变（str: 新路径，可能为空字符串表示新文档）
    file_path_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path = ""          # 当前文件路径，空字符串表示新建未保存文档
        self._is_modified = False     # 是否有未保存修改

    @property
    def file_path(self) -> str:
        return self._file_path

    @property
    def is_modified(self) -> bool:
        return self._is_modified

    def new_document(self):
        """新建文档：清空路径和修改状态"""
        self._set_file_path("")
        self._set_modified(False)

    def open_document(self, path: str):
        """打开文档：设置路径，并重置修改状态"""
        self._set_file_path(path)
        self._set_modified(False)

    def mark_modified(self):
        """标记文档已修改"""
        self._set_modified(True)

    def mark_saved(self):
        """标记文档已保存（未修改状态）"""
        self._set_modified(False)

    def set_file_path(self, path: str):
        """设置文件路径（用于另存为）"""
        self._set_file_path(path)

    def _set_modified(self, modified: bool):
        if self._is_modified != modified:
            self._is_modified = modified
            self.modification_changed.emit(modified)

    def _set_file_path(self, path: str):
        if self._file_path != path:
            self._file_path = path
            self.file_path_changed.emit(path)