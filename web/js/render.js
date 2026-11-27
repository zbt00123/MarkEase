// MarkEase 渲染管线（阶段 16-13 修复 2）
//   ★ v2.1.7 修改：
//     1) BUILD_TAG 更新为 render-v27
//     2) 预览任务列表去掉额外的 “- ” 前缀，只保留复选框
//     3) 有序列表按源码实际编号渲染（<li value>），保证所见即所得
//   ★ v2.1.6 修改：
//     1) BUILD_TAG 更新为 render-v26
//     2) 修复正文中转义的 \[ ... \] 被误判为独立公式导致断行
//        —— 仅行首/行尾的 \[ ... \] 按独立公式处理，
//           正文中的 \[ \] 还原为字面量方括号
//   ★ v2.1.5 修改：
//     1) BUILD_TAG 更新为 render-v25
//     2) 代码块按逻辑行包裹，长行自动换行 + 续行悬挂缩进
//        （预览 / PDF 导出 / HTML 导出共用；不再出现横向滚动条或裁切）
//   ★ v2.1.4 修改：
//     1) BUILD_TAG 更新为 render-v24
//     2) 含图标 <img> 的链接在 domToMarkdown 中还原为 Markdown 链接
//     3) 图片保存 data-md-src，预览编辑回写时还原原始相对路径/网络 URL
//     4) 链接内的图标图片允许双击编辑，普通正文图片仍禁止
//     5) contenteditable 的 &nbsp; 回写时还原为普通空格
//   ★ 历史修改：
//     1) BUILD_TAG 更新为 render-v23
//     2) domToMarkdown 支持 <strike>（预览编辑态删除线由 execCommand 产生）
//     3) preprocessHtmlBlocks 新增 <ins> / <u> 预处理
//        —— 把内部 markdown 提前用 marked.parseInline 解析
//        —— 解决 <ins>**粗体**</ins> 渲染成源代码的问题
//     4) restoreHtmlBlocks 改为多轮循环替换，处理嵌套占位符
(function (global) {
    'use strict';

    var BUILD_TAG = 'render-v27';
    console.log('[MarkEase] ' + BUILD_TAG + ' loaded');

    var KATEX_OPTS = {
        throwOnError: false,
        strict: false,
        trust: false,
        output: 'htmlAndMathml'
    };

    var FOLD_STATE_KEY = 'markease_fold_state_v1';

    function _escHtml(s) {
        if (typeof global.escapeHtml === 'function') {
            try { return global.escapeHtml(s); } catch (e) { /* fallthrough */ }
        }
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function _escapeAttr(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/'/g, '&#39;');
    }

    // ============================================================
    //  路径解析工具
    // ============================================================
    function _getDocDir(options) {
        if (options && options.docDir) return String(options.docDir);
        if (global.__currentDocDir) return String(global.__currentDocDir);
        return '';
    }

    function _getAssetBase() {
        return global.__assetBaseUrl || '';
    }

    function _toProxyUrl(remoteUrl) {
        var baseUrl = _getAssetBase();
        if (!baseUrl) return remoteUrl;
        if (!remoteUrl) return remoteUrl;
        if (remoteUrl.indexOf(baseUrl) === 0) return remoteUrl;
        return baseUrl + '/proxy?url=' + encodeURIComponent(remoteUrl);
    }

    function _fromProxyUrl(proxiedUrl) {
        if (!proxiedUrl) return proxiedUrl;
        var baseUrl = _getAssetBase();
        if (!baseUrl) return proxiedUrl;
        var prefix = baseUrl + '/proxy?url=';
        if (proxiedUrl.indexOf(prefix) !== 0) return proxiedUrl;
        try {
            return decodeURIComponent(proxiedUrl.slice(prefix.length));
        } catch (e) {
            return proxiedUrl;
        }
    }

    function _resolveToAbsPath(src, docDir) {
        if (!src) return null;
        if (/^file:\/\//i.test(src)) {
            return decodeURIComponent(src.replace(/^file:\/\/\/?/i, ''));
        }
        if (/^[a-z]+:\/\//i.test(src)) return null;
        if (/^data:/i.test(src) || /^blob:/i.test(src)) return null;
        if (/^[A-Za-z]:[\/\\]/.test(src)) return src;
        if (src.charAt(0) === '/' && !/^\/\//.test(src)) return src;
        if (!docDir) return null;
        var normDir = String(docDir).replace(/\\/g, '/').replace(/\/+$/, '');
        if (!normDir) return null;
        return normDir + '/' + src;
    }

    function _toAssetUrl(absPath) {
        if (!absPath) return null;
        var baseUrl = _getAssetBase();
        if (!baseUrl) return null;
        var normalized = String(absPath).replace(/\\/g, '/').replace(/^\/+/, '');
        return baseUrl + '/fs/' + encodeURIComponent(normalized);
    }

    function _toFileUrl(absPath) {
        if (!absPath) return null;
        var normalized = String(absPath).replace(/\\/g, '/').replace(/^\/+/, '');
        return 'file:///' + normalized;
    }

    function _rewriteSrc(src, docDir) {
        if (!src) return src;

        if (/^data:/i.test(src)) return src;
        if (/^blob:/i.test(src)) return src;
        if (/^file:/i.test(src)) return src;

        var baseUrl = _getAssetBase();
        if (baseUrl && src.indexOf(baseUrl) === 0) return src;

        if (/^https?:/i.test(src)) {
            return _toProxyUrl(src);
        }

        if (src.indexOf('base64') !== -1 || src.indexOf('[图片') !== -1) return src;

        var absPath = _resolveToAbsPath(src, docDir);
        if (!absPath) return src;
        var assetUrl = _toAssetUrl(absPath);
        if (assetUrl) return assetUrl;
        return _toFileUrl(absPath) || src;
    }

    // ============================================================
    //  DOM → Markdown
    // ============================================================
    function domToMarkdown(el, opts) {
        opts = opts || {};
        var skipNestedLists = opts.skipNestedLists === true;

        let out = '';
        const nodes = el.childNodes;
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            if (node.nodeType === 3) {
                // ★ 预览编辑时 contenteditable 会把普通空格写成 &nbsp;，
                //   回写 Markdown 前统一还原为普通空格
                out += node.nodeValue.replace(/\u00a0/g, ' ');
            } else if (node.nodeType === 1) {
                const tag = node.tagName.toLowerCase();

                if (skipNestedLists && (tag === 'ul' || tag === 'ol')) {
                    continue;
                }

                if (tag === 'img') {
                    const src = node.getAttribute('src') || '';
                    const width = node.getAttribute('width') || '';
                    const height = node.getAttribute('height') || '';

                    // ★ 优先使用渲染时保存的原始 src / alt（相对路径/原始网络 URL/
                    //   原始 HTML 实体），保证预览编辑回写的 Markdown 与源文档一致。
                    const mdSrc = node.getAttribute('data-md-src');
                    const mdAlt = node.getAttribute('data-md-alt');
                    const alt = mdAlt !== null ? mdAlt : (node.getAttribute('alt') || '');
                    let realSrc = mdSrc || src;

                    if (!mdSrc) {
                        if (/^http:\/\/127\.0\.0\.1:\d+\/proxy\?url=/i.test(src)) {
                            realSrc = _fromProxyUrl(src);
                        }
                        else if (/^http:\/\/127\.0\.0\.1:\d+\/fs\//i.test(src)) {
                            try {
                                realSrc = decodeURIComponent(src.replace(
                                    /^http:\/\/127\.0\.0\.1:\d+\/fs\//i, ''));
                            } catch (e) { /* 保留 */ }
                        }
                        else if (/^file:\/\//i.test(src)) {
                            try {
                                realSrc = decodeURIComponent(src.replace(
                                    /^file:\/\/\/?/i, ''));
                            } catch (e) { /* 保留 */ }
                        }
                    }

                    if (width || height) {
                        let attrs = ' src="' + String(realSrc).replace(/"/g, '&quot;') + '"';
                        if (alt || mdAlt !== null) {
                            attrs += ' alt="' + String(alt).replace(/"/g, '&quot;') + '"';
                        }
                        if (width) attrs += ' width="' + String(width).replace(/"/g, '&quot;') + '"';
                        if (height) attrs += ' height="' + String(height).replace(/"/g, '&quot;') + '"';
                        out += '<img' + attrs + '>';
                    } else {
                        if (/[\s()<>]/.test(realSrc) && !realSrc.startsWith('<')) {
                            realSrc = '<' + realSrc + '>';
                        }
                        out += '![' + alt + '](' + realSrc + ')';
                    }
                    continue;
                }

                if (tag === 'sup' && node.getAttribute &&
                    node.getAttribute('data-footnote-ref') === '1') {
                    const idx = node.getAttribute('data-footnote-index') || '';
                    out += '[^' + idx + ']';
                    continue;
                }

                const inner = domToMarkdown(node, opts);
                switch (tag) {
                    case 'br': out += '\n'; break;
                    // 空的行内格式标签不再输出标记（避免删空文字后残留 **** / ~~~~）
                    case 'strong':
                    case 'b': out += inner ? '**' + inner + '**' : ''; break;
                    case 'em':
                    case 'i': out += inner ? '*' + inner + '*' : ''; break;
                    case 'del':
                    case 's':
                    case 'strike': out += inner ? '~~' + inner + '~~' : ''; break;
                    case 'ins':
                    case 'u': out += inner ? '<ins>' + inner + '</ins>' : ''; break;
                    case 'code': out += inner ? '`' + inner + '`' : ''; break;
                    case 'a': {
                        if (node.getAttribute &&
                            node.getAttribute('data-footnote-backref') === '1') {
                            break;
                        }
                        // ★ 链接文字里即使含图标 <img>，也统一还原为 Markdown 链接：
                        //   [<img src="..." ...> 名称](地址)
                        //   这样预览编辑修改链接文字后才能无损写回源文档。
                        const href = node.getAttribute('href') || '';
                        const title = node.getAttribute('title');
                        if (title) {
                            out += '[' + inner + '](' + href + ' "' + title + '")';
                        } else {
                            out += '[' + inner + '](' + href + ')';
                        }
                        break;
                    }
                    case 'span': {
                        if (node.classList) {
                            if (node.classList.contains('task-list-bullet') ||
                                node.classList.contains('task-list-checkbox')) {
                                break;
                            }
                        }
                        out += inner;
                        break;
                    }
                    case 'div':
                    case 'p':
                        if (out && !out.endsWith('\n')) out += '\n';
                        out += inner;
                        break;
                    default: out += inner;
                }
            }
        }
        return out;
    }

    function getEditableText(el) {
        let out = '';
        const nodes = el.childNodes;
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            if (node.nodeType === 3) {
                out += node.nodeValue;
            } else if (node.nodeType === 1) {
                const tag = node.tagName.toLowerCase();
                if (tag === 'br') {
                    out += '\n';
                } else if (tag === 'div' || tag === 'p') {
                    if (out && !out.endsWith('\n')) out += '\n';
                    out += getEditableText(node);
                } else {
                    out += node.textContent;
                }
            }
        }
        return out;
    }

    // ============================================================
    //  ★ 新增：查找 Markdown 中的围栏代码块（用于 pre 双击编辑）
    //  返回每段代码块的：
    //    fullStart/fullEnd  —— 整段（含 ``` 围栏）
    //    contentStart/End   —— 内部纯代码内容（不含围栏行）
    //    lang                —— 语言
    //    content             —— 内部代码内容（已去掉尾部换行）
    // ============================================================
    function findCodeBlocks(md) {
        var source = String(md == null ? '' : md);
        var blocks = [];
        var re = /(^|\n)([ \t]*)(```|~~~)([^\n]*)\n([\s\S]*?)\n\2\3[ \t]*(?=\n|$)/g;
        var m;
        while ((m = re.exec(source)) !== null) {
            var fullStart = m.index + m[1].length;
            var fullEnd = m.index + m[0].length;
            var contentStart = fullStart + 3 + m[4].length + 1;
            var rawContent = m[5];
            var content = rawContent.replace(/\n+$/, '');
            var contentEnd = contentStart + content.length;
            blocks.push({
                fullStart: fullStart,
                fullEnd: fullEnd,
                contentStart: contentStart,
                contentEnd: contentEnd,
                lang: m[4],
                content: content
            });
        }
        return blocks;
    }

    // ============================================================
    //  代码块范围
    // ============================================================
    function collectCodeRanges(md) {
        var ranges = [];
        var m;

        var reBlock = /(^|\n)([ \t]*)(```|~~~)([^\n]*)\n([\s\S]*?)\n\2\3[ \t]*(?=\n|$)/g;
        while ((m = reBlock.exec(md)) !== null) {
            var start = m.index + m[1].length;
            var end = m.index + m[0].length;
            ranges.push([start, end]);
        }

        var reInline = /`[^`\n]*`/g;
        while ((m = reInline.exec(md)) !== null) {
            var skip = false;
            for (var i = 0; i < ranges.length; i++) {
                if (m.index >= ranges[i][0] && m.index < ranges[i][1]) {
                    skip = true; break;
                }
            }
            if (!skip) ranges.push([m.index, m.index + m[0].length]);
        }

        ranges.sort(function (a, b) { return a[0] - b[0]; });
        return ranges;
    }

    function makeIsInCode(codeRanges) {
        return function (idx) {
            for (var i = 0; i < codeRanges.length; i++) {
                if (idx >= codeRanges[i][0] && idx < codeRanges[i][1]) return true;
                if (codeRanges[i][0] > idx) break;
            }
            return false;
        };
    }

    // ============================================================
    //  脚注预处理
    // ============================================================
    function preprocessFootnotes(md) {
        var source = String(md == null ? '' : md);
        var footnotes = [];
        var seen = {};

        var codeRanges = collectCodeRanges(source);
        var isInCode = makeIsInCode(codeRanges);

        var defReplacements = [];
        var lineStart = 0;
        var lineEnd = 0;
        var n = source.length;
        var defRe = /^([ \t]*\[\^([^\]\s]+)\]:[ \t]*)(.*)$/;

        while (lineStart <= n) {
            lineEnd = source.indexOf('\n', lineStart);
            if (lineEnd === -1) lineEnd = n;
            var line = source.slice(lineStart, lineEnd);

            if (!isInCode(lineStart)) {
                var m = defRe.exec(line);
                if (m) {
                    var prefix = m[1] || '';
                    var key = m[2];
                    var content = m[3] || '';
                    var contentStart = lineStart + prefix.length;
                    var contentEnd = lineEnd;

                    if (!Object.prototype.hasOwnProperty.call(seen, key)) {
                        seen[key] = true;
                        footnotes.push({
                            index: key,
                            content: content,
                            contentStart: contentStart,
                            contentEnd: contentEnd,
                        });
                    }
                    defReplacements.push({
                        start: lineStart,
                        end: lineEnd,
                        placeholder: '\n\n@@MKFNDEF_' + key + '@@\n\n'
                    });
                }
            }

            if (lineEnd === n) break;
            lineStart = lineEnd + 1;
        }

        var result = source;
        for (var di = defReplacements.length - 1; di >= 0; di--) {
            var d = defReplacements[di];
            result = result.slice(0, d.start) + d.placeholder + result.slice(d.end);
        }

        codeRanges = collectCodeRanges(result);
        isInCode = makeIsInCode(codeRanges);

        result = result.replace(/\[\^([^\]\s]+)\](?!:)/g, function (m, key, offset) {
            if (isInCode(offset)) return m;
            if (!Object.prototype.hasOwnProperty.call(seen, key)) {
                return m;
            }
            return '@@MKFNREF_' + key + '@@';
        });

        return { text: result, footnotes: footnotes };
    }

    function renderInlineMarkdown(text) {
        if (typeof marked === 'undefined') return _escHtml(text);
        try {
            if (typeof marked.parseInline === 'function') {
                return marked.parseInline(String(text == null ? '' : text));
            }
            var html = marked.parse(String(text == null ? '' : text));
            return html.replace(/^\s*<p>/, '').replace(/<\/p>\s*$/, '');
        } catch (e) {
            return _escHtml(text);
        }
    }

    // ============================================================
    //  脚注后处理
    // ============================================================
    function postprocessFootnotes(html, footnotes) {
        if (!html) return html;

        html = html.replace(
            /<p>\s*@@MKFNDEF_([^@\s]+)@@\s*<\/p>\s*/g,
            ''
        );
        html = html.replace(/@@MKFNDEF_[^@\s]+@@/g, '');

        var refCounter = {};
        html = html.replace(/@@MKFNREF_([^@\s]+)@@/g, function (m, key) {
            var c = (refCounter[key] || 0) + 1;
            refCounter[key] = c;
            var idSuffix = (c === 1) ? '' : ('-' + c);
            var kEsc = _escapeAttr(key);
            return '<sup class="footnote-ref" data-footnote-ref="1" ' +
                   'data-footnote-index="' + kEsc + '">' +
                   '<a href="#fn-' + kEsc + '" id="fnref-' + kEsc + idSuffix +
                   '" role="doc-noteref">' + _escHtml(key) + '</a>' +
                   '</sup>';
        });

        if (footnotes && footnotes.length > 0) {
            var items = [];
            for (var i = 0; i < footnotes.length; i++) {
                var fn = footnotes[i];
                var kEsc2 = _escapeAttr(fn.index);
                var contentHtml = renderInlineMarkdown(fn.content || '');
                if (typeof global.sanitizeHtml === 'function') {
                    try {
                        contentHtml = global.sanitizeHtml(contentHtml);
                    } catch (e) { /* 保持已 escape 文本 */ }
                }
                var startAttr = (typeof fn.contentStart === 'number') ? fn.contentStart : '';
                var endAttr = (typeof fn.contentEnd === 'number') ? fn.contentEnd : '';
                var oldTextAttr = _escapeAttr(fn.content || '');

                items.push(
                    '<li id="fn-' + kEsc2 + '" data-footnote-item="1" ' +
                    'data-footnote-index="' + kEsc2 + '">' +
                    '<p data-md-editable="footnote" ' +
                    'data-md-start="' + startAttr + '" ' +
                    'data-md-end="' + endAttr + '" ' +
                    'data-md-old-text="' + oldTextAttr + '" ' +
                    'contenteditable="false" spellcheck="false">' +
                    contentHtml +
                    '</p>' +
                    '<a href="#fnref-' + kEsc2 + '" ' +
                    'class="footnote-backref" data-footnote-backref="1" ' +
                    'data-no-edit="1" contenteditable="false" ' +
                    'role="doc-backlink" aria-label="返回引用">↩</a>' +
                    '</li>'
                );
            }
            html +=
                '<section class="footnotes" data-footnotes="1" ' +
                'role="doc-endnotes" aria-label="脚注">' +
                '<hr class="footnotes-sep">' +
                '<ol class="footnotes-list">' + items.join('') + '</ol>' +
                '</section>';
        }

        return html;
    }

    // ============================================================
    //  脚注点击跳转
    // ============================================================
    function setupFootnoteClick(previewEl) {
        if (!previewEl) return;
        if (previewEl.__footnoteClickBound) return;
        previewEl.__footnoteClickBound = true;

        previewEl.addEventListener('click', function (e) {
            var a = null;
            var el = e.target;
            while (el && el !== previewEl) {
                if (el.nodeType === 1 && el.tagName &&
                    el.tagName.toLowerCase() === 'a') {
                    var href = el.getAttribute('href') || '';
                    if (/^#fn(ref)?-/.test(href)) {
                        a = el;
                        break;
                    }
                    break;
                }
                el = el.parentElement;
            }
            if (!a) return;

            var href2 = a.getAttribute('href') || '';
            if (!/^#fn(ref)?-/.test(href2)) return;

            e.preventDefault();
            e.stopPropagation();

            var targetId = href2.slice(1);
            var target = document.getElementById(targetId);
            if (!target) return;

            var container = previewEl.parentElement;
            if (container) {
                var cRect = container.getBoundingClientRect();
                var tRect = target.getBoundingClientRect();
                var targetTop = tRect.top - cRect.top + container.scrollTop;
                var desired = targetTop - container.clientHeight / 3;
                container.scrollTop = Math.max(0, desired);
            }

            target.classList.add('footnote-flash');
            setTimeout(function () {
                target.classList.remove('footnote-flash');
            }, 1200);
        }, true);
    }

    // ============================================================
    //  任务列表预处理
    // ============================================================
    function preprocessTaskLists(md) {
        var source = String(md);
        var codeRanges = collectCodeRanges(source);
        var isInCode = makeIsInCode(codeRanges);
        var taskItems = [];
        var lines = source.split('\n');
        var out = [];
        var offset = 0;
        var prevLine = '';

        for (var li = 0; li < lines.length; li++) {
            var line = lines[li];
            var lineStart = offset;
            offset += line.length + 1;

            if (isInCode(lineStart)) {
                out.push(line);
                prevLine = line;
                continue;
            }

            var m = /^([ \t]*)(>[ \t]*)?([-*+][ \t]+)\[([ xX])\]([ \t]+)/.exec(line);
            if (m) {
                var indent = m[1] || '';
                var quote = m[2] || '';
                var bullet = m[3];
                var mark = m[4];
                var space = m[5];

                var isCodeBlock = false;

                if (!quote && indent.length >= 4) {
                    var prevIsList = /^[ \t]*[-*+][ \t]|^[ \t]*\d+\.[ \t]/.test(prevLine);
                    if (!prevIsList) isCodeBlock = true;
                } else if (quote) {
                    var quoteSpaces = quote.length - 1;
                    if (quoteSpaces >= 4) {
                        var prevIsQuoteList = /^[ \t]*>[ \t]*[-*+][ \t]/.test(prevLine);
                        if (!prevIsQuoteList) isCodeBlock = true;
                    }
                }

                if (isCodeBlock) {
                    out.push(line);
                    prevLine = line;
                    continue;
                }

                var idx = taskItems.length;
                var placeholder = '@@MKTASK' + idx + 'MKTASK@@';
                var prefix = indent + quote + bullet;
                var bracketPos = lineStart + prefix.length;
                taskItems.push({
                    placeholder: placeholder,
                    bracketPos: bracketPos,
                    checked: (mark === 'x' || mark === 'X'),
                });
                out.push(prefix + placeholder + space + line.slice(m[0].length));
                prevLine = line;
                continue;
            }

            out.push(line);
            prevLine = line;
        }

        return { text: out.join('\n'), taskItems: taskItems };
    }

    function restoreTaskListHtml(html, taskItems) {
        if (!taskItems || taskItems.length === 0) return html;
        var out = html;
        for (var i = 0; i < taskItems.length; i++) {
            var item = taskItems[i];
            var checkedVal = item.checked ? '1' : '0';
            var ariaVal = item.checked ? 'true' : 'false';
            var text = item.checked ? '[x]' : '[ ]';
            var spanHtml =
                '<span class="task-list-checkbox"' +
                ' data-md-task-ordinal="' + i + '"' +
                ' data-md-task-checked="' + checkedVal + '"' +
                ' role="checkbox"' +
                ' aria-checked="' + ariaVal + '"' +
                ' contenteditable="false">' + text + '</span>';
            out = out.split(item.placeholder).join(spanHtml);
        }
        return out;
    }

    // ============================================================
    //  列表松散段落修复
    //  解包 li 的第一个直接 <p>（允许后面有嵌套列表）
    // ============================================================
    function fixLooseListParagraphs(html) {
        if (!html) return html;
        if (typeof DOMParser === 'undefined') return html;
        try {
            var doc = new DOMParser().parseFromString(
                '<div id="__fix_loose_root__">' + html + '</div>',
                'text/html'
            );
            var root = doc.getElementById('__fix_loose_root__');
            if (!root) return html;

            var lis = root.querySelectorAll('li');
            for (var i = 0; i < lis.length; i++) {
                var li = lis[i];

                var firstP = null;
                var firstNonWhitespace = null;
                for (var c = 0; c < li.childNodes.length; c++) {
                    var child = li.childNodes[c];
                    if (child.nodeType === 3) {
                        if (child.nodeValue && child.nodeValue.trim()) {
                            firstNonWhitespace = child;
                            break;
                        }
                    } else if (child.nodeType === 1) {
                        firstNonWhitespace = child;
                        if (child.tagName.toLowerCase() === 'p') {
                            firstP = child;
                        }
                        break;
                    }
                }

                if (!firstP || firstNonWhitespace !== firstP) continue;

                var frag = doc.createDocumentFragment();
                while (firstP.firstChild) {
                    frag.appendChild(firstP.firstChild);
                }
                li.replaceChild(frag, firstP);
            }
            return root.innerHTML;
        } catch (e) {
            console.warn('[fixLooseListParagraphs]', e);
            return html;
        }
    }

    // ============================================================
    //  数学公式
    // ============================================================
    // ★ v2.1.6：`\[` / `\]` 同时也是 CommonMark 的转义写法。
    //   只有行首的 `\[` 与行尾的 `\]`（允许前后空白）才按独立公式处理；
    //   正文里成对出现的 `\[文字\]` 交给 marked 还原为字面量方括号，
    //   否则会被当成块级公式插入 <div class="math-block">，造成断行。
    function isBlockMathDelimiter(md, start, end) {
        var i = start - 1;
        while (i >= 0) {
            var before = md.charAt(i);
            if (before === '\n') break;
            if (before !== ' ' && before !== '\t') return false;
            i--;
        }
        i = end;
        while (i < md.length) {
            var after = md.charAt(i);
            if (after === '\n') break;
            if (after !== ' ' && after !== '\t' && after !== '\r') return false;
            i++;
        }
        return true;
    }

    function preprocessMath(md) {
        var mathList = [];
        var codeRanges = collectCodeRanges(md);
        var isInCode = makeIsInCode(codeRanges);
        var m;

        var allMatches = [];

        var blockRe = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]/g;
        while ((m = blockRe.exec(md)) !== null) {
            if (isInCode(m.index)) continue;
            if (m[2] !== undefined &&
                !isBlockMathDelimiter(md, m.index, m.index + m[0].length)) {
                continue;
            }
            var texB = (m[1] !== undefined) ? m[1] : m[2];
            texB = texB.replace(/^\s+|\s+$/g, '');
            if (!texB) continue;
            allMatches.push({
                start: m.index, end: m.index + m[0].length,
                tex: texB, display: true
            });
        }

        var inlineRe = /\$(?![\s\d])([^\$\n]+?)\$|\\\(([\s\S]+?)\\\)/g;
        while ((m = inlineRe.exec(md)) !== null) {
            if (isInCode(m.index)) continue;
            var overlap = false;
            for (var k = 0; k < allMatches.length; k++) {
                if (m.index >= allMatches[k].start &&
                    m.index < allMatches[k].end) {
                    overlap = true; break;
                }
            }
            if (overlap) continue;
            var texI = (m[1] !== undefined) ? m[1] : m[2];
            if (!texI) continue;
            allMatches.push({
                start: m.index, end: m.index + m[0].length,
                tex: texI, display: false
            });
        }

        allMatches.sort(function (a, b) { return b.start - a.start; });

        var result = md;
        for (var j = 0; j < allMatches.length; j++) {
            var item = allMatches[j];
            var prefix = item.display ? '@@MATHBLOCK_' : '@@MATHINLINE_';
            var placeholder = prefix + j + '@@';
            mathList.push({
                placeholder: placeholder,
                tex: item.tex,
                display: item.display
            });
            result = result.slice(0, item.start) +
                     placeholder +
                     result.slice(item.end);
        }

        return { text: result, mathList: mathList };
    }

    function replaceMathPlaceholders(html, mathList) {
        if (!html || !mathList || mathList.length === 0) return html;
        var out = html;
        for (var i = 0; i < mathList.length; i++) {
            var item = mathList[i];
            var katexHtml = renderKatexToString(item.tex, item.display);
            if (item.display) {
                katexHtml = '<div class="math-block">' + katexHtml + '</div>';
            } else {
                katexHtml = '<span class="katex-inline">' + katexHtml + '</span>';
            }
            out = out.split(item.placeholder).join(katexHtml);
        }
        return out;
    }

    // ============================================================
    //  HTML 块保护（★ 本轮：新增 <ins>/<u> 内部 markdown 解析）
    // ============================================================
    function preprocessHtmlBlocks(md, docDir) {
        var htmlList = [];
        var result = String(md);

        var codeRanges = collectCodeRanges(result);
        var isInCode = makeIsInCode(codeRanges);

        // ★ 处理 <ins> 和 <u>：把内部 markdown 提前用 marked.parseInline 解析
        function preprocessUnderlineTag(tagName) {
            var openTag = '<' + tagName + '>';
            var closeTag = '</' + tagName + '>';
            var re = new RegExp(
                '<' + tagName + '\\b[^>]*>([\\s\\S]*?)<\\/' + tagName + '>',
                'gi'
            );
            result = result.replace(re, function (match, inner, offset) {
                if (isInCode(offset)) return match;
                var innerHtml;
                if (typeof marked !== 'undefined' &&
                    typeof marked.parseInline === 'function') {
                    try {
                        innerHtml = marked.parseInline(inner);
                    } catch (e) {
                        innerHtml = _escHtml(inner);
                    }
                } else {
                    innerHtml = _escHtml(inner);
                }
                var idx = htmlList.length;
                var placeholder = '@@MKHTML' + idx + 'MKHTML@@';
                htmlList.push({
                    placeholder: placeholder,
                    html: '<ins>' + innerHtml + '</ins>'
                });
                return placeholder;
            });
        }

        preprocessUnderlineTag('ins');
        preprocessUnderlineTag('u');

        // 处理 <a>
        var reA = /<a\b[^>]*>[\s\S]*?<\/a>/gi;
        result = result.replace(reA, function (match, offset) {
            if (isInCode(offset)) return match;
            var idx = htmlList.length;
            var placeholder = '@@MKHTML' + idx + 'MKHTML@@';
            htmlList.push({ placeholder: placeholder, html: match });
            return placeholder;
        });

        // 处理 <img>
        var reImg = /<img\b([^>]*?)\/?>/gi;
        result = result.replace(reImg, function (match, p1, offset) {
            if (isInCode(offset)) return match;
            var idx = htmlList.length;
            var placeholder = '@@MKHTML' + idx + 'MKHTML@@';

            var rewritten = match;
            var hasMdSrc = /\bdata-md-src\s*=/i.test(match);
            var hasMdAlt = /\bdata-md-alt\s*=/i.test(match);
            var altMatch = match.match(/(?:^|\s)alt\s*=\s*(["'])([\s\S]*?)\1/i);
            var altVal = altMatch ? altMatch[2] : '';
            if (docDir !== undefined) {
                rewritten = match.replace(
                    /(\bsrc\s*=\s*)(["'])([^"']*)(\2)/i,
                    function (m, prefix, quote1, srcVal) {
                        var newSrc = _rewriteSrc(srcVal, docDir || '');
                        // ★ 在重写前保存原始 src / alt，供预览编辑回写 Markdown
                        var extra = '';
                        if (!hasMdSrc) {
                            extra += ' data-md-src="' + _escapeAttr(srcVal) + '"';
                        }
                        if (altMatch && !hasMdAlt) {
                            extra += ' data-md-alt="' + _escapeAttr(altVal) + '"';
                        }
                        return prefix + quote1 + newSrc + quote1 + extra;
                    }
                );
            }

            htmlList.push({ placeholder: placeholder, html: rewritten });
            return placeholder;
        });

        return { text: result, htmlList: htmlList };
    }

    // ★ 多轮循环替换，处理嵌套占位符
    function restoreHtmlBlocks(html, htmlList) {
        if (!htmlList || htmlList.length === 0) return html;
        var out = html;
        var maxIter = 5;
        for (var it = 0; it < maxIter; it++) {
            var before = out;
            for (var i = 0; i < htmlList.length; i++) {
                var item = htmlList[i];
                if (out.indexOf(item.placeholder) >= 0) {
                    out = out.split(item.placeholder).join(item.html);
                }
            }
            if (out === before) break;
        }
        return out;
    }

    // ============================================================
    //  marked 自定义渲染
    // ============================================================
    if (typeof marked !== 'undefined') {
        var mdRenderer = new marked.Renderer();

        mdRenderer.code = function (code, infostring, escaped) {
            var info = (infostring || '').trim();
            var lang = (info.match(/^\S+/) || [''])[0].toLowerCase();

            if (lang === 'math' || lang === 'latex' || lang === 'katex' || lang === 'tex') {
                return '<div class="math-block" data-tex="' +
                       encodeURIComponent(code) + '">' +
                       _escHtml(code) + '</div>\n';
            }

            if (typeof hljs !== 'undefined') {
                var highlighted;
                try {
                    if (lang && hljs.getLanguage(lang)) {
                        highlighted = hljs.highlight(code, {
                            language: lang,
                            ignoreIllegals: true
                        }).value;
                    } else {
                        highlighted = hljs.highlightAuto(code).value;
                    }
                } catch (e) {
                    highlighted = _escHtml(code);
                }
                var cls = 'hljs' + (lang ? ' language-' + lang : '');
                return '<pre><code class="' + cls + '">' + highlighted + '</code></pre>\n';
            }
            return '<pre><code>' + _escHtml(code) + '</code></pre>\n';
        };

        mdRenderer.html = function (html) {
            var trimmed = String(html).trim();

            if (/^<\/?(ins|u|span|sub|sup|mark|kbd|abbr|cite|q|dfn|time|var|samp|small|big|del|s|strike|tt|font|em|strong|b|i)\b/i.test(trimmed)) {
                return html;
            }

            if (/^<(details|summary|a|picture)\b/i.test(trimmed) ||
                /^<\/(details|summary|a|picture)\b/i.test(trimmed)) {
                return html + '\n';
            }
            if (/^<(img|br|source)\b/i.test(trimmed)) {
                return html + '\n';
            }
            return '<p>' + _escHtml(html) + '</p>\n';
        };

        marked.setOptions({
            renderer: mdRenderer,
            breaks: true,
            gfm: true,
            pedantic: false,
            smartLists: false,
            smartypants: false,
            xhtml: false
        });
    }

    // ============================================================
    //  KaTeX
    // ============================================================
    function renderKatexToString(tex, display) {
        if (typeof katex === 'undefined') {
            return '<code>' + _escHtml(tex) + '</code>';
        }
        try {
            var opts = Object.assign({}, KATEX_OPTS, { displayMode: !!display });
            return katex.renderToString(tex, opts);
        } catch (e) {
            return '<span class="katex-error">[公式错误] ' +
                   _escHtml(tex) + '</span>';
        }
    }

    function renderMathBlocks(root) {
        if (typeof katex === 'undefined') return;
        var blocks = root.querySelectorAll('.math-block[data-tex]');
        for (var i = 0; i < blocks.length; i++) {
            var el = blocks[i];
            var tex = el.getAttribute('data-tex');
            try { tex = decodeURIComponent(tex); }
            catch (e) { tex = el.textContent; }

            try {
                katex.render(tex, el, {
                    displayMode: true,
                    throwOnError: false,
                    strict: false,
                    trust: false,
                    output: 'htmlAndMathml'
                });
            } catch (e) {
                el.innerHTML = '<span class="katex-error">[公式错误] ' +
                               _escHtml(String(e.message || e)) +
                               '</span><br><code>' +
                               _escHtml(tex) + '</code>';
            }
        }
    }

    // ============================================================
    //  ★ v2.1.5：代码块自动换行
    //  - 把每个逻辑行包成 block 级 span，长行在容器内自动换行，
    //    不再依赖 <pre> 的横向滚动条（PDF 打印时滚动区会被裁断）
    //  - 行首缩进写入 --md-code-indent，续行按该缩进 +2ch 悬挂缩进，
    //    换行后的文字仍然看得出代码层级
    //  - 行与行之间保留原始 "\n" 文本节点：textContent 与源码完全一致，
    //    预览编辑（extractPreText）、复制、HTML 导出都不会丢换行
    //  - 跨行的高亮 <span> 在换行处先闭合、下一行再重开，高亮不丢
    // ============================================================
    var CODE_TAB_SIZE = 4;
    var CODE_MAX_INDENT = 24;

    function _decodeIndentText(s) {
        return String(s)
            .replace(/&nbsp;|&#160;|&#[xX]a0;/gi, ' ')
            .replace(/&Tab;|&#9;|&#[xX]9;/gi, '\t')
            .replace(/\u00a0/g, ' ');
    }

    function _codeIndentChars(text) {
        var m = /^[ \t]*/.exec(String(text || ''));
        if (!m) return 0;
        var s = m[0];
        var n = 0;
        for (var i = 0; i < s.length; i++) {
            n += (s.charAt(i) === '\t') ? CODE_TAB_SIZE : 1;
        }
        return n;
    }

    // 把高亮后的 HTML 按 "\n" 切成逻辑行；跨行的标签在断点处闭合 / 重开。
    function _splitCodeHtmlLines(html) {
        var tokenRe = /<[^>]*>|[^<]+/g;
        var lineHtml = '';
        var lineText = '';
        var openTags = [];
        var lines = [];
        var m;

        function closeOpenTags() {
            var out = '';
            for (var i = openTags.length - 1; i >= 0; i--) {
                out += '</' + openTags[i].name + '>';
            }
            return out;
        }

        function reopenTags() {
            var out = '';
            for (var i = 0; i < openTags.length; i++) {
                out += openTags[i].open;
            }
            return out;
        }

        function pushLine() {
            lines.push({
                html: lineHtml + closeOpenTags(),
                indent: _codeIndentChars(lineText)
            });
            lineHtml = reopenTags();
            lineText = '';
        }

        while ((m = tokenRe.exec(html)) !== null) {
            var token = m[0];
            if (!token) continue;

            if (token.charAt(0) === '<') {
                if (/^<\//.test(token)) {
                    var closeMatch = /^<\s*\/\s*([a-zA-Z0-9:-]+)/.exec(token);
                    if (closeMatch) {
                        var closeName = closeMatch[1].toLowerCase();
                        for (var ci = openTags.length - 1; ci >= 0; ci--) {
                            if (openTags[ci].name === closeName) {
                                openTags.splice(ci, 1);
                                break;
                            }
                        }
                    }
                    lineHtml += token;
                } else if (/^<!|^<\?/.test(token) ||
                           /\/>\s*$/.test(token) ||
                           /^<\s*(br|hr|img|input|meta|link|wbr|source|area|col|embed)\b/i.test(token)) {
                    lineHtml += token;
                } else {
                    var openMatch = /^<\s*([a-zA-Z0-9:-]+)/.exec(token);
                    openTags.push({
                        name: (openMatch ? openMatch[1] : 'span').toLowerCase(),
                        open: token
                    });
                    lineHtml += token;
                }
                continue;
            }

            var parts = token.split('\n');
            for (var pi = 0; pi < parts.length; pi++) {
                if (pi > 0) pushLine();
                lineHtml += parts[pi];
                lineText += _decodeIndentText(parts[pi]);
            }
        }

        lines.push({
            html: lineHtml + closeOpenTags(),
            indent: _codeIndentChars(lineText)
        });
        return lines;
    }

    // 给预览里的代码块加行包裹（幂等：pre 上有 data-md-code-wrapped 就跳过）
    function wrapCodeBlockLines(root) {
        if (!root || !root.querySelectorAll) return;

        var pres = root.querySelectorAll('pre');
        for (var i = 0; i < pres.length; i++) {
            var pre = pres[i];
            if (pre.getAttribute('data-md-code-wrapped') === '1') continue;

            var code = pre.querySelector(':scope > code');
            if (!code) continue;

            pre.classList.add('md-code-wrap');
            pre.setAttribute('data-md-code-wrapped', '1');

            var html = code.innerHTML;
            if (!html) continue;

            var lines = _splitCodeHtmlLines(html);
            var out = [];
            for (var li = 0; li < lines.length; li++) {
                var indent = Math.min(lines[li].indent, CODE_MAX_INDENT);
                out.push(
                    '<span class="md-code-line" style="--md-code-indent:' +
                    indent + '">' + lines[li].html + '</span>'
                );
            }
            // 行间保留 "\n"：textContent / 预览编辑 / 复制仍拿到原始换行
            code.innerHTML = out.join('\n');
        }
    }

    // ============================================================
    //  图片解析兜底
    // ============================================================
    function resolveLocalImages(root, docDir) {
        if (!root) return;
        var imgs = root.querySelectorAll('img[src]');
        for (var i = 0; i < imgs.length; i++) {
            var img = imgs[i];
            var src = img.getAttribute('src');
            if (!src) continue;

            // ★ 保存 Markdown 里的原始 src（可能是相对路径 assets/x.png），
            //   预览编辑回写时用它还原，避免变成 /fs/ 解码后的绝对路径。
            if (!img.hasAttribute('data-md-src')) {
                img.setAttribute('data-md-src', src);
            }

            if (img.getAttribute('data-resolved') === '1') continue;

            if (/^(data:|blob:)/i.test(src)) {
                img.setAttribute('data-resolved', '1');
                continue;
            }

            if (src.indexOf('base64') !== -1 || src.indexOf('[图片') !== -1) {
                img.setAttribute('data-resolved', '1');
                continue;
            }

            var baseUrl = _getAssetBase();
            if (baseUrl && src.indexOf(baseUrl) === 0) {
                img.setAttribute('data-resolved', '1');
                continue;
            }

            var newSrc = _rewriteSrc(src, docDir);
            if (newSrc && newSrc !== src) {
                img.setAttribute('src', newSrc);
            }
            img.setAttribute('data-resolved', '1');
        }
    }

    // ============================================================
    //  段落可编辑性判定
    // ============================================================
    var BLOCK_TAGS_FOR_P = {
        'div': 1, 'p': 1, 'ul': 1, 'ol': 1, 'li': 1,
        'table': 1, 'pre': 1, 'blockquote': 1,
        'h1': 1, 'h2': 1, 'h3': 1, 'h4': 1, 'h5': 1, 'h6': 1,
        'details': 1, 'summary': 1
    };

    var BLOCK_TAGS_FOR_LI = {
        'div': 1, 'p': 1,
        'table': 1, 'pre': 1, 'blockquote': 1,
        'h1': 1, 'h2': 1, 'h3': 1, 'h4': 1, 'h5': 1, 'h6': 1,
        'details': 1, 'summary': 1
    };

    function hasBlockChildren(el) {
        for (var i = 0; i < el.childNodes.length; i++) {
            var child = el.childNodes[i];
            if (child.nodeType === 1) {
                var tag = child.tagName.toLowerCase();
                if (BLOCK_TAGS_FOR_P[tag]) return true;
            }
        }
        return false;
    }

    function hasNonListBlockChildren(liEl) {
        for (var i = 0; i < liEl.childNodes.length; i++) {
            var child = liEl.childNodes[i];
            if (child.nodeType === 1) {
                var tag = child.tagName.toLowerCase();
                if (BLOCK_TAGS_FOR_LI[tag]) return true;
            }
        }
        return false;
    }

    // ★ 只有“链接内的图标图片”不阻止编辑；
    //   普通正文图片仍保持不可双击编辑，避免误改图片块。
    function hasImageOutsideLink(el) {
        var imgs = el.querySelectorAll('img');
        for (var i = 0; i < imgs.length; i++) {
            var img = imgs[i];
            if (!img.closest || !img.closest('a')) return true;
        }
        return false;
    }

    function markEditableBlocks(root, markdownText) {
        var normArr = [];
        var map = [];
        for (var i = 0; i < markdownText.length; i++) {
            var ch = markdownText[i];
            if (/\s/.test(ch)) continue;
            normArr.push(ch);
            map.push(i);
        }
        var normStr = normArr.join('');

        var candidates = [];

        var ps = root.querySelectorAll('p, h1, h2, h3, h4, h5, h6');
        for (var pi = 0; pi < ps.length; pi++) {
            candidates.push({ el: ps[pi], kind: 'p' });
        }

        var lis = root.querySelectorAll('li');
        for (var li = 0; li < lis.length; li++) {
            var liEl = lis[li];
            var hasDirectP = false;
            for (var ci = 0; ci < liEl.children.length; ci++) {
                if (liEl.children[ci].tagName.toLowerCase() === 'p') {
                    hasDirectP = true;
                    break;
                }
            }
            if (hasDirectP) continue;
            candidates.push({ el: liEl, kind: 'li' });
        }

        candidates.sort(function (a, b) {
            if (a.el === b.el) return 0;
            var pos = a.el.compareDocumentPosition(b.el);
            if (pos & 4) return -1;
            if (pos & 2) return 1;
            return 0;
        });

        // ★ 新增：把围栏代码块（pre）标记为可双击编辑
        try {
            var codeBlocks = findCodeBlocks(markdownText);
            var pres = root.querySelectorAll('pre');
            for (var pri = 0; pri < pres.length; pri++) {
                if (pri >= codeBlocks.length) break;
                var preEl = pres[pri];
                // 跳过在 details / footnotes / table 内的代码块
                if (preEl.closest && (
                    preEl.closest('details') ||
                    preEl.closest('section.footnotes') ||
                    preEl.closest('td, th')
                )) {
                    preEl.setAttribute('data-md-editable', '0');
                    continue;
                }
                var blk = codeBlocks[pri];
                preEl.setAttribute('data-md-editable', '1');
                preEl.setAttribute('data-md-start', String(blk.contentStart));
                preEl.setAttribute('data-md-end', String(blk.contentEnd));
                preEl.setAttribute('data-md-old-text', blk.content);
                preEl.setAttribute('data-md-kind', 'codeblock');
                preEl.setAttribute('contenteditable', 'false');
                preEl.setAttribute('spellcheck', 'false');
            }
        } catch (e) {
            console.warn('[markEditableBlocks] code block mark failed', e);
        }

        var searchFromNorm = 0;

        for (var bi = 0; bi < candidates.length; bi++) {
            var item = candidates[bi];
            var el = item.el;
            var kind = item.kind;

            if (el.getAttribute && el.getAttribute('data-md-editable') === 'footnote') {
                continue;
            }

            if (el.closest && el.closest('details')) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            if (el.closest && el.closest('section.footnotes')) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            if (el.closest && el.closest('td, th')) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            if (el.parentElement && el.parentElement !== root) {
                var parentTag = el.parentElement.tagName.toLowerCase();
                if (parentTag === 'details' || parentTag === 'summary') {
                    el.setAttribute('data-md-editable', '0');
                    continue;
                }
            }

            if (kind === 'li') {
                if (hasNonListBlockChildren(el)) {
                    el.setAttribute('data-md-editable', '0');
                    continue;
                }
            } else {
                if (hasBlockChildren(el)) {
                    el.setAttribute('data-md-editable', '0');
                    continue;
                }
            }

            if (hasImageOutsideLink(el)) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            if (el.querySelector('.katex, .katex-inline, .math-block')) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            var mdText;
            if (kind === 'li') {
                mdText = domToMarkdown(el, { skipNestedLists: true });
            } else {
                mdText = domToMarkdown(el);
            }

            var targetNorm = mdText.replace(/\s+/g, '');
            if (!targetNorm) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            var idx = normStr.indexOf(targetNorm, searchFromNorm);
            if (idx < 0) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            var startInSource = map[idx];
            var endInSource = map[idx + targetNorm.length - 1] + 1;

            el.setAttribute('data-md-editable', '1');
            el.setAttribute('data-md-start', String(startInSource));
            el.setAttribute('data-md-end', String(endInSource));
            el.setAttribute('data-md-old-text',
                markdownText.slice(startInSource, endInSource));
            el.setAttribute('contenteditable', 'false');
            el.setAttribute('spellcheck', 'false');

            searchFromNorm = idx + targetNorm.length;
        }
    }

    // ============================================================
    //  表格
    // ============================================================
    function findMarkdownTables(md) {
        var source = String(md);
        var lines = source.split('\n');
        var tables = [];
        var lineOffsets = [];
        var acc = 0;
        for (var k = 0; k < lines.length; k++) {
            lineOffsets.push(acc);
            acc += lines[k].length + 1;
        }

        var SEP_RE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/;

        var i = 0;
        while (i < lines.length - 1) {
            if (lines[i].indexOf('|') === -1) { i++; continue; }
            if (!SEP_RE.test(lines[i + 1])) { i++; continue; }
            var j = i + 2;
            while (j < lines.length && lines[j].indexOf('|') !== -1 &&
                   lines[j].trim() !== '') {
                j++;
            }
            var lastLine = j - 1;
            var startOff = lineOffsets[i];
            var endOff = lineOffsets[lastLine] + lines[lastLine].length;
            tables.push({
                startLine: i,
                endLine: lastLine,
                start: startOff,
                end: endOff
            });
            i = j;
        }
        return tables;
    }

    function annotateTables(root, tables) {
        if (!tables || tables.length === 0) return;
        var domTables = root.querySelectorAll('table');
        if (!domTables || domTables.length === 0) return;

        var n = Math.min(domTables.length, tables.length);
        for (var i = 0; i < n; i++) {
            var domTable = domTables[i];
            var info = tables[i];

            domTable.setAttribute('data-md-table-index', String(i));
            domTable.setAttribute('data-md-table-start', String(info.start));
            domTable.setAttribute('data-md-table-end', String(info.end));

            var rows = domTable.querySelectorAll('tr');
            for (var r = 0; r < rows.length; r++) {
                var cells = rows[r].children;
                for (var c = 0; c < cells.length; c++) {
                    var cell = cells[c];
                    var tag = cell.tagName.toLowerCase();
                    if (tag !== 'td' && tag !== 'th') continue;

                    cell.setAttribute('data-md-table-index', String(i));
                    cell.setAttribute('data-md-row', String(r));
                    cell.setAttribute('data-md-col', String(c));
                    cell.setAttribute('data-md-cell-kind', tag);
                    cell.setAttribute('data-md-cell-header',
                        tag === 'th' ? '1' : '0');
                    cell.setAttribute('data-md-old-html', cell.innerHTML);
                    cell.setAttribute('data-md-editable', '1');
                    cell.setAttribute('contenteditable', 'false');
                    cell.setAttribute('spellcheck', 'false');
                }
            }
        }
    }

    // ============================================================
    //  ★ v2.1.7：有序列表“所见即所得”编号
    //  浏览器默认会把 <ol> 重新按 1,2,3 编号，导致编辑器里手写的
    //  1,3,4 在预览中变成 1,2,3。这里把源码里的实际编号写到
    //  <li value="...">，保证预览编号与编辑器一致。
    // ============================================================
    function collectOrderedListNumbers(source) {
        var text = String(source == null ? '' : source);
        var codeRanges = collectCodeRanges(text);
        var isInCode = makeIsInCode(codeRanges);
        var numbers = [];
        var lines = text.split('\n');
        var offset = 0;
        var prevLine = '';

        for (var li = 0; li < lines.length; li++) {
            var line = lines[li];
            var lineStart = offset;
            offset += line.length + 1;

            if (isInCode(lineStart)) {
                prevLine = line;
                continue;
            }

            var m = /^([ \t]*)(>[ \t]*)?(\d{1,9})([.)])[ \t]+/.exec(line);
            if (m) {
                var indent = m[1] || '';
                var quote = m[2] || '';
                if (!quote && indent.length >= 4) {
                    var prevIsList = /^[ \t]*[-*+][ \t]|^[ \t]*\d+\.[ \t]/.test(prevLine);
                    if (!prevIsList) {
                        prevLine = line;
                        continue;
                    }
                }
                numbers.push(parseInt(m[3], 10));
            }
            prevLine = line;
        }

        return numbers;
    }

    function applyOrderedListNumbers(html, source) {
        if (!html || typeof DOMParser === 'undefined') return html;

        var numbers = collectOrderedListNumbers(source);
        if (numbers.length === 0) return html;

        try {
            var doc = new DOMParser().parseFromString(
                '<div id="__ol_value_root__">' + html + '</div>',
                'text/html'
            );
            var root = doc.getElementById('__ol_value_root__');
            if (!root) return html;

            var lis = root.querySelectorAll('ol > li');
            // 数量不一致说明列表结构映射不可靠（例如源码里有裸 HTML <ol>），
            // 保持浏览器默认顺序编号，避免把编号写错。
            if (lis.length !== numbers.length) return html;

            for (var i = 0; i < lis.length; i++) {
                lis[i].setAttribute('value', String(numbers[i]));
            }
            return root.innerHTML;
        } catch (e) {
            console.warn('[applyOrderedListNumbers]', e);
            return html;
        }
    }

    // ============================================================
    //  任务列表
    // ============================================================
    function markTaskListItems(root) {
        var spans = root.querySelectorAll('.task-list-checkbox');
        if (spans.length === 0) return;

        for (var i = 0; i < spans.length; i++) {
            var span = spans[i];
            var li = span.closest('li');
            if (!li) continue;
            li.classList.add('task-list-item');
            var list = li.parentElement;
            if (list && (list.tagName === 'UL' || list.tagName === 'OL')) {
                list.classList.add('contains-task-list');
            }

            // ★ v2.1.7：预览中不再插入 “- ” 前缀，只保留复选框本身；
            //   复制 / 导出仍由 checkbox 状态还原为 “- [x] ”。
        }
    }

    // ============================================================
    //  折叠 <details>
    // ============================================================
    function loadFoldState() {
        try {
            var raw = localStorage.getItem(FOLD_STATE_KEY);
            if (!raw) return {};
            return JSON.parse(raw) || {};
        } catch (e) {
            return {};
        }
    }

    function saveFoldState(state) {
        try {
            localStorage.setItem(FOLD_STATE_KEY, JSON.stringify(state));
        } catch (e) { /* ignore */ }
    }

    function foldKeyForDetails(details) {
        var summary = details.querySelector('summary');
        var title = summary ? (summary.textContent || '').trim() : '';
        var startAttr = details.getAttribute('data-md-start');
        if (startAttr != null) {
            return 'p' + startAttr + ':' + title;
        }
        return 't:' + title;
    }

    function setupDetailsBlocks(root) {
        var detailsList = root.querySelectorAll('details');
        if (detailsList.length === 0) return;

        var state = loadFoldState();

        for (var i = 0; i < detailsList.length; i++) {
            var d = detailsList[i];
            d.classList.add('md-details');

            if (!d.hasAttribute('data-md-restored')) {
                var key = foldKeyForDetails(d);
                if (Object.prototype.hasOwnProperty.call(state, key)) {
                    if (state[key]) d.setAttribute('open', '');
                    else d.removeAttribute('open');
                }
                d.setAttribute('data-md-restored', '1');
            }

            if (!d.hasAttribute('data-md-bound')) {
                d.setAttribute('data-md-bound', '1');
                d.addEventListener('toggle', function (ev) {
                    var el = ev.currentTarget;
                    var st = loadFoldState();
                    var k = foldKeyForDetails(el);
                    st[k] = !!el.open;
                    saveFoldState(st);
                });
            }

            var summary = d.querySelector(':scope > summary');
            if (summary) {
                summary.classList.add('md-summary');
                summary.setAttribute('data-md-editable', '0');
            }
        }
    }

    function locateDetailsInSource(root, markdownText) {
        var detailsList = root.querySelectorAll('details');
        if (detailsList.length === 0) return;

        var re = /<details\b[^>]*>[\s\S]*?<\/details>/gi;
        var spans = [];
        var m;
        while ((m = re.exec(markdownText)) !== null) {
            spans.push({ start: m.index, end: m.index + m[0].length });
        }

        var n = Math.min(detailsList.length, spans.length);
        for (var i = 0; i < n; i++) {
            var d = detailsList[i];
            d.setAttribute('data-md-start', String(spans[i].start));
            d.setAttribute('data-md-end', String(spans[i].end));
            d.setAttribute('data-md-type', 'details');
        }
    }

    // ============================================================
    //  主渲染
    // ============================================================
    function renderMarkdown(markdownText, options) {
        options = options || {};
        var contentElement = options.target;
        var docDir = _getDocDir(options);
        if (!contentElement) return;

        try {
            if (typeof marked !== 'undefined') {
                var tableList = findMarkdownTables(markdownText);

                var footnotePre = preprocessFootnotes(markdownText);
                var taskPre = preprocessTaskLists(footnotePre.text);
                var mathPre = preprocessMath(taskPre.text);
                var htmlPre = preprocessHtmlBlocks(mathPre.text, docDir);

                var html = marked.parse(htmlPre.text);

                html = restoreHtmlBlocks(html, htmlPre.htmlList);
                html = restoreTaskListHtml(html, taskPre.taskItems);
                html = replaceMathPlaceholders(html, mathPre.mathList);
                html = fixLooseListParagraphs(html);
                html = applyOrderedListNumbers(html, htmlPre.text);
                html = window.sanitizeHtml(html);
                html = postprocessFootnotes(html, footnotePre.footnotes);

                contentElement.innerHTML = html;

                // ★ v2.1.5：代码块按行包裹（必须在 sanitize 之后、标记可编辑之前）
                wrapCodeBlockLines(contentElement);

                resolveLocalImages(contentElement, docDir);
                renderMathBlocks(contentElement);
                locateDetailsInSource(contentElement, markdownText);
                setupDetailsBlocks(contentElement);
                annotateTables(contentElement, tableList);
                markEditableBlocks(contentElement, markdownText);
                markTaskListItems(contentElement);
                setupFootnoteClick(contentElement);
            } else {
                contentElement.textContent = markdownText;
            }
        } catch (e) {
            contentElement.textContent = markdownText;
            console.error('[renderMarkdown] failed', e);
        }
    }

    global.renderMarkdown = renderMarkdown;
    global.getEditableText = getEditableText;
    global.domToMarkdown = domToMarkdown;
    global.setupFootnoteClick = setupFootnoteClick;
    global.preprocessFootnotes = preprocessFootnotes;
    global.postprocessFootnotes = postprocessFootnotes;
})(window);