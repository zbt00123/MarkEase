# -*- coding: utf-8 -*-
"""
MarkEase 主窗口模块
集成文档管理、编辑器、菜单栏、状态栏、预览控件、工具栏、目录面板、查找替换、同步滚动、主题和语言
"""

import sys
import os
import subprocess
import json
import urllib.request
import webbrowser
import ctypes
import winreg
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QMenuBar, QMenu, QStatusBar, QFileDialog, QMessageBox,
    QSizePolicy, QSplitter, QToolBar, QDockWidget, QSlider
)
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QPoint
from PySide6.QtGui import QAction, QKeySequence, QCloseEvent, QActionGroup, QColor, QIcon

from app.constants import (
    APP_TITLE, APP_VERSION, MODE_EDIT, MODE_PREVIEW, MODE_SPLIT, MODE_LABELS,
    DEFAULT_WIDTH, DEFAULT_HEIGHT, MARKDOWN_FILE_FILTER, GITHUB_REPO, GITHUB_API_URL
)
from document.document_manager import DocumentManager
from document.file_manager import FileManager
from editor.markdown_editor import MarkdownEditor
from preview.preview_widget import PreviewWidget
from preview.scroll_sync import ScrollSyncManager
from ui.toolbar import MarkdownToolBar
from toc.toc_manager import TocManager
from toc.toc_panel import TocPanel
from editor.find_replace import FindReplacePanel
from app.settings_manager import SettingsManager
from app.theme_manager import ThemeManager
from app.language_manager import LanguageManager
from toc.floating_toc_button import FloatingTocButton


