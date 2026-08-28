# -*- coding: utf-8 -*-
"""
Markdown 格式工具栏
使用 Unicode 符号代替文字
"""

from PySide6.QtWidgets import QToolBar
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction


class MarkdownToolBar(QToolBar):
    def __init__(self, editor, parent=None):
        super().__init__("Markdown 格式", parent)
        self.editor = editor
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        self._create_actions()

    def _create_actions(self):
        # 标题
        for level in range(1, 7):
            action = QAction(f"H{level}", self)
            action.setToolTip(f"标题 {level} 级")
            action.triggered.connect(lambda checked, l=level: self.editor.make_heading(l))
            self.addAction(action)

        self.addSeparator()

        # 加粗
        bold_action = QAction("𝐁", self)
        bold_action.setToolTip("加粗")
        bold_action.triggered.connect(self.editor.make_bold)
        self.addAction(bold_action)

        # 斜体
        italic_action = QAction("𝐼", self)
        italic_action.setToolTip("斜体")
        italic_action.triggered.connect(self.editor.make_italic)
        self.addAction(italic_action)

        # 删除线
        strike_action = QAction("S̶", self)
        strike_action.setToolTip("删除线")
        strike_action.triggered.connect(self.editor.make_strikethrough)
        self.addAction(strike_action)

        self.addSeparator()

        # 引用
        quote_action = QAction("❝", self)
        quote_action.setToolTip("引用")
        quote_action.triggered.connect(self.editor.make_quote)
        self.addAction(quote_action)

        # 行内代码
        code_action = QAction("</>", self)
        code_action.setToolTip("行内代码")
        code_action.triggered.connect(self.editor.make_inline_code)
        self.addAction(code_action)

        # 代码块
        code_block_action = QAction("```", self)
        code_block_action.setToolTip("代码块")
        code_block_action.triggered.connect(self.editor.make_code_block)
        self.addAction(code_block_action)

        # 分隔线
        hr_action = QAction("—", self)
        hr_action.setToolTip("分隔线")
        hr_action.triggered.connect(self.editor.make_horizontal_rule)
        self.addAction(hr_action)

        self.addSeparator()

        # 链接
        link_action = QAction("🔗", self)
        link_action.setToolTip("插入链接")
        link_action.triggered.connect(self.editor.make_link)
        self.addAction(link_action)

        # 图片
        image_action = QAction("🖼", self)
        image_action.setToolTip("插入图片")
        image_action.triggered.connect(self.editor.make_image)
        self.addAction(image_action)

        self.addSeparator()

        # 无序列表
        ul_action = QAction("•", self)
        ul_action.setToolTip("无序列表")
        ul_action.triggered.connect(self.editor.make_unordered_list)
        self.addAction(ul_action)

        # 有序列表
        ol_action = QAction("1.", self)
        ol_action.setToolTip("有序列表")
        ol_action.triggered.connect(self.editor.make_ordered_list)
        self.addAction(ol_action)

        # 任务列表
        task_action = QAction("☑", self)
        task_action.setToolTip("任务列表")
        task_action.triggered.connect(self.editor.make_task_list)
        self.addAction(task_action)

        self.addSeparator()

        # 表格
        table_action = QAction("⊞", self)
        table_action.setToolTip("插入表格")
        table_action.triggered.connect(self.editor.make_table)
        self.addAction(table_action)