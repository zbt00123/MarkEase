# -*- coding: utf-8 -*-
"""
MarkEase 常量定义模块
统一管理应用名称、版本号、模式标识等公共常量
"""

# 应用信息
APP_NAME = "MarkEase"
APP_VERSION = "1.3.0"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"

# GitHub 仓库信息（用于检查更新）
GITHUB_REPO = "zbt00123/MarkEase"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# 显示模式常量
MODE_EDIT = "edit"
MODE_PREVIEW = "preview"
MODE_SPLIT = "split"

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

# 统一的“打开”文件过滤器：支持 md / markdown / pdf
OPEN_FILE_FILTER = (
    "所有支持的文档 (*.md *.markdown *.pdf);;"
    "Markdown 文件 (*.md *.markdown);;"
    "PDF 文件 (*.pdf);;"
    "所有文件 (*.*)"
)

# 导出过滤器
PDF_EXPORT_FILTER = "PDF 文件 (*.pdf)"