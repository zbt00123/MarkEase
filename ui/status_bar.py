# -*- coding: utf-8 -*-
"""
状态栏模块
创建主窗口状态栏，包含文档状态、统计信息、缩放控件、同步滚动开关等
"""

from PySide6.QtWidgets import QStatusBar, QLabel, QPushButton, QSlider
from PySide6.QtCore import Qt


class StatusBar(QStatusBar):
    """MarkEase 状态栏"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.language_manager = main_window.language_manager

        self._init_widgets()

    def _init_widgets(self):
        self.status_doc_label = QLabel(self.language_manager.tr("saved"))
        self.addWidget(self.status_doc_label)

        self.status_stats_label = QLabel("")
        self.addPermanentWidget(self.status_stats_label)

        self.zoom_button = QPushButton(f"{self.main_window.zoom_percent}%")
        self.zoom_button.setFlat(True)
        self.zoom_button.setToolTip(self.language_manager.tr("zoom"))
        self.zoom_button.clicked.connect(self.main_window._show_zoom_menu)
        self.addPermanentWidget(self.zoom_button)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 500)
        self.zoom_slider.setValue(self.main_window.zoom_percent)
        self.zoom_slider.setFixedWidth(100)
        self.zoom_slider.setToolTip(self.language_manager.tr("zoom"))
        self.zoom_slider.valueChanged.connect(self.main_window._on_zoom_slider_changed)
        self.addPermanentWidget(self.zoom_slider)

        self.sync_scroll_button = QPushButton(self.language_manager.tr("sync_scroll"))
        self.sync_scroll_button.setCheckable(True)
        self.sync_scroll_button.setChecked(self.main_window.settings.sync_scroll)
        self.sync_scroll_button.setToolTip(self.language_manager.tr("sync_scroll"))
        self.sync_scroll_button.setStyleSheet("QPushButton:checked { background-color: #2a82da; color: white; }")
        self.sync_scroll_button.toggled.connect(self.main_window._on_sync_scroll_toggled)
        self.addPermanentWidget(self.sync_scroll_button)

        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setFlat(True)
        self.theme_toggle_button.setFixedWidth(32)
        self.theme_toggle_button.setToolTip(self.language_manager.tr("theme"))
        self.theme_toggle_button.clicked.connect(self.main_window.toggle_theme_quick)
        self.addPermanentWidget(self.theme_toggle_button)