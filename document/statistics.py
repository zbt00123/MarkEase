# -*- coding: utf-8 -*-
"""
文档统计模块
提供 Markdown 文本的字数、行数等统计功能
"""

class DocumentStatistics:
    """文档统计工具类"""

    @staticmethod
    def count_words(text: str) -> int:
        """统计字符数（含空格）"""
        return len(text)

    @staticmethod
    def count_lines(text: str) -> int:
        """统计行数"""
        return text.count('\n') + 1 if text else 0

    @staticmethod
    def count_non_punctuation_words(text: str) -> int:
        """统计无标点字符数（简单实现：仅统计非空白非标点字符）"""
        import re
        # 去除空白和常见标点
        clean = re.sub(r'[\s\W_]+', '', text)
        return len(clean)

    @staticmethod
    def get_statistics(text: str) -> dict:
        """返回统计信息字典"""
        return {
            "chars": DocumentStatistics.count_words(text),
            "lines": DocumentStatistics.count_lines(text),
            "non_punct_chars": DocumentStatistics.count_non_punctuation_words(text)
        }