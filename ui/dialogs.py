# -*- coding: utf-8 -*-
"""
对话框模块
封装常用的对话框，支持多语言
"""

from PySide6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt

class MarkEaseDialogs:
    """对话框工具类"""

    @staticmethod
    def show_about(parent, title: str, html_content: str):
        """显示关于对话框（HTML 内容）"""
        msg = QMessageBox(parent)
        msg.setWindowTitle(title)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html_content)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    @staticmethod
    def show_unsaved_changes(parent, title: str, message: str, save_text: str, discard_text: str, cancel_text: str):
        """显示未保存修改对话框，返回 'save'、'discard' 或 'cancel'"""
        msg = QMessageBox(parent)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setIcon(QMessageBox.Icon.Question)
        save_btn = msg.addButton(save_text, QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton(discard_text, QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton(cancel_text, QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(save_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == save_btn:
            return "save"
        elif clicked == discard_btn:
            return "discard"
        else:
            return "cancel"

    @staticmethod
    def show_info(parent, title: str, message: str):
        QMessageBox.information(parent, title, message)

    @staticmethod
    def show_error(parent, title: str, message: str):
        QMessageBox.critical(parent, title, message)