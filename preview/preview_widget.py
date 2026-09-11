# -*- coding: utf-8 -*-
"""
Markdown 预览控件
基于 QWebEngineView，加载本地 HTML 页面并注入 Markdown 内容
支持主题切换、目录跳转、滚动同步、自定义右键菜单和复制快捷键
"""

import os
import json
import webbrowser
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings, QWebEngineProfile
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, QObject, Slot, Signal, QTimer, Qt, QMarginsF
from PySide6.QtGui import (
    QColor, QKeySequence, QAction, QContextMenuEvent, QShortcut,
    QPageLayout, QPageSize
)
from PySide6.QtWidgets import QMenu


class PreviewBridge(QObject):
    """与 JavaScript 通信的桥接对象"""
    on_scroll_called = Signal()
    scroll_ratio_reported = Signal(float)
    heading_reported = Signal(int)

    @Slot()
    def on_scroll(self):
        self.on_scroll_called.emit()

    @Slot(float)
    def report_scroll_ratio(self, ratio: float):
        self.scroll_ratio_reported.emit(ratio)

    @Slot(int)
    def report_heading(self, line: int):
        self.heading_reported.emit(line)


class PreviewPage(QWebEnginePage):
    """自定义 QWebEnginePage，允许本地页面访问远程资源，并拦截链接在外部浏览器打开"""

    def __init__(self, parent=None):
        super().__init__(parent)

        settings = self.profile().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        """把 JS 的 console 输出转发到 Python 控制台，方便排查问题"""
        try:
            level_name = {
                QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: "INFO",
                QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "WARN",
                QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: "ERROR",
            }.get(level, "LOG")
            print(f"[JS {level_name}] {sourceID}:{lineNumber} {message}")
        except Exception:
            pass
        # 不调用 super()，避免在部分 Qt 版本里默认弹窗

    def acceptNavigationRequest(self, url: QUrl, navigation_type: QWebEnginePage.NavigationType, is_main_frame: bool):
        if url.scheme() in ("file", "about", "data"):
            return True

        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            webbrowser.open(url.toString())
            return False

        if is_main_frame:
            webbrowser.open(url.toString())
            return False

        return True

    def createWindow(self, navigation_type: QWebEnginePage.WebWindowType):
        return None


class PreviewWidget(QWebEngineView):
    """Markdown 预览控件"""

    scroll_ratio_changed = Signal(float)
    heading_changed = Signal(int)
    pdf_export_finished = Signal(str, bool)   # (文件路径, 是否成功)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
        self.index_path = os.path.join(self.web_dir, "index.html")

        self._loaded = False
        self._pending_markdown = None
        self._pending_headings = None
        self._pending_theme = "light"
        self._pending_scroll_line = None
        self._zoom_percent = 100
        self.language_manager = None

        self._page = PreviewPage(self)
        self.setPage(self._page)

        qwebchannel_path = os.path.join(self.web_dir, "js", "qwebchannel.js")
        self.qwebchannel_available = os.path.exists(qwebchannel_path)

        if self.qwebchannel_available:
            self.channel = QWebChannel(self)
            self.bridge = PreviewBridge()
            self.channel.registerObject("bridge", self.bridge)
            self._page.setWebChannel(self.channel)
            self.bridge.on_scroll_called.connect(self._on_bridge_scroll)
            self.bridge.scroll_ratio_reported.connect(self.scroll_ratio_changed)
            self.bridge.heading_reported.connect(self.heading_changed)
        else:
            print("警告：未找到 qwebchannel.js，同步滚动功能将被禁用。")

        self.load(QUrl.fromLocalFile(self.index_path))
        self.loadFinished.connect(self._on_load_finished)

        self._scroll_debounce_timer = QTimer(self)
        self._scroll_debounce_timer.setSingleShot(True)
        self._scroll_debounce_timer.timeout.connect(self._fetch_scroll_info)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self._on_copy_shortcut)

        # PDF 导出信号
        self._page.pdfPrintingFinished.connect(self._on_pdf_printing_finished)

    def _on_copy_shortcut(self):
        if self.hasFocus() or self.isActiveWindow():
            self.page().triggerAction(QWebEnginePage.WebAction.Copy)

    def set_language_manager(self, lm):
        self.language_manager = lm

    def _on_load_finished(self, ok: bool):
        self._loaded = ok
        if ok:
            self.page().runJavaScript(f"setTheme('{self._pending_theme}');")
            self.setZoomFactor(self._zoom_percent / 100.0)
            if self._pending_markdown is not None:
                self.set_markdown(self._pending_markdown, self._pending_headings, self._pending_theme)
                self._pending_markdown = None
                self._pending_headings = None
            if self._pending_scroll_line is not None:
                self.scroll_to_line(self._pending_scroll_line)
                self._pending_scroll_line = None
        else:
            print("[PreviewWidget] 页面加载失败")

    def _build_js_args(self, markdown_text: str, headings_map) -> str:
        """
        把 Python 字符串安全地转换成 JS 字面量。
        关键：用 json.dumps 保证转义正确；再把 </ 替换为 <\\/ 防止
        字符串里出现 </script> 破坏 QWebEngine 内部 HTML 结构。
        """
        md_json = json.dumps(markdown_text, ensure_ascii=False)
        md_json = md_json.replace('</', '<\\/')

        if headings_map:
            headings_json = json.dumps(headings_map, ensure_ascii=False)
        else:
            headings_json = "[]"
        headings_json = headings_json.replace('</', '<\\/')

        return md_json, headings_json

    def set_markdown(self, markdown_text: str, headings_map: list = None, theme: str = "light"):
        self._pending_theme = theme
        if not self._loaded:
            self._pending_markdown = markdown_text
            self._pending_headings = headings_map
            return

        # 主题
        theme_json = json.dumps(theme, ensure_ascii=False)
        self.page().runJavaScript(f"setTheme({theme_json});")

        # Markdown 内容（用安全的字面量）
        md_json, headings_json = self._build_js_args(markdown_text, headings_map)
        js_code = f"window.renderMarkdown({md_json}, {headings_json});"
        self.page().runJavaScript(js_code)
        self.page().runJavaScript("document.body.offsetHeight;")

    def set_theme(self, theme: str):
        self._pending_theme = theme
        if self._loaded:
            theme_json = json.dumps(theme, ensure_ascii=False)
            self.page().runJavaScript(f"setTheme({theme_json});")

    def scroll_to_line(self, line: int):
        if not self._loaded:
            self._pending_scroll_line = line
            return
        self.page().runJavaScript(f"window.scrollToLine({int(line)});")

    def set_scroll_ratio(self, ratio: float):
        if not self._loaded:
            return
        self.page().runJavaScript(f"window.scrollToRatio({float(ratio)});")

    def set_zoom_percent(self, percent: int):
        self._zoom_percent = percent
        if self._loaded:
            self.setZoomFactor(percent / 100.0)

    def find_text(self, text: str, backward: bool = False, case_sensitive: bool = False):
        if not text:
            return
        flags = QWebEnginePage.FindFlag(0)
        if backward:
            flags |= QWebEnginePage.FindFlag.FindBackward
        if case_sensitive:
            flags |= QWebEnginePage.FindFlag.FindCaseSensitively
        self.page().findText(text, flags)

    # ==================== PDF 导出 ====================
    def export_to_pdf(self, output_path: str):
        """将当前预览导出为 PDF（A4 纵向，15mm 边距）"""
        if not self._loaded:
            print("[PreviewWidget] 页面未加载，无法导出 PDF")
            self.pdf_export_finished.emit(output_path, False)
            return

        # 先检查页面是否有内容，避免空页面导出
        self.page().runJavaScript(
            "document.getElementById('markdown-content') ? "
            "document.getElementById('markdown-content').innerHTML.length : -1;",
            lambda result: self._start_pdf_export(output_path, result)
        )

    def _start_pdf_export(self, output_path: str, content_length):
        try:
            content_length = int(content_length) if content_length is not None else -1
        except Exception:
            content_length = -1

        if content_length <= 0:
            print(f"[PreviewWidget] 预览内容为空(length={content_length})，取消导出")
            self.pdf_export_finished.emit(output_path, False)
            return

        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15),
            QPageLayout.Unit.Millimeter
        )
        print(f"[PreviewWidget] 开始 printToPdf: {output_path}")
        self.page().printToPdf(output_path, layout)

    def _on_pdf_printing_finished(self, file_path: str, success: bool):
        print(f"[PreviewWidget] printToPdf 完成: {file_path} success={success}")
        self.pdf_export_finished.emit(file_path, success)

    def _on_bridge_scroll(self):
        if not self.qwebchannel_available:
            return
        self._scroll_debounce_timer.start(100)

    def _fetch_scroll_info(self):
        if not self.qwebchannel_available:
            return
        js_code = """
        (function() {
            var headings = document.querySelectorAll('[data-line]');
            var viewportTop = window.scrollY;
            var viewportHeight = window.innerHeight;
            var center = viewportTop + viewportHeight / 2;
            var closest = -1;
            var closestDist = Infinity;
            for (var i = 0; i < headings.length; i++) {
                var rect = headings[i].getBoundingClientRect();
                var top = rect.top + window.scrollY;
                var dist = Math.abs(top - center);
                if (dist < closestDist) {
                    closestDist = dist;
                    closest = parseInt(headings[i].getAttribute('data-line'), 10);
                }
            }
            var ratio = getScrollRatio();
            return JSON.stringify({line: closest, ratio: ratio});
        })();
        """
        self.page().runJavaScript(js_code, self._handle_scroll_info_result)

    def _handle_scroll_info_result(self, result):
        if not result:
            return
        try:
            import json as json_module
            data = json_module.loads(result)
        except Exception:
            return
        line = data.get("line", -1)
        ratio = data.get("ratio", 0.0)
        self.scroll_ratio_changed.emit(ratio)
        self.heading_changed.emit(line)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            if self.hasFocus():
                self.page().triggerAction(QWebEnginePage.WebAction.Copy)
                event.accept()
                return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)

        copy_action = QAction(self._tr("copy"), self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(lambda: self.page().triggerAction(QWebEnginePage.WebAction.Copy))
        menu.addAction(copy_action)

        select_all_action = QAction(self._tr("select_all"), self)
        select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all_action.triggered.connect(lambda: self.page().triggerAction(QWebEnginePage.WebAction.SelectAll))
        menu.addAction(select_all_action)

        menu.addSeparator()

        reload_action = QAction(self._tr("reload"), self)
        reload_action.triggered.connect(self.reload)
        menu.addAction(reload_action)

        menu.exec(event.globalPos())

    def _tr(self, key: str, default: str = "") -> str:
        if self.language_manager:
            return self.language_manager.tr(key, default)
        return default if default else key