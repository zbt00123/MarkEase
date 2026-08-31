# -*- coding: utf-8 -*-
"""
Markdown 编辑器控件
继承 QPlainTextEdit，集成行号显示、语法高亮、查找替换、缩放、主题适配
"""

from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QMenu
from PySide6.QtCore import Qt, QRect, QSize, QPoint
from PySide6.QtGui import (
    QPainter, QColor, QTextFormat, QTextCursor,
    QTextDocument, QFont, QPalette, QAction, QContextMenuEvent, QKeySequence
)

from editor.line_number_area import LineNumberArea
from editor.syntax_highlighter import MarkdownSyntaxHighlighter


class MarkdownEditor(QPlainTextEdit):
    """Markdown 编辑器，带有行号和语法高亮"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        self._highlighter = MarkdownSyntaxHighlighter(self.document())

        # 设置编辑器属性
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)  # 自动换行
        self.setTabStopDistance(40)

        # 默认颜色（浅色）
        self.line_number_bg_color = QColor("#f5f5f5")
        self.line_number_fg_color = QColor("#999999")
        self.line_number_current_fg = QColor("#000000")
        self.current_line_highlight = QColor("#f0f0f0")

        # ========== 设置默认字体：固定使用中韩文列表 ==========
        self.default_font_size = self.fontInfo().pointSizeF()
        font = self.font()
        font.setFamilies(["Microsoft YaHei", "Malgun Gothic"])
        font.setPointSizeF(self.default_font_size)
        self.setFont(font)
        # ======================================================

        # ========== 基础缩放系数（使编辑器在 100% 时显示为 150%） ==========
        self.base_font_scale = 1.5
        # =========================================================================

        # ========== 语言管理器（用于右键菜单翻译） ==========
        self.language_manager = None
        # ====================================================

        # 连接信号
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)

        # 初始化
        self._update_line_number_area_width()
        self._highlight_current_line()

    # ====================== 语言管理器设置 ======================
    def set_language_manager(self, lm):
        """注入语言管理器，用于翻译右键菜单"""
        self.language_manager = lm

    # ====================== 主题应用 ======================
    def apply_theme(self, is_dark: bool):
        if is_dark:
            editor_bg = "#2a2a2a"
            editor_fg = "#dcdcdc"
            line_number_bg = "#2a2a2a"
            line_number_fg = "#888888"
            line_number_current = "#ffffff"
            current_line_bg = "#1e3a5f"
        else:
            editor_bg = "#ffffff"
            editor_fg = "#1e1e1e"
            line_number_bg = "#f5f5f5"
            line_number_fg = "#999999"
            line_number_current = "#000000"
            current_line_bg = "#f0f0f0"

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(editor_bg))
        palette.setColor(QPalette.ColorRole.Text, QColor(editor_fg))
        self.setPalette(palette)

        self.line_number_bg_color = QColor(line_number_bg)
        self.line_number_fg_color = QColor(line_number_fg)
        self.line_number_current_fg = QColor(line_number_current)
        self.current_line_highlight = QColor(current_line_bg)

        self._highlighter.set_dark_mode(is_dark)

        self._line_number_area.update()
        self._highlight_current_line()

    # ====================== 行号区域相关 ======================
    def line_number_area_width(self) -> int:
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def _update_line_number_area_width(self):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), self.line_number_bg_color)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        current_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current_line:
                    painter.setPen(self.line_number_current_fg)
                else:
                    painter.setPen(self.line_number_fg_color)
                painter.drawText(
                    0, int(top), self._line_number_area.width() - 5,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, number
                )

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def _highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(self.current_line_highlight)
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    # ====================== 自定义右键菜单（多语言支持） ======================
    def contextMenuEvent(self, event: QContextMenuEvent):
        """自定义右键菜单，支持多语言"""
        menu = QMenu(self)

        def tr(key, default=""):
            if self.language_manager:
                return self.language_manager.tr(key, default)
            return default if default else key

        # 撤销
        undo_action = QAction(tr("undo", "Undo"), self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.undo)
        undo_action.setEnabled(self.document().isUndoAvailable())
        menu.addAction(undo_action)

        # 重做
        redo_action = QAction(tr("redo", "Redo"), self)
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(self.redo)
        redo_action.setEnabled(self.document().isRedoAvailable())
        menu.addAction(redo_action)

        menu.addSeparator()

        # 剪切
        cut_action = QAction(tr("cut", "Cut"), self)
        cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        cut_action.triggered.connect(self.cut)
        cut_action.setEnabled(self.textCursor().hasSelection())
        menu.addAction(cut_action)

        # 复制
        copy_action = QAction(tr("copy", "Copy"), self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(self.copy)
        copy_action.setEnabled(self.textCursor().hasSelection())
        menu.addAction(copy_action)

        # 粘贴
        paste_action = QAction(tr("paste", "Paste"), self)
        paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)

        # 删除
        delete_action = QAction(tr("delete", "Delete"), self)
        delete_action.triggered.connect(self._delete_selected)
        delete_action.setEnabled(self.textCursor().hasSelection())
        menu.addAction(delete_action)

        menu.addSeparator()

        # 全选
        select_all_action = QAction(tr("select_all", "Select All"), self)
        select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)

        menu.exec(event.globalPos())

    def _delete_selected(self):
        """删除选中的文本"""
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()

    # ====================== Markdown 格式化辅助方法 ======================

    def insert_text(self, text: str):
        self.insertPlainText(text)

    def wrap_selection(self, before: str, after: str = None):
        if after is None:
            after = before
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.insertText(before)
            cursor.setPosition(end + len(before))
            cursor.insertText(after)
            cursor.endEditBlock()
            cursor.setPosition(start + len(before))
            cursor.setPosition(end + len(before), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
        else:
            cursor.insertText(before + after)
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, len(after))
            self.setTextCursor(cursor)

    def insert_block(self, prefix: str, placeholder: str = ""):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.insertText(prefix + placeholder)
        self.setTextCursor(cursor)

    def make_bold(self):
        self.wrap_selection("**")

    def make_italic(self):
        self.wrap_selection("*")

    def make_strikethrough(self):
        self.wrap_selection("~~")

    def make_inline_code(self):
        self.wrap_selection("`")

    def make_heading(self, level: int):
        prefix = "#" * level + " "
        self.insert_block(prefix, "标题")

    def make_quote(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            doc = self.document()
            start_block = doc.findBlock(start)
            end_block = doc.findBlock(end)
            if end == end_block.position() and end_block != start_block:
                end_block = end_block.previous()
            lines = []
            block = start_block
            while block.isValid() and block.blockNumber() <= end_block.blockNumber():
                lines.append(block.text())
                block = block.next()
            new_lines = [f"> {line}" for line in lines]
            replacement = '\n'.join(new_lines)
            cursor.beginEditBlock()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(replacement)
            cursor.endEditBlock()
        else:
            self.insert_block("> ", "引用内容")

    def make_code_block(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            selected = selected.replace('\u2029', '\n')
            replacement = f"```\n{selected}\n```"
            cursor.insertText(replacement)
        else:
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            cursor.insertText("```\n代码块\n```\n")
            cursor.endEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.Up, QTextCursor.MoveMode.MoveAnchor, 2)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
            self.setTextCursor(cursor)

    def make_horizontal_rule(self):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.insertText("---\n")
        self.setTextCursor(cursor)

    def make_link(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            replacement = f"[{selected_text}](url)"
            cursor.insertText(replacement)
        else:
            cursor.insertText("[链接文字](url)")
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 4)
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 3)
            self.setTextCursor(cursor)

    def make_image(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected_text = cursor.selectedText()
            replacement = f"![{selected_text}](图片路径)"
            cursor.insertText(replacement)
        else:
            cursor.insertText("![图片描述](图片路径)")
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 4)
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, 3)
            self.setTextCursor(cursor)

    def make_unordered_list(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            lines = selected.split('\u2029')
            new_lines = [f"- {line}" for line in lines]
            replacement = '\n'.join(new_lines)
            cursor.insertText(replacement)
        else:
            self.insert_block("- ", "列表项")

    def make_ordered_list(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            lines = selected.split('\u2029')
            new_lines = [f"{i+1}. {line}" for i, line in enumerate(lines)]
            replacement = '\n'.join(new_lines)
            cursor.insertText(replacement)
        else:
            self.insert_block("1. ", "列表项")

    def make_task_list(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            lines = selected.split('\u2029')
            new_lines = [f"- [ ] {line}" for line in lines]
            replacement = '\n'.join(new_lines)
            cursor.insertText(replacement)
        else:
            self.insert_block("- [ ] ", "任务项")

    def make_table(self):
        table_template = (
            "| 列1 | 列2 | 列3 |\n"
            "| --- | --- | --- |\n"
            "| 内容 | 内容 | 内容 |\n"
        )
        cursor = self.textCursor()
        cursor.insertText(table_template)
        self.setTextCursor(cursor)

    # ====================== 鼠标点击切换任务列表状态 ======================
    def mousePressEvent(self, event):
        cursor_before = self.textCursor()
        has_selection = cursor_before.hasSelection()
        sel_start = cursor_before.selectionStart() if has_selection else -1
        sel_end = cursor_before.selectionEnd() if has_selection else -1

        super().mousePressEvent(event)

        if event.button() != Qt.MouseButton.LeftButton:
            return

        cursor = self.cursorForPosition(event.pos())
        if cursor.isNull():
            return

        block = cursor.block()
        line_text = block.text()

        stripped = line_text.lstrip()
        prefix_len = len(line_text) - len(stripped)
        marker_start = prefix_len
        marker_end = -1
        is_checked = None

        if stripped.startswith("- [ ] "):
            is_checked = False
            marker_end = prefix_len + len("- [ ] ")
        elif stripped.startswith("- [x] "):
            is_checked = True
            marker_end = prefix_len + len("- [x] ")

        if is_checked is not None and marker_start <= cursor.positionInBlock() <= marker_end:
            if has_selection and sel_start <= cursor.position() <= sel_end:
                self._toggle_task_lines(sel_start, sel_end, new_state=not is_checked)
            else:
                self._toggle_single_task_line_by_cursor(cursor, new_state=not is_checked)

    def _toggle_task_lines(self, start_pos: int, end_pos: int, new_state: bool):
        doc = self.document()
        start_block = doc.findBlock(start_pos)
        end_block = doc.findBlock(end_pos)
        if end_pos == end_block.position() and end_block != start_block:
            end_block = end_block.previous()

        lines = []
        block = start_block
        while block.isValid() and block.blockNumber() <= end_block.blockNumber():
            lines.append(block.text())
            block = block.next()

        new_lines = []
        for line in lines:
            new_lines.append(self._toggle_single_task_line(line, new_state))

        replacement = '\n'.join(new_lines)

        cursor = self.textCursor()
        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertText(replacement)
        cursor.endEditBlock()

    def _toggle_single_task_line_by_cursor(self, cursor: QTextCursor, new_state: bool):
        block = cursor.block()
        line_text = block.text()
        new_line = self._toggle_single_task_line(line_text, new_state)
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(new_line)
        cursor.endEditBlock()

    def _toggle_single_task_line(self, line: str, new_state: bool) -> str:
        stripped = line.lstrip()
        if stripped.startswith("- [ ] "):
            prefix = line[:len(line)-len(stripped)]
            rest = stripped[len("- [ ] "):]
            if new_state:
                return prefix + "- [x] " + rest
            else:
                return prefix + "- [ ] " + rest
        elif stripped.startswith("- [x] "):
            prefix = line[:len(line)-len(stripped)]
            rest = stripped[len("- [x] "):]
            if new_state:
                return prefix + "- [x] " + rest
            else:
                return prefix + "- [ ] " + rest
        else:
            return line

    # ====================== 查找与跳转辅助方法 ======================

    def find_text(self, text: str, case_sensitive: bool = False, whole_word: bool = False, backward: bool = False):
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_word:
            flags |= QTextDocument.FindFlag.FindWholeWords
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward

        cursor = self.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == text:
            if backward:
                cursor.setPosition(cursor.selectionStart())
            else:
                cursor.setPosition(cursor.selectionEnd())

        found_cursor = self.document().find(text, cursor, flags)
        if not found_cursor.isNull():
            self.setTextCursor(found_cursor)
            self.centerCursor()
            return True
        else:
            if backward:
                start_cursor = self.textCursor()
                start_cursor.movePosition(QTextCursor.MoveOperation.End)
                found_cursor = self.document().find(text, start_cursor, flags)
            else:
                start_cursor = self.textCursor()
                start_cursor.movePosition(QTextCursor.MoveOperation.Start)
                found_cursor = self.document().find(text, start_cursor, flags)
            if not found_cursor.isNull():
                self.setTextCursor(found_cursor)
                self.centerCursor()
                return True
        return False

    def replace_current(self, find_text: str, replace_text: str, case_sensitive: bool = False, whole_word: bool = False):
        cursor = self.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == find_text:
            cursor.insertText(replace_text)
            return True
        return False

    def replace_all(self, find_text: str, replace_text: str, case_sensitive: bool = False, whole_word: bool = False) -> int:
        count = 0
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)

        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_word:
            flags |= QTextDocument.FindFlag.FindWholeWords

        while True:
            found_cursor = self.document().find(find_text, cursor, flags)
            if found_cursor.isNull():
                break
            found_cursor.insertText(replace_text)
            cursor = found_cursor
            count += 1
        cursor.endEditBlock()
        return count

    def go_to_line(self, line_number: int):
        if line_number < 0 or line_number >= self.blockCount():
            return
        block = self.document().findBlockByNumber(line_number)
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def get_current_visible_heading_line_simple(self) -> int:
        line, _ = self.get_current_visible_heading_info()
        return line

    def get_current_visible_heading_info(self):
        viewport = self.viewport()
        viewport_height = viewport.height()
        center_y = viewport_height / 2

        cursor = self.cursorForPosition(QPoint(0, int(center_y)))
        center_block = cursor.block()

        block = center_block
        while block.isValid() and block.blockNumber() >= 0:
            text = block.text()
            if text.lstrip().startswith('#'):
                stripped = text.lstrip()
                if stripped and stripped[0] == '#':
                    if len(stripped) == 1 or stripped[1] == ' ':
                        block_geometry = self.blockBoundingGeometry(block)
                        block_top = block_geometry.top() - self.contentOffset().y()
                        offset_ratio = (block_top - center_y) / viewport_height
                        return block.blockNumber(), offset_ratio
            block = block.previous()

        block = center_block
        while block.isValid() and block.blockNumber() < self.blockCount():
            text = block.text()
            if text.lstrip().startswith('#'):
                stripped = text.lstrip()
                if stripped and stripped[0] == '#':
                    if len(stripped) == 1 or stripped[1] == ' ':
                        block_geometry = self.blockBoundingGeometry(block)
                        block_top = block_geometry.top() - self.contentOffset().y()
                        offset_ratio = (block_top - center_y) / viewport_height
                        return block.blockNumber(), offset_ratio
            block = block.next()
            if block.blockNumber() - center_block.blockNumber() > 100:
                break
        return -1, 0

    # ====================== 缩放功能（带基础偏移系数） ======================

    def zoom_in(self):
        self.zoomIn(1)

    def zoom_out(self):
        self.zoomOut(1)

    def reset_zoom(self):
        self.set_zoom_percent(100)

    def set_zoom_percent(self, percent: int):
        """
        设置编辑器缩放百分比。
        实际字体大小为 default_font_size * (percent/100) * base_font_scale
        同时保留字体族列表不变。
        """
        percent = max(10, min(500, percent))
        new_size = self.default_font_size * (percent / 100.0) * self.base_font_scale
        font = self.font()
        font.setFamilies(["Microsoft YaHei", "Malgun Gothic"])  # 确保保留列表
        font.setPointSizeF(new_size)
        self.setFont(font)