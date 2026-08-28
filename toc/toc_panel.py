# -*- coding: utf-8 -*-
"""
目录面板
显示标题树，支持缩进、当前高亮、点击跳转、宽度调整、文字自动换行
"""

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QLabel
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor

from toc.toc_manager import TocItem


class TocPanel(QWidget):
    """目录面板，用于显示文档结构"""

    heading_clicked = Signal(int)  # 行号（0 基）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._headings = []
        self._current_item = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_label = QLabel("目录")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("background-color: #f0f0f0; padding: 4px; font-weight: bold;")
        layout.addWidget(self.title_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setWordWrap(True)                # 启用自动换行
        self.tree.setUniformRowHeights(False)      # 允许不同行高
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

        self.setMinimumWidth(150)
        self.setMaximumWidth(400)

        self.highlight_color = QColor("#cce5ff")
        self.title_bg_color = QColor("#f0f0f0")
        self.set_theme(self.highlight_color, self.title_bg_color)

    def set_theme(self, highlight_color, title_bg_color):
        self.highlight_color = highlight_color
        self.title_bg_color = title_bg_color
        self.title_label.setStyleSheet(
            f"background-color: {title_bg_color.name()}; padding: 4px; font-weight: bold;"
        )
        if self._current_item:
            self._current_item.setBackground(0, self.highlight_color)

    def set_headings(self, headings: list[TocItem]):
        """更新目录内容"""
        self._headings = headings
        self.tree.clear()
        self._current_item = None

        for heading in headings:
            item = QTreeWidgetItem([heading.text])
            item.setData(0, Qt.ItemDataRole.UserRole, heading.line_number)

            font = QFont()
            if heading.level == 1:
                font.setPointSize(11)
                font.setBold(True)
            elif heading.level == 2:
                font.setPointSize(10)
                font.setBold(True)
            else:
                font.setPointSize(9)
                font.setBold(False)
            item.setFont(0, font)

            # 动态计算行高：根据文本长度和面板宽度估算
            approx_width = self.tree.viewport().width() - 30  # 减去缩进和滚动条
            if approx_width < 50:
                approx_width = 200
            # 每个字符平均宽度（近似）
            char_width = 8
            chars_per_line = max(1, approx_width // char_width)
            lines = max(1, -(-len(heading.text) // chars_per_line))  # 向上取整
            line_height = font.pointSize() + 6
            item.setSizeHint(0, QSize(100, lines * line_height + 4))

            self.tree.addTopLevelItem(item)

    def set_current_heading(self, line_number: int):
        current_item = None
        for i, heading in enumerate(self._headings):
            if heading.line_number <= line_number:
                current_item = self.tree.topLevelItem(i)
            else:
                break

        if current_item and current_item != self._current_item:
            if self._current_item:
                self._current_item.setBackground(0, Qt.GlobalColor.transparent)
            current_item.setBackground(0, self.highlight_color)
            self._current_item = current_item
            self.tree.scrollToItem(current_item)

    def _on_item_clicked(self, item, column):
        line_number = item.data(0, Qt.ItemDataRole.UserRole)
        if line_number is not None:
            self.heading_clicked.emit(line_number)

    def clear(self):
        self.tree.clear()
        self._headings = []
        self._current_item = None