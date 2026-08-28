# -*- coding: utf-8 -*-
"""
菜单栏模块
创建主窗口菜单栏，包含文件、编辑、窗口、帮助等菜单
"""

from PySide6.QtWidgets import QMenuBar, QMenu, QAction, QActionGroup
from PySide6.QtGui import QKeySequence


class MenuBar(QMenuBar):
    """MarkEase 菜单栏"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.language_manager = main_window.language_manager

        self._create_file_menu()
        self._create_edit_menu()
        self._create_window_menu()
        self._create_help_menu()

    def _create_file_menu(self):
        file_menu = self.addMenu(self.language_manager.tr("file"))
        self.new_action = QAction(self.language_manager.tr("new"), self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.main_window.new_document)
        file_menu.addAction(self.new_action)

        self.open_action = QAction(self.language_manager.tr("open"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.main_window.open_document)
        file_menu.addAction(self.open_action)

        self.save_action = QAction(self.language_manager.tr("save"), self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.main_window.save_document)
        file_menu.addAction(self.save_action)

        self.save_as_action = QAction(self.language_manager.tr("save_as"), self)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.main_window.save_document_as)
        file_menu.addAction(self.save_as_action)

        file_menu.addSeparator()

        self.reveal_action = QAction(self.language_manager.tr("reveal_in_explorer"), self)
        self.reveal_action.triggered.connect(self.main_window.reveal_in_explorer)
        file_menu.addAction(self.reveal_action)

        file_menu.addSeparator()
        self.exit_action = QAction(self.language_manager.tr("exit"), self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.main_window.close)
        file_menu.addAction(self.exit_action)

        self.file_menu = file_menu

    def _create_edit_menu(self):
        edit_menu = self.addMenu(self.language_manager.tr("edit"))
        self.undo_action = QAction(self.language_manager.tr("undo"), self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.main_window.editor.undo)
        edit_menu.addAction(self.undo_action)

        self.redo_action = QAction(self.language_manager.tr("redo"), self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.main_window.editor.redo)
        edit_menu.addAction(self.redo_action)

        edit_menu.addSeparator()
        self.cut_action = QAction(self.language_manager.tr("cut"), self)
        self.cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        self.cut_action.triggered.connect(self.main_window.editor.cut)
        edit_menu.addAction(self.cut_action)

        self.copy_action = QAction(self.language_manager.tr("copy"), self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self.main_window.editor.copy)
        edit_menu.addAction(self.copy_action)

        self.paste_action = QAction(self.language_manager.tr("paste"), self)
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self.main_window.editor.paste)
        edit_menu.addAction(self.paste_action)

        edit_menu.addSeparator()
        self.find_action = QAction(self.language_manager.tr("find"), self)
        self.find_action.setShortcut(QKeySequence.StandardKey.Find)
        self.find_action.triggered.connect(lambda: self.main_window.show_find_replace(False))
        edit_menu.addAction(self.find_action)

        self.replace_action = QAction(self.language_manager.tr("replace"), self)
        self.replace_action.setShortcut(QKeySequence("Ctrl+H"))
        self.replace_action.triggered.connect(lambda: self.main_window.show_find_replace(True))
        edit_menu.addAction(self.replace_action)

        self.edit_menu = edit_menu

    def _create_window_menu(self):
        window_menu = self.addMenu(self.language_manager.tr("window"))

        self.edit_mode_action = QAction(self.language_manager.tr("edit_mode"), self)
        self.edit_mode_action.triggered.connect(lambda: self.main_window.set_mode("edit"))
        window_menu.addAction(self.edit_mode_action)

        self.preview_mode_action = QAction(self.language_manager.tr("preview_mode"), self)
        self.preview_mode_action.triggered.connect(lambda: self.main_window.set_mode("preview"))
        window_menu.addAction(self.preview_mode_action)

        self.split_mode_action = QAction(self.language_manager.tr("split_mode"), self)
        self.split_mode_action.triggered.connect(lambda: self.main_window.set_mode("split"))
        window_menu.addAction(self.split_mode_action)

        window_menu.addSeparator()
        self.toggle_toc_action = QAction(self.language_manager.tr("show_hide_toc"), self)
        self.toggle_toc_action.setCheckable(True)
        self.toggle_toc_action.triggered.connect(self.main_window.toggle_toc_panel)
        window_menu.addAction(self.toggle_toc_action)

        window_menu.addSeparator()
        self.zoom_in_action = QAction(self.language_manager.tr("zoom_in"), self)
        self.zoom_in_action.setShortcut(QKeySequence("Ctrl+="))
        self.zoom_in_action.triggered.connect(self.main_window.zoom_in)
        window_menu.addAction(self.zoom_in_action)

        self.zoom_out_action = QAction(self.language_manager.tr("zoom_out"), self)
        self.zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self.zoom_out_action.triggered.connect(self.main_window.zoom_out)
        window_menu.addAction(self.zoom_out_action)

        self.zoom_reset_action = QAction(self.language_manager.tr("reset_zoom"), self)
        self.zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        self.zoom_reset_action.triggered.connect(self.main_window.reset_zoom)
        window_menu.addAction(self.zoom_reset_action)

        self.sync_scroll_action = QAction(self.language_manager.tr("sync_scroll"), self)
        self.sync_scroll_action.setCheckable(True)
        self.sync_scroll_action.toggled.connect(self.main_window._on_sync_scroll_toggled)
        window_menu.addAction(self.sync_scroll_action)

        self.window_menu = window_menu

    def _create_help_menu(self):
        help_menu = self.addMenu(self.language_manager.tr("help"))
        # 主题子菜单
        theme_menu = help_menu.addMenu(self.language_manager.tr("theme"))
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)

        self.theme_system_action = QAction(self.language_manager.tr("system"), self)
        self.theme_system_action.setCheckable(True)
        self.theme_system_action.setActionGroup(self.theme_group)
        self.theme_system_action.triggered.connect(lambda: self.main_window.change_theme("system"))
        theme_menu.addAction(self.theme_system_action)

        self.theme_light_action = QAction(self.language_manager.tr("light"), self)
        self.theme_light_action.setCheckable(True)
        self.theme_light_action.setActionGroup(self.theme_group)
        self.theme_light_action.triggered.connect(lambda: self.main_window.change_theme("light"))
        theme_menu.addAction(self.theme_light_action)

        self.theme_dark_action = QAction(self.language_manager.tr("dark"), self)
        self.theme_dark_action.setCheckable(True)
        self.theme_dark_action.setActionGroup(self.theme_group)
        self.theme_dark_action.triggered.connect(lambda: self.main_window.change_theme("dark"))
        theme_menu.addAction(self.theme_dark_action)

        # 语言子菜单
        language_menu = help_menu.addMenu(self.language_manager.tr("language"))
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)

        # 添加语言动作...
        # 此处省略具体语言动作，可参考 main_window 中的实现

        help_menu.addSeparator()
        self.about_action = QAction(self.language_manager.tr("about"), self)
        self.about_action.triggered.connect(self.main_window.show_about_dialog)
        help_menu.addAction(self.about_action)

        self.help_menu = help_menu