// MarkEase 渲染管线（阶段 15 修订 9：img src 提前改写 + 多重兜底）
(function (global) {
    'use strict';

    var BUILD_TAG = 'render-v9';
    console.log('[MarkEase] ' + BUILD_TAG + ' loaded');

    var KATEX_OPTS = {
        throwOnError: false,
        strict: false,
        trust: false,
        output: 'html'
    };

    var FOLD_STATE_KEY = 'markease_fold_state_v1';

    // ============================================================
    //  ★ 路径解析工具（所有 img 处理都靠这几个函数）
    // ============================================================
    function _getDocDir(options) {
        if (options && options.docDir) return String(options.docDir);
        if (global.__currentDocDir) return String(global.__currentDocDir);
        return '';
    }

    function _getAssetBase() {
        return global.__assetBaseUrl || '';
    }

    function _resolveToAbsPath(src, docDir) {
        if (!src) return null;

        // 已有协议
        if (/^file:\/\//i.test(src)) {
            return decodeURIComponent(src.replace(/^file:\/\/\/?/i, ''));
        }
        if (/^[a-z]+:\/\//i.test(src)) return null;   // http/https 等不动
        if (/^data:/i.test(src) || /^blob:/i.test(src)) return null;

        // Windows 盘符
        if (/^[A-Za-z]:[\/\\]/.test(src)) return src;

        // Unix 绝对路径（不处理 // 开头的 UNC）
        if (src.charAt(0) === '/' && !/^\/\//.test(src)) return src;

        // 相对路径 → 拼到文档目录
        if (!docDir) return null;
        var normDir = String(docDir).replace(/\\/g, '/').replace(/\/+$/, '');
        if (!normDir) return null;
        return normDir + '/' + src;
    }

    function _toAssetUrl(absPath) {
        if (!absPath) return null;
        var baseUrl = _getAssetBase();
        if (!baseUrl) return null;   // 无 asset 服务
        var normalized = String(absPath).replace(/\\/g, '/').replace(/^\/+/, '');
        return baseUrl + '/fs/' + encodeURIComponent(normalized);
    }

    function _toFileUrl(absPath) {
        if (!absPath) return null;
        var normalized = String(absPath).replace(/\\/g, '/').replace(/^\/+/, '');
        return 'file:///' + normalized;
    }

    // ★ 把 src 改写为可加载的 URL（优先 asset server，其次 file:///）
    function _rewriteSrc(src, docDir) {
        if (!src) return src;
        if (/^(https?:|data:|blob:)/i.test(src)) return src;

        var absPath = _resolveToAbsPath(src, docDir);
        if (!absPath) return src;

        var assetUrl = _toAssetUrl(absPath);
        if (assetUrl) return assetUrl;

        // ★ asset server 不可用时，回退到 file:///（WebView2 通常允许）
        return _toFileUrl(absPath) || src;
    }

    // ============================================================
    //  DOM → Markdown
    // ============================================================
    function domToMarkdown(el) {
        let out = '';
        const nodes = el.childNodes;
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            if (node.nodeType === 3) {
                out += node.nodeValue;
            } else if (node.nodeType === 1) {
                const tag = node.tagName.toLowerCase();
                if (tag === 'img') {
                    const src = node.getAttribute('src') || '';
                    const alt = node.getAttribute('alt') || '';
                    const width = node.getAttribute('width') || '';
                    const height = node.getAttribute('height') || '';
                    let realSrc = src;
                    if (/^http:\/\/127\.0\.0\.1:\d+\/fs\//i.test(src)) {
                        try {
                            realSrc = decodeURIComponent(src.replace(
                                /^http:\/\/127\.0\.0\.1:\d+\/fs\//i, ''));
                        } catch (e) { /* 保留 */ }
                    } else if (/^file:\/\//i.test(src)) {
                        try {
                            realSrc = decodeURIComponent(src.replace(
                                /^file:\/\/\/?/i, ''));
                        } catch (e) { /* 保留 */ }
                    }
                    if (width || height) {
                        let attrs = ' src="' + String(realSrc).replace(/"/g, '&quot;') + '"';
                        if (alt) attrs += ' alt="' + String(alt).replace(/"/g, '&quot;') + '"';
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
                const inner = domToMarkdown(node);
                switch (tag) {
                    case 'br': out += '\n'; break;
                    case 'strong':
                    case 'b': out += '**' + inner + '**'; break;
                    case 'em':
                    case 'i': out += '*' + inner + '*'; break;
                    case 'del':
                    case 's': out += '~~' + inner + '~~'; break;
                    case 'code': out += '`' + inner + '`'; break;
                    case 'a': {
                        if (node.querySelector('img')) {
                            const href = node.getAttribute('href') || '';
                            let attrs = ' href="' + String(href).replace(/"/g, '&quot;') + '"';
                            const title = node.getAttribute('title');
                            if (title) attrs += ' title="' + String(title).replace(/"/g, '&quot;') + '"';
                            out += '<a' + attrs + '>' + inner + '</a>';
                        } else {
                            const href = node.getAttribute('href') || '';
                            const title = node.getAttribute('title');
                            if (title) {
                                out += '[' + inner + '](' + href + ' "' + title + '")';
                            } else {
                                out += '[' + inner + '](' + href + ')';
                            }
                        }
                        break;
                    }
                    case 'span': out += inner; break;
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
    //  代码块范围
    // ============================================================
    function collectCodeRanges(md) {
        var ranges = [];
        var m;
        var reBlock = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
        while ((m = reBlock.exec(md)) !== null) {
            ranges.push([m.index, m.index + m[0].length]);
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

    // ============================================================
    //  任务列表还原
    // ============================================================
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
                ' data-md-task-index="' + item.bracketPos + '"' +
                ' data-md-task-checked="' + checkedVal + '"' +
                ' role="checkbox"' +
                ' aria-checked="' + ariaVal + '"' +
                ' contenteditable="false">' + text + '</span>';
            out = out.split(item.placeholder).join(spanHtml);
        }
        return out;
    }

    // ============================================================
    //  ★ HTML 块保护：提取 <a> 与 <img>，同时【立即改写 img 的 src】
    //
    //  为什么在这里改写（而不是 marked 之后）？
    //    restoreHtmlBlocks 用字符串替换把 <img> 塞回 HTML，
    //    那一刻浏览器可能还没执行到 rewriteImgSrcInHtml。
    //    直接在提取阶段就把 src 改成 asset URL，可保证任何后续流程
    //    拿到的都是可直接加载的地址。
    // ============================================================
    function preprocessHtmlBlocks(md, docDir) {
        var htmlList = [];
        var result = String(md);

        // 1) <a ...>...</a>
        var reA = /<a\b[^>]*>[\s\S]*?<\/a>/gi;
        result = result.replace(reA, function (match) {
            var idx = htmlList.length;
            var placeholder = '@@MKHTML' + idx + 'MKHTML@@';
            htmlList.push({ placeholder: placeholder, html: match });
            return placeholder;
        });

        // 2) <img ...> / <img ... />（★ 立即改写 src）
        var reImg = /<img\b([^>]*?)\/?>/gi;
        result = result.replace(reImg, function (match) {
            var idx = htmlList.length;
            var placeholder = '@@MKHTML' + idx + 'MKHTML@@';

            var rewritten = match;
            if (docDir) {
                rewritten = match.replace(
                    /(\bsrc\s*=\s*)(["'])([^"']*)(\2)/i,
                    function (m, prefix, quote1, srcVal) {
                        var newSrc = _rewriteSrc(srcVal, docDir);
                        return prefix + quote1 + newSrc + quote1;
                    }
                );
            }

            htmlList.push({ placeholder: placeholder, html: rewritten });
            return placeholder;
        });

        return { text: result, htmlList: htmlList };
    }

    function restoreHtmlBlocks(html, htmlList) {
        if (!htmlList || htmlList.length === 0) return html;
        var out = html;
        for (var i = 0; i < htmlList.length; i++) {
            var item = htmlList[i];
            out = out.split(item.placeholder).join(item.html);
        }
        return out;
    }

    // ---------- marked 自定义渲染 ----------
    if (typeof marked !== 'undefined') {
        var mdRenderer = new marked.Renderer();

        mdRenderer.code = function (code, infostring, escaped) {
            var info = (infostring || '').trim();
            var lang = (info.match(/^\S+/) || [''])[0].toLowerCase();

            if (lang === 'math' || lang === 'latex' || lang === 'katex' || lang === 'tex') {
                return '<div class="math-block" data-tex="' +
                       encodeURIComponent(code) + '">' +
                       window.escapeHtml(code) + '</div>\n';
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
                    highlighted = window.escapeHtml(code);
                }
                var cls = 'hljs' + (lang ? ' language-' + lang : '');
                return '<pre><code class="' + cls + '">' + highlighted + '</code></pre>\n';
            }
            return '<pre><code>' + window.escapeHtml(code) + '</code></pre>\n';
        };

        mdRenderer.html = function (html) {
            var trimmed = String(html).trim();
            if (/^<(details|summary|a|picture)\b/i.test(trimmed) ||
                /^<\/(details|summary|a|picture)\b/i.test(trimmed)) {
                return html + '\n';
            }
            if (/^<(img|br|source)\b/i.test(trimmed)) {
                return html + '\n';
            }
            return '<p>' + window.escapeHtml(html) + '</p>\n';
        };

        marked.setOptions({
            renderer: mdRenderer,
            breaks: true,
            gfm: true
        });
    }

    // ---------- KaTeX ----------
    function renderKatexToString(tex, display) {
        if (typeof katex === 'undefined') {
            return '<code>' + window.escapeHtml(tex) + '</code>';
        }
        try {
            var opts = Object.assign({}, KATEX_OPTS, { displayMode: !!display });
            return katex.renderToString(tex, opts);
        } catch (e) {
            return '<span class="katex-error">[公式错误] ' +
                   window.escapeHtml(tex) + '</span>';
        }
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
            var placeholder = '@@MKPH' + j + 'MKPH@@';
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
                    output: 'html'
                });
            } catch (e) {
                el.innerHTML = '<span class="katex-error">[公式错误] ' +
                               window.escapeHtml(String(e.message || e)) +
                               '</span><br><code>' +
                               window.escapeHtml(tex) + '</code>';
            }
        }
    }

    // ---------- 图片解析兜底（处理 Markdown 语法 ![]() 生成的 img）----------
    function resolveLocalImages(root, docDir) {
        if (!root) return;
        var imgs = root.querySelectorAll('img[src]');
        for (var i = 0; i < imgs.length; i++) {
            var img = imgs[i];
            var src = img.getAttribute('src');
            if (!src) continue;
            if (img.getAttribute('data-resolved') === '1') continue;
            if (/^(https?:|data:|blob:)/i.test(src)) {
                img.setAttribute('data-resolved', '1');
                continue;
            }
            // 已经是 asset URL 或 file:// → 标记已解析
            if (/^http:\/\/127\.0\.0\.1:\d+\/fs\//i.test(src) ||
                /^file:\/\//i.test(src)) {
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

    // ---------- 段落可编辑性判定 ----------
    function hasBlockChildren(el) {
        var BLOCK_TAGS = {
            'div': 1, 'p': 1, 'ul': 1, 'ol': 1, 'li': 1,
            'table': 1, 'pre': 1, 'blockquote': 1,
            'h1': 1, 'h2': 1, 'h3': 1, 'h4': 1, 'h5': 1, 'h6': 1,
            'details': 1, 'summary': 1
        };
        for (var i = 0; i < el.childNodes.length; i++) {
            var child = el.childNodes[i];
            if (child.nodeType === 1) {
                var tag = child.tagName.toLowerCase();
                if (BLOCK_TAGS[tag]) return true;
            }
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

        var blocks = root.querySelectorAll('p, h1, h2, h3, h4, h5, h6');
        var searchFromNorm = 0;

        for (var bi = 0; bi < blocks.length; bi++) {
            var el = blocks[bi];

            if (el.closest && el.closest('details')) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            if (el.parentElement && el.parentElement !== root) {
                var parentTag = el.parentElement.tagName.toLowerCase();
                if (parentTag === 'li' || parentTag === 'blockquote' ||
                    parentTag === 'td' || parentTag === 'th' ||
                    parentTag === 'details' || parentTag === 'summary') {
                    el.setAttribute('data-md-editable', '0');
                    continue;
                }
            }

            if (hasBlockChildren(el)) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            if (el.querySelector('img')) {
                el.setAttribute('data-md-editable', '0');
                continue;
            }

            var mdText = domToMarkdown(el);
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
    //  表格定位 / 标注（省略内部实现，与之前相同）
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
            if (!li.querySelector(':scope > .task-list-bullet')) {
                var bullet = document.createElement('span');
                bullet.className = 'task-list-bullet';
                bullet.setAttribute('contenteditable', 'false');
                bullet.textContent = '- ';
                li.insertBefore(bullet, li.firstChild);
            }
        }
    }

    // ---------- 折叠 <details> ----------
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

    // ---------- 主渲染 ----------
    function renderMarkdown(markdownText, options) {
        options = options || {};
        var contentElement = options.target;
        var docDir = _getDocDir(options);
        if (!contentElement) return;

        try {
            if (typeof marked !== 'undefined') {
                var tableList = findMarkdownTables(markdownText);

                var taskPre = preprocessTaskLists(markdownText);

                var pre = preprocessMath(taskPre.text);

                // ★ 关键：把 docDir 传给预处理函数，img src 在这里就被改写
                var pre2 = preprocessHtmlBlocks(pre.text, docDir);

                var html = marked.parse(pre2.text);

                html = restoreHtmlBlocks(html, pre2.htmlList);
                html = restoreTaskListHtml(html, taskPre.taskItems);

                // XSS 清洗
                html = window.sanitizeHtml(html);

                // 注入 KaTeX
                for (var i = 0; i < pre.mathList.length; i++) {
                    var item = pre.mathList[i];
                    var katexHtml = renderKatexToString(item.tex, item.display);
                    if (item.display) {
                        katexHtml = '<div class="math-block">' + katexHtml + '</div>';
                    } else {
                        katexHtml = '<span class="katex-inline">' + katexHtml + '</span>';
                    }
                    html = html.split(item.placeholder).join(katexHtml);
                }

                contentElement.innerHTML = html;

                // ★ 二次兜底：处理 Markdown 语法 ![]() 生成的 img（路径解析）
                resolveLocalImages(contentElement, docDir);

                renderMathBlocks(contentElement);
                locateDetailsInSource(contentElement, markdownText);
                setupDetailsBlocks(contentElement);
                annotateTables(contentElement, tableList);
                markEditableBlocks(contentElement, markdownText);
                markTaskListItems(contentElement);
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
})(window);