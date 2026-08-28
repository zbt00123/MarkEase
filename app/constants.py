# -*- coding: utf-8 -*-
"""
MarkEase 常量定义模块
统一管理应用名称、版本号、模式标识等公共常量
"""

# 应用信息
APP_NAME = "MarkEase"
APP_VERSION = "1.0.0"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

# 显示模式常量
MODE_EDIT = "edit"
MODE_PREVIEW = "preview"
MODE_SPLIT = "split"

# 模式显示名称（后续多语言系统会替换，此处先使用简单映射）
MODE_LABELS = {
    MODE_EDIT: "✏️ 编辑",
    MODE_PREVIEW: "🔎 预览",
    MODE_SPLIT: "📖 分屏",
}

# 窗口默认尺寸
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800

# 文件过滤器
MARKDOWN_FILE_FILTER = "Markdown 文件 (*.md *.markdown);;所有文件 (*.*)"