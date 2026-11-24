// MarkEase 预览区查找高亮（v2.1.6）
//   - 普通 <script> 加载，挂 window.PreviewSearch
//   - 消费 find.js 的源码匹配（{from,to}），不单独统计
//   - 用块级 data-md-start/end 把源码片段对齐到预览可见文本
//   - 用 CSS Custom Highlight API 绘制，不修改 DOM
//   - 负责滚动定位、折叠 <details> 自动展开、目标块闪烁
(function (global) {
    'use strict';

    var MATCH_NAME = 'mk-find-match';
    var CURRENT_NAME = 'mk-find-current';
    var FUZZY_NAME = 'mk-find-fuzzy';
    var FUZZY_CURRENT_NAME = 'mk-find-fuzzy-current';
    var FLASH_CLASS = 'mk-find-flash';

    var _source = '';
    var _matches = [];
    var _currentIdx = -1;
    var _units = [];
    var _indexDirty = true;

    var _fuzzyBlocks = [];
    var _fuzzyDirty = true;

    var _ranges = [];       // _ranges[i] = Range[]
    var _visible = [];      // _visible[i] = boolean

    var _flashTimers = new WeakMap();
    var _supported = null;

    // ============================================================
    //  基础工具
    // ============================================================
    function getPreview() {
        return document.getElementById('preview');
    }

    function getContainer() {
        var p = getPreview();
        return p ? p.parentElement : null;
    }

    function getMode() {
        var main = document.getElementById('main');
        return (main && main.getAttribute('data-mode')) || 'edit';
    }

    function isSupported() {
        if (_supported === null) {
            _supported = !!(global.CSS && global.CSS.highlights &&
                typeof global.Highlight === 'function');
        }
        return _supported;
    }

    function isWs(ch) {
        return !ch || /\s/.test(ch);
    }

    function numAttr(el, name) {
        if (!el || !el.getAttribute) return NaN;
        var v = el.getAttribute(name);
        if (v == null || v === '') return NaN;
        var n = parseInt(v, 10);
        return isFinite(n) ? n : NaN;
    }

    function validRange(a, b) {
        return isFinite(a) && isFinite(b) && a >= 0 && b > a;
    }

    // ============================================================
    //  预览可见文本
    // ============================================================
    function isSkippedSubtree(el) {
        if (!el || el.nodeType !== 1) return false;
        try {
            return el.matches(
                '.katex, .math-block, .katex-inline, ' +
                '.task-list-bullet, .task-list-checkbox, ' +
                'a.footnote-backref, script, style, svg, math'
            );
        } catch (e) {
            return false;
        }
    }

    function collectText(root, opts) {
        opts = opts || {};
        var skipNestedLists = opts.skipNestedLists === true;
        var brAsSpace = opts.brAsSpace === true;
        var text = '';
        var nodes = [];

        function walk(node) {
            if (!node) return;
            if (node.nodeType === 3) {
                var val = node.nodeValue || '';
                if (!val) return;
                // 只做等长归一化：NBSP -> 普通空格
                var norm = val.replace(/\u00a0/g, ' ');
                nodes.push({
                    node: node,
                    start: text.length,
                    end: text.length + norm.length
                });
                text += norm;
                return;
            }
            if (node.nodeType !== 1) return;
            if (isSkippedSubtree(node)) return;
            var tag = node.tagName ? node.tagName.toLowerCase() : '';
            if (skipNestedLists && (tag === 'ul' || tag === 'ol')) return;
            if (tag === 'br') {
                if (brAsSpace) {
                    nodes.push({
                        node: node,
                        start: text.length,
                        end: text.length + 1
                    });
                    text += ' ';
                }
                return;
            }
            var children = node.childNodes;
            for (var i = 0; i < children.length; i++) {
                walk(children[i]);
            }
        }

        walk(root);
        return { text: text, nodes: nodes };
    }

    function collectDescendantRange(el) {
        var bestStart = null;
        var bestEnd = null;
        var nodes;
        try {
            nodes = el.querySelectorAll('[data-md-start][data-md-end]');
        } catch (e) {
            return null;
        }
        for (var i = 0; i < nodes.length; i++) {
            var s = numAttr(nodes[i], 'data-md-start');
            var e = numAttr(nodes[i], 'data-md-end');
            if (!validRange(s, e)) continue;
            if (bestStart === null || s < bestStart) bestStart = s;
            if (bestEnd === null || e > bestEnd) bestEnd = e;
        }
        if (bestStart !== null && bestEnd !== null && bestEnd > bestStart) {
            return { start: bestStart, end: bestEnd };
        }
        return null;
    }

    function getUnitRange(el) {
        var tag = el.tagName ? el.tagName.toLowerCase() : '';

        // 表格有自己精确的 table-start/end（data-md-start 可能只是块级近似值）
        if (tag === 'table') {
            var ts = numAttr(el, 'data-md-table-start');
            var te = numAttr(el, 'data-md-table-end');
            if (validRange(ts, te)) return { start: ts, end: te };
        }

        var ownStart = numAttr(el, 'data-md-start');
        var ownEnd = numAttr(el, 'data-md-end');

        // 这些容器自身的 data-md-* 可能只是块级近似值，优先用子块精确范围
        var preferDesc = (tag === 'ul' || tag === 'ol' ||
                          tag === 'blockquote' || tag === 'div' ||
                          tag === 'section');

        if (!preferDesc && validRange(ownStart, ownEnd)) {
            return { start: ownStart, end: ownEnd };
        }

        var desc = collectDescendantRange(el);
        if (desc) return desc;

        if (validRange(ownStart, ownEnd)) {
            return { start: ownStart, end: ownEnd };
        }
        return null;
    }

    function addUnit(list, root, textRoot, range) {
        if (!range) return;
        var start = Math.max(0, range.start);
        var end = Math.min(_source.length, range.end);
        if (!validRange(start, end)) return;

        var info = collectText(textRoot);
        if (!info.text) return;

        list.push({
            root: root,
            textRoot: textRoot,
            start: start,
            end: end,
            text: info.text,
            nodes: info.nodes,
            map: null
        });
    }

    function collectUnits() {
        var preview = getPreview();
        if (!preview || !_source) return [];

        var list = [];
        var children = preview.children;
        for (var i = 0; i < children.length; i++) {
            var el = children[i];
            if (!el || el.nodeType !== 1) continue;

            var tag = el.tagName ? el.tagName.toLowerCase() : '';
            if (tag === 'hr') continue;

            // 脚注区：每个脚注内容块单独映射，避免把序号/返回箭头算进去
            if (el.classList && el.classList.contains('footnotes')) {
                var ps;
                try {
                    ps = el.querySelectorAll('p[data-md-start][data-md-end]');
                } catch (e) {
                    ps = [];
                }
                for (var j = 0; j < ps.length; j++) {
                    addUnit(list, ps[j], ps[j], {
                        start: numAttr(ps[j], 'data-md-start'),
                        end: numAttr(ps[j], 'data-md-end')
                    });
                }
                continue;
            }

            var range = getUnitRange(el);
            if (!range) continue;
            addUnit(list, el, el, range);
        }

        list.sort(function (a, b) {
            return a.start - b.start || a.end - b.end;
        });

        // 块级近似范围可能吃掉下一个块（尤其前一块是含图片的段落），
        // 用后一个块的起点截断，避免同一段文字被两个块重复映射。
        for (var k = 0; k < list.length - 1; k++) {
            if (list[k].end > list[k + 1].start) {
                list[k].end = list[k + 1].start;
            }
        }
        return list.filter(function (u) { return u.end > u.start; });
    }

    // ============================================================
    //  源码掩码：标记“不可见”的源码片段
    // ============================================================
    function findCodeRanges(S) {
        var ranges = [];
        var m;

        var reFence = /(^|\n)([ \t]*)(```|~~~)([^\n]*)\n([\s\S]*?)\n\2\3[ \t]*(?=\n|$)/g;
        while ((m = reFence.exec(S)) !== null) {
            var fullStart = m.index + m[1].length;
            var contentStart = fullStart + 3 + m[4].length + 1;
            var contentEnd = contentStart + m[5].length;
            ranges.push({ start: contentStart, end: contentEnd });
        }

        var reInline = /`([^`\n]*)`/g;
        while ((m = reInline.exec(S)) !== null) {
            ranges.push({ start: m.index + 1, end: m.index + 1 + m[1].length });
        }

        ranges.sort(function (a, b) { return a.start - b.start; });

        // 合并
        var merged = [];
        for (var i = 0; i < ranges.length; i++) {
            var r = ranges[i];
            if (r.end <= r.start) continue;
            if (merged.length && r.start <= merged[merged.length - 1].end) {
                if (r.end > merged[merged.length - 1].end) {
                    merged[merged.length - 1].end = r.end;
                }
            } else {
                merged.push({ start: r.start, end: r.end });
            }
        }
        return merged;
    }

    function buildMask(S) {
        var n = S.length;
        var mask = new Uint8Array(n);
        var codeRanges = findCodeRanges(S);

        function inCode(i) {
            var lo = 0;
            var hi = codeRanges.length - 1;
            while (lo <= hi) {
                var mid = (lo + hi) >> 1;
                var r = codeRanges[mid];
                if (i < r.start) hi = mid - 1;
                else if (i >= r.end) lo = mid + 1;
                else return true;
            }
            return false;
        }

        function mark(a, b, force) {
            if (a < 0) a = 0;
            if (b > n) b = n;
            for (var i = a; i < b; i++) {
                if (!force && inCode(i)) continue;
                mask[i] = 1;
            }
        }

        function each(re, fn) {
            var m;
            re.lastIndex = 0;
            while ((m = re.exec(S)) !== null) {
                if (!m[0]) { re.lastIndex++; continue; }
                fn(m);
            }
        }

        // 1) HTML 注释 / 标签（autolink 除外）
        each(/<!--[\s\S]*?-->/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });

        each(/<\/?[A-Za-z][^>]*>/g, function (m) {
            if (inCode(m.index)) return;
            var t = m[0];
            if (/^<[A-Za-z][A-Za-z0-9+.-]*:[^<>\s]+>$/.test(t)) return;
            if (/^<[^<>\s@]+@[^<>\s]+>$/.test(t)) return;
            mark(m.index, m.index + t.length);
        });

        // 2) 图片：整个语法都不可见（alt 不会成为文本节点）
        each(/!\[[^\]]*\]\([^)]*\)/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });
        each(/!\[[^\]]*\]\[[^\]]*\]/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });

        // 3) 链接：保留链接文字，只把 ](url) 掩掉
        each(/\[[^\]]*\]\([^)]*\)/g, function (m) {
            if (inCode(m.index)) return;
            var pos = m[0].lastIndexOf('](');
            if (pos >= 0) {
                mark(m.index + pos, m.index + m[0].length);
            }
        });
        each(/\[[^\]]*\]\[[^\]]*\]/g, function (m) {
            if (inCode(m.index)) return;
            var pos = m[0].indexOf('][');
            if (pos >= 0) {
                mark(m.index + pos + 1, m.index + m[0].length);
            }
        });

        // 4) 引用式链接定义
        each(/^[ \t]{0,3}\[[^\]]+\]:.*$/gm, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });

        // 5) 数学公式
        each(/\$\$[\s\S]*?\$\$/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });
        each(/\\\[[\s\S]*?\\\]/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });
        each(/\$(?![\s\d])[^$\n]+?\$/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });
        each(/\\\([\s\S]*?\\\)/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });

        // 6) 代码围栏行（内容可见，围栏与语言标记不可见）
        each(/^[ \t]*(```|~~~)[^\n]*$/gm, function (m) {
            mark(m.index, m.index + m[0].length, true);
        });

        // 7) 行内代码的反引号（内容可见）
        each(/`([^`\n]*)`/g, function (m) {
            mark(m.index, m.index + 1, true);
            mark(m.index + m[0].length - 1, m.index + m[0].length, true);
        });

        // 8) Markdown 转义反斜杠
        each(/\\([\\`*{}\[\]()#+\-.!_>~|])/g, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + 1);
        });

        // 9) 行首标记：引用 / 标题 / 列表 / 表格分隔行
        each(/^[ \t]{0,3}>[ \t]?/gm, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });
        each(/^[ \t]{0,3}#{1,6}[ \t]+/gm, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });
        each(/^[ \t]{0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+/gm, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });
        each(/^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)+\|?[ \t]*$/gm, function (m) {
            if (!inCode(m.index)) mark(m.index, m.index + m[0].length);
        });

        return mask;
    }

    // ============================================================
    //  对齐：源码字符 -> 预览文本下标
    // ============================================================
    function alignUnit(unit) {
        if (unit.map) return unit.map;

        var S = _source.slice(unit.start, unit.end);
        var T = unit.text;
        var map = new Int32Array(S.length);
        map.fill(-1);

        if (!S.length || !T.length) {
            unit.map = map;
            return map;
        }

        var masked = buildMask(S);
        var si = 0;
        var ti = 0;

        while (si < S.length && ti < T.length) {
            if (masked[si]) { si++; continue; }

            var sc = S.charAt(si);
            var tc = T.charAt(ti);

            if (sc === tc) {
                map[si] = ti;
                si++;
                ti++;
                continue;
            }
            if (isWs(sc)) { si++; continue; }
            if (isWs(tc)) { ti++; continue; }

            // 向前多看一格：处理源码语法字符 / 预览侧多出的字符
            if (si + 1 < S.length && !masked[si + 1] &&
                S.charAt(si + 1) === tc) {
                si++;
                continue;
            }
            if (ti + 1 < T.length && sc === T.charAt(ti + 1)) {
                ti++;
                continue;
            }

            // 默认把当前源码字符当作 Markdown 语法跳过
            si++;
        }

        unit.map = map;
        return map;
    }

    // ============================================================
    //  模糊搜索：按“渲染出来的可见文字”建块
    //  - 块内空白折叠，可跨软换行；不跨段落/列表项/表格单元格
    //  - 每个字符都带源码位置，便于替换时只替换对应源码跨度
    // ============================================================
    function normalizeQuery(q) {
        // 忽略零宽字符（输入法/粘贴常见），并折叠空白
        return String(q == null ? '' : q)
            .replace(/[\u200B-\u200D\uFEFF]/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function expandFuzzySpan(source, from, to) {
        var a = from;
        var b = to;
        var slice = source.slice(a, b);

        var pairs = [
            { open: '**', close: '**' },
            { open: '__', close: '__' },
            { open: '~~', close: '~~' },
            { open: '*', close: '*' },
            { open: '_', close: '_' },
            { open: '`', close: '`' },
            { open: '<ins>', close: '</ins>' },
            { open: '<u>', close: '</u>' },
            { open: '<del>', close: '</del>' },
            { open: '<s>', close: '</s>' },
            { open: '<mark>', close: '</mark>' },
            { open: '<strong>', close: '</strong>' },
            { open: '<em>', close: '</em>' },
            { open: '<code>', close: '</code>' }
        ];

        // 如果匹配完全在某一对标记内部，保留标记，不扩到外侧
        var insidePair = false;
        for (var i = 0; i < pairs.length; i++) {
            var p = pairs[i];
            if (source.slice(Math.max(0, a - p.open.length), a) === p.open &&
                source.slice(b, b + p.close.length) === p.close) {
                insidePair = true;
                break;
            }
        }
        if (insidePair) return { from: a, to: b };

        // 收尾：把紧跟在后面的闭合标记 / 链接目标 / HTML 闭合标签包含进来
        var changed = true;
        while (changed && b < source.length) {
            changed = false;
            for (var j = 0; j < pairs.length; j++) {
                var q = pairs[j];
                if (source.slice(b, b + q.close.length) === q.close) {
                    b += q.close.length;
                    changed = true;
                    break;
                }
            }
            if (changed) continue;

            if (source.slice(b, b + 2) === '](') {
                var depth = 0;
                var k = b + 1;
                for (; k < source.length; k++) {
                    var ch = source.charAt(k);
                    if (ch === '(') depth++;
                    else if (ch === ')') {
                        depth--;
                        if (depth === 0) { k++; break; }
                    }
                }
                b = Math.min(source.length, k);
                changed = true;
                continue;
            }
            if (source.slice(b, b + 2) === '][' ) {
                var endRef = source.indexOf(']', b + 2);
                if (endRef >= 0) {
                    b = Math.min(source.length, endRef + 1);
                    changed = true;
                    continue;
                }
            }
            var closeTag = /^<\/[A-Za-z][^>]*>/.exec(source.slice(b));
            if (closeTag) {
                b += closeTag[0].length;
                changed = true;
            }
        }

        // 开头：如果匹配吃掉了某对标记的闭合端，就把对应的开启标记也包含进来
        for (var t = 0; t < pairs.length; t++) {
            var r = pairs[t];
            var openStart = a - r.open.length;
            if (openStart < 0) continue;
            if (source.slice(openStart, a) !== r.open) continue;
            if (source.slice(a, b).indexOf(r.close) >= 0) {
                a = openStart;
                break;
            }
        }
        if (a > 0 && source.charAt(a - 1) === '[' &&
            source.slice(a, b).indexOf('](') >= 0) {
            a -= 1;
        }

        return { from: a, to: b };
    }

    function liHasDirectP(li) {
        for (var i = 0; i < li.children.length; i++) {
            if (li.children[i].tagName &&
                li.children[i].tagName.toLowerCase() === 'p') {
                return true;
            }
        }
        return false;
    }

    function splitTableRow(line, lineStart) {
        var cells = [];
        var start = 0;
        var i = 0;
        var n = line.length;

        function push(end) {
            var a = start;
            var b = end;
            while (a < b && /\s/.test(line.charAt(a))) a++;
            while (b > a && /\s/.test(line.charAt(b - 1))) b--;
            cells.push({
                start: lineStart + a,
                end: lineStart + b
            });
        }

        while (i < n) {
            if (line.charAt(i) === '\\' && i + 1 < n) { i += 2; continue; }
            if (line.charAt(i) === '|') {
                push(i);
                start = i + 1;
            }
            i++;
        }
        push(n);

        // 去掉首尾竖线产生的空单元格
        if (line.charAt(0) === '|' && cells.length && cells[0].end <= cells[0].start) {
            cells.shift();
        }
        if (line.charAt(n - 1) === '|' && cells.length &&
            cells[cells.length - 1].end <= cells[cells.length - 1].start) {
            cells.pop();
        }
        return cells;
    }

    function buildTableCellRangeMap(tableEl) {
        var start = numAttr(tableEl, 'data-md-table-start');
        var end = numAttr(tableEl, 'data-md-table-end');
        if (!validRange(start, end) || end > _source.length) return null;

        var src = _source.slice(start, end);
        var lines = src.split('\n');
        var offset = start;
        var rows = [];
        var sepRe = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/;

        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var lineStart = offset;
            offset += line.length + 1;
            if (sepRe.test(line)) continue;
            if (line.indexOf('|') === -1) continue;
            rows.push(splitTableRow(line, lineStart));
        }
        return rows;
    }

    function getTableCellRange(cell) {
        var table = cell.closest ? cell.closest('table') : null;
        if (!table) return null;
        var rows = buildTableCellRangeMap(table);
        if (!rows) return null;
        var tr = cell.parentElement;
        if (!tr || tr.tagName.toLowerCase() !== 'tr') return null;
        var row = tr.rowIndex;
        var col = cell.cellIndex;
        if (row < 0 || row >= rows.length) return null;
        if (col < 0 || col >= rows[row].length) return null;
        var r = rows[row][col];
        if (!validRange(r.start, r.end)) return null;
        return r;
    }

    function buildFuzzyBlocks() {
        var preview = getPreview();
        if (!preview || !_source) return [];

        var out = [];
        var candidates;
        try {
            candidates = preview.querySelectorAll(
                'p, h1, h2, h3, h4, h5, h6, li, pre, td, th, details, div'
            );
        } catch (e) {
            return [];
        }

        for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            if (!el || el.nodeType !== 1) continue;
            if (el.closest && el.closest('.katex, .math-block')) continue;

            var tag = el.tagName.toLowerCase();
            if (tag === 'li' && liHasDirectP(el)) continue;
            if (tag === 'table' || tag === 'tr' || tag === 'thead' ||
                tag === 'tbody' || tag === 'tfoot') continue;

            // 表格单元格内部不再单独建块；单元格自己就是块
            if (tag !== 'td' && tag !== 'th' &&
                el.closest && el.closest('td, th')) continue;

            // 折叠块整体建块，内部子块不重复
            if (tag === 'details' && el.parentElement !== preview) continue;
            if (tag !== 'details' && el.closest && el.closest('details')) continue;

            // 顶层 div 只有不再包含其它块时才单独建块
            if (tag === 'div') {
                if (el.parentElement !== preview) continue;
                if (el.querySelector('p, h1, h2, h3, h4, h5, h6, li, pre, table, details')) {
                    continue;
                }
            }

            var range;
            if (tag === 'td' || tag === 'th') {
                range = getTableCellRange(el);
            } else {
                range = getUnitRange(el);
            }
            if (!range) continue;

            var start = Math.max(0, range.start);
            var end = Math.min(_source.length, range.end);
            if (!validRange(start, end)) continue;

            var info = collectText(el, {
                skipNestedLists: tag === 'li',
                brAsSpace: true
            });
            if (!info.text) continue;

            var unit = {
                root: el,
                start: start,
                end: end,
                text: info.text,
                nodes: info.nodes,
                map: null
            };
            alignUnit(unit);

            var textToSource = new Int32Array(unit.text.length);
            textToSource.fill(-1);
            for (var si = 0; si < unit.map.length; si++) {
                var ti = unit.map[si];
                if (ti >= 0 && ti < textToSource.length && textToSource[ti] < 0) {
                    textToSource[ti] = start + si;
                }
            }

            var text = '';
            var map = [];
            var pendingSpace = false;
            for (var t = 0; t < unit.text.length; t++) {
                var ch = unit.text.charAt(t);
                var srcIdx = textToSource[t];
                // 零宽字符不参与模糊匹配，也不产生空格
                if (/[\u200B-\u200D\uFEFF]/.test(ch)) continue;
                if (/\s/.test(ch)) {
                    pendingSpace = true;
                    continue;
                }
                if (srcIdx < 0) continue;
                if (pendingSpace && text.length) {
                    text += ' ';
                    map.push(srcIdx);
                    pendingSpace = false;
                }
                text += ch;
                map.push(srcIdx);
            }
            if (!text || !map.length) continue;

            out.push({
                start: start,
                end: end,
                text: text,
                map: map,
                root: el
            });
        }

        out.sort(function (a, b) {
            return a.start - b.start || a.end - b.end;
        });

        // 去掉被兄弟块完全覆盖的重复块（例如 details 与内部块同时被选中）
        var filtered = [];
        for (var k = 0; k < out.length; k++) {
            var b = out[k];
            var covered = false;
            for (var j = 0; j < filtered.length; j++) {
                var p = filtered[j];
                if (p.start <= b.start && p.end >= b.end) {
                    covered = true;
                    break;
                }
            }
            if (!covered) filtered.push(b);
        }
        return filtered;
    }

    // 源码级兜底：预览块缺失/未渲染时，直接在 Markdown 源码上匹配。
    // 允许跳过强调、链接、代码等语法标记，从而支持 "foo bar" 命中
    // "foo **bar**" / "foo [bar](url)" 这类跨格式文本。
    function isSkippableMarkup(ch) {
        return /[*_~`\[\]()<>#|\\]/.test(ch);
    }

    function findFuzzyInSource(source, query, caseSensitive) {
        var src = String(source == null ? '' : source);
        var q = normalizeQuery(query);
        if (!src || !q) return [];
        var hay = caseSensitive ? src : src.toLowerCase();
        var needle = caseSensitive ? q : q.toLowerCase();
        var out = [];
        var i = 0;
        while (i < hay.length) {
            if (hay.charAt(i) !== needle.charAt(0)) { i++; continue; }
            var si = i;
            var qi = 0;
            var last = i;
            while (si < hay.length && qi < needle.length) {
                var qc = needle.charAt(qi);
                var sc = hay.charAt(si);
                if (qc === ' ') {
                    if (/\s/.test(sc)) { si++; qi++; continue; }
                    if (isSkippableMarkup(sc)) { si++; continue; }
                    break;
                }
                if (sc === qc) { last = si; si++; qi++; continue; }
                if (isSkippableMarkup(sc)) { si++; continue; }
                break;
            }
            if (qi >= needle.length) {
                out.push({ from: i, to: last + 1, kind: 'fuzzy' });
                i = last + 1;
            } else {
                i++;
            }
        }
        return out;
    }

    function findFuzzyMatches(sourceText, query, caseSensitive) {
        if (sourceText != null) setSource(sourceText);
        var q = normalizeQuery(query);
        if (!q) return [];
        if (!getPreview()) return [];

        if (_fuzzyDirty) {
            _fuzzyBlocks = buildFuzzyBlocks();
            _fuzzyDirty = false;
        }

        var needle = caseSensitive ? q : q.toLowerCase();
        var found = [];
        var seen = {};

        for (var i = 0; i < _fuzzyBlocks.length; i++) {
            var block = _fuzzyBlocks[i];
            var hay = caseSensitive ? block.text : block.text.toLowerCase();
            var from = 0;
            while (from <= hay.length) {
                var idx = hay.indexOf(needle, from);
                if (idx < 0) break;
                var endIdx = idx + needle.length - 1;
                var s = block.map[idx];
                var e = block.map[endIdx];
                if (s >= 0 && e >= 0 && e >= s) {
                    var span = expandFuzzySpan(_source, s, e + 1);
                    var key = span.from + ':' + span.to;
                    if (!seen[key]) {
                        seen[key] = true;
                        found.push({
                            from: span.from,
                            to: span.to,
                            kind: 'fuzzy'
                        });
                    }
                }
                from = idx + Math.max(1, needle.length);
            }
            if (found.length > 10000) break;
        }

        found.sort(function (a, b) { return a.from - b.from || a.to - b.to; });
        // 预览块不可用 / 没有命中时，退回源码级匹配，保证跨格式搜索可用
        if (!found.length && _source) {
            found = findFuzzyInSource(_source, q, caseSensitive);
        }
        return found;
    }

    function isSourceSpanVisible(from, to) {
        if (!validRange(from, to)) return false;
        if (_indexDirty) {
            try { buildIndex(); } catch (e) { return false; }
        }
        for (var i = 0; i < _units.length; i++) {
            var unit = _units[i];
            if (unit.end <= from) continue;
            if (unit.start >= to) break;

            alignUnit(unit);
            var localFrom = Math.max(from, unit.start) - unit.start;
            var localTo = Math.min(to, unit.end) - unit.start;
            for (var j = localFrom; j < localTo; j++) {
                if (unit.map[j] >= 0) return true;
            }
        }
        return false;
    }

    function posAt(unit, index) {
        var nodes = unit.nodes;
        if (!nodes.length) return null;
        if (index <= 0) {
            return { node: nodes[0].node, offset: 0 };
        }
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            if (index < n.end) {
                return { node: n.node, offset: index - n.start };
            }
        }
        var last = nodes[nodes.length - 1];
        return {
            node: last.node,
            offset: (last.node.nodeValue || '').length
        };
    }

    function makeRange(unit, startT, endT) {
        var a = posAt(unit, startT);
        var b = posAt(unit, endT);
        if (!a || !b) return null;
        try {
            var r = document.createRange();
            r.setStart(a.node, a.offset);
            r.setEnd(b.node, b.offset);
            return r;
        } catch (e) {
            return null;
        }
    }

    function mapMatchInUnit(unit, match) {
        alignUnit(unit);
        var localFrom = Math.max(match.from, unit.start) - unit.start;
        var localTo = Math.min(match.to, unit.end) - unit.start;
        if (localTo <= localFrom) return null;

        var first = -1;
        var last = -1;
        for (var i = localFrom; i < localTo; i++) {
            var t = unit.map[i];
            if (t >= 0) {
                if (first < 0) first = t;
                last = t;
            }
        }
        if (first < 0) return null;
        return makeRange(unit, first, last + 1);
    }

    // ============================================================
    //  高亮绘制
    // ============================================================
    function removeFlashes() {
        try {
            var els = document.querySelectorAll('.' + FLASH_CLASS);
            for (var i = 0; i < els.length; i++) {
                els[i].classList.remove(FLASH_CLASS);
            }
        } catch (e) { /* ignore */ }
    }

    function clearHighlights() {
        try {
            if (global.CSS && global.CSS.highlights) {
                global.CSS.highlights.delete(MATCH_NAME);
                global.CSS.highlights.delete(CURRENT_NAME);
                global.CSS.highlights.delete(FUZZY_NAME);
                global.CSS.highlights.delete(FUZZY_CURRENT_NAME);
            }
        } catch (e) { /* ignore */ }
        removeFlashes();
    }

    function makeHighlight(ranges) {
        if (!ranges || !ranges.length) return null;
        try {
            var h = new global.Highlight();
            for (var i = 0; i < ranges.length; i++) {
                h.add(ranges[i]);
            }
            return h;
        } catch (e) {
            return null;
        }
    }

    function setHighlight(name, ranges) {
        var h = makeHighlight(ranges);
        if (!h) return;
        try { global.CSS.highlights.set(name, h); } catch (e) { /* ignore */ }
    }

    function applyHighlights() {
        clearHighlights();
        if (!isSupported()) return;

        var exactAll = [];
        var fuzzyAll = [];
        var exactCur = [];
        var fuzzyCur = [];

        for (var i = 0; i < _ranges.length; i++) {
            var rs = _ranges[i];
            if (!rs || !rs.length) continue;
            var isFuzzy = _matches[i] && _matches[i].kind === 'fuzzy';
            var targetAll = isFuzzy ? fuzzyAll : exactAll;
            for (var j = 0; j < rs.length; j++) targetAll.push(rs[j]);
            if (i === _currentIdx) {
                var targetCur = isFuzzy ? fuzzyCur : exactCur;
                for (var k = 0; k < rs.length; k++) targetCur.push(rs[k]);
            }
        }

        if (exactAll.length) setHighlight(MATCH_NAME, exactAll);
        if (fuzzyAll.length) setHighlight(FUZZY_NAME, fuzzyAll);
        if (exactCur.length) setHighlight(CURRENT_NAME, exactCur);
        if (fuzzyCur.length) setHighlight(FUZZY_CURRENT_NAME, fuzzyCur);
    }

    // ============================================================
    //  定位 / 展开 / 闪烁
    // ============================================================
    function expandDetailsForNode(node) {
        var el = node && node.nodeType === 1 ? node : (node ? node.parentElement : null);
        while (el && el !== document.body) {
            if (el.tagName && el.tagName.toLowerCase() === 'details' &&
                !el.open) {
                el.open = true;
            }
            el = el.parentElement;
        }
    }

    function closestBlock(node) {
        var preview = getPreview();
        var el = node && node.nodeType === 1 ? node : (node ? node.parentElement : null);
        while (el && el !== preview) {
            var tag = el.tagName ? el.tagName.toLowerCase() : '';
            if (/^(p|li|h[1-6]|pre|table|blockquote|div|details|summary|td|th)$/.test(tag)) {
                return el;
            }
            el = el.parentElement;
        }
        return preview;
    }

    function flashBlock(el) {
        if (!el || !el.classList || el === getPreview()) return;
        el.classList.remove(FLASH_CLASS);
        // 强制重排，让同一块连续跳转时动画能重新播放
        void el.offsetWidth;
        el.classList.add(FLASH_CLASS);

        var old = _flashTimers.get(el);
        if (old) clearTimeout(old);
        _flashTimers.set(el, setTimeout(function () {
            el.classList.remove(FLASH_CLASS);
            _flashTimers.delete(el);
        }, 1000));
    }

    function scrollRectIntoView(rect, align) {
        var container = getContainer();
        if (!container || !rect) return;
        var cRect = container.getBoundingClientRect();
        var delta = rect.top - cRect.top;
        var target = container.scrollTop + delta -
            container.clientHeight * align;
        var max = container.scrollHeight - container.clientHeight;
        if (max < 0) max = 0;
        if (target < 0) target = 0;
        if (target > max) target = max;
        container.scrollTop = target;
    }

    function nearestBlockForMatch(match) {
        if (!_units.length) return null;

        var best = null;
        var bestSpan = Infinity;

        for (var i = 0; i < _units.length; i++) {
            var u = _units[i];
            if (u.end <= match.from) continue;
            if (u.start >= match.to) break;

            var root = u.root;
            var localBest = root;
            var localSpan = u.end - u.start;

            var els;
            try {
                els = root.querySelectorAll('[data-md-start][data-md-end]');
            } catch (e) {
                els = [];
            }
            for (var j = 0; j < els.length; j++) {
                var s = numAttr(els[j], 'data-md-start');
                var e = numAttr(els[j], 'data-md-end');
                if (!validRange(s, e)) continue;
                if (s <= match.from && match.from < e) {
                    var span = e - s;
                    if (span < localSpan) {
                        localSpan = span;
                        localBest = els[j];
                    }
                }
            }

            if (localSpan < bestSpan) {
                bestSpan = localSpan;
                best = localBest;
            }
            break;
        }

        if (best) return best;

        // 匹配落在所有块之外：取最近块
        if (match.from < _units[0].start) return _units[0].root;
        if (match.from >= _units[_units.length - 1].end) {
            return _units[_units.length - 1].root;
        }
        for (var k = 0; k < _units.length; k++) {
            if (_units[k].end > match.from) return _units[k].root;
        }
        return _units[_units.length - 1].root;
    }

    // ============================================================
    //  对外接口
    // ============================================================
    function setSource(text) {
        var s = String(text == null ? '' : text);
        if (s !== _source) {
            _source = s;
            _indexDirty = true;
            _fuzzyDirty = true;
            _fuzzyBlocks = [];
        }
    }

    function buildIndex() {
        _units = collectUnits();
        _indexDirty = false;
    }

    function update(matches, currentIdx, sourceText) {
        if (sourceText != null) setSource(sourceText);
        _matches = matches || [];
        _currentIdx = currentIdx;

        _ranges = [];
        _visible = [];

        if (!getPreview() || getMode() === 'edit' || !_matches.length) {
            clearHighlights();
            return;
        }

        if (_indexDirty) buildIndex();

        var ui = 0;
        for (var i = 0; i < _matches.length; i++) {
            var m = _matches[i];
            var rs = [];

            while (ui < _units.length && _units[ui].end <= m.from) ui++;

            for (var u = ui; u < _units.length && _units[u].start < m.to; u++) {
                var unit = _units[u];
                if (unit.end <= m.from) continue;
                var r = mapMatchInUnit(unit, m);
                if (r) rs.push(r);
            }

            _ranges.push(rs);
            _visible.push(rs.length > 0);
        }

        applyHighlights();
    }

    function getStartIndex(matches, sourceText) {
        if (sourceText != null) setSource(sourceText);
        if (!matches || !matches.length) return -1;
        if (getMode() !== 'preview') return 0;

        if (_indexDirty) {
            try { buildIndex(); } catch (e) { /* ignore */ }
        }

        var container = getContainer();
        if (!container) return 0;

        var pos = null;
        try {
            if (global.MKPreviewPos &&
                typeof global.MKPreviewPos.topToSourcePos === 'function') {
                pos = global.MKPreviewPos.topToSourcePos(container.scrollTop + 1);
            }
        } catch (e) { pos = null; }

        if (pos == null) {
            var cRect = container.getBoundingClientRect();
            for (var i = 0; i < _units.length; i++) {
                var r = _units[i].root.getBoundingClientRect();
                if (r.bottom > cRect.top) {
                    pos = _units[i].start;
                    break;
                }
            }
        }
        if (pos == null) pos = 0;

        for (var j = 0; j < matches.length; j++) {
            if (matches[j].from >= pos) return j;
        }
        return matches.length - 1;
    }

    function isVisible(idx) {
        return !!(idx >= 0 && idx < _visible.length && _visible[idx]);
    }

    function scrollToIndex(idx, opts) {
        opts = opts || {};
        var align = typeof opts.align === 'number' ? opts.align : 0.35;

        if (!_matches.length || idx < 0 || idx >= _matches.length) {
            return { visible: false };
        }

        if (_indexDirty || _ranges.length !== _matches.length) {
            update(_matches, _currentIdx);
        }

        var ranges = _ranges[idx] || [];
        var rect = null;
        var usedRange = null;

        for (var i = 0; i < ranges.length; i++) {
            expandDetailsForNode(ranges[i].startContainer);
        }
        for (var j = 0; j < ranges.length; j++) {
            var r = ranges[j].getBoundingClientRect();
            if (r && (r.width || r.height)) {
                rect = r;
                usedRange = ranges[j];
                break;
            }
        }

        if (rect) {
            scrollRectIntoView(rect, align);
            flashBlock(closestBlock(usedRange.startContainer));
            return {
                visible: true,
                block: closestBlock(usedRange.startContainer),
                unsupported: !isSupported()
            };
        }

        var block = nearestBlockForMatch(_matches[idx]);
        if (block) {
            expandDetailsForNode(block);
            var br = block.getBoundingClientRect();
            if (br) scrollRectIntoView(br, align);
            flashBlock(block);
        }
        return {
            visible: false,
            block: block,
            unsupported: !isSupported()
        };
    }

    function onPreviewRendered() {
        _indexDirty = true;
        _units = [];
        _ranges = [];
        _visible = [];
        _fuzzyDirty = true;
        _fuzzyBlocks = [];
        clearHighlights();
    }

    function expandAtSource(pos) {
        if (pos == null) return false;
        if (_indexDirty) {
            try { buildIndex(); } catch (e) { return false; }
        }
        var block = nearestBlockForMatch({ from: pos, to: pos + 1 });
        if (!block) return false;
        expandDetailsForNode(block);
        return true;
    }

    function clear() {
        _matches = [];
        _currentIdx = -1;
        _units = [];
        _ranges = [];
        _visible = [];
        _indexDirty = true;
        _fuzzyDirty = true;
        _fuzzyBlocks = [];
        clearHighlights();
    }

    // ============================================================
    //  对外接口
    // ============================================================
    global.PreviewSearch = {
        isSupported: isSupported,
        setSource: setSource,
        update: update,
        clear: clear,
        clearHighlights: clearHighlights,
        onPreviewRendered: onPreviewRendered,
        getStartIndex: getStartIndex,
        isVisible: isVisible,
        isSourceSpanVisible: isSourceSpanVisible,
        findFuzzyMatches: findFuzzyMatches,
        normalizeQuery: normalizeQuery,
        scrollToIndex: scrollToIndex,
        expandAtSource: expandAtSource
    };
})(window);
