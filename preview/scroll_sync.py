# -*- coding: utf-8 -*-
"""
同步滚动管理器（纯比例版本）
基于滚动条比例的简单同步，稳定可靠
"""

from PySide6.QtCore import QObject


class ScrollSyncManager(QObject):
    """管理编辑器与预览的滚动同步"""

    def __init__(self, editor, preview, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.preview = preview
        self.sync_enabled = False
        self._syncing = False

    def set_sync_enabled(self, enabled: bool):
        self.sync_enabled = enabled
        if not enabled:
            self._syncing = False

    def on_editor_scrolled(self):
        """编辑器滚动事件处理（由主窗口调用）"""
        if not self.sync_enabled or self._syncing:
            return
        self._syncing = True
        try:
            editor_scroll = self.editor.verticalScrollBar()
            max_val = editor_scroll.maximum()
            if max_val > 0:
                ratio = editor_scroll.value() / max_val
                self.preview.set_scroll_ratio(ratio)
        finally:
            self._syncing = False

    def on_preview_ratio_changed(self, ratio: float):
        """预览滚动比例变化（由 PreviewWidget 信号触发）"""
        if not self.sync_enabled or self._syncing:
            return
        self._syncing = True
        try:
            editor_scroll = self.editor.verticalScrollBar()
            max_val = editor_scroll.maximum()
            if max_val > 0:
                editor_scroll.setValue(int(ratio * max_val))
        finally:
            self._syncing = False