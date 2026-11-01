# 第三方组件与许可声明

本项目自身代码以 [MIT License](LICENSE) 发布（Copyright (c) 2026 zbt00123）。

本文件列出 MarkEase 源代码与 Windows 便携版（`dist/MarkEase`）中**实际包含**的第三方组件及其许可证。
再分发时请完整保留 `LICENSE`、本文件、`licenses/` 目录以及 `web/css/fonts/OFL.txt`。

> 下表中的版本号为 2026-11-02 本地构建时的参考版本；CI 构建会安装 `requirements.txt` 约束下满足条件的最新版本。

---

## 1. 运行时 / 构建组件

| 组件 | 参考版本 | 许可证 | 说明 / 相关文件 |
|---|---|---|---|
| Python | 3.14.5 | PSF-2.0 | `python314.dll`、`python3.dll`、标准库；版权归 Python Software Foundation；全文 `licenses/Python-3.14-PSF-2.0.txt` |
| PyInstaller | 6.22.0 | GPL-2.0-or-later，附 bootloader exception | 生成的 `MarkEase.exe` 内含 PyInstaller bootloader；exception 允许分发打包产物；全文 `licenses/PyInstaller-GPL-2.0-with-exception.txt` |
| OpenSSL | 3.x | Apache-2.0 | `libcrypto-3.dll`、`libssl-3.dll`（由 Python 官方构建携带） |
| libffi | 3.x | MIT | `libffi-8.dll` |
| Microsoft Visual C++ 运行时 / UCRT | 2015-2022 | Microsoft 可再分发运行时许可 | `msvcp140*.dll`、`vcruntime140*.dll`、`ucrtbase.dll`、`api-ms-win-*.dll` |
| Microsoft .NET Framework 程序集 | 4.x | Microsoft 许可（随 pythonnet 分发） | `pythonnet/runtime/*.dll`（`System.*.dll`、`netstandard.dll`、`Python.Runtime.dll` 的依赖） |
| Microsoft WebView2 SDK | 1.0.x | Microsoft 软件许可（允许随应用再分发） | `webview/lib/Microsoft.Web.WebView2.*.dll`、`WebView2Loader.dll`；WebView2 **运行时本身**由系统安装，不随包分发 |

---

## 2. Python 包

| 组件 | 参考版本 | 许可证 | 许可证全文 |
|---|---|---|---|
| pywebview | 6.2.1 | BSD-3-Clause | `licenses/pywebview-BSD-3-Clause.txt` |
| pythonnet | 3.1.0 | MIT | `licenses/pythonnet-MIT.txt` |
| clr-loader | 0.3.1 | MIT | `licenses/clr-loader-MIT.txt` |
| **PyMuPDF / MuPDF** | 1.28.2 | **AGPL-3.0 或 Artifex 商业许可** | 见 4.1；全文 <https://www.gnu.org/licenses/agpl-3.0.txt> |
| Pillow | 12.2.0 | MIT-CMU (HPND) | `licenses/Pillow-MIT-CMU.txt` |
| numpy | 2.5.0 | BSD-3-Clause（另含 0BSD/MIT/Zlib/CC0 及 OpenBLAS 等 bundled 组件） | `licenses/numpy-BSD-3-Clause.txt` |
| lxml | 6.1.3 | BSD-3-Clause | `licenses/lxml-BSD-3-Clause.txt`、`licenses/lxml-bundled-LICENSES.txt` |
| python-docx | 1.2.0 | MIT | `licenses/python-docx-MIT.txt` |
| psutil | 7.2.2 | BSD-3-Clause | `licenses/psutil-BSD-3-Clause.txt` |
| PyYAML | 6.0.3 | MIT | `licenses/PyYAML-MIT.txt` |
| MarkupSafe | 3.0.4 | BSD-3-Clause | `licenses/MarkupSafe-BSD-3-Clause.txt` |
| charset-normalizer | 3.5.1 | MIT | `licenses/charset-normalizer-MIT.txt` |
| pywin32 | 312 | PSF-2.0 | `licenses/pywin32-PSF-2.0.txt` |
| setuptools | 78.1.0 | MIT | `licenses/setuptools-MIT.txt` |

> `python-docx` 与 `lxml` 目前未被应用逻辑直接使用，但会被 PyInstaller 收集进包体；
> 后续如果从 `MarkEase.spec` 移除，请同步更新本文件。

---

## 3. 前端库 / 资源

| 组件 | 许可证 | 说明 |
|---|---|---|
| CodeMirror 6（及 `@codemirror/*`、`@lezer/*` 等依赖） | MIT | `web/js/vendor/*.mjs`；版权归 Marijn Haverbeke 及贡献者 |
| KaTeX（代码） | MIT | `web/js/katex.min.js`、`auto-render.min.js`、`katex.min.css`；Copyright (c) 2013-2020 Khan Academy and other contributors |
| KaTeX 字体文件 | SIL OFL 1.1 | `web/css/fonts/*`；版权与保留字体名见 `web/css/fonts/OFL.txt` |
| highlight.js | BSD-3-Clause | `web/js/highlight.min.js`；Copyright (c) 2006, Ivan Sagalaev |
| marked | MIT | `web/js/marked.min.js`；Copyright (c) 2011-2024, Christopher Jeffrey |
| github-markdown-css | MIT | `web/css/github-markdown.css`；Copyright (c) Sindre Sorhus |
| GitHub Octicons | MIT | 关于窗口图标；Copyright (c) GitHub, Inc. |
| **Qt qwebchannel.js** | **LGPL-3.0-only / GPL-2.0-only / GPL-3.0-only / Qt 商业许可** | `web/js/qwebchannel.js`；Copyright (C) 2016 The Qt Company Ltd. |

---

## 4. 重要合规说明

### 4.1 PyMuPDF / MuPDF（AGPL-3.0）

- PDF 导入/导出由 **PyMuPDF 1.28.2** 实现，它采用 **AGPL-3.0 或 Artifex 商业许可** 双授权，底层 MuPDF 同样为 AGPL-3.0。
- 只要再分发包含 PyMuPDF 的二进制包，就需要满足 AGPL-3.0 的义务（例如向接收者提供对应源代码/构建方式），
  或者向 Artifex 购买商业许可。
- 本项目源代码公开，但仍建议在正式商用/闭源分发前咨询法律意见，或替换为许可更宽松的 PDF 库。
- 许可全文：<https://www.gnu.org/licenses/agpl-3.0.txt>；商业许可：<https://artifex.com/licensing/>

### 4.2 Qt qwebchannel.js（LGPL/GPL）

- `web/js/qwebchannel.js` 来自 Qt WebChannel，头部 SPDX 标注：
  `LicenseRef-Qt-Commercial OR LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`。
- 当前 Windows EdgeChromium 后端**没有引用**该文件（仅 pywebview 的 Qt 后端会用到）。
- 如果继续随包分发，请保留文件头与许可声明；如果确认不需要，建议从 `web/js/` 删除以减小许可面。

### 4.3 Microsoft 组件

- WebView2 SDK 的托管 DLL 与 `WebView2Loader.dll` 允许随应用再分发，但需遵守 Microsoft 软件许可条款。
- **WebView2 运行时**是系统组件（Windows 10/11 通常已安装），不包含在本项目中。
- .NET Framework 程序集与 VC++ 运行时同样按 Microsoft 可再分发条款使用。

### 4.4 KaTeX 字体（OFL 1.1）

- KaTeX 字体使用 SIL Open Font License 1.1，保留字体名为 `KaTeX_*`。
- 完整许可文本已随字体放在 `web/css/fonts/OFL.txt`；再分发时请保留该文件。

---

## 5. 许可证全文位置

- Python 包：本仓库 `licenses/` 目录（见 [`licenses/README.md`](licenses/README.md)）。
- KaTeX 字体：`web/css/fonts/OFL.txt`。
- PyMuPDF / MuPDF：<https://www.gnu.org/licenses/agpl-3.0.txt>。
- Qt qwebchannel.js：<https://www.qt.io/licensing>。
- Apache-2.0（OpenSSL）：<https://www.apache.org/licenses/LICENSE-2.0>。
- Microsoft WebView2 / .NET / VC++：<https://learn.microsoft.com/microsoft-edge/webview2/>、
  <https://dotnet.microsoft.com/>。

---

## 6. 再分发检查清单

- [ ] 保留 `LICENSE`、`THIRD_PARTY_NOTICES.md`、`licenses/`、`web/css/fonts/OFL.txt`
- [ ] 确认 PyMuPDF 的 AGPL-3.0 义务已满足，或已购买 Artifex 商业许可
- [ ] 不要删除 JS/CSS 文件头中的版权与许可注释
- [ ] 保留 Microsoft WebView2 / VC++ 运行时的可再分发声明
- [ ] 若移除/替换任一组件（如 PyMuPDF、qwebchannel.js、python-docx），同步更新本文件
- [ ] 发布 Release 时附上本文件与 `licenses/` 的压缩包/链接