class MainWindow(QMainWindow):
    """MarkEase 主窗口"""

    def __init__(self):
        super().__init__()
        self.current_mode = MODE_EDIT

        # 初始化管理器
        self.settings = SettingsManager()
        self.theme_manager = ThemeManager()
        self.language_manager = LanguageManager()

        # 应用上次保存的主题和语言
        saved_theme = self.settings.theme
        saved_language = self.settings.language
        self.theme_manager.apply_theme(saved_theme)
        self.language_manager.set_language(saved_language)

        # 初始化文档管理器
        self.doc_manager = DocumentManager(self)

        # 初始化 UI
        self._init_window()
        self._init_central_widget()
        self._init_toc_panel()
        self._init_menu_bar()
        self._init_toolbar()

        # 缩放状态
        self.zoom_percent = self.settings.zoom_percent

        self._init_status_bar()
        self._init_find_replace_panel()
        self._init_zoom_controls()

        # 应用保存的缩放比例
        self.set_zoom_percent(self.zoom_percent)

        # 初始化同步滚动管理器
        self.scroll_sync_manager = ScrollSyncManager(self.editor, self.preview, self)
        self.editor.verticalScrollBar().valueChanged.connect(self._on_editor_scrolled)
        self.preview.scroll_ratio_changed.connect(self._on_preview_ratio_changed)
        self.preview.heading_changed.connect(self._on_preview_heading_changed)
        self.last_scroll_source = "editor"
        self.scroll_sync_manager.set_sync_enabled(False)

        # 连接编辑器文本和光标信号
        self.editor.textChanged.connect(self._on_editor_text_changed)
        self.editor.cursorPositionChanged.connect(self._on_cursor_position_changed)

        # 连接文档管理器信号
        self.doc_manager.modification_changed.connect(self._on_modification_changed)
        self.doc_manager.file_path_changed.connect(self._on_file_path_changed)

        # 应用默认模式
        self.set_mode(MODE_EDIT)

        # 恢复目录可见性和宽度
        if self.settings.toc_visible:
            self.toc_panel.setVisible(True)
        else:
            self.toc_panel.setVisible(False)
        self.toc_panel.setFixedWidth(self.settings.toc_width)

        # 应用主题到自定义控件
        self._apply_theme_to_widgets()

        # 初始更新预览和目录
        self._update_preview()
        self._update_toc()

        # 创建目录悬浮按钮
        self._init_floating_toc_button()

        # 语言改变时刷新 UI 文本
        self.language_manager.language_changed.connect(self._retranslate_ui)
        # 延迟刷新，确保所有控件已创建
        QTimer.singleShot(0, self._retranslate_ui)

        # 更新工具栏提示
        self._update_toolbar_tooltips()

    # ---------- UI 初始化 ----------
    def _init_window(self):
        """初始化窗口基本属性"""
        self.resize(*self.settings.window_size)
        self.setWindowTitle(APP_TITLE)

        # 设置窗口图标
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "resources", "icons", "图标.ico"
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def _init_central_widget(self):
        """初始化中央区域：左侧目录面板（可选）+ 右侧主区域（模式栏+工具栏+分割器）"""
        central = QWidget()
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # 左侧目录面板容器
        self.toc_container = QWidget()
        self.toc_layout = QVBoxLayout(self.toc_container)
        self.toc_layout.setContentsMargins(0, 0, 0, 0)
        self.toc_layout.setSpacing(0)
        central_layout.addWidget(self.toc_container)

        # 右侧主区域
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # 模式切换标签栏
        mode_bar = self._create_mode_bar()
        right_layout.addWidget(mode_bar)

        # 工具栏容器
        self.toolbar_container = QWidget()
        self.toolbar_layout = QVBoxLayout(self.toolbar_container)
        self.toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar_layout.setSpacing(0)
        right_layout.addWidget(self.toolbar_container)

        # 编辑/预览分割器
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor = MarkdownEditor()
        self.preview = PreviewWidget()
        # 注入语言管理器到预览控件，用于翻译右键菜单
        self.preview.set_language_manager(self.language_manager)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([int(self.width() * self.settings.splitter_ratio),
                                int(self.width() * (1 - self.settings.splitter_ratio))])
        right_layout.addWidget(self.splitter, 1)

        central_layout.addWidget(right_widget, 1)
        self.setCentralWidget(central)

    def _init_toc_panel(self):
        """初始化目录面板（放入左侧容器）"""
        self.toc_panel = TocPanel()
        self.toc_layout.addWidget(self.toc_panel)
        self.toc_panel.setVisible(False)
        self.toc_panel.heading_clicked.connect(self._on_toc_heading_clicked)

    def _init_floating_toc_button(self):
        """创建目录悬浮按钮，父控件设为中央控件"""
        central = self.centralWidget()
        self.floating_toc_btn = FloatingTocButton(central)
        self.floating_toc_btn.dragged.connect(self._on_floating_toc_btn_dragged)
        self.floating_toc_btn.clicked.connect(self.toggle_toc_panel)
        # 延迟更新位置，确保布局完成
        QTimer.singleShot(0, self._update_floating_toc_button_position)

    def _on_floating_toc_btn_dragged(self, global_pos: QPoint):
        """处理悬浮按钮拖动，应用位置约束"""
        parent = self.floating_toc_btn.parentWidget()
        if not parent:
            return
        local_pos = parent.mapFromGlobal(global_pos)
        self._constrain_floating_button(local_pos)

    def _constrain_floating_button(self, local_pos: QPoint):
        """根据目录状态和窗口布局约束按钮位置"""
        btn = self.floating_toc_btn
        parent = btn.parentWidget()
        if not parent:
            return
        btn_w = btn.width()
        btn_h = btn.height()

        # 确定 X 位置
        if self.toc_panel.isVisible():
            toc_right = self.toc_container.width()
            x = toc_right + 10
        else:
            x = 10

        # 确定 Y 范围：工具栏底部 到 状态栏顶部
        mode_bar_height = 48
        toolbar_height = self.toolbar_container.height() if self.toolbar_container.isVisible() else 0
        top_limit = mode_bar_height + toolbar_height + 10
        status_bar_height = self.statusBar().height()
        bottom_limit = parent.height() - status_bar_height - btn_h - 10

        y = local_pos.y()
        if y < top_limit:
            y = top_limit
        elif y > bottom_limit:
            y = bottom_limit

        btn.move(x, y)
        btn.raise_()

    def _update_floating_toc_button_position(self):
        """根据当前状态更新按钮位置"""
        if hasattr(self, 'floating_toc_btn'):
            current_pos = self.floating_toc_btn.pos()
            self._constrain_floating_button(current_pos)

    def _create_mode_bar(self):
        """创建模式切换标签栏：固定大小，左对齐，不随窗口宽度变化"""
        mode_bar = QWidget()
        mode_bar.setFixedHeight(48)
        layout = QHBoxLayout(mode_bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.btn_edit = QPushButton(MODE_LABELS[MODE_EDIT])
        self.btn_preview = QPushButton(MODE_LABELS[MODE_PREVIEW])
        self.btn_split = QPushButton(MODE_LABELS[MODE_SPLIT])

        for btn in (self.btn_edit, self.btn_preview, self.btn_split):
            btn.setMinimumWidth(100)      # 允许按钮根据文本扩展
            btn.setFixedHeight(32)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setStyleSheet("")
            btn.clicked.connect(self._on_mode_button_clicked)

        layout.addWidget(self.btn_edit)
        layout.addWidget(self.btn_preview)
        layout.addWidget(self.btn_split)
        return mode_bar

    def _init_toolbar(self):
        """初始化工具栏并添加到容器"""
        self.toolbar = MarkdownToolBar(self.editor)
        self.toolbar_layout.addWidget(self.toolbar)

    def _init_menu_bar(self):
        """初始化菜单栏"""
        menu_bar = self.menuBar()

        # 文件菜单
        self.file_menu = menu_bar.addMenu(self.language_manager.tr("file"))
        self.new_action = QAction(self.language_manager.tr("new"), self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_document)
        self.file_menu.addAction(self.new_action)

        self.open_action = QAction(self.language_manager.tr("open"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_document)
        self.file_menu.addAction(self.open_action)

        self.save_action = QAction(self.language_manager.tr("save"), self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_document)
        self.file_menu.addAction(self.save_action)

        self.save_as_action = QAction(self.language_manager.tr("save_as"), self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.save_document_as)
        self.file_menu.addAction(self.save_as_action)

        self.file_menu.addSeparator()

        self.reveal_action = QAction(self.language_manager.tr("reveal_in_explorer"), self)
        self.reveal_action.triggered.connect(self.reveal_in_explorer)
        self.file_menu.addAction(self.reveal_action)

        self.file_menu.addSeparator()
        self.exit_action = QAction(self.language_manager.tr("exit"), self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        # 编辑菜单
        self.edit_menu = menu_bar.addMenu(self.language_manager.tr("edit"))
        self.undo_action = QAction(self.language_manager.tr("undo"), self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.editor.undo)
        self.edit_menu.addAction(self.undo_action)

        self.redo_action = QAction(self.language_manager.tr("redo"), self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.editor.redo)
        self.edit_menu.addAction(self.redo_action)

        self.edit_menu.addSeparator()
        self.cut_action = QAction(self.language_manager.tr("cut"), self)
        self.cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        self.cut_action.triggered.connect(self.editor.cut)
        self.edit_menu.addAction(self.cut_action)

        self.copy_action = QAction(self.language_manager.tr("copy"), self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self.editor.copy)
        self.edit_menu.addAction(self.copy_action)

        self.paste_action = QAction(self.language_manager.tr("paste"), self)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self.editor.paste)
        self.edit_menu.addAction(self.paste_action)

        self.edit_menu.addSeparator()
        self.find_action = QAction(self.language_manager.tr("find"), self)
        self.find_action.setShortcut(QKeySequence.StandardKey.Find)
        self.find_action.triggered.connect(lambda: self.show_find_replace(False))
        self.edit_menu.addAction(self.find_action)

        self.replace_action = QAction(self.language_manager.tr("replace"), self)
        self.replace_action.setShortcut(QKeySequence("Ctrl+H"))
        self.replace_action.triggered.connect(lambda: self.show_find_replace(True))
        self.edit_menu.addAction(self.replace_action)

        # 窗口菜单
        self.window_menu = menu_bar.addMenu(self.language_manager.tr("window"))
        self.edit_mode_action = QAction(self.language_manager.tr("edit_mode"), self)
        self.edit_mode_action.triggered.connect(lambda: self.set_mode(MODE_EDIT))
        self.window_menu.addAction(self.edit_mode_action)

        self.preview_mode_action = QAction(self.language_manager.tr("preview_mode"), self)
        self.preview_mode_action.triggered.connect(lambda: self.set_mode(MODE_PREVIEW))
        self.window_menu.addAction(self.preview_mode_action)

        self.split_mode_action = QAction(self.language_manager.tr("split_mode"), self)
        self.split_mode_action.triggered.connect(lambda: self.set_mode(MODE_SPLIT))
        self.window_menu.addAction(self.split_mode_action)

        self.window_menu.addSeparator()
        self.toggle_toc_action = QAction(self.language_manager.tr("show_hide_toc"), self)
        self.toggle_toc_action.setCheckable(True)
        self.toggle_toc_action.triggered.connect(self.toggle_toc_panel)
        self.window_menu.addAction(self.toggle_toc_action)

        self.window_menu.addSeparator()
        self.zoom_in_action = QAction(self.language_manager.tr("zoom_in"), self)
        self.zoom_in_action.setShortcut(QKeySequence("Ctrl+="))
        self.zoom_in_action.triggered.connect(self.zoom_in)
        self.window_menu.addAction(self.zoom_in_action)

        self.zoom_out_action = QAction(self.language_manager.tr("zoom_out"), self)
        self.zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self.zoom_out_action.triggered.connect(self.zoom_out)
        self.window_menu.addAction(self.zoom_out_action)

        self.zoom_reset_action = QAction(self.language_manager.tr("reset_zoom"), self)
        self.zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        self.zoom_reset_action.triggered.connect(self.reset_zoom)
        self.window_menu.addAction(self.zoom_reset_action)

        self.sync_scroll_action = QAction(self.language_manager.tr("sync_scroll"), self)
        self.sync_scroll_action.setCheckable(True)
        self.sync_scroll_action.setChecked(self.settings.sync_scroll)
        self.sync_scroll_action.toggled.connect(self._on_sync_scroll_toggled)
        self.window_menu.addAction(self.sync_scroll_action)

        # 帮助菜单
        self.help_menu = menu_bar.addMenu(self.language_manager.tr("help"))

        # 主题子菜单
        self.theme_menu = self.help_menu.addMenu(self.language_manager.tr("theme"))
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)

        self.theme_system_action = QAction(self.language_manager.tr("system"), self)
        self.theme_system_action.setCheckable(True)
        self.theme_system_action.setActionGroup(self.theme_group)
        self.theme_system_action.triggered.connect(lambda: self.change_theme("system"))
        self.theme_system_action.setChecked(self.settings.theme == "system")
        self.theme_menu.addAction(self.theme_system_action)

        self.theme_light_action = QAction(self.language_manager.tr("light"), self)
        self.theme_light_action.setCheckable(True)
        self.theme_light_action.setActionGroup(self.theme_group)
        self.theme_light_action.triggered.connect(lambda: self.change_theme("light"))
        self.theme_light_action.setChecked(self.settings.theme == "light")
        self.theme_menu.addAction(self.theme_light_action)

        self.theme_dark_action = QAction(self.language_manager.tr("dark"), self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.setActionGroup(self.theme_group)
        self.theme_dark_action.triggered.connect(lambda: self.change_theme("dark"))
        self.theme_dark_action.setChecked(self.settings.theme == "dark")
        self.theme_menu.addAction(self.theme_dark_action)

        # 语言子菜单
        self.language_menu = self.help_menu.addMenu(self.language_manager.tr("language"))
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)

        self.language_system_action = QAction(self.language_manager.tr("system"), self)
        self.language_system_action.setCheckable(True)
        self.language_system_action.setActionGroup(self.language_group)
        self.language_system_action.triggered.connect(lambda: self.change_language("system"))
        self.language_system_action.setChecked(self.settings.language == "system")
        self.language_menu.addAction(self.language_system_action)

        self.language_zh_cn_action = QAction(self.language_manager.tr("zh_CN"), self)
        self.language_zh_cn_action.setCheckable(True)
        self.language_zh_cn_action.setActionGroup(self.language_group)
        self.language_zh_cn_action.triggered.connect(lambda: self.change_language("zh_CN"))
        self.language_zh_cn_action.setChecked(self.settings.language == "zh_CN")
        self.language_menu.addAction(self.language_zh_cn_action)

        self.language_zh_tw_action = QAction(self.language_manager.tr("zh_TW"), self)
        self.language_zh_tw_action.setCheckable(True)
        self.language_zh_tw_action.setActionGroup(self.language_group)
        self.language_zh_tw_action.triggered.connect(lambda: self.change_language("zh_TW"))
        self.language_zh_tw_action.setChecked(self.settings.language == "zh_TW")
        self.language_menu.addAction(self.language_zh_tw_action)

        self.language_en_us_action = QAction(self.language_manager.tr("en_US"), self)
        self.language_en_us_action.setCheckable(True)
        self.language_en_us_action.setActionGroup(self.language_group)
        self.language_en_us_action.triggered.connect(lambda: self.change_language("en_US"))
        self.language_en_us_action.setChecked(self.settings.language == "en_US")
        self.language_menu.addAction(self.language_en_us_action)

        self.language_ko_kr_action = QAction(self.language_manager.tr("ko_KR"), self)
        self.language_ko_kr_action.setCheckable(True)
        self.language_ko_kr_action.setActionGroup(self.language_group)
        self.language_ko_kr_action.triggered.connect(lambda: self.change_language("ko_KR"))
        self.language_ko_kr_action.setChecked(self.settings.language == "ko_KR")
        self.language_menu.addAction(self.language_ko_kr_action)

        self.language_ja_jp_action = QAction(self.language_manager.tr("ja_JP"), self)
        self.language_ja_jp_action.setCheckable(True)
        self.language_ja_jp_action.setActionGroup(self.language_group)
        self.language_ja_jp_action.triggered.connect(lambda: self.change_language("ja_JP"))
        self.language_ja_jp_action.setChecked(self.settings.language == "ja_JP")
        self.language_menu.addAction(self.language_ja_jp_action)

        # 更新菜单项
        self.help_menu.addSeparator()
        self.check_update_action = QAction(self.language_manager.tr("check_update"), self)
        self.check_update_action.triggered.connect(self.check_for_updates)
        self.help_menu.addAction(self.check_update_action)

        # 设置为默认程序
        self.set_default_program_action = QAction(self.language_manager.tr("set_default_program"), self)
        self.set_default_program_action.triggered.connect(self.set_as_default_program)
        self.help_menu.addAction(self.set_default_program_action)

        self.help_menu.addSeparator()
        self.about_action = QAction(self.language_manager.tr("about"), self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.help_menu.addAction(self.about_action)

    def _init_status_bar(self):
        """初始化状态栏"""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        self.status_doc_label = QLabel(self.language_manager.tr("saved"))
        status_bar.addWidget(self.status_doc_label)

        self.status_stats_label = QLabel("")
        status_bar.addPermanentWidget(self.status_stats_label)

        self.zoom_button = QPushButton(f"{self.zoom_percent}%")
        self.zoom_button.setFlat(True)
        self.zoom_button.setToolTip(self.language_manager.tr("zoom"))
        self.zoom_button.clicked.connect(self._show_zoom_menu)
        status_bar.addPermanentWidget(self.zoom_button)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 500)
        self.zoom_slider.setValue(self.zoom_percent)
        self.zoom_slider.setFixedWidth(100)
        self.zoom_slider.setToolTip(self.language_manager.tr("zoom"))
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        status_bar.addPermanentWidget(self.zoom_slider)

        self.sync_scroll_button = QPushButton(self.language_manager.tr("sync_scroll"))
        self.sync_scroll_button.setCheckable(True)
        self.sync_scroll_button.setChecked(self.settings.sync_scroll)
        self.sync_scroll_button.setToolTip(self.language_manager.tr("sync_scroll"))
        self.sync_scroll_button.setStyleSheet("""
            QPushButton:checked {
                background-color: #2a82da;
                color: white;
                border: 1px solid #1a5da8;
            }
        """)
        self.sync_scroll_button.toggled.connect(self._on_sync_scroll_toggled)
        status_bar.addPermanentWidget(self.sync_scroll_button)

        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setFlat(True)
        self.theme_toggle_button.setFixedWidth(32)
        self.theme_toggle_button.setToolTip(self.language_manager.tr("theme"))
        self.theme_toggle_button.clicked.connect(self.toggle_theme_quick)
        status_bar.addPermanentWidget(self.theme_toggle_button)
        self._update_theme_toggle_icon()

    def _init_find_replace_panel(self):
        self.find_replace_panel = FindReplacePanel(self)
        self.find_replace_panel.find_next_requested.connect(self._on_find_next)
        self.find_replace_panel.find_prev_requested.connect(self._on_find_prev)
        self.find_replace_panel.replace_requested.connect(self._on_replace)
        self.find_replace_panel.replace_all_requested.connect(self._on_replace_all)

    def _init_zoom_controls(self):
        self.zoom_menu = QMenu(self)
        zoom_values = [10, 25, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400, 450, 500]
        for value in zoom_values:
            action = QAction(f"{value}%", self)
            action.triggered.connect(lambda checked, v=value: self.set_zoom_percent(v))
            self.zoom_menu.addAction(action)

    # ---------- 主题应用 ----------
    def _apply_theme_to_widgets(self):
        theme = self.theme_manager.get_current_theme()
        is_dark = theme == "dark"
        self.editor.apply_theme(is_dark)
        if is_dark:
            self.toc_panel.set_theme(QColor("#1a5276"), QColor("#353535"))
        else:
            self.toc_panel.set_theme(QColor("#cce5ff"), QColor("#f0f0f0"))
        if hasattr(self, 'preview'):
            self.preview.set_theme(theme)

    # ---------- 语言更新 ----------
    def _retranslate_ui(self):
        self.file_menu.setTitle(self.language_manager.tr("file"))
        self.new_action.setText(self.language_manager.tr("new"))
        self.open_action.setText(self.language_manager.tr("open"))
        self.save_action.setText(self.language_manager.tr("save"))
        self.save_as_action.setText(self.language_manager.tr("save_as"))
        self.reveal_action.setText(self.language_manager.tr("reveal_in_explorer"))
        self.exit_action.setText(self.language_manager.tr("exit"))

        self.edit_menu.setTitle(self.language_manager.tr("edit"))
        self.undo_action.setText(self.language_manager.tr("undo"))
        self.redo_action.setText(self.language_manager.tr("redo"))
        self.cut_action.setText(self.language_manager.tr("cut"))
        self.copy_action.setText(self.language_manager.tr("copy"))
        self.paste_action.setText(self.language_manager.tr("paste"))
        self.find_action.setText(self.language_manager.tr("find"))
        self.replace_action.setText(self.language_manager.tr("replace"))

        self.window_menu.setTitle(self.language_manager.tr("window"))
        self.edit_mode_action.setText(self.language_manager.tr("edit_mode"))
        self.preview_mode_action.setText(self.language_manager.tr("preview_mode"))
        self.split_mode_action.setText(self.language_manager.tr("split_mode"))
        self.toggle_toc_action.setText(self.language_manager.tr("show_hide_toc"))
        self.zoom_in_action.setText(self.language_manager.tr("zoom_in"))
        self.zoom_out_action.setText(self.language_manager.tr("zoom_out"))
        self.zoom_reset_action.setText(self.language_manager.tr("reset_zoom"))
        self.sync_scroll_action.setText(self.language_manager.tr("sync_scroll"))

        self.help_menu.setTitle(self.language_manager.tr("help"))
        self.theme_menu.setTitle(self.language_manager.tr("theme"))
        self.language_menu.setTitle(self.language_manager.tr("language"))
        self.check_update_action.setText(self.language_manager.tr("check_update"))
        self.set_default_program_action.setText(self.language_manager.tr("set_default_program"))
        self.about_action.setText(self.language_manager.tr("about"))

        self.theme_system_action.setText(self.language_manager.tr("system"))
        self.theme_light_action.setText(self.language_manager.tr("light"))
        self.theme_dark_action.setText(self.language_manager.tr("dark"))
        self.language_system_action.setText(self.language_manager.tr("system"))
        self.language_zh_cn_action.setText(self.language_manager.tr("zh_CN"))
        self.language_zh_tw_action.setText(self.language_manager.tr("zh_TW"))
        self.language_en_us_action.setText(self.language_manager.tr("en_US"))
        self.language_ko_kr_action.setText(self.language_manager.tr("ko_KR"))
        self.language_ja_jp_action.setText(self.language_manager.tr("ja_JP"))

        self.status_doc_label.setText(
            self.language_manager.tr("saved") if not self.doc_manager.is_modified else self.language_manager.tr("unsaved")
        )
        self.zoom_button.setToolTip(self.language_manager.tr("zoom"))
        self.zoom_slider.setToolTip(self.language_manager.tr("zoom"))
        self.sync_scroll_button.setText(self.language_manager.tr("sync_scroll"))
        self.sync_scroll_button.setToolTip(self.language_manager.tr("sync_scroll"))
        self.theme_toggle_button.setToolTip(self.language_manager.tr("theme"))

        self.btn_edit.setText("✏️ " + self.language_manager.tr("edit_mode"))
        self.btn_preview.setText("🔎 " + self.language_manager.tr("preview_mode"))
        self.btn_split.setText("📖 " + self.language_manager.tr("split_mode"))

        self.toc_panel.title_label.setText(self.language_manager.tr("toc_title"))

        self._update_stats_label()
        self._update_toolbar_tooltips()
        self._update_theme_toggle_icon()

    def _update_stats_label(self):
        if hasattr(self, 'editor'):
            text = self.editor.toPlainText()
            char_count = len(text)
            line_count = self.editor.blockCount()
            self.status_stats_label.setText(
                f"{self.language_manager.tr('words')}: {char_count} | {self.language_manager.tr('lines')}: {line_count}"
            )

    def _update_toolbar_tooltips(self):
        if hasattr(self, 'toolbar'):
            self.toolbar.update_tooltips(self.language_manager)

    # ---------- 主题切换 ----------
    def change_theme(self, theme: str):
        self.theme_manager.apply_theme(theme)
        self.settings.theme = theme
        self._update_theme_toggle_icon()
        self._apply_theme_to_widgets()
        self.editor.viewport().update()
        self.editor._line_number_area.update()
        self._update_preview()

    def toggle_theme_quick(self):
        current = self.theme_manager.get_current_theme()
        if current == "dark":
            self.change_theme("light")
        else:
            self.change_theme("dark")

    def _update_theme_toggle_icon(self):
        current = self.theme_manager.get_current_theme()
        if current == "dark":
            self.theme_toggle_button.setText("☀️")
        else:
            self.theme_toggle_button.setText("🌙")

    # ---------- 语言切换 ----------
    def change_language(self, lang: str):
        self.language_manager.set_language(lang)
        self.settings.language = lang
        self._retranslate_ui()

    # ---------- 更新检查 ----------
    def _get_latest_release_info(self):
        try:
            with urllib.request.urlopen(GITHUB_API_URL, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                tag = data.get('tag_name', '')
                version = tag.lstrip('v')
                notes = data.get('body', '')
                html_url = data.get('html_url', '')
                return version, notes, html_url
        except Exception:
            return None

    def _version_tuple(self, v):
        try:
            return tuple(map(int, v.split('.')))
        except:
            return (0, 0, 0)

    def _is_newer_version(self, latest: str) -> bool:
        return self._version_tuple(latest) > self._version_tuple(APP_VERSION)

    def check_for_updates(self):
        info = self._get_latest_release_info()
        if not info:
            QMessageBox.warning(self,
                                self.language_manager.tr("update_error_title"),
                                self.language_manager.tr("update_error_message"))
            return
        latest, notes, url = info
        if self._is_newer_version(latest):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.language_manager.tr("update_available_title"))
            msg_box.setText(self.language_manager.tr("update_available_message").format(
                version=latest, notes=notes))
            download_btn = msg_box.addButton(self.language_manager.tr("open_download_page"),
                                             QMessageBox.ButtonRole.AcceptRole)
            later_btn = msg_box.addButton(self.language_manager.tr("later"),
                                          QMessageBox.ButtonRole.RejectRole)
            msg_box.exec()
            if msg_box.clickedButton() == download_btn:
                webbrowser.open(url)
        else:
            QMessageBox.information(self,
                                    self.language_manager.tr("update_latest_title"),
                                    self.language_manager.tr("update_latest_message").format(version=APP_VERSION))

    # ---------- 设置为默认程序 ----------
    def set_as_default_program(self):
        """将 MarkEase 设置为 .md 和 .markdown 文件的默认打开程序"""
        exe_path = sys.executable
        # 对于源码运行，提示用户必须使用打包后的版本
        if not exe_path.lower().endswith("markease.exe"):
            QMessageBox.warning(self,
                                self.language_manager.tr("set_default_failed_title"),
                                self.language_manager.tr("set_default_failed_message"))
            return

        try:
            # 设置 .md 关联
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.md") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, "MarkEase.md")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.markdown") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, "MarkEase.md")

            # 创建 MarkEase.md 文件类型
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\MarkEase.md") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, "Markdown 文件")

            # 设置默认图标
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\MarkEase.md\DefaultIcon") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f'"{exe_path}",0')

            # 设置打开命令
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\MarkEase.md\shell\open\command") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f'"{exe_path}" "%1"')

            # 刷新文件关联
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)

            QMessageBox.information(self,
                                    self.language_manager.tr("set_default_success_title"),
                                    self.language_manager.tr("set_default_success_message"))
        except Exception as e:
            QMessageBox.critical(self,
                                 self.language_manager.tr("set_default_failed_title"),
                                 self.language_manager.tr("set_default_failed_message") + f"\n{str(e)}")

    # ---------- 模式切换 ----------
    def _on_mode_button_clicked(self):
        sender = self.sender()
        if sender == self.btn_edit:
            self.set_mode(MODE_EDIT)
        elif sender == self.btn_preview:
            self.set_mode(MODE_PREVIEW)
        elif sender == self.btn_split:
            self.set_mode(MODE_SPLIT)

    def set_mode(self, mode):
        self.current_mode = mode
        self.btn_edit.setChecked(mode == MODE_EDIT)
        self.btn_preview.setChecked(mode == MODE_PREVIEW)
        self.btn_split.setChecked(mode == MODE_SPLIT)

        if mode == MODE_EDIT:
            self.editor.setVisible(True)
            self.preview.setVisible(False)
            self.toolbar_container.setVisible(True)
            self.splitter.setSizes([1, 0])
        elif mode == MODE_PREVIEW:
            self.editor.setVisible(False)
            self.preview.setVisible(True)
            self.toolbar_container.setVisible(False)
            self.splitter.setSizes([0, 1])
        elif mode == MODE_SPLIT:
            self.editor.setVisible(True)
            self.preview.setVisible(True)
            self.toolbar_container.setVisible(True)
            total = self.splitter.width()
            self.splitter.setSizes([total // 2, total // 2])

        if mode == MODE_SPLIT:
            self.scroll_sync_manager.set_sync_enabled(self.sync_scroll_button.isChecked())
        else:
            self.scroll_sync_manager.set_sync_enabled(False)

        self.last_scroll_source = "editor"
        self._update_floating_toc_button_position()

    # ---------- 目录相关 ----------
    def toggle_toc_panel(self):
        visible = not self.toc_panel.isVisible()
        self.toc_panel.setVisible(visible)
        self._update_floating_toc_button_position()

    def _update_toc(self):
        markdown_text = self.editor.toPlainText()
        headings = TocManager.parse_headings(markdown_text)
        self.toc_panel.set_headings(headings)

    def _on_cursor_position_changed(self):
        if not self.toc_panel.isVisible():
            return
        if self.current_mode == MODE_EDIT or (self.current_mode == MODE_SPLIT and self.last_scroll_source == "editor"):
            cursor = self.editor.textCursor()
            line_number = cursor.blockNumber()
            self.toc_panel.set_current_heading(line_number)

    def _on_toc_heading_clicked(self, line_number):
        self.editor.go_to_line(line_number)
        self.editor.setFocus()
        if hasattr(self, 'preview'):
            self.preview.scroll_to_line(line_number)
        self.toc_panel.set_current_heading(line_number)
        self.last_scroll_source = "editor"

    # ---------- 查找替换 ----------
    def show_find_replace(self, replace: bool = False):
        self.find_replace_panel.set_mode(replace)
        self.find_replace_panel.show()
        self.find_replace_panel.raise_()
        self.find_replace_panel.activateWindow()

    def _on_find_next(self, text, case, whole):
        self.editor.find_text(text, case, whole, backward=False)

    def _on_find_prev(self, text, case, whole):
        self.editor.find_text(text, case, whole, backward=True)

    def _on_replace(self, find_text, replace_text, case, whole):
        if self.editor.replace_current(find_text, replace_text, case, whole):
            self.editor.find_text(find_text, case, whole, backward=False)
        else:
            if self.editor.find_text(find_text, case, whole, backward=False):
                self.editor.replace_current(find_text, replace_text, case, whole)

    def _on_replace_all(self, find_text, replace_text, case, whole):
        count = self.editor.replace_all(find_text, replace_text, case, whole)
        QMessageBox.information(self, self.language_manager.tr("replace_done"),
                                self.language_manager.tr("replaced_count").format(count=count))

    # ---------- 缩放控制 ----------
    def _show_zoom_menu(self):
        btn_pos = self.zoom_button.rect().topRight()
        global_pos = self.zoom_button.mapToGlobal(btn_pos)
        menu_height = self.zoom_menu.sizeHint().height()
        global_pos.setY(global_pos.y() - menu_height - 5)
        self.zoom_menu.popup(global_pos)

    def _on_zoom_slider_changed(self, value):
        self.set_zoom_percent(value)

    def set_zoom_percent(self, percent: int):
        percent = max(10, min(500, percent))
        self.zoom_percent = percent
        self.zoom_button.setText(f"{percent}%")
        if self.zoom_slider.value() != percent:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(percent)
            self.zoom_slider.blockSignals(False)
        self.editor.set_zoom_percent(percent)
        self.preview.set_zoom_percent(percent)

    def zoom_in(self):
        self.set_zoom_percent(self.zoom_percent + 10)

    def zoom_out(self):
        self.set_zoom_percent(self.zoom_percent - 10)

    def reset_zoom(self):
        self.set_zoom_percent(100)

    # ---------- 同步滚动 ----------
    def _on_sync_scroll_toggled(self, checked):
        self.settings.sync_scroll = checked
        if self.current_mode == MODE_SPLIT:
            self.scroll_sync_manager.set_sync_enabled(checked)
        else:
            self.scroll_sync_manager.set_sync_enabled(False)
        if self.sync_scroll_button.isChecked() != checked:
            self.sync_scroll_button.blockSignals(True)
            self.sync_scroll_button.setChecked(checked)
            self.sync_scroll_button.blockSignals(False)
        if self.sync_scroll_action.isChecked() != checked:
            self.sync_scroll_action.blockSignals(True)
            self.sync_scroll_action.setChecked(checked)
            self.sync_scroll_action.blockSignals(False)

    def _on_editor_scrolled(self):
        self.last_scroll_source = "editor"
        self.scroll_sync_manager.on_editor_scrolled()
        if self.toc_panel.isVisible() and (self.current_mode == MODE_EDIT or (self.current_mode == MODE_SPLIT and self.last_scroll_source == "editor")):
            line = self.editor.get_current_visible_heading_line_simple()
            if line >= 0:
                self.toc_panel.set_current_heading(line)

    def _on_preview_ratio_changed(self, ratio: float):
        self.last_scroll_source = "preview"
        self.scroll_sync_manager.on_preview_ratio_changed(ratio)

    def _on_preview_heading_changed(self, line: int):
        self.last_scroll_source = "preview"
        if self.toc_panel.isVisible() and (self.current_mode == MODE_PREVIEW or (self.current_mode == MODE_SPLIT and self.last_scroll_source == "preview")):
            if line >= 0:
                self.toc_panel.set_current_heading(line)

    # ---------- 文档操作 ----------
    def _show_unsaved_dialog(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.language_manager.tr("unsaved_changes"))
        msg_box.setText(self.language_manager.tr("unsaved_message"))
        save_btn = msg_box.addButton(self.language_manager.tr("save"), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg_box.addButton(self.language_manager.tr("discard"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg_box.addButton(self.language_manager.tr("cancel"), QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(save_btn)
        msg_box.exec()
        clicked = msg_box.clickedButton()
        if clicked == save_btn:
            return "save"
        elif clicked == discard_btn:
            return "discard"
        else:
            return "cancel"

    def new_document(self):
        if self.doc_manager.is_modified:
            choice = self._show_unsaved_dialog()
            if choice == "save":
                if not self.save_document():
                    return
            elif choice == "cancel":
                return

        self.editor.clear()
        self.doc_manager.new_document()
        self._update_preview()
        self._update_toc()
        self._update_stats_label()

    def open_document(self):
        if self.doc_manager.is_modified:
            choice = self._show_unsaved_dialog()
            if choice == "save":
                if not self.save_document():
                    return
            elif choice == "cancel":
                return

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.language_manager.tr("open"), "", MARKDOWN_FILE_FILTER
        )
        if file_path:
            self.open_file_from_path(file_path)

    def open_file_from_path(self, path: str):
        """通过命令行参数或文件关联打开文件"""
        if self.doc_manager.is_modified:
            choice = self._show_unsaved_dialog()
            if choice == "save":
                if not self.save_document():
                    return
            elif choice == "cancel":
                return

        try:
            content = FileManager.read_file(path)
            self.editor.setPlainText(content)
            self.doc_manager.open_document(path)
            self._update_preview()
            self._update_toc()
            self._update_stats_label()
            self.set_mode(MODE_EDIT)
        except Exception as e:
            QMessageBox.critical(self, self.language_manager.tr("open_failed"),
                                f"{self.language_manager.tr('open_failed')}: {e}")

    def save_document(self) -> bool:
        if not self.doc_manager.file_path:
            return self.save_document_as()
        try:
            FileManager.write_file(self.doc_manager.file_path, self.editor.toPlainText())
            self.doc_manager.mark_saved()
            return True
        except Exception as e:
            QMessageBox.critical(self, self.language_manager.tr("save_failed"),
                                f"{self.language_manager.tr('save_failed')}: {e}")
            return False

    def save_document_as(self) -> bool:
        # 如果文档未保存过，尝试将第一行作为默认文件名
        default_name = ""
        if not self.doc_manager.file_path:
            first_line = self.editor.toPlainText().split('\n', 1)[0].strip()
            if first_line:
                # 移除 Markdown 标题标记和非法字符
                default_name = first_line.lstrip('#').strip()
                import re
                default_name = re.sub(r'[\\/:*?"<>|]', '', default_name)[:50]
                default_name += ".md"
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.language_manager.tr("save_as"), default_name, MARKDOWN_FILE_FILTER
        )
        if file_path:
            try:
                FileManager.write_file(file_path, self.editor.toPlainText())
                self.doc_manager.set_file_path(file_path)
                self.doc_manager.mark_saved()
                return True
            except Exception as e:
                QMessageBox.critical(self, self.language_manager.tr("save_failed"),
                                    f"{self.language_manager.tr('save_failed')}: {e}")
        return False

    def reveal_in_explorer(self):
        if self.doc_manager.file_path:
            path = os.path.normpath(self.doc_manager.file_path)
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            QMessageBox.information(self, self.language_manager.tr("info"),
                                    self.language_manager.tr("no_file_saved"))

    # ---------- 信号处理 ----------
    def _on_editor_text_changed(self):
        if not self.doc_manager.is_modified:
            self.doc_manager.mark_modified()
        self._update_stats_label()
        self._update_preview()
        self._update_toc()

    def _update_preview(self):
        if hasattr(self, 'preview'):
            headings = TocManager.parse_headings(self.editor.toPlainText())
            headings_map = [{"line": h.line_number, "text": h.text, "level": h.level} for h in headings]
            theme = self.theme_manager.get_current_theme()
            self.preview.set_markdown(self.editor.toPlainText(), headings_map, theme)

    def _on_modification_changed(self, modified: bool):
        self.status_doc_label.setText(self.language_manager.tr("unsaved") if modified else self.language_manager.tr("saved"))

    def _on_file_path_changed(self, path: str):
        if path:
            file_name = FileManager.get_file_name(path)
            file_dir = FileManager.get_file_dir(path)
            if len(file_dir) > 30:
                file_dir = "..." + file_dir[-27:]
            self.setWindowTitle(f"{file_name} — {file_dir} - {APP_TITLE}")
        else:
            self.setWindowTitle(APP_TITLE)

    # ---------- 其他 ----------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'floating_toc_btn'):
            self._update_floating_toc_button_position()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'floating_toc_btn'):
            self._update_floating_toc_button_position()
        # 强制刷新所有 UI 文本，确保语言正确显示（解决启动时语言不刷新的问题）
        self._retranslate_ui()

    def closeEvent(self, event: QCloseEvent):
        self.settings.window_size = (self.width(), self.height())
        if self.splitter.sizes():
            total = sum(self.splitter.sizes())
            if total > 0:
                self.settings.splitter_ratio = self.splitter.sizes()[0] / total
        self.settings.toc_visible = self.toc_panel.isVisible()
        self.settings.toc_width = self.toc_panel.width()
        self.settings.zoom_percent = self.zoom_percent
        self.settings.sync_scroll = self.sync_scroll_button.isChecked()

        if self.doc_manager.is_modified:
            choice = self._show_unsaved_dialog()
            if choice == "save":
                if not self.save_document():
                    event.ignore()
                    return
            elif choice == "cancel":
                event.ignore()
                return
        event.accept()

    def show_about_dialog(self):
        if self.theme_manager.get_current_theme() == "dark":
            link_color = "#8ab4f8"
        else:
            link_color = "#0000EE"
        style = f"<style>a {{ color: {link_color}; }}</style>"

        about_html = f"""
        {style}
        <h3>MarkEase</h3>
        <p><b>{self.language_manager.tr('about_version')}:</b> {APP_VERSION}</p>
        <p><b>{self.language_manager.tr('about_author')}:</b> ZBT Studio<br>
        <a href="https://github.com/zbt00123/">https://github.com/zbt00123/</a></p>
        <p><b>{self.language_manager.tr('about_outline')}:</b> ChatGPT<br>
        <a href="https://chatgpt.com/">https://chatgpt.com/</a></p>
        <p><b>{self.language_manager.tr('about_coding')}:</b> DeepSeek<br>
        <a href="https://chat.deepseek.com/">https://chat.deepseek.com/</a></p>
        <p><b>{self.language_manager.tr('about_copyright')}:</b> {self.language_manager.tr('about_copyright_text')}</p>
        <p><b>{self.language_manager.tr('about_acknowledgements')}:</b><br>
        PySide6 - <a href="https://pypi.org/project/PySide6/">https://pypi.org/project/PySide6/</a> (LGPL)<br>
        marked.js - <a href="https://marked.js.org/">https://marked.js.org/</a> (MIT)<br>
        highlight.js - <a href="https://highlightjs.org/">https://highlightjs.org/</a> (BSD-3-Clause)<br>
        github-markdown-css - <a href="https://github.com/sindresorhus/github-markdown-css">GitHub</a> (MIT)<br>
        QWebChannel.js - part of Qt (LGPL)<br>
        Emoji icons from system emoji fonts.
        </p>
        """
        QMessageBox.about(self, self.language_manager.tr("about"), about_html)