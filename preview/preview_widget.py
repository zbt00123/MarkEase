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
from PySide6.QtCore import QUrl, QObject, Slot, Signal, QTimer, Qt
from PySide6.QtGui import QColor, QKeySequence, QAction, QContextMenuEvent
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

        # ========== 关键设置：允许本地文件加载远程资源（如徽章图片） ==========
        settings = self.profile().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        # 可选：清空缓存强制重新加载
        # self.profile().clearHttpCache()
        # ======================================================================

    def acceptNavigationRequest(self, url: QUrl, navigation_type: QWebEnginePage.NavigationType, is_main_frame: bool):
        """
        拦截所有导航请求。
        - 本地文件（file://）放行。
        - 用户点击链接（LinkClicked）→ 系统浏览器打开，阻止加载。
        - 主框架跳转（JS 重定向等）→ 系统浏览器打开，阻止加载。
        - 子资源请求（图片、CSS、JS 等）→ 允许加载（保证徽章等图片正常显示）。
        """
        # 放行本地文件、about:blank、data:image 等
        if url.scheme() in ("file", "about", "data"):
            return True

        # 如果是用户点击链接触发的导航，在系统浏览器中打开并阻止
        if navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            webbrowser.open(url.toString())
            return False

        # 如果是主框架导航（例如 JS 跳转、地址栏输入等），在系统浏览器中打开并阻止
        if is_main_frame:
            webbrowser.open(url.toString())
            return False

        # 子资源请求（图片、CSS、JS 等）—— 允许加载
        return True

    def createWindow(self, navigation_type: QWebEnginePage.WebWindowType):
        """当页面请求创建新窗口时（如 target="_blank"），返回 None 以阻止创建"""
        return None


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
        self.language_manager = None  # 由外部设置

        # 设置页面背景色为白色，作为加载时的后备
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

        # 设置焦点策略，允许接收键盘事件
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_language_manager(self, lm):
        """注入语言管理器，用于翻译右键菜单"""
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

    def set_markdown(self, markdown_text: str, headings_map: list = None, theme: str = "light"):
        self._pending_theme = theme
        if not self._loaded:
            self._pending_markdown = markdown_text
            self._pending_headings = headings_map
            return

        self.page().runJavaScript(f"setTheme('{theme}');")

        headings_json = json.dumps(headings_map) if headings_map else "[]"
        js_code = f"window.renderMarkdown({markdown_text!r}, {headings_json});"
        self.page().runJavaScript(js_code)
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

    # ---------- 键盘事件处理 ----------
    def keyPressEvent(self, event):
        """支持 Ctrl+C 复制选中内容"""
        if event.matches(QKeySequence.StandardKey.Copy):
            self.page().triggerAction(QWebEnginePage.WebAction.Copy)
            event.accept()
            return
        super().keyPressEvent(event)

    # ---------- 自定义右键菜单 ----------
    def contextMenuEvent(self, event: QContextMenuEvent):
        """使用自定义菜单，支持翻译"""
        menu = QMenu(self)

        # 复制
        copy_action = QAction(self._tr("copy"), self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(lambda: self.page().triggerAction(QWebEnginePage.WebAction.Copy))
        menu.addAction(copy_action)

        # 全选
        select_all_action = QAction(self._tr("select_all"), self)
        select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all_action.triggered.connect(lambda: self.page().triggerAction(QWebEnginePage.WebAction.SelectAll))
        menu.addAction(select_all_action)

        menu.addSeparator()

        # 重新加载
        reload_action = QAction(self._tr("reload"), self)
        reload_action.triggered.connect(self.reload)
        menu.addAction(reload_action)

        menu.exec(event.globalPos())

    def _tr(self, key: str, default: str = "") -> str:
        """使用外部语言管理器翻译，若不可用则返回默认值"""
        if self.language_manager:
            return self.language_manager.tr(key, default)
        return default if default else key