# -*- coding: utf-8 -*-
"""
查找与替换浮动窗口
支持两种模式：仅查找（find）和查找替换（replace）
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QLabel
)
from PySide6.QtCore import Qt, Signal


class FindReplacePanel(QWidget):
    """查找替换浮动面板"""

    # 信号：请求查找下一个
    find_next_requested = Signal(str, bool, bool)
    # 信号：请求查找上一个
    find_prev_requested = Signal(str, bool, bool)
    # 信号：请求替换当前
    replace_requested = Signal(str, str, bool, bool)
    # 信号：请求全部替换
    replace_all_requested = Signal(str, str, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("查找与替换")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._init_ui()
        # 默认显示替换功能（可通过 set_mode 修改）
        self.set_mode(replace=True)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 查找行
        find_layout = QHBoxLayout()
        find_layout.addWidget(QLabel("查找:"))
        self.find_edit = QLineEdit()
        self.find_edit.setMinimumWidth(200)
        find_layout.addWidget(self.find_edit)
        layout.addLayout(find_layout)

        # 替换行（可隐藏）
        self.replace_layout = QHBoxLayout()
        self.replace_label = QLabel("替换:")
        self.replace_edit = QLineEdit()
        self.replace_edit.setMinimumWidth(200)
        self.replace_layout.addWidget(self.replace_label)
        self.replace_layout.addWidget(self.replace_edit)
        layout.addLayout(self.replace_layout)

        # 选项行
        options_layout = QHBoxLayout()
        self.case_sensitive_check = QCheckBox("区分大小写")
        self.whole_word_check = QCheckBox("全词匹配")
        options_layout.addWidget(self.case_sensitive_check)
        options_layout.addWidget(self.whole_word_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # 按钮行
        button_layout = QHBoxLayout()
        self.find_prev_btn = QPushButton("上一个")
        self.find_next_btn = QPushButton("下一个")
        self.replace_btn = QPushButton("替换")
        self.replace_all_btn = QPushButton("全部替换")
        self.close_btn = QPushButton("关闭")

        button_layout.addWidget(self.find_prev_btn)
        button_layout.addWidget(self.find_next_btn)
        button_layout.addWidget(self.replace_btn)
        button_layout.addWidget(self.replace_all_btn)
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)

        # 连接信号
        self.find_next_btn.clicked.connect(self._on_find_next)
        self.find_prev_btn.clicked.connect(self._on_find_prev)
        self.replace_btn.clicked.connect(self._on_replace)
        self.replace_all_btn.clicked.connect(self._on_replace_all)
        self.close_btn.clicked.connect(self.hide)

        # 回车触发查找下一个
        self.find_edit.returnPressed.connect(self._on_find_next)

    def set_mode(self, replace: bool):
        """设置面板模式：replace=True 显示替换功能，False 仅查找"""
        self.replace_label.setVisible(replace)
        self.replace_edit.setVisible(replace)
        self.replace_btn.setVisible(replace)
        self.replace_all_btn.setVisible(replace)
        if not replace:
            self.setWindowTitle("查找")
        else:
            self.setWindowTitle("查找与替换")
        # 调整窗口大小适应内容
        self.adjustSize()

    def _get_options(self):
        return (
            self.case_sensitive_check.isChecked(),
            self.whole_word_check.isChecked()
        )

    def _on_find_next(self):
        text = self.find_edit.text()
        if text:
            case, whole = self._get_options()
            self.find_next_requested.emit(text, case, whole)

    def _on_find_prev(self):
        text = self.find_edit.text()
        if text:
            case, whole = self._get_options()
            self.find_prev_requested.emit(text, case, whole)

    def _on_replace(self):
        find_text = self.find_edit.text()
        replace_text = self.replace_edit.text()
        if find_text:
            case, whole = self._get_options()
            self.replace_requested.emit(find_text, replace_text, case, whole)

    def _on_replace_all(self):
        find_text = self.find_edit.text()
        replace_text = self.replace_edit.text()
        if find_text:
            case, whole = self._get_options()
            self.replace_all_requested.emit(find_text, replace_text, case, whole)

    def showEvent(self, event):
        super().showEvent(event)
        self.find_edit.setFocus()
        self.find_edit.selectAll()