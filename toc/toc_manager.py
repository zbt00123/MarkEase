# -*- coding: utf-8 -*-
"""
目录管理模块
解析 Markdown 标题，提供标题列表与定位服务
"""

import re
from dataclasses import dataclass


@dataclass
class TocItem:
    """目录条目"""
    level: int          # 标题级别 1~6
    text: str           # 标题文本（不含 # 和空格）
    line_number: int    # 在文档中的行号（0 基）
    block_number: int   # 在 QTextDocument 中的块号（等于行号，因为每行一个块）


class TocManager:
    """Markdown 标题解析器"""

    # 匹配 ATX 风格标题：行首 1~6 个 # 后跟空格或直接跟内容
    HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')

    @staticmethod
    def parse_headings(markdown_text: str) -> list[TocItem]:
        """
        解析 Markdown 文本，返回所有标题条目（按出现顺序）
        """
        headings = []
        lines = markdown_text.split('\n')
        for line_number, line in enumerate(lines):
            match = TocManager.HEADING_PATTERN.match(line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                headings.append(TocItem(
                    level=level,
                    text=text,
                    line_number=line_number,
                    block_number=line_number  # 假设每行一个 QTextBlock
                ))
        return headings

    @staticmethod
    def get_heading_at_line(headings: list[TocItem], line_number: int) -> TocItem | None:
        """获取指定行号之前的最后一个标题（用于判断当前位置所在章节）"""
        current = None
        for heading in headings:
            if heading.line_number <= line_number:
                current = heading
            else:
                break
        return current