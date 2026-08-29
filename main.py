# -*- coding: utf-8 -*-
"""
MarkEase 主入口
"""

import sys
from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # 处理命令行参数：如果有文件路径，则打开该文件
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        window.open_file_from_path(file_path)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()