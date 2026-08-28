# -*- coding: utf-8 -*-
"""
文件管理模块
负责 Markdown 文件的读取和写入
"""

import os

class FileManager:
    """文件读写静态工具类"""

    @staticmethod
    def read_file(path: str) -> str:
        """读取文件内容，使用 UTF-8 编码"""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def write_file(path: str, content: str) -> None:
        """写入文件内容，使用 UTF-8 编码"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def get_file_name(path: str) -> str:
        """获取文件名（不含路径）"""
        return os.path.basename(path)

    @staticmethod
    def get_file_dir(path: str) -> str:
        """获取文件所在目录"""
        return os.path.dirname(path)
