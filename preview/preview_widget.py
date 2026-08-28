# -*- coding: utf-8 -*-
"""
Markdown 预览控件
基于 QWebEngineView，加载本地 HTML 页面并注入 Markdown 内容
支持主题切换、目录跳转和滚动同步
"""

import os
import json
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, QObject, Slot, Signal, QTimer
from PySide6.QtGui import QColor


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


class PreviewWidget(QWebEngineView):
    """Markdown 预览控件"""

    scroll_ratio_changed = Signal(float)
    heading_changed = Signal(int)

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

        # 设置页面背景色为白色，作为加载时的后备
        self.page().setBackgroundColor(QColor("#ffffff"))

        qwebchannel_path = os.path.join(self.web_dir, "js", "qwebchannel.js")
        self.qwebchannel_available = os.path.exists(qwebchannel_path)

        if self.qwebchannel_available:
            self.channel = QWebChannel(self)
            self.bridge = PreviewBridge()
            self.channel.registerObject("bridge", self.bridge)
            self.page().setWebChannel(self.channel)
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

    def _on_load_finished(self, ok: bool):
        self._loaded = ok
        if ok:
            # 应用主题
            self.page().runJavaScript(f"setTheme('{self._pending_theme}');")
            # 应用缩放
            self.setZoomFactor(self._zoom_percent / 100.0)
            if self._pending_markdown is not None:
                self.set_markdown(self._pending_markdown, self._pending_headings, self._pending_theme)
                self._pending_markdown = None
                self._pending_headings = None
            if self._pending_scroll_line is not None:
                self.scroll_to_line(self._pending_scroll_line)
                self._pending_scroll_line = None

    def set_markdown(self, markdown_text: str, headings_map: list = None, theme: str = "light"):
        self._pending_theme = theme
        if not self._loaded:
            self._pending_markdown = markdown_text
            self._pending_headings = headings_map
            return

        # 确保主题已应用
        self.page().runJavaScript(f"setTheme('{theme}');")

        headings_json = json.dumps(headings_map) if headings_map else "[]"
        js_code = f"window.renderMarkdown({markdown_text!r}, {headings_json});"
        self.page().runJavaScript(js_code)
        # 强制刷新
        self.page().runJavaScript("document.body.offsetHeight;")

    def set_theme(self, theme: str):
        self._pending_theme = theme
        if self._loaded:
            self.page().runJavaScript(f"setTheme('{theme}');")

    def scroll_to_line(self, line: int):
        if not self._loaded:
            self._pending_scroll_line = line
            return
        js_code = f"window.scrollToLine({line});"
        self.page().runJavaScript(js_code)

    def set_scroll_ratio(self, ratio: float):
        if not self._loaded:
            return
        js_code = f"window.scrollToRatio({ratio});"
        self.page().runJavaScript(js_code)

    def set_zoom_percent(self, percent: int):
        self._zoom_percent = percent
        if self._loaded:
            self.setZoomFactor(percent / 100.0)

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
        except:
            return
        line = data.get("line", -1)
        ratio = data.get("ratio", 0.0)
        self.scroll_ratio_changed.emit(ratio)
        self.heading_changed.emit(line)