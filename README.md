# 📝 MarkEase

**MarkEase** 是一款运行于 Windows 平台、完全离线、轻量级的 **GitHub 风格 Markdown 编辑器**。  
它专注于提供简单直观的 Markdown 编辑体验，以及高质量的 GitHub 风格预览效果。

![License](https://img.shields.io/badge/license-MIT-blue) ![Platform](https://img.shields.io/badge/platform-Windows%20x64-lightgrey) ![Version](https://img.shields.io/badge/version-1.0.0-green)

---

## ✨ 功能特性

- ✅ **完全离线**：所有核心功能本地运行，不依赖网络。
- ✅ **三种显示模式**：编辑、预览、分屏自由切换。
- ✅ **GitHub 风格预览**：高度还原 GitHub Markdown 渲染效果，支持 GFM、代码高亮、表格、任务列表等。
- ✅ **语法高亮**：编辑模式提供轻量 Markdown 语法高亮，提高源码可读性。
- ✅ **自动目录**：根据标题自动生成目录，支持跳转、当前章节高亮、宽度调整。
- ✅ **智能同步滚动**：分屏模式下，编辑器和预览可双向滚动同步，基于标题锚点映射，位置更准确。
- ✅ **查找与替换**：支持区分大小写、全词匹配、全部替换等。
- ✅ **多主题**：跟随系统 / 浅色 / 深色，全局即时切换。
- ✅ **多语言**：简体中文、繁体中文、English、한국어、日本語，界面文字随语言即时更新。
- ✅ **缩放控制**：编辑器和预览均可独立缩放（10%～500%），支持快捷键和滑块。
- ✅ **悬浮目录按钮**：可拖动的半透明按钮，快速显示/隐藏目录。
- ✅ **文件管理**：新建、打开、保存、另存为、打开文件所在位置、未保存提醒。
- ✅ **统计信息**：状态栏实时显示字数、行数。
- ✅ **便携版**：解压即用，无需安装，可放在任意目录运行。

---

## 📸 软件截图

### 编辑模式
<img width="2022" height="1243" alt="PixPin_2026-08-29_02-18-49" src="https://github.com/user-attachments/assets/6489d6ad-53ad-4d0b-a085-fa71fd3d5514" />

### 预览模式
<img width="2022" height="1243" alt="PixPin_2026-08-29_02-19-22" src="https://github.com/user-attachments/assets/260dce0a-1959-4e48-90b7-d1a4b1d0ea24" />

### 分屏模式
<img width="2022" height="1243" alt="PixPin_2026-08-29_02-19-42" src="https://github.com/user-attachments/assets/a506cc80-69cd-43d4-9900-92672de7f81f" />

### 深色主题
<img width="2022" height="1243" alt="PixPin_2026-08-29_02-20-06" src="https://github.com/user-attachments/assets/77ebe96c-7f5d-4296-9e58-f0ddb219a26d" />

---

## 📥 下载与安装

### 下载
前往 [Releases](https://github.com/你的用户名/MarkEase/releases) 页面下载最新版本：

- **绿色免安装版**：`MarkEase_v1.0.0_Windows_x64_portable.7z`  
  解压后运行 `MarkEase.exe` 即可。

### 运行要求
- Windows 10 / 11（64 位）
- 无需安装 Python 或其他依赖

> ⚠️ **提示**：由于程序使用 PyInstaller 打包，部分杀毒软件可能误报。请将程序文件夹添加到杀毒软件信任区（白名单）后使用。

---

## 🚀 快速开始

1. 下载并解压 `MarkEase_v1.0.0_Windows_x64_portable.7z`。
2. 双击 `MarkEase.exe` 启动。
3. 点击“打开”选择 Markdown 文件，或直接新建文档开始编辑。
4. 使用顶部标签切换 **编辑 / 预览 / 分屏** 模式。
5. 通过工具栏快速插入 Markdown 格式（标题、加粗、链接、图片、表格等）。
6. 点击悬浮目录按钮（左侧边缘）或使用“窗口”菜单显示目录。

---

## ⌨️ 快捷键

| 功能         | 快捷键            |
|--------------|-------------------|
| 新建         | `Ctrl + N`        |
| 打开         | `Ctrl + O`        |
| 保存         | `Ctrl + S`        |
| 另存为       | `Ctrl + Shift + S`|
| 撤销         | `Ctrl + Z`        |
| 重做         | `Ctrl + Y` / `Ctrl + Shift + Z` |
| 查找         | `Ctrl + F`        |
| 替换         | `Ctrl + H`        |
| 放大         | `Ctrl + =`        |
| 缩小         | `Ctrl + -`        |
| 重置缩放     | `Ctrl + 0`        |

---

## 🎨 主题与语言

- **主题**：帮助菜单 → 主题，或状态栏右侧快速切换按钮（☀️/🌙）。
- **语言**：帮助菜单 → 语言，支持即时切换。

---

## 🛠 技术栈

- **Python 3.8+**
- **PySide6**（Qt for Python）
- **QWebEngine**（预览渲染）
- **marked.js**（Markdown 解析）
- **highlight.js**（代码高亮）
- **github-markdown-css**（GitHub 风格样式）

---

## 📁 项目结构

```
MarkEase/
├── app/                    # 主程序模块
├── editor/                 # Markdown 编辑器
├── preview/                # Markdown 预览系统
├── toc/                    # 目录系统
├── ui/                     # UI 组件
├── document/               # 文档管理
├── web/                    # 本地 WebEngine 资源
├── resources/              # 图标、翻译、主题
├── scripts/                # 一键脚本
├── main.py                 # 入口文件
└── requirements.txt
```

---

## 🧪 从源码运行

如果您希望从源码运行或进行二次开发：

1. 克隆仓库：
   ```bash
   git clone https://github.com/你的用户名/MarkEase.git
   cd MarkEase
   ```

2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

3. 运行：
   ```bash
   python main.py
   ```

---

## 📦 打包

项目提供了 `scripts/打包软件.py` 一键打包脚本，支持生成绿色版和安装版。

- **生成绿色版文件夹**：运行 `python scripts/打包软件.py`，结束后 `dist/MarkEase/` 即为绿色版。
- **生成安装程序**：需安装 [Inno Setup](https://jrsoftware.org/isinfo.php)，脚本会自动调用并生成 `Setup.exe`。

---

## 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！  
如果您发现 bug 或有新功能建议，请在 [Issues](https://github.com/你的用户名/MarkEase/issues) 中提出。

---

## 📄 版权说明

> 仅供学习使用，可以任意修改、复制、发布代码，严禁商用。

---

## 🙏 鸣谢

- [PySide6](https://pypi.org/project/PySide6/) (LGPL)
- [marked.js](https://marked.js.org/) (MIT)
- [highlight.js](https://highlightjs.org/) (BSD-3-Clause)
- [github-markdown-css](https://github.com/sindresorhus/github-markdown-css) (MIT)
- [QWebChannel.js](https://doc.qt.io/qt-6/qtwebchannel-index.html) (LGPL)
- Emoji icons from system emoji fonts

---

## 👨‍💻 作者

**ZBT Studio**  
GitHub: [zbt00123](https://github.com/zbt00123/)

大纲：ChatGPT (https://chatgpt.com/)  
编码：DeepSeek (https://chat.deepseek.com/)
