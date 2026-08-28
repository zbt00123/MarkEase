# -*- coding: utf-8 -*-
"""
Markdown 基础语法高亮器
支持浅色/深色主题切换，深色模式下使用高对比度颜色
"""

from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QTextDocument
from PySide6.QtCore import QRegularExpression

class MarkdownSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._dark = False
        self._formats = {}
        self._build_formats()
        self._build_rules()

    def _build_formats(self):
        """构建格式对象（根据当前主题）"""
        self._formats.clear()
        if not self._dark:
            # 浅色模式
            self._formats['heading'] = self._make_format(bold=True, color="#2c3e50")
            self._formats['bold'] = self._make_format(bold=True)
            self._formats['italic'] = self._make_format(italic=True)
            self._formats['inline_code'] = self._make_format(font_family="Consolas, monospace", color="#c7254e")
            self._formats['code_block'] = self._make_format(font_family="Consolas, monospace", color="#333333")
            self._formats['link'] = self._make_format(color="#0366d6", underline=True)
            self._formats['list'] = self._make_format(color="#e36209")
            self._formats['quote'] = self._make_format(color="#6a737d", italic=True)
        else:
            # 深色模式（高对比度）
            self._formats['heading'] = self._make_format(bold=True, color="#8ab4f8")   # 亮蓝
            self._formats['bold'] = self._make_format(bold=True)
            self._formats['italic'] = self._make_format(italic=True)
            self._formats['inline_code'] = self._make_format(font_family="Consolas, monospace", color="#ff7b72")
            self._formats['code_block'] = self._make_format(font_family="Consolas, monospace", color="#e6e6e6")
            self._formats['link'] = self._make_format(color="#58a6ff", underline=True)
            self._formats['list'] = self._make_format(color="#ffa657")
            self._formats['quote'] = self._make_format(color="#b0c4de", italic=True)   # 亮蓝灰

    def _make_format(self, bold=False, italic=False, color=None, underline=False, font_family=None):
        fmt = QTextCharFormat()
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        if color:
            fmt.setForeground(QColor(color))
        if underline:
            fmt.setFontUnderline(True)
        if font_family:
            fmt.setFontFamilies([font_family])
        return fmt

    def _build_rules(self):
        """构建正则规则列表"""
        self.rules = []
        self.rules.append((QRegularExpression(r"^#{1,6}\s.*$"), self._formats['heading']))
        self.rules.append((QRegularExpression(r"\*\*[^*\n]+\*\*|__[^_\n]+__"), self._formats['bold']))
        self.rules.append((QRegularExpression(r"(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_)"), self._formats['italic']))
        self.rules.append((QRegularExpression(r"`[^`\n]+`"), self._formats['inline_code']))
        self.rules.append((QRegularExpression(r"\[[^\]]+\]\([^)]+\)"), self._formats['link']))
        self.rules.append((QRegularExpression(r"^\s*[-*+]\s"), self._formats['list']))
        self.rules.append((QRegularExpression(r"^\s*\d+\.\s"), self._formats['list']))
        self.rules.append((QRegularExpression(r"^\s*>\s?.*$"), self._formats['quote']))

    def set_dark_mode(self, dark: bool):
        """切换深色模式并刷新"""
        if self._dark != dark:
            self._dark = dark
            self._build_formats()
            self._build_rules()
            self.rehighlight()

    def highlightBlock(self, text: str):
        for pattern, fmt in self.rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)