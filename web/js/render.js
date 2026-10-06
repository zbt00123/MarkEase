// MarkEase 渲染管线（阶段 16-13 修复 2）
//   ★ 本轮修改：
//     1) BUILD_TAG 更新为 render-v22
//     2) preprocessHtmlBlocks 新增 <ins> / <u> 预处理
//        —— 把内部 markdown 提前用 marked.parseInline 解析
//        —— 解决 <ins>**粗体**</ins> 渲染成源代码的问题
//     3) restoreHtmlBlocks 改为多轮循环替换，处理嵌套占位符
(function (global) {
    'use strict';

    var BUILD_TAG = 'render-v22';
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
                out += node.nodeValue;
            } else if (node.nodeType === 1) {
                const tag = node.tagName.toLowerCase();

                if (skipNestedLists && (tag === 'ul' || tag === 'ol')) {
                    continue;
                }

                if (tag === 'img') {
                    const src = node.getAttribute('src') || '';
                    const alt = node.getAttribute('alt') || '';
                    const width = node.getAttribute('width') || '';
                    const height = node.getAttribute('height') || '';
                    let realSrc = src;

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

                if (tag === 'sup' && node.getAttribute &&
                    node.getAttribute('data-footnote-ref') === '1') {
                    const idx = node.getAttribute('data-footnote-index') || '';
                    out += '[^' + idx + ']';
                    continue;
                }

                const inner = domToMarkdown(node, opts);
                switch (tag) {
                    case 'br': out += '\n'; break;
                    case 'strong':
                    case 'b': out += '**' + inner + '**'; break;
                    case 'em':
                    case 'i': out += '*' + inner + '*'; break;
                    case 'del':
                    case 's': out += '~~' + inner + '~~'; break;
                    case 'ins':
                    case 'u': out += '<ins>' + inner + '</ins>'; break;
                    case 'code': out += '`' + inner + '`'; break;
                    case 'a': {
                        if (node.getAttribute &&
                            node.getAttribute('data-footnote-backref') === '1') {
                            break;
                        }
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
            if (docDir !== undefined) {
                rewritten = match.replace(
                    /(\bsrc\s*=\s*)(["'])([^"']*)(\2)/i,
                    function (m, prefix, quote1, srcVal) {
                        var newSrc = _rewriteSrc(srcVal, docDir || '');
                        return prefix + quote1 + newSrc + quote1;
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
    //  图片解析兜底
    // ============================================================
    function resolveLocalImages(root, docDir) {
        if (!root) return;
        var imgs = root.querySelectorAll('img[src]');
        for (var i = 0; i < imgs.length; i++) {
            var img = imgs[i];
            var src = img.getAttribute('src');
            if (!src) continue;
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

            if (el.querySelector('img')) {
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

            var target = li;
            for (var c = 0; c < li.childNodes.length; c++) {
                var child = li.childNodes[c];
                if (child.nodeType === 1 &&
                    child.tagName.toLowerCase() === 'p') {
                    target = child;
                    break;
                }
            }

            if (target.firstChild &&
                target.firstChild.nodeType === 1 &&
                target.firstChild.classList &&
                target.firstChild.classList.contains('task-list-bullet')) {
                continue;
            }

            var bullet = document.createElement('span');
            bullet.className = 'task-list-bullet';
            bullet.setAttribute('contenteditable', 'false');
            bullet.textContent = '- ';
            target.insertBefore(bullet, target.firstChild);
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
                html = window.sanitizeHtml(html);
                html = postprocessFootnotes(html, footnotePre.footnotes);

                contentElement.innerHTML = html;

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