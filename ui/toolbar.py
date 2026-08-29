# -*- coding: utf-8 -*-
"""
Markdown 格式工具栏
使用 Unicode 符号代替文字，并支持多语言提示
"""

from PySide6.QtWidgets import QToolBar, QToolButton
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor


class MarkdownToolBar(QToolBar):
    def __init__(self, editor, parent=None):
        super().__init__("Markdown 格式", parent)
        self.editor = editor
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        self._actions = []  # 存储所有动作及其翻译键
        self._create_actions()

        # 创建浅蓝色“»”图标
        self._light_blue_icon = self._make_extender_icon(QColor("#5686fe"))

        # 延迟设置扩展按钮图标，确保按钮已创建
        QTimer.singleShot(0, self._apply_extender_icon)
        QTimer.singleShot(500, self._apply_extender_icon)
        QTimer.singleShot(1000, self._apply_extender_icon)

    def _make_extender_icon(self, color):
        """绘制一个'»'字符图标，颜色由参数指定"""
        pixmap = QPixmap(26, 26)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(color)
        font = painter.font()
        font.setPointSize(32)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "»")
        painter.end()
        return QIcon(pixmap)

    def _apply_extender_icon(self):
        """将扩展按钮的图标替换为浅蓝色“»”图标"""
        for btn in self.findChildren(QToolButton):
            if btn.objectName() == "qt_toolbar_ext_button":
                btn.setIcon(self._light_blue_icon)
                btn.setIconSize(QSize(16, 16))
                break

    def _add_action(self, text, tooltip_key, callback, shortcut=None):
        action = QAction(text, self)
        action.setToolTip(tooltip_key)   # 临时存储键，update_tooltips 时替换
        action.setData(tooltip_key)      # 存储翻译键
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
        self.addAction(action)
        self._actions.append(action)
        return action

    def _create_actions(self):
        # 标题
        for level in range(1, 7):
            self._add_action(
                f"H{level}",
                f"heading_{level}",
                lambda checked, l=level: self.editor.make_heading(l)
            )
        self.addSeparator()

        # 加粗
        self._add_action("𝐁", "bold", self.editor.make_bold)
        # 斜体
        self._add_action("𝐼", "italic", self.editor.make_italic)
        # 删除线
        self._add_action("S̶", "strikethrough", self.editor.make_strikethrough)

        self.addSeparator()

        # 引用
        self._add_action("❝", "quote", self.editor.make_quote)
        # 行内代码
        self._add_action("</>", "inline_code", self.editor.make_inline_code)
        # 代码块
        self._add_action("```", "code_block", self.editor.make_code_block)
        # 分隔线
        self._add_action("—", "horizontal_rule", self.editor.make_horizontal_rule)

        self.addSeparator()

        # 链接
        self._add_action("🔗", "link", self.editor.make_link)
        # 图片
        self._add_action("🖼", "image", self.editor.make_image)

        self.addSeparator()

        # 无序列表
        self._add_action("•", "unordered_list", self.editor.make_unordered_list)
        # 有序列表
        self._add_action("1.", "ordered_list", self.editor.make_ordered_list)
        # 任务列表
        self._add_action("☑", "task_list", self.editor.make_task_list)

        self.addSeparator()

        # 表格：符号“田”
        self._add_action("田", "table", self.editor.make_table)

    def update_tooltips(self, language_manager):
        """根据语言管理器更新所有动作的提示文本"""
        for action in self._actions:
            key = action.data()
            if key:
                action.setToolTip(language_manager.tr(key))