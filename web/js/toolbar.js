// MarkEase 工具栏逻辑（阶段 16-14 修复 1）
//   ★ 本轮修改：
//     1) 新增 toggleUnderlineMultiline：多行选区按行独立包裹 <ins>
//     2) toggleUnderlineFormat 检测跨行选区，走多行分支
(function () {
    'use strict';

    let _ES = null;
    let _IH = null;
    let _ST = null;

    let view = null;
    let externalHandlers = {};
    let bound = false;

    let _savedSelection = null;

    // ---- H 下拉全局状态 ----
    let _hBtnMain = null;
    let _hMenuEl = null;
    let _hMenuOpen = false;
    let _hPressTimer = null;
    let _hLongPress = false;

    // ---- 表格菜单 ----
    let _tableBtn = null;
    let _tableMenu = null;
    let _tableOpen = false;

    // ---- 格式刷 ----
    const _painter = {
        active: false,
        continuous: false,
        format: null,
        applying: false,
    };
    let _painterClickTimer = null;

    // ---- 工具栏自适应 ----
    let _allButtons = [];
    let _overflowBtn = null;
    let _overflowMenu = null;
    let _resizeObserver = null;
    let _overflowOpen = false;

    // ---- 链接弹窗 ----
    let _linkModal = null;
    let _linkModalBuilt = false;

    // ---- JS tooltip ----
    let _tooltipEl = null;
    let _tooltipTimer = null;
    const TOOLTIP_DELAY = 350;
    const TOOLTIP_GAP = 12;
    const TOOLTIP_EDGE = 6;

    // ============================================================
    //  扫描光标/选区两侧的 * 或 _ 包裹层数
    // ============================================================
    function scanStarWrapAt(state, from, to) {
        try {
            const line = state.doc.lineAt(from);
            if (state.doc.lineAt(to).from !== line.from) return null;

            const lineText = line.text;
            const relFrom = from - line.from;
            const relTo = to - line.from;

            function scan(marker) {
                let leftCount = 0;
                let p = relFrom - 1;
                while (p >= 0 && lineText[p] === marker) { leftCount++; p--; }

                let rightCount = 0;
                let q = relTo;
                while (q < lineText.length && lineText[q] === marker) { rightCount++; q++; }

                return { leftCount, rightCount };
            }

            const s1 = scan('*');
            const s2 = scan('_');

            let result = null;
            if (s1.leftCount > 0 && s1.rightCount > 0) {
                result = { leftCount: s1.leftCount, rightCount: s1.rightCount, marker: '*' };
            } else if (s2.leftCount > 0 && s2.rightCount > 0) {
                result = { leftCount: s2.leftCount, rightCount: s2.rightCount, marker: '_' };
            }
            if (!result) return null;

            const layers = Math.min(3, Math.min(result.leftCount, result.rightCount));
            if (layers < 1) return null;

            return {
                start: from - layers,
                end: to + layers,
                contentStart: from,
                contentEnd: to,
                layers: layers,
                marker: result.marker,
            };
        } catch (e) {
            return null;
        }
    }

    // ============================================================
    //  加粗/斜体专用切换（状态机）
    // ============================================================
    function toggleBoldOrItalicFormat(editorView, type) {
        if (!editorView || !_ES || !_IH) return;
        const state = editorView.state;

        // ★ 新增：场景 3 —— 选区在 marker...marker 内 → 仅剥离选中部分
        const _sel = state.selection.main;
        if (!_sel.empty) {
            const startLine = state.doc.lineAt(_sel.from).number;
            const endLine = state.doc.lineAt(_sel.to).number;
            if (startLine === endLine) {
                const marker = (type === 'bold') ? '**' : '*';
                if (removeMarkerInRange(editorView, _sel.from, _sel.to, marker)) {
                    editorView.focus();
                    return;
                }
            }
        }

        const spec = state.changeByRange(range => {
            const wrap = scanStarWrapAt(state, range.from, range.to);

            if (!wrap) {
                const sel = state.sliceDoc(range.from, range.to);
                if (type === 'bold') {
                    const insert = '**' + sel + '**';
                    return {
                        changes: { from: range.from, to: range.to, insert },
                        range: _ES.range(range.from + 2, range.from + 2 + sel.length)
                    };
                } else {
                    const insert = '*' + sel + '*';
                    return {
                        changes: { from: range.from, to: range.to, insert },
                        range: _ES.range(range.from + 1, range.from + 1 + sel.length)
                    };
                }
            }

            let newLayers = wrap.layers;
            if (type === 'bold') {
                if (wrap.layers === 1) newLayers = 3;
                else if (wrap.layers === 2) newLayers = 0;
                else if (wrap.layers === 3) newLayers = 1;
            } else {
                if (wrap.layers === 1) newLayers = 0;
                else if (wrap.layers === 2) newLayers = 3;
                else if (wrap.layers === 3) newLayers = 2;
            }

            const inner = state.sliceDoc(wrap.contentStart, wrap.contentEnd);
            const m = wrap.marker;
            let prefix = '';
            let suffix = '';
            for (let i = 0; i < newLayers; i++) { prefix += m; suffix += m; }
            const newText = prefix + inner + suffix;

            const relFrom = range.from - wrap.contentStart;
            const relTo = range.to - wrap.contentStart;
            const newContentStart = wrap.start + newLayers * m.length;
            const newSelFrom = newContentStart + relFrom;
            const newSelTo = newContentStart + relTo;

            return {
                changes: { from: wrap.start, to: wrap.end, insert: newText },
                range: _ES.range(newSelFrom, newSelTo)
            };
        });

        editorView.dispatch({
            changes: spec.changes,
            selection: spec.selection,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
    }

    // ============================================================
    //  检测光标是否落在 ***X*** / ___X___ 粗斜体结构中
    // ============================================================
    function detectTripleWrapAt(state, pos) {
        try {
            const line = state.doc.lineAt(pos);
            const lineText = line.text;
            const col = pos - line.from;

            const patterns = [
                /\*\*\*[^*\n]+\*\*\*/g,
                /___[^_\n]+___/g,
            ];
            for (let k = 0; k < patterns.length; k++) {
                const re = patterns[k];
                re.lastIndex = 0;
                let m;
                while ((m = re.exec(lineText)) !== null) {
                    if (col >= m.index && col <= m.index + m[0].length) {
                        return true;
                    }
                }
            }
        } catch (e) { /* ignore */ }
        return false;
    }

    // ============================================================
    //  检测光标是否在 <ins>...</ins> 或 <u>...</u> 内
    // ============================================================
    function detectUnderlineAt(state, pos) {
        try {
            if (_ST) {
                const tree = _ST(state);
                let node = tree.resolveInner(pos, 1);
                while (node) {
                    const name = node.name;
                    if (name === 'InlineCode' || name === 'FencedCode' || name === 'CodeText') {
                        return false;
                    }
                    node = node.parent;
                }
            }

            const line = state.doc.lineAt(pos);
            const lineText = line.text;
            const col = pos - line.from;

            const re = /<ins>[\s\S]*?<\/ins>|<u>[\s\S]*?<\/u>/g;
            let m;
            while ((m = re.exec(lineText)) !== null) {
                const startIdx = m.index;
                const endIdx = m.index + m[0].length;
                if (col >= startIdx && col <= endIdx) {
                    return true;
                }
            }
        } catch (e) { /* ignore */ }
        return false;
    }
    
    // ============================================================
    //  阶段 16-16 新增：检测光标/选区是否在 ~~...~~ 内
    //  参数：
    //    pos  —— 光标位置（用于光标场景）
    //    from, to —— 选区范围（用于选中场景，可选）
    //  返回 true 表示应显示删除线高亮
    // ============================================================
    function detectStrikethroughAt(state, pos, from, to) {
        try {
            if (_ST) {
                const tree = _ST(state);
                let node = tree.resolveInner(pos, 1);
                while (node) {
                    if (node.name === 'Strikethrough') return true;
                    if (node.name === 'InlineCode' || node.name === 'FencedCode' || node.name === 'CodeText') {
                        return false;
                    }
                    node = node.parent;
                }
            }

            const line = state.doc.lineAt(pos);
            const lineText = line.text;

            const re = /~~[^~\n]+?~~/g;
            let m;

            // 光标场景：pos 落在 ~~...~~ 区间内
            const col = pos - line.from;
            while ((m = re.exec(lineText)) !== null) {
                const start = m.index;
                const end = start + m[0].length;
                if (col >= start && col <= end) {
                    return true;
                }
            }

            // 选中场景：选区完全覆盖 ~~...~~，或选区在 ~~...~~ 内
            if (from != null && to != null && from !== to) {
                if (state.doc.lineAt(from).from !== line.from) return false;
                const relFrom = from - line.from;
                const relTo = to - line.from;

                re.lastIndex = 0;
                while ((m = re.exec(lineText)) !== null) {
                    const start = m.index;
                    const end = start + m[0].length;
                    // 选区与 ~~...~~ 有交叠
                    if (relFrom < end && relTo > start) {
                        return true;
                    }
                }
            }
        } catch (e) { /* ignore */ }
        return false;
    }

    // ============================================================
    //  扫描选区是否被 <ins>...</ins> 或 <u>...</u> 包裹
    // ============================================================
    function scanUnderlineWrapAt(state, from, to) {
        try {
            if (_ST) {
                const tree = _ST(state);
                let node = tree.resolveInner(from, 1);
                while (node) {
                    const name = node.name;
                    if (name === 'InlineCode' || name === 'FencedCode' || name === 'CodeText') {
                        return null;
                    }
                    node = node.parent;
                }
            }

            const line = state.doc.lineAt(from);
            if (state.doc.lineAt(to).from !== line.from) return null;

            const lineText = line.text;
            const relFrom = from - line.from;
            const relTo = to - line.from;

            const leftText = lineText.slice(0, relFrom);
            const rightText = lineText.slice(relTo);

            function tryTag(tag) {
                const openTag = '<' + tag + '>';
                const closeTag = '</' + tag + '>';

                const uOpenIdx = leftText.lastIndexOf(openTag);
                const uCloseIdx = leftText.lastIndexOf(closeTag);
                if (uOpenIdx < 0) return null;
                if (uCloseIdx > uOpenIdx) return null;

                const betweenLeft = leftText.slice(uOpenIdx + openTag.length);
                if (!/^[*_~]*$/.test(betweenLeft)) return null;

                const rightCloseIdx = rightText.indexOf(closeTag);
                if (rightCloseIdx < 0) return null;

                const betweenRight = rightText.slice(0, rightCloseIdx);
                if (!/^[*_~]*$/.test(betweenRight)) return null;

                const uStartRel = uOpenIdx;
                const uEndRel = relTo + rightCloseIdx + closeTag.length;
                const contentStartRel = uOpenIdx + openTag.length;
                const contentEndRel = relTo + rightCloseIdx;

                return {
                    start: line.from + uStartRel,
                    end: line.from + uEndRel,
                    contentStart: line.from + contentStartRel,
                    contentEnd: line.from + contentEndRel,
                    tag: tag,
                };
            }

            const insWrap = tryTag('ins');
            if (insWrap) return insWrap;
            const uWrap = tryTag('u');
            if (uWrap) return uWrap;
            return null;
        } catch (e) {
            return null;
        }
    }

    // ============================================================
    //  多行下划线：按行独立包裹/剥离 <ins>
    // ============================================================
    function toggleUnderlineMultiline(editorView, from, to) {
        const state = editorView.state;
        const startLine = state.doc.lineAt(from).number;
        const endLine = state.doc.lineAt(to).number;

        const lineInfos = [];
        let anyLine = false;
        let allWrapped = true;

        for (let ln = startLine; ln <= endLine; ln++) {
            const line = state.doc.line(ln);
            const text = line.text;
            if (!text.trim()) {
                lineInfos.push(null);
                continue;
            }
            anyLine = true;
            const m = /^(\s*)<ins>([\s\S]*)<\/ins>[ \t]*$/.exec(text);
            lineInfos.push({ line, m });
            if (!m) allWrapped = false;
        }

        if (!anyLine) return;

        const changes = [];
        for (let i = 0; i < lineInfos.length; i++) {
            const info = lineInfos[i];
            if (!info) continue;
            const { line, m } = info;
            const text = line.text;

            if (allWrapped && m) {
                const newText = m[1] + m[2];
                if (newText !== text) {
                    changes.push({ from: line.from, to: line.to, insert: newText });
                }
            } else {
                if (m) continue;
                const indentMatch = /^(\s*)/.exec(text);
                const indent = indentMatch ? indentMatch[1] : '';
                const content = text.slice(indent.length);
                if (!content) continue;
                const newText = indent + '<ins>' + content + '</ins>';
                changes.push({ from: line.from, to: line.to, insert: newText });
            }
        }

        if (changes.length === 0) return;

        editorView.dispatch({
            changes,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
    }

    // ============================================================
    //  下划线切换（统一输出 <ins>...</ins>）
    //  - 光标空 → 插入 <ins></ins>，光标落在中间
    //  - 选区内容本身就是 <ins>...</ins> → 剥离
    //  - 单行选区两侧有 <ins>...</ins> → 剥离
    //  - 单行选区无包裹 → <ins>...</ins>
    //  - 多行选区 → 每行独立包裹/剥离
    // ============================================================
    function toggleUnderlineFormat(editorView) {
        if (!editorView || !_ES || !_IH) return;
        const state = editorView.state;
        const range = state.selection.main;

        // 场景 1：光标在 <ins>...</ins> 内 → 移除整个包裹
        if (range.empty) {
            if (removeEnclosingUnderline(editorView, range.head)) {
                editorView.focus();
                return;
            }
        }

        // 场景 2：选区在 <ins>...</ins> 内 → 仅剥离选中部分的下划线
        if (!range.empty) {
            const startLine = state.doc.lineAt(range.from).number;
            const endLine = state.doc.lineAt(range.to).number;
            if (startLine === endLine) {
                if (removeUnderlineInRange(editorView, range.from, range.to)) {
                    editorView.focus();
                    return;
                }
            }
        }

        // 选区自身就是 <ins>...</ins> 或 <u>...</u> → 整体剥离
        if (!range.empty) {
            const sel = state.sliceDoc(range.from, range.to);
            const m = /^<ins>([\s\S]*)<\/ins>$/.exec(sel) ||
                      /^<u>([\s\S]*)<\/u>$/.exec(sel);
            if (m) {
                const inner = m[1];
                editorView.dispatch({
                    changes: { from: range.from, to: range.to, insert: inner },
                    selection: _ES.range(range.from, range.from + inner.length),
                    annotations: [_IH.of('full')]
                });
                editorView.focus();
                return;
            }
        }

        // 多行选区 → 逐行独立处理
        if (!range.empty) {
            const startLine = state.doc.lineAt(range.from).number;
            const endLine = state.doc.lineAt(range.to).number;
            if (startLine !== endLine) {
                toggleUnderlineMultiline(editorView, range.from, range.to);
                return;
            }
        }

        const spec = state.changeByRange(range => {
            const wrap = scanUnderlineWrapAt(state, range.from, range.to);

            if (wrap) {
                const inner = state.sliceDoc(wrap.contentStart, wrap.contentEnd);
                const newSelFrom = wrap.start + (range.from - wrap.contentStart);
                const newSelTo = wrap.start + (range.to - wrap.contentStart);

                return {
                    changes: { from: wrap.start, to: wrap.end, insert: inner },
                    range: _ES.range(newSelFrom, newSelTo)
                };
            }

            if (range.empty) {
                const insert = '<ins></ins>';
                return {
                    changes: { from: range.from, insert },
                    range: _ES.cursor(range.from + 5)
                };
            }

            const sel = state.sliceDoc(range.from, range.to);
            const insert = '<ins>' + sel + '</ins>';
            return {
                changes: { from: range.from, to: range.to, insert },
                range: _ES.range(range.from + 5, range.from + 5 + sel.length)
            };
        });

        editorView.dispatch({
            changes: spec.changes,
            selection: spec.selection,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
    }

    // ============================================================
    //  阶段 16-15 新增：下划线/加粗/斜体/删除线的"部分剥离"
    // ============================================================

    // 场景 1 辅助函数：光标在 <ins>...</ins> 内 → 移除整个包裹
    function removeEnclosingUnderline(editorView, pos) {
        const state = editorView.state;
        const line = state.doc.lineAt(pos);
        const lineText = line.text;
        const col = pos - line.from;

        const re = /<ins>([\s\S]*?)<\/ins>|<u>([\s\S]*?)<\/u>/g;
        let m;
        while ((m = re.exec(lineText)) !== null) {
            const start = m.index;
            const end = start + m[0].length;
            if (col > start && col < end) {
                const isIns = m[1] !== undefined;
                const tagLen = isIns ? 5 : 3;
                const inner = isIns ? m[1] : m[2];

                const relPos = Math.max(0, Math.min(inner.length, col - start - tagLen));

                editorView.dispatch({
                    changes: {
                        from: line.from + start,
                        to: line.from + end,
                        insert: inner
                    },
                    selection: _ES.cursor(line.from + start + relPos),
                    annotations: [_IH.of('full')]
                });
                return true;
            }
        }
        return false;
    }

    // 场景 2 辅助函数：选区在 <ins>...</ins> 内 → 仅剥离选中部分的下划线
    function removeUnderlineInRange(editorView, from, to) {
        const state = editorView.state;
        const line = state.doc.lineAt(from);
        if (state.doc.lineAt(to).from !== line.from) return false;

        const lineText = line.text;
        const relFrom = from - line.from;
        const relTo = to - line.from;

        const re = /<ins>([\s\S]*?)<\/ins>|<u>([\s\S]*?)<\/u>/g;
        let m;
        while ((m = re.exec(lineText)) !== null) {
            const start = m.index;
            const end = start + m[0].length;
            if (relFrom >= start && relTo <= end) {
                const isIns = m[1] !== undefined;
                const tagLen = isIns ? 5 : 3;
                const inner = isIns ? m[1] : m[2];
                const innerStart = start + tagLen;
                const relInnerFrom = relFrom - innerStart;
                const relInnerTo = relTo - innerStart;

                if (relInnerFrom < 0 || relInnerTo > inner.length) return false;
                if (relInnerFrom === 0 && relInnerTo === inner.length) return false;

                const wrapMatch = /^(\*{1,3}|_{1,3}|~{2})([\s\S]*)\1$/.exec(inner);

                let newText = '';

                if (wrapMatch) {
                    const marker = wrapMatch[1];
                    const body = wrapMatch[2];
                    const bodyStartInInner = marker.length;

                    const relBodyFrom = Math.max(0, relInnerFrom - bodyStartInInner);
                    const relBodyTo = Math.min(body.length, relInnerTo - bodyStartInInner);

                    if (relBodyFrom >= relBodyTo) return false;

                    const beforeBody = body.slice(0, relBodyFrom);
                    const selectedBody = body.slice(relBodyFrom, relBodyTo);
                    const afterBody = body.slice(relBodyTo);

                    if (beforeBody) newText += '<ins>' + marker + beforeBody + marker + '</ins>';
                    newText += marker + selectedBody + marker;
                    if (afterBody) newText += '<ins>' + marker + afterBody + marker + '</ins>';
                } else {
                    const beforeText = inner.slice(0, relInnerFrom);
                    const selectedText = inner.slice(relInnerFrom, relInnerTo);
                    const afterText = inner.slice(relInnerTo);

                    if (beforeText) newText += '<ins>' + beforeText + '</ins>';
                    newText += selectedText;
                    if (afterText) newText += '<ins>' + afterText + '</ins>';
                }

                editorView.dispatch({
                    changes: {
                        from: line.from + start,
                        to: line.from + end,
                        insert: newText
                    },
                    annotations: [_IH.of('full')]
                });
                return true;
            }
        }
        return false;
    }

    // 场景 3 辅助函数：选区在 marker...marker 内 → 仅剥离选中部分的标记
    function removeMarkerInRange(editorView, from, to, marker) {
        const state = editorView.state;
        const line = state.doc.lineAt(from);
        if (state.doc.lineAt(to).from !== line.from) return false;

        const lineText = line.text;
        const relFrom = from - line.from;
        const relTo = to - line.from;
        const mlen = marker.length;

        let openIdx = -1;
        for (let i = relFrom - mlen; i >= 0; i--) {
            if (lineText.slice(i, i + mlen) === marker) {
                if (mlen === 1) {
                    if (i > 0 && lineText[i - 1] === marker[0]) continue;
                    if (i + mlen < lineText.length && lineText[i + mlen] === marker[0]) continue;
                }
                openIdx = i;
                break;
            }
        }
        if (openIdx < 0) return false;

        let closeIdx = -1;
        for (let i = relTo; i <= lineText.length - mlen; i++) {
            if (lineText.slice(i, i + mlen) === marker) {
                if (mlen === 1) {
                    if (i > 0 && lineText[i - 1] === marker[0]) continue;
                    if (i + mlen < lineText.length && lineText[i + mlen] === marker[0]) continue;
                }
                closeIdx = i;
                break;
            }
        }
        if (closeIdx < 0) return false;

        const innerStart = openIdx + mlen;
        const innerEnd = closeIdx;
        const inner = lineText.slice(innerStart, innerEnd);

        const relInnerFrom = relFrom - innerStart;
        const relInnerTo = relTo - innerStart;

        if (relInnerFrom < 0 || relInnerTo > inner.length) return false;
        if (relInnerFrom === 0 && relInnerTo === inner.length) return false;
        if (relInnerFrom >= relInnerTo) return false;

        const beforeText = inner.slice(0, relInnerFrom);
        const selectedText = inner.slice(relInnerFrom, relInnerTo);
        const afterText = inner.slice(relInnerTo);

        let newText = '';
        if (beforeText) newText += marker + beforeText + marker;
        newText += selectedText;
        if (afterText) newText += marker + afterText + marker;

        editorView.dispatch({
            changes: {
                from: line.from + openIdx,
                to: line.from + closeIdx + mlen,
                insert: newText
            },
            annotations: [_IH.of('full')]
        });
        return true;
    }

    // ============================================================
    //  i18n 工具
    // ============================================================
    function T(key, fallback) {
        try {
            if (window.I18N && typeof window.I18N.t === 'function') {
                return window.I18N.t(key);
            }
        } catch (e) { /* ignore */ }
        return fallback || key;
    }

    function buildTooltip(item) {
        if (!item) return '';
        let base = '';
        if (item.titleKey) base = T(item.titleKey, item.title || item.titleKey);
        else if (item.title) base = item.title;
        return base + (item.titleSuffix || '');
    }

    // ============================================================
    //  JS Tooltip 管理
    // ============================================================
    function ensureTooltipEl() {
        if (_tooltipEl && _tooltipEl.parentNode) return _tooltipEl;
        _tooltipEl = document.createElement('div');
        _tooltipEl.className = 'tb-tooltip';
        _tooltipEl.style.display = 'none';
        document.body.appendChild(_tooltipEl);
        return _tooltipEl;
    }

    function showTooltip(target) {
        const text = target.getAttribute('data-tooltip');
        if (!text) return;

        const tip = ensureTooltipEl();
        tip.textContent = text;
        tip.style.visibility = 'hidden';
        tip.style.display = 'block';
        tip.style.left = '0px';
        tip.style.top = '0px';

        const tipRect = tip.getBoundingClientRect();
        const btnRect = target.getBoundingClientRect();

        let top = btnRect.top - tipRect.height - TOOLTIP_GAP;
        if (top < TOOLTIP_EDGE) {
            top = TOOLTIP_EDGE;
        }

        let left = btnRect.left + btnRect.width / 2 - tipRect.width / 2;
        if (left < TOOLTIP_EDGE) {
            left = TOOLTIP_EDGE;
        }
        const maxLeft = window.innerWidth - tipRect.width - TOOLTIP_EDGE;
        if (left > maxLeft) {
            left = maxLeft;
        }
        if (maxLeft < TOOLTIP_EDGE) {
            left = TOOLTIP_EDGE;
        }

        const arrowX = btnRect.left + btnRect.width / 2 - left;

        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
        tip.setAttribute('data-arrow', 'top');
        tip.style.setProperty('--arrow-x', arrowX + 'px');
        tip.style.visibility = 'visible';
    }

    function hideTooltip() {
        if (_tooltipTimer) {
            clearTimeout(_tooltipTimer);
            _tooltipTimer = null;
        }
        if (_tooltipEl) {
            _tooltipEl.style.display = 'none';
        }
    }

    function bindTooltips(root) {
        const scope = root || document;
        const selector = '.tb-btn[data-tooltip],' +
                         '.tb-h-btn-main[data-tooltip],' +
                         '.tb-h-btn-caret[data-tooltip]';
        scope.querySelectorAll(selector).forEach(el => {
            if (el.dataset.tooltipBound === '1') return;
            el.dataset.tooltipBound = '1';

            el.addEventListener('mouseenter', () => {
                if (_tooltipTimer) clearTimeout(_tooltipTimer);
                _tooltipTimer = setTimeout(() => {
                    _tooltipTimer = null;
                    try { showTooltip(el); } catch (e) { /* ignore */ }
                }, TOOLTIP_DELAY);
            });

            el.addEventListener('mouseleave', () => {
                hideTooltip();
            });

            el.addEventListener('mousedown', () => {
                hideTooltip();
            });

            el.addEventListener('click', () => {
                hideTooltip();
            });
        });
    }

    window.addEventListener('resize', hideTooltip);
    window.addEventListener('scroll', hideTooltip, true);

    // ============================================================
    //  选区保存与恢复
    // ============================================================
    function saveCurrentSelection() {
        if (!view) return;
        try {
            const sel = view.state.selection;
            if (!sel || !sel.ranges || sel.ranges.length === 0) return;
            _savedSelection = sel;
        } catch (e) { /* ignore */ }
    }

    function restoreSavedSelection() {
        if (!view) return;
        if (!_savedSelection) return;
        try {
            view.dispatch({ selection: _savedSelection });
        } catch (e) { /* ignore */ }
    }

    function initSelectionTracker() {
        if (!view) return;
        const saveHandler = () => {
            try {
                const sel = view.state.selection;
                if (sel && sel.ranges && sel.ranges.length > 0) {
                    _savedSelection = sel;
                }
            } catch (e) { /* ignore */ }
        };
        view.dom.addEventListener('mouseup', saveHandler, true);
        view.dom.addEventListener('keyup', saveHandler, true);
    }

    function getCurrentSelectionText() {
        if (!view) return '';

        try {
            if (_savedSelection && _savedSelection.ranges && _savedSelection.ranges.length > 0) {
                const r = _savedSelection.main;
                if (r && !r.empty) {
                    const txt = view.state.sliceDoc(r.from, r.to);
                    if (txt) return txt;
                }
            }
        } catch (e) { /* ignore */ }

        try {
            const sel = view.state.selection;
            if (sel && sel.ranges && sel.ranges.length > 0) {
                const r = sel.main;
                if (r && !r.empty) {
                    const txt = view.state.sliceDoc(r.from, r.to);
                    if (txt) return txt;
                }
            }
        } catch (e) { /* ignore */ }

        return '';
    }

    // ============================================================
    //  布局定义
    // ============================================================
    const TOOLBAR_LAYOUT = [
        { type: 'action', action: 'new',   icon: 'newFile', titleKey: 'new',  titleSuffix: ' (Ctrl+N)' },
        { type: 'action', action: 'open',  icon: 'open',    titleKey: 'open', titleSuffix: ' (Ctrl+O)' },
        { type: 'action', action: 'save',  icon: 'save',    titleKey: 'save', titleSuffix: ' (Ctrl+S)' },
        { type: 'sep' },
        { type: 'action', action: 'undo',  icon: 'undo',    titleKey: 'undo', titleSuffix: ' (Ctrl+Z)' },
        { type: 'action', action: 'redo',  icon: 'redo',    titleKey: 'redo', titleSuffix: ' (Ctrl+Y)' },
        { type: 'sep' },
        { type: 'fmt', fmt: 'bold',       icon: 'bold',       titleKey: 'bold' },
        { type: 'fmt', fmt: 'italic',     icon: 'italic',     titleKey: 'italic' },
        { type: 'fmt', fmt: 'underline',  icon: 'underline',  titleKey: 'underline' },
        { type: 'fmt', fmt: 'strike',     icon: 'strike',     titleKey: 'strikethrough' },
        { type: 'heading',                                    titleKey: 'heading' },
        { type: 'fmt', fmt: 'ul',         icon: 'ul',         titleKey: 'unordered_list' },
        { type: 'fmt', fmt: 'ol',         icon: 'ol',         titleKey: 'ordered_list' },
        { type: 'fmt', fmt: 'taskList',   icon: 'taskList',   titleKey: 'task_list' },
        { type: 'fmt', fmt: 'quote',      icon: 'quote',      titleKey: 'quote' },
        { type: 'fmt', fmt: 'inlineCode', icon: 'inlineCode', titleKey: 'inline_code' },
        { type: 'fmt', fmt: 'codeBlock',  icon: 'codeBlock',  titleKey: 'code_block' },
        { type: 'action', action: 'insert_footnote', icon: 'footnote', titleKey: 'footnote' },
        { type: 'action', action: 'insert_link',  icon: 'link',  titleKey: 'insert_link' },
        { type: 'action', action: 'insert_image', icon: 'image', titleKey: 'insert_image' },
        { type: 'sep' },
        { type: 'painter',  icon: 'formatPainter', titleKey: 'format_painter' },
        { type: 'eraser',   icon: 'eraser',        titleKey: 'eraser' },
        { type: 'table',    icon: 'table',         titleKey: 'table' },
        { type: 'collapse', icon: 'collapse',      titleKey: 'collapse' },
        { type: 'sep' },
        { type: 'mode',   mode: 'edit',    icon: 'editMode',    titleKey: 'edit_mode',    titleSuffix: ' (Ctrl+1)' },
        { type: 'mode',   mode: 'split',   icon: 'splitMode',   titleKey: 'split_mode',   titleSuffix: ' (Ctrl+2)' },
        { type: 'mode',   mode: 'preview', icon: 'previewMode', titleKey: 'preview_mode', titleSuffix: ' (Ctrl+3)' },
        { type: 'sep' },
        { type: 'toggle', toggle: 'theme', icon: 'theme', titleKey: 'toggle_theme' },
        { type: 'toggle', toggle: 'toc',   icon: 'toc',   titleKey: 'show_toc',     titleSuffix: ' (Ctrl+B)' },
    ];

    // ============================================================
    //  初始化
    // ============================================================
    function initToolbar(editorView, handlers, deps) {
        view = editorView;
        externalHandlers = handlers || {};
        _ES = (deps && deps.EditorSelection) || null;
        _IH = (deps && deps.isolateHistory) || null;
        _ST = (deps && deps.syntaxTree) || null;

        buildToolbar();
        bindGlobalEvents();
        watchThemeChange();
        setupOverflow();
        bindEditorForPainter();
        bindTabIndent();
        initSelectionTracker();
        refreshToolbarState();
    }

    function getIcon(name) {
        return (window.ICONS && window.ICONS[name]) || '';
    }

    function setStatusHint(msg) {
        if (typeof externalHandlers.status === 'function') {
            try { externalHandlers.status(msg); } catch (e) { /* ignore */ }
        }
    }

    function forceRefreshPreview() {
        if (typeof externalHandlers.refreshPreview === 'function') {
            try { externalHandlers.refreshPreview(); } catch (e) { /* ignore */ }
        }
    }

    // ============================================================
    //  构建工具栏
    // ============================================================
    function buildToolbar() {
        const el = document.getElementById('toolbar');
        if (!el) { console.warn('[toolbar] #toolbar not found'); return; }
        el.innerHTML = '';

        for (const item of TOOLBAR_LAYOUT) {
            if (item.type === 'sep') {
                const sep = document.createElement('div');
                sep.className = 'tb-sep';
                el.appendChild(sep);
                continue;
            }
            if (item.type === 'heading') {
                el.appendChild(buildHeadingDropdown(item));
                continue;
            }

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'tb-btn';
            btn.setAttribute('data-tooltip', buildTooltip(item));
            if (item.titleKey) {
                btn.setAttribute('data-i18n-key', item.titleKey);
                if (item.titleSuffix) {
                    btn.setAttribute('data-i18n-suffix', item.titleSuffix);
                }
            }
            btn.innerHTML = getIcon(item.icon);

            btn.addEventListener('mousedown', (e) => {
                e.preventDefault();
                saveCurrentSelection();
            });

            if (item.type === 'action') {
                btn.dataset.action = item.action;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    if (item.action === 'insert_link') {
                        openLinkDialog();
                    } else if (item.action === 'insert_footnote') {
                        insertFootnote();
                    } else {
                        dispatchAction(item.action);
                    }
                });
            } else if (item.type === 'fmt') {
                btn.dataset.fmt = item.fmt;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    handleFormat(item.fmt);
                });
            } else if (item.type === 'mode') {
                btn.dataset.mode = item.mode;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    if (typeof externalHandlers.setMode === 'function') {
                        externalHandlers.setMode(item.mode);
                    }
                });
            } else if (item.type === 'toggle') {
                btn.dataset.toggle = item.toggle;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    if (typeof externalHandlers.toggle === 'function') {
                        externalHandlers.toggle(item.toggle);
                    }
                });
                if (item.toggle === 'theme') setTimeout(refreshThemeIcon, 0);
            } else if (item.type === 'painter') {
                btn.dataset.tool = 'painter';
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handlePainterClick();
                });
            } else if (item.type === 'eraser') {
                btn.dataset.tool = 'eraser';
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleEraser();
                });
            } else if (item.type === 'collapse') {
                btn.dataset.tool = 'collapse';
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleCollapse();
                });
            } else if (item.type === 'table') {
                btn.dataset.tool = 'table';
                _tableBtn = btn;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    toggleTableMenu();
                });
            }

            el.appendChild(btn);
        }

        _overflowBtn = document.createElement('button');
        _overflowBtn.type = 'button';
        _overflowBtn.className = 'tb-btn tb-overflow-btn';
        _overflowBtn.setAttribute('data-tooltip', T('toolbar_more', '更多'));
        _overflowBtn.setAttribute('data-i18n-key', 'toolbar_more');
        _overflowBtn.innerHTML =
            '<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true">' +
            '<circle cx="3" cy="8" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="13" cy="8" r="1.5"/>' +
            '</svg>';
        _overflowBtn.style.display = 'none';
        _overflowBtn.addEventListener('mousedown', (e) => {
            e.preventDefault();
            saveCurrentSelection();
        });
        el.appendChild(_overflowBtn);

        bindTooltips(el);
    }

    // ============================================================
    //  H1~H6 下拉
    // ============================================================
    function buildHeadingDropdown(item) {
        const wrap = document.createElement('div');
        wrap.className = 'tb-h-wrap';

        const headingLabel = item && item.titleKey
            ? T(item.titleKey, '标题')
            : '标题';

        const btnMain = document.createElement('button');
        btnMain.type = 'button';
        btnMain.className = 'tb-btn tb-h-btn-main';
        btnMain.setAttribute('data-i18n-key', 'heading');
        btnMain.setAttribute('data-tooltip', headingLabel + '（H1~H6）');
        btnMain.innerHTML = '<span class="tb-h-label">H</span>';

        const btnCaret = document.createElement('button');
        btnCaret.type = 'button';
        btnCaret.className = 'tb-btn tb-h-btn-caret';
        btnCaret.setAttribute('data-i18n-key', 'heading');
        btnCaret.setAttribute('data-tooltip', headingLabel + ' H1~H6');
        btnCaret.innerHTML = '<svg viewBox="0 0 8 8" width="8" height="8" fill="currentColor" aria-hidden="true"><path d="M1 3l3 3 3-3z"/></svg>';

        const menu = document.createElement('div');
        menu.className = 'tb-dropdown-menu';
        menu.style.position = 'fixed';
        menu.style.display = 'none';
        document.body.appendChild(menu);

        for (let i = 1; i <= 6; i++) {
            const it = document.createElement('div');
            it.className = 'tb-dropdown-item';
            it.dataset.heading = String(i);
            it.textContent = 'H' + i;
            it.addEventListener('click', (e) => {
                e.stopPropagation();
                applyHeading(view, i);
                closeDropdown();
                refreshToolbarState();
            });
            menu.appendChild(it);
        }

        _hBtnMain = btnMain;
        _hMenuEl = menu;

        btnMain.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            saveCurrentSelection();
            _hLongPress = false;
            if (_hPressTimer) clearTimeout(_hPressTimer);
            _hPressTimer = setTimeout(() => {
                _hPressTimer = null;
                _hLongPress = true;
                openDropdown();
            }, 400);
        });

        btnMain.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (_hLongPress) { _hLongPress = false; return; }
            if (_hMenuOpen) { closeDropdown(); return; }

            let curHeading = 0;
            try {
                const line = view.state.doc.lineAt(view.state.selection.main.head);
                const m = /^(#{1,6})\s+/.exec(line.text);
                if (m) curHeading = m[1].length;
            } catch (err) { /* ignore */ }

            if (curHeading > 0) {
                applyHeading(view, curHeading);
                refreshToolbarState();
            } else {
                openDropdown();
            }
        });

        btnCaret.addEventListener('mousedown', (e) => {
            e.preventDefault();
            saveCurrentSelection();
        });

        btnCaret.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (_hMenuOpen) closeDropdown();
            else openDropdown();
        });

        btnCaret.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();
            openDropdown();
        });

        wrap.appendChild(btnMain);
        wrap.appendChild(btnCaret);
        return wrap;
    }

    function openDropdown() {
        if (!_hBtnMain || !_hMenuEl) return;
        const rect = _hBtnMain.getBoundingClientRect();
        _hMenuEl.style.left = rect.left + 'px';
        _hMenuEl.style.top = (rect.bottom + 4) + 'px';
        _hMenuEl.style.display = 'block';
        _hMenuEl.classList.add('open');
        _hMenuOpen = true;
    }

    function closeDropdown() {
        if (_hMenuEl) {
            _hMenuEl.style.display = 'none';
            _hMenuEl.classList.remove('open');
        }
        _hMenuOpen = false;
        document.querySelectorAll('.tb-dropdown.open').forEach(el => el.classList.remove('open'));
    }

    // ============================================================
    //  全局事件
    // ============================================================
    function bindGlobalEvents() {
        if (bound) return;
        bound = true;

        document.addEventListener('click', () => {
            closeDropdown();
            closeTableMenu();
            closeOverflowMenu();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeDropdown();
                closeTableMenu();
                closeOverflowMenu();
                hideTooltip();
                if (_painter.active) exitFormatPainter();
            }
        });

        document.addEventListener('mouseup', (e) => {
            if (_hPressTimer) { clearTimeout(_hPressTimer); _hPressTimer = null; }
            if (!_hLongPress) return;
            _hLongPress = false;

            const target = document.elementFromPoint(e.clientX, e.clientY);
            if (target && _hMenuEl && _hMenuEl.contains(target)) {
                const it = target.closest
                    ? target.closest('.tb-dropdown-item[data-heading]')
                    : null;
                if (it) {
                    const level = parseInt(it.dataset.heading, 10);
                    if (Number.isFinite(level)) {
                        applyHeading(view, level);
                        refreshToolbarState();
                    }
                }
            }
            closeDropdown();
        }, true);
    }

    function watchThemeChange() {
        try {
            const mo = new MutationObserver(() => refreshThemeIcon());
            mo.observe(document.body, { attributes: true, attributeFilter: ['class'] });
            mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
        } catch (e) { /* ignore */ }
    }

    function refreshThemeIcon() {
        const btn = document.querySelector('.tb-btn[data-toggle="theme"]');
        if (!btn) return;
        const isDark = document.body.classList.contains('dark');
        btn.innerHTML = isDark ? getIcon('sun') : getIcon('moon');
    }

    function dispatchAction(action) {
        const fn = externalHandlers[action];
        if (typeof fn === 'function') {
            try { fn(); } catch (e) { console.error('[toolbar]', action, e); }
        }
    }

    // ============================================================
    //  插入脚注
    //  - 引用插入点：有选区时，回退掉选区末尾的空白字符
    //  - 定义内容：trim 掉首尾空白/换行
    //  - 定义追加位置：文档内容末尾（去掉尾部空白后）
    //  - 若引用插入点 >= 内容末尾，合并成单个 change（避免位置重合）
    // ============================================================
    function insertFootnote() {
        if (!view || !_IH) return;
        restoreSavedSelection();

        const state = view.state;
        const range = state.selection.main;
        const docText = state.doc.toString();
        const docLen = state.doc.length;

        // 1) 扫描最大编号（引用 + 定义各一次）
        let maxIdx = 0;
        let m;
        const refScanRe = /\[\^(\d+)\](?!:)/g;
        while ((m = refScanRe.exec(docText)) !== null) {
            const n = parseInt(m[1], 10);
            if (Number.isFinite(n) && n > maxIdx) maxIdx = n;
        }
        const defScanRe = /^\[\^(\d+)\]:/gm;
        while ((m = defScanRe.exec(docText)) !== null) {
            const n = parseInt(m[1], 10);
            if (Number.isFinite(n) && n > maxIdx) maxIdx = n;
        }

        const nextIdx = maxIdx + 1;
        const refText = '[^' + nextIdx + ']';

        // 2) 定义内容：trim 掉首尾空白/换行（★ 修复 1）
        const rawSelText = range.empty ? '' : state.sliceDoc(range.from, range.to);
        const selText = rawSelText.replace(/^\s+|\s+$/g, '');
        const defContent = selText || '脚注内容';
        const defText = '[^' + nextIdx + ']: ' + defContent;

        // 3) 引用插入点：有选区时回退掉末尾空白（★ 修复 2）
        let insertPos;
        if (range.empty) {
            insertPos = range.from;
        } else {
            insertPos = range.to;
            while (insertPos > range.from && /\s/.test(docText.charAt(insertPos - 1))) {
                insertPos--;
            }
        }

        // 4) 文档内容末尾（去掉尾部空白）
        let contentEnd = docLen;
        while (contentEnd > 0 && /\s/.test(docText.charAt(contentEnd - 1))) {
            contentEnd--;
        }

        // 5) 定义与引用之间的分隔始终用 \n\n
        const sep = '\n\n';

        // 6) 判断：引用插入点是否在内容末尾或之后
        //    若是 → 合并成单个 change（★ 修复 3）
        //    否则 → 两处独立插入
        if (insertPos >= contentEnd) {
            const combined = refText + sep + defText;
            view.dispatch({
                changes: { from: contentEnd, to: docLen, insert: combined },
                selection: { anchor: contentEnd + refText.length },
                annotations: [_IH.of('full')],
            });
        } else {
            const changes = [
                { from: contentEnd, to: docLen, insert: sep + defText },
                { from: insertPos, to: insertPos, insert: refText }
            ];
            changes.sort((a, b) => a.from - b.from);
            view.dispatch({
                changes,
                selection: { anchor: insertPos + refText.length },
                annotations: [_IH.of('full')],
            });
        }

        view.focus();
        forceRefreshPreview();
        refreshToolbarState();
        setStatusHint('已插入脚注 ' + refText);
    }

    // ============================================================
    //  删除选区内的 [^N] 及对应定义
    // ============================================================
    function removeFootnotesInSelection(editorView, from, to) {
        if (!editorView || !_IH) return false;
        const state = editorView.state;
        const text = state.doc.toString();
        const selected = text.slice(from, to);

        const keys = new Set();
        let m;
        const scanRe = /\[\^([^\]\s]+)\](?!:)/g;
        while ((m = scanRe.exec(selected)) !== null) {
            keys.add(m[1]);
        }
        if (keys.size === 0) return false;

        const changes = [];

        const refMatches = [];
        const refRe = /\[\^([^\]\s]+)\](?!:)/g;
        let rm;
        while ((rm = refRe.exec(selected)) !== null) {
            if (keys.has(rm[1])) {
                refMatches.push({
                    start: from + rm.index,
                    end: from + rm.index + rm[0].length,
                });
            }
        }
        for (const mt of refMatches) {
            changes.push({ from: mt.start, to: mt.end, insert: '' });
        }

        const lines = text.split('\n');
        let offset = 0;
        const defLineRe = /^[ \t]*\[\^([^\]\s]+)\]:/;
        for (const line of lines) {
            const dm = defLineRe.exec(line);
            if (dm && keys.has(dm[1])) {
                const lineStart = offset;
                const lineEnd = offset + line.length;
                const hasNewline = lineEnd < text.length &&
                    text.charAt(lineEnd) === '\n';
                changes.push({
                    from: lineStart,
                    to: hasNewline ? lineEnd + 1 : lineEnd,
                    insert: ''
                });
            }
            offset += line.length + 1;
        }

        if (changes.length === 0) return false;

        changes.sort((a, b) => a.from - b.from);
        const merged = [];
        for (const c of changes) {
            if (merged.length > 0 && c.from < merged[merged.length - 1].to) {
                continue;
            }
            merged.push(c);
        }
        if (merged.length === 0) return false;

        editorView.dispatch({
            changes: merged,
            annotations: [_IH.of('full')],
        });
        return true;
    }

    // ============================================================
    //  TAB 缩进
    // ============================================================
    function bindTabIndent() {
        if (!view) return;
        view.dom.addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;
            if (e.shiftKey) return;
            e.preventDefault();

            const state = view.state;
            const ranges = state.selection.ranges;

            let selFrom = ranges[0].from;
            let selTo = ranges[0].to;
            for (let i = 1; i < ranges.length; i++) {
                if (ranges[i].from < selFrom) selFrom = ranges[i].from;
                if (ranges[i].to > selTo) selTo = ranges[i].to;
            }

            const startLine = state.doc.lineAt(selFrom).number;
            const endLine = state.doc.lineAt(selTo).number;

            let anyOrdered = false;
            for (let ln = startLine; ln <= endLine; ln++) {
                const line = state.doc.line(ln);
                if (!line.text.trim()) continue;
                if (/^\s*\d+\.\s+/.test(line.text)) { anyOrdered = true; break; }
            }
            const INDENT = anyOrdered ? '   ' : '  ';

            const changes = [];
            for (let ln = startLine; ln <= endLine; ln++) {
                const line = state.doc.line(ln);
                if (!line.text.trim()) continue;
                changes.push({ from: line.from, to: line.from, insert: INDENT });
            }
            if (changes.length === 0) return;

            view.dispatch({
                changes,
                annotations: [_IH.of('full')],
            });
            view.focus();
        });
    }

    // ============================================================
    //  状态检测
    // ============================================================
    function getFormatState(state) {
        const pos = state.selection.main.head;
        const line = state.doc.lineAt(pos);
        const text = line.text;

        const headingMatch = /^(#{1,6})\s+/.exec(text);
        const heading = headingMatch ? headingMatch[1].length : 0;
        const quote = /^\s*>\s?/.test(text);
        const taskList = /^\s*[-*+]\s+\[[ xX]\]\s/.test(text);
        const unorderedList = /^\s*[-*+]\s+/.test(text) && !taskList;
        const orderedList = /^\s*\d+\.\s+/.test(text);

        let bold = false, italic = false, strike = false;
        let underline = false;
        let inlineCode = false, link = false;
        let codeBlock = false;

        try {
            const before = state.doc.sliceString(0, pos);
            const fences = before.match(/^(?:```|~~~)/gm);
            if (fences && fences.length % 2 === 1) codeBlock = true;
        } catch (e) { /* ignore */ }

        if (_ST && !codeBlock) {
            try {
                const tree = _ST(state);
                let node = tree.resolveInner(pos, 1);
                while (node) {
                    const name = node.name;
                    if (name === 'StrongEmphasis') bold = true;
                    else if (name === 'Emphasis') italic = true;
                    else if (name === 'Strikethrough') strike = true;
                    else if (name === 'InlineCode') inlineCode = true;
                    else if (name === 'Link') link = true;
                    node = node.parent;
                }
            } catch (e) { /* ignore */ }
        }

        if (!codeBlock && !inlineCode) {
            if (detectTripleWrapAt(state, pos)) {
                bold = true;
                italic = true;
            }
        }

        if (!codeBlock && !inlineCode) {
            if (detectUnderlineAt(state, pos)) {
                underline = true;
            }
        }

        // ★ 新增：删除线文本兜底
        if (!codeBlock && !inlineCode && !strike) {
            const sel = state.selection.main;
            if (detectStrikethroughAt(state, pos, sel.from, sel.to)) {
                strike = true;
            }
        }

        return {
            heading, quote,
            unorderedList, orderedList, taskList,
            bold, italic, underline, strike, inlineCode, link, codeBlock,
        };
    }

    function refreshToolbarState() {
        if (!view) return;
        let st;
        try { st = getFormatState(view.state); } catch (e) { return; }

        setPressed('bold', st.bold);
        setPressed('italic', st.italic);
        setPressed('underline', st.underline);
        setPressed('strike', st.strike);
        setPressed('inlineCode', st.inlineCode);
        setPressed('codeBlock', st.codeBlock);
        setPressed('ul', st.unorderedList);
        setPressed('ol', st.orderedList);
        setPressed('taskList', st.taskList);
        setPressed('quote', st.quote);

        const hLabel = document.querySelector('.tb-h-label');
        if (hLabel) hLabel.textContent = st.heading > 0 ? 'H' + st.heading : 'H';

        if (_hMenuEl) {
            _hMenuEl.querySelectorAll('.tb-dropdown-item[data-heading]').forEach(el => {
                el.dataset.active = (el.dataset.heading === String(st.heading))
                    ? 'true' : 'false';
            });
        }
    }

    function setPressed(fmt, pressed) {
        const btn = document.querySelector('.tb-btn[data-fmt="' + fmt + '"]');
        if (btn) btn.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    }

    // ============================================================
    //  基础格式化
    // ============================================================
    function handleFormat(fmt) {
        if (!view) return;
        restoreSavedSelection();

        switch (fmt) {
            case 'bold':       toggleBoldOrItalicFormat(view, 'bold'); break;
            case 'italic':     toggleBoldOrItalicFormat(view, 'italic'); break;
            case 'underline':  toggleUnderlineFormat(view); break;
            case 'strike':     toggleInlineFormat(view, '~~'); break;
            case 'inlineCode': toggleInlineFormat(view, '`');  break;
            case 'ul':         toggleList(view, 'ul');         break;
            case 'ol':         toggleList(view, 'ol');         break;
            case 'taskList':   toggleTaskListFormat(view);     break;
            case 'quote':      toggleList(view, 'quote');      break;
            case 'codeBlock':  insertCodeBlock(view);          break;
        }
        refreshToolbarState();
    }

    // ============================================================
    //  单字符 marker 的歧义处理
    // ============================================================
    function toggleInlineFormat(editorView, marker) {
        if (!editorView || !_ES || !_IH) return;
        const { state } = editorView;
        const mlen = marker.length;

        // ★ 新增：场景 3 —— 对 ~~ 生效（内联代码不适用）
        if (marker === '~~') {
            const _sel = state.selection.main;
            if (!_sel.empty) {
                const startLine = state.doc.lineAt(_sel.from).number;
                const endLine = state.doc.lineAt(_sel.to).number;
                if (startLine === endLine) {
                    if (removeMarkerInRange(editorView, _sel.from, _sel.to, marker)) {
                        editorView.focus();
                        return;
                    }
                }
            }
        }

        const spec = state.changeByRange(range => {
            if (!range.empty) {
                const before = state.sliceDoc(Math.max(0, range.from - mlen), range.from);
                const after = state.sliceDoc(range.to, Math.min(state.doc.length, range.to + mlen));

                let isWrapped = (before === marker && after === marker);
                if (isWrapped && mlen === 1) {
                    const before2 = state.sliceDoc(Math.max(0, range.from - 2), range.from - 1);
                    const after2 = state.sliceDoc(range.to + 1, Math.min(state.doc.length, range.to + 2));
                    if (before2 === marker || after2 === marker) {
                        isWrapped = false;
                    }
                }

                if (isWrapped) {
                    return {
                        changes: [
                            { from: range.from - mlen, to: range.from, insert: '' },
                            { from: range.to, to: range.to + mlen, insert: '' }
                        ],
                        range: _ES.range(range.from - mlen, range.to - mlen)
                    };
                }

                const sel = state.sliceDoc(range.from, range.to);
                if (sel.length >= mlen * 2 &&
                    sel.startsWith(marker) && sel.endsWith(marker)) {
                    const inner = sel.slice(mlen, sel.length - mlen);

                    let canUnwrap = true;
                    if (mlen === 1 && inner.indexOf(marker) !== -1) {
                        canUnwrap = false;
                    }

                    if (canUnwrap) {
                        return {
                            changes: { from: range.from, to: range.to, insert: inner },
                            range: _ES.range(range.from, range.from + inner.length)
                        };
                    }
                }

                const insert = marker + sel + marker;
                return {
                    changes: { from: range.from, to: range.to, insert },
                    range: _ES.range(range.from + mlen, range.from + mlen + sel.length)
                };
            }

            const before = state.sliceDoc(Math.max(0, range.from - mlen), range.from);
            const after = state.sliceDoc(range.from, Math.min(state.doc.length, range.from + mlen));

            let isWrapped2 = (before === marker && after === marker);
            if (isWrapped2 && mlen === 1) {
                const before2 = state.sliceDoc(Math.max(0, range.from - 2), range.from - 1);
                const after2 = state.sliceDoc(range.from + 1, Math.min(state.doc.length, range.from + 2));
                if (before2 === marker || after2 === marker) {
                    isWrapped2 = false;
                }
            }

            if (isWrapped2) {
                return {
                    changes: [
                        { from: range.from - mlen, to: range.from, insert: '' },
                        { from: range.from, to: range.from + mlen, insert: '' }
                    ],
                    range: _ES.cursor(range.from - mlen)
                };
            }

            return {
                changes: { from: range.from, insert: marker + marker },
                range: _ES.cursor(range.from + mlen)
            };
        });

        editorView.dispatch({
            changes: spec.changes,
            selection: spec.selection,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
    }

    function toggleTaskListFormat(editorView) {
        if (!editorView || !_IH) return;
        const state = editorView.state;

        const ranges = state.selection.ranges;
        let selFrom = ranges[0].from;
        let selTo = ranges[0].to;
        for (let i = 1; i < ranges.length; i++) {
            if (ranges[i].from < selFrom) selFrom = ranges[i].from;
            if (ranges[i].to > selTo) selTo = ranges[i].to;
        }

        const startLine = state.doc.lineAt(selFrom).number;
        const endLine = state.doc.lineAt(selTo).number;

        const taskRe = /^(\s*)([-*+]|\d+\.)\s+\[[ xX]\]\s+/;

        let anyLine = false;
        let allMatch = true;
        for (let ln = startLine; ln <= endLine; ln++) {
            const line = state.doc.line(ln);
            if (!line.text.trim()) continue;
            anyLine = true;
            if (!taskRe.test(line.text)) {
                allMatch = false;
                break;
            }
        }
        if (!anyLine) return;

        const changes = [];
        for (let ln = startLine; ln <= endLine; ln++) {
            const line = state.doc.line(ln);
            const text = line.text;
            if (!text.trim()) continue;

            const indentMatch = /^(\s*)/.exec(text);
            const indent = indentMatch ? indentMatch[1] : '';
            let rest = text.slice(indent.length);

            let newText;
            if (allMatch) {
                const m = taskRe.exec(text);
                const content = text.slice(m[0].length);
                newText = indent + content;
            } else {
                rest = rest.replace(/^([-*+]|\d+\.)\s+\[[ xX]\]\s+/, '');
                rest = rest.replace(/^([-*+]|\d+\.)\s+/, '');
                newText = indent + '- [ ] ' + rest;
            }

            if (newText !== text) {
                changes.push({ from: line.from, to: line.to, insert: newText });
            }
        }

        if (changes.length === 0) return;

        editorView.dispatch({
            changes,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
        forceRefreshPreview();
        setStatusHint(allMatch ? '已取消任务列表' : '已添加任务列表');
    }

    function toggleList(editorView, type) {
        if (!editorView || !_IH) return;
        const state = editorView.state;

        const ranges = state.selection.ranges;
        let selFrom = ranges[0].from;
        let selTo = ranges[0].to;
        for (let i = 1; i < ranges.length; i++) {
            if (ranges[i].from < selFrom) selFrom = ranges[i].from;
            if (ranges[i].to > selTo) selTo = ranges[i].to;
        }

        const startLine = state.doc.lineAt(selFrom).number;
        const endLine = state.doc.lineAt(selTo).number;

        let matcher, prefixFn;

        if (type === 'ul') {
            matcher = /^(\s*)[-*+]\s+(?!\[[ xX]\])/;
            prefixFn = () => '- ';
        } else if (type === 'ol') {
            matcher = /^(\s*)\d+\.\s+/;
            prefixFn = (idx) => (idx + 1) + '. ';
        } else if (type === 'quote') {
            matcher = /^(\s*)>\s?/;
            prefixFn = () => '> ';
        } else {
            return;
        }

        let allMatch = true;
        let anyLine = false;
        for (let ln = startLine; ln <= endLine; ln++) {
            const line = state.doc.line(ln);
            if (!line.text.trim()) continue;
            anyLine = true;
            if (!matcher.test(line.text)) {
                allMatch = false;
                break;
            }
        }
        if (!anyLine) return;

        const changes = [];
        let orderedIdx = 0;

        for (let ln = startLine; ln <= endLine; ln++) {
            const line = state.doc.line(ln);
            const text = line.text;
            if (!text.trim()) continue;

            const m = matcher.exec(text);
            const indent = m ? m[1] : (/^(\s*)/.exec(text)[1]);
            const content = m ? text.slice(m[0].length) : text.slice(indent.length);

            let newText;
            if (allMatch) {
                newText = indent + content;
            } else {
                const prefix = prefixFn(orderedIdx);
                if (type === 'ol') orderedIdx++;
                newText = indent + prefix + content;
            }
            if (newText !== text) {
                changes.push({ from: line.from, to: line.to, insert: newText });
            }
        }

        if (changes.length === 0) return;

        editorView.dispatch({
            changes,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
        forceRefreshPreview();
    }

    function applyHeading(editorView, level) {
        if (!editorView || !_ES || !_IH) return;
        const { state } = editorView;

        const spec = state.changeByRange(range => {
            const line = state.doc.lineAt(range.head);
            const text = line.text;
            const m = /^(#{1,6})\s+/.exec(text);

            let newText, offset;
            if (m) {
                if (m[1].length === level) {
                    newText = text.slice(m[0].length);
                    offset = -m[0].length;
                } else {
                    newText = '#'.repeat(level) + ' ' + text.slice(m[0].length);
                    offset = level + 1 - m[0].length;
                }
            } else {
                newText = '#'.repeat(level) + ' ' + text;
                offset = level + 1;
            }

            const newPos = Math.max(line.from, Math.min(line.from + newText.length, range.head + offset));
            return {
                changes: { from: line.from, to: line.to, insert: newText },
                range: _ES.cursor(newPos)
            };
        });

        editorView.dispatch({
            changes: spec.changes,
            selection: spec.selection,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
    }

    function insertCodeBlock(editorView) {
        if (!editorView || !_ES || !_IH) return;
        const { state } = editorView;

        const spec = state.changeByRange(range => {
            if (!range.empty) {
                const sel = state.sliceDoc(range.from, range.to);
                const insert = '```\n' + sel + '\n```';
                return {
                    changes: { from: range.from, to: range.to, insert },
                    range: _ES.range(range.from + 4, range.from + 4 + sel.length)
                };
            }
            const insert = '```\n\n```';
            return {
                changes: { from: range.from, insert },
                range: _ES.cursor(range.from + 4)
            };
        });

        editorView.dispatch({
            changes: spec.changes,
            selection: spec.selection,
            annotations: [_IH.of('full')]
        });
        editorView.focus();
    }

    // ============================================================
    //  通用工具
    // ============================================================
    function isBlockFormat(fmt) {
        if (!fmt || !fmt.block) return false;
        return fmt.block.heading > 0 || fmt.block.quote ||
               fmt.block.unorderedList || fmt.block.orderedList ||
               fmt.block.taskList;
    }
    function isInlineFormat(fmt) {
        if (!fmt || !fmt.inline) return false;
        return fmt.inline.bold || fmt.inline.italic ||
               fmt.inline.underline ||
               fmt.inline.strike || fmt.inline.code ||
               fmt.inline.codeBlock;
    }

    function stripBlockPrefixKeepIndent(text) {
        let s = text;
        s = s.replace(/^\s*<\/?details\b[^>]*>\s*$/i, '');
        s = s.replace(/^\s*<\/?summary\b[^>]*>\s*$/i, '');
        s = s.replace(/^\s+/, '');
        s = s.replace(/^(#{1,6})\s+/, '');
        s = s.replace(/^(\s*)>\s?/, '$1');
        s = s.replace(/^(\s*)[-*+]\s+\[[ xX]\]\s+/, '$1');
        s = s.replace(/^(\s*)[-*+]\s+/, '$1');
        s = s.replace(/^(\s*)\d+\.\s+/, '$1');
        s = s.replace(/^\s*```\s*\w*\s*$/i, '');
        s = s.replace(/^\s*~~~\s*\w*\s*$/i, '');
        return s;
    }

    function stripInlineMarkers(text) {
        let s = String(text);
        for (let i = 0; i < 6; i++) {
            const before = s;
            s = s.replace(/\*\*(.+?)\*\*/g, '$1');
            s = s.replace(/__(.+?)__/g, '$1');
            s = s.replace(/~~(.+?)~~/g, '$1');
            s = s.replace(/`([^`]+)`/g, '$1');
            s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
            s = s.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, '$1$2');
            s = s.replace(/(^|[^_])_([^_\n]+?)_(?!_)/g, '$1$2');
            s = s.replace(/<ins>([\s\S]*?)<\/ins>/g, '$1');
            s = s.replace(/<u>([\s\S]*?)<\/u>/g, '$1');
            if (s === before) break;
        }
        return s;
    }

    function blockPrefixFor(fmt) {
        if (!fmt || !fmt.block) return '';
        if (fmt.block.heading > 0) return '#'.repeat(fmt.block.heading) + ' ';
        if (fmt.block.quote) return '> ';
        if (fmt.block.taskList) return '- [ ] ';
        if (fmt.block.unorderedList) return '- ';
        if (fmt.block.orderedList) return '1. ';
        return '';
    }

    // ============================================================
    //  格式刷
    // ============================================================
    function handlePainterClick() {
        restoreSavedSelection();

        if (view && !_painter.active) {
            const sel = view.state.selection.main;
            if (!sel.empty) {
                const selText = view.state.sliceDoc(sel.from, sel.to);
                if (/\[\^[^\]\s]+\](?!:)/.test(selText)) {
                    const removed = removeFootnotesInSelection(view, sel.from, sel.to);
                    if (removed) {
                        refreshToolbarState();
                        forceRefreshPreview();
                        setStatusHint('格式刷：已删除脚注');
                        return;
                    }
                }
            }
        }

        if (_painterClickTimer) {
            clearTimeout(_painterClickTimer);
            _painterClickTimer = null;
            if (_painter.active && _painter.continuous) {
                exitFormatPainter();
            } else {
                enterFormatPainter(true);
            }
            return;
        }
        _painterClickTimer = setTimeout(() => {
            _painterClickTimer = null;
            if (_painter.active) {
                exitFormatPainter();
            } else {
                enterFormatPainter(false);
            }
        }, 220);
    }

    function enterFormatPainter(continuous) {
        if (!view) return;
        const fmt = captureFormat(view);
        if (!fmt) { setStatusHint('格式刷：请先在带格式的文本上放置光标'); return; }
        _painter.active = true;
        _painter.continuous = continuous;
        _painter.format = fmt;

        updatePainterButton();
        document.body.classList.add('format-painter-active');
        view.focus();
    }

    function exitFormatPainter() {
        _painter.active = false;
        _painter.continuous = false;
        _painter.format = null;
        updatePainterButton();
        document.body.classList.remove('format-painter-active');
    }

    function updatePainterButton() {
        const btn = document.querySelector('.tb-btn[data-tool="painter"]');
        if (!btn) return;
        btn.classList.toggle('active', _painter.active);
        btn.classList.toggle('continuous', _painter.active && _painter.continuous);
    }

    function captureFormat(editorView) {
        const state = editorView.state;
        const pos = state.selection.main.head;
        const line = state.doc.lineAt(pos);
        const text = line.text;

        const headingMatch = /^(#{1,6})\s+/.exec(text);
        const heading = headingMatch ? headingMatch[1].length : 0;
        const quote = /^\s*>\s?/.test(text);
        const taskList = /^\s*[-*+]\s+\[[ xX]\]\s/.test(text);
        const unorderedList = /^\s*[-*+]\s+/.test(text) && !taskList;
        const orderedList = /^\s*\d+\.\s+/.test(text);

        const inline = {
            bold: false, italic: false, underline: false,
            strike: false, code: false, link: false, codeBlock: false
        };

        try {
            const before = state.doc.sliceString(0, pos);
            const fences = before.match(/^(?:```|~~~)/gm);
            if (fences && fences.length % 2 === 1) inline.codeBlock = true;
        } catch (e) { /* ignore */ }

        if (_ST && !inline.codeBlock) {
            try {
                const tree = _ST(state);
                let node = tree.resolveInner(pos, 1);
                while (node) {
                    const name = node.name;
                    if (name === 'StrongEmphasis') inline.bold = true;
                    else if (name === 'Emphasis') inline.italic = true;
                    else if (name === 'Strikethrough') inline.strike = true;
                    else if (name === 'InlineCode') inline.code = true;
                    else if (name === 'Link') inline.link = true;
                    node = node.parent;
                }
            } catch (e) { /* ignore */ }
        }

        if (!inline.codeBlock && !inline.code) {
            if (detectTripleWrapAt(state, pos)) {
                inline.bold = true;
                inline.italic = true;
            }
        }

        if (!inline.codeBlock && !inline.code) {
            if (detectUnderlineAt(state, pos)) {
                inline.underline = true;
            }
        }

        // ★ 新增：删除线文本兜底
        if (!inline.codeBlock && !inline.code && !inline.strike) {
            const sel = state.selection.main;
            if (detectStrikethroughAt(state, pos, sel.from, sel.to)) {
                inline.strike = true;
            }
        }

        return {
            block: { heading, quote, unorderedList, orderedList, taskList },
            inline,
        };
    }

    function applyBlockFormatToLine(editorView, pos, fmt) {
        if (!editorView || !_IH) return false;
        const state = editorView.state;
        const line = state.doc.lineAt(pos);
        const text = line.text;
        const indentMatch = /^(\s*)/.exec(text);
        const indent = indentMatch ? indentMatch[1] : '';
        const content = text.slice(indent.length);
        const stripped = stripBlockPrefixKeepIndent(content);
        const prefix = blockPrefixFor(fmt);
        if (!prefix) return false;

        const newText = indent + prefix + stripped;
        if (newText === text) return false;

        editorView.dispatch({
            changes: { from: line.from, to: line.to, insert: newText },
            annotations: [_IH.of('full')],
        });
        return true;
    }

    function applyBlockFormatToLines(editorView, from, to, fmt) {
        if (!editorView || !_IH) return false;
        const state = editorView.state;
        const startLine = state.doc.lineAt(from).number;
        const endLine = state.doc.lineAt(to).number;
        const prefix = blockPrefixFor(fmt);
        if (!prefix) return false;

        const changes = [];
        for (let ln = startLine; ln <= endLine; ln++) {
            const line = state.doc.line(ln);
            const text = line.text;
            if (!text.trim()) continue;
            const indentMatch = /^(\s*)/.exec(text);
            const indent = indentMatch ? indentMatch[1] : '';
            const content = text.slice(indent.length);
            const stripped = stripBlockPrefixKeepIndent(content);
            const newText = indent + prefix + stripped;
            if (newText !== text) {
                changes.push({ from: line.from, to: line.to, insert: newText });
            }
        }
        if (changes.length === 0) return false;

        editorView.dispatch({ changes, annotations: [_IH.of('full')] });
        return true;
    }

    function applyInlineFormatToRange(editorView, from, to, fmt) {
        if (!editorView || !_IH) return false;
        const state = editorView.state;

        let expandFrom = from;
        let expandTo = to;

        if (_ST) {
            try {
                const tree = _ST(state);
                let node = tree.resolveInner(from, 1);
                while (node) {
                    const name = node.name;
                    if (name === 'StrongEmphasis' || name === 'Emphasis' ||
                        name === 'Strikethrough' || name === 'InlineCode') {
                        if (node.from <= from && node.to >= to) {
                            expandFrom = node.from;
                            expandTo = node.to;
                            break;
                        }
                    }
                    node = node.parent;
                }
            } catch (e) { /* ignore */ }
        }

        const selText = state.sliceDoc(from, to);
        const stripped = stripInlineMarkers(selText);
        const inl = fmt.inline;

        let result = stripped;
        if (inl.codeBlock) {
            result = '```\n' + result + '\n```';
        } else if (inl.code) {
            result = '`' + result + '`';
        } else {
            if (inl.italic) result = '*' + result + '*';
            if (inl.bold) result = '**' + result + '**';
            if (inl.strike) result = '~~' + result + '~~';
            if (inl.underline) result = '<ins>' + result + '</ins>';
        }
        if (result === state.sliceDoc(expandFrom, expandTo)) return false;

        editorView.dispatch({
            changes: { from: expandFrom, to: expandTo, insert: result },
            annotations: [_IH.of('full')],
        });
        return true;
    }

    function isSelectionCoveringWholeLine(state, from, to) {
        const startLine = state.doc.lineAt(from).number;
        const endLine = state.doc.lineAt(to).number;
        if (startLine !== endLine) return false;
        const line = state.doc.line(startLine);
        const selText = state.sliceDoc(from, to).trim();
        const lineText = line.text.trim();
        if (!selText) return false;
        if (selText === lineText) return true;
        if (stripBlockPrefixKeepIndent(lineText) === selText) return true;
        return false;
    }

    function bindEditorForPainter() {
        if (!view) return;
        view.dom.addEventListener('mouseup', () => {
            if (!_painter.active || !_painter.format) return;
            if (_painter.applying) return;

            _painter.applying = true;
            setTimeout(() => {
                try {
                    if (!_painter.active || !_painter.format) return;
                    const state = view.state;
                    const range = state.selection.main;
                    const fmt = _painter.format;
                    const blockFmt = isBlockFormat(fmt);
                    const inlineFmt = isInlineFormat(fmt);

                    if (!range.empty) {
                        const selText = state.sliceDoc(range.from, range.to);
                        if (/\[\^[^\]\s]+\](?!:)/.test(selText)) {
                            const removed = removeFootnotesInSelection(
                                view, range.from, range.to);
                            if (removed) {
                                if (!_painter.continuous) {
                                    exitFormatPainter();
                                }
                                refreshToolbarState();
                                forceRefreshPreview();
                                setStatusHint('格式刷：已删除脚注引用');
                                return;
                            }
                        }
                    }

                    let applied = false;

                    if (range.empty) {
                        if (blockFmt) {
                            applied = applyBlockFormatToLine(view, range.head, fmt);
                        }
                    } else {
                        const startLine = state.doc.lineAt(range.from).number;
                        const endLine = state.doc.lineAt(range.to).number;
                        const multiline = (startLine !== endLine);
                        const coversWhole = isSelectionCoveringWholeLine(state, range.from, range.to);

                        if (inlineFmt) {
                            applied = applyInlineFormatToRange(view, range.from, range.to, fmt);
                        } else if (blockFmt && (multiline || coversWhole)) {
                            applied = applyBlockFormatToLines(view, range.from, range.to, fmt);
                        } else if (blockFmt) {
                            applied = applyBlockFormatToLine(view, range.from, fmt);
                        }
                    }

                    if (applied) {
                        if (!_painter.continuous) {
                            exitFormatPainter();
                        }
                        refreshToolbarState();
                        forceRefreshPreview();
                    }
                } finally {
                    _painter.applying = false;
                }
            }, 0);
        });
    }

    // ============================================================
    //  橡皮擦
    // ============================================================
    function handleEraser() {
        if (!view || !_IH) return;
        restoreSavedSelection();

        let state = view.state;
        let ranges = state.selection.ranges;

        let selFrom = ranges[0].from;
        let selTo = ranges[0].to;
        for (let i = 1; i < ranges.length; i++) {
            if (ranges[i].from < selFrom) selFrom = ranges[i].from;
            if (ranges[i].to > selTo) selTo = ranges[i].to;
        }

        let footnoteRemoved = false;

        if (selFrom !== selTo) {
            const removed = removeFootnotesInSelection(view, selFrom, selTo);
            if (removed) {
                footnoteRemoved = true;
                state = view.state;
                ranges = state.selection.ranges;
                selFrom = ranges[0].from;
                selTo = ranges[0].to;
                for (let i = 1; i < ranges.length; i++) {
                    if (ranges[i].from < selFrom) selFrom = ranges[i].from;
                    if (ranges[i].to > selTo) selTo = ranges[i].to;
                }
            }
        }

        const changes = [];

        const startLine = state.doc.lineAt(selFrom).number;
        const endLine = state.doc.lineAt(selTo).number;
        for (let ln = startLine; ln <= endLine; ln++) {
            const line = state.doc.line(ln);
            const text = line.text;
            if (!text.trim()) continue;
            const stripped = stripBlockPrefixKeepIndent(text);
            if (stripped !== text) {
                changes.push({ from: line.from, to: line.to, insert: stripped });
            }
        }

        if (selFrom !== selTo) {
            const inlineChange = computeInlineEraseChange(state, selFrom, selTo);
            if (inlineChange) {
                changes.push(inlineChange);
            } else {
                const selText = state.sliceDoc(selFrom, selTo);
                const stripped = stripInlineMarkers(selText);
                if (stripped !== selText) {
                    changes.push({ from: selFrom, to: selTo, insert: stripped });
                }
            }
        }

        if (changes.length === 0) {
            if (footnoteRemoved) {
                refreshToolbarState();
                forceRefreshPreview();
                setStatusHint('橡皮擦：已删除脚注');
            } else {
                setStatusHint('橡皮擦：当前选区无格式可清除');
            }
            return;
        }

        changes.sort((a, b) => a.from - b.from);
        const merged = [];
        for (const c of changes) {
            if (merged.length === 0) { merged.push(c); continue; }
            const prev = merged[merged.length - 1];
            if (c.from >= prev.to) {
                merged.push(c);
            }
        }

        view.dispatch({
            changes: merged,
            annotations: [_IH.of('full')],
        });
        view.focus();
        setStatusHint(footnoteRemoved ? '橡皮擦：已删除脚注并清除格式' : '橡皮擦：已清除格式');
        refreshToolbarState();
        forceRefreshPreview();
    }

    function computeInlineEraseChange(state, from, to) {
        const fullMd = state.doc.toString();

        const defs = [
            { open: '**', close: '**' },
            { open: '__', close: '__' },
            { open: '~~', close: '~~' },
            { open: '`', close: '`' },
            { open: '*', close: '*' },
            { open: '_', close: '_' },
        ];

        for (const def of defs) {
            const openLen = def.open.length;
            const closeLen = def.close.length;

            let openStart = -1;
            for (let i = from - openLen; i >= 0; i--) {
                if (fullMd.slice(i, i + openLen) === def.open) {
                    if (openLen === 1) {
                        if (i > 0 && fullMd[i - 1] === def.open[0]) continue;
                        if (fullMd[i + openLen] === def.open[0]) continue;
                    }
                    openStart = i;
                    break;
                }
            }
            if (openStart < 0) continue;

            const contentStart = openStart + openLen;
            if (contentStart > from) continue;

            let closeStart = -1;
            for (let i = to; i <= fullMd.length - closeLen; i++) {
                if (fullMd.slice(i, i + closeLen) === def.close) {
                    if (closeLen === 1) {
                        if (i > 0 && fullMd[i - 1] === def.close[0]) continue;
                        if (fullMd[i + closeLen] === def.close[0]) continue;
                    }
                    closeStart = i;
                    break;
                }
            }
            if (closeStart < 0) continue;

            const contentEnd = closeStart;
            if (contentEnd < to) continue;

            const inner = fullMd.slice(contentStart, contentEnd);
            if (inner.includes('\n')) continue;

            if (from <= contentStart && to >= contentEnd) {
                return {
                    from: openStart,
                    to: contentEnd + closeLen,
                    insert: fullMd.slice(contentStart, contentEnd),
                };
            }

            const A = fullMd.slice(contentStart, from);
            const SEL = fullMd.slice(from, to);
            const B = fullMd.slice(to, contentEnd);

            const frontText = A ? (def.open + A + def.close) : '';
            const backText = B ? (def.open + B + def.close) : '';
            const newText = frontText + SEL + backText;

            return {
                from: openStart,
                to: contentEnd + closeLen,
                insert: newText,
            };
        }

        return null;
    }

    // ============================================================
    //  表格下拉
    // ============================================================
    function toggleTableMenu() {
        if (_tableOpen) { closeTableMenu(); return; }
        openTableMenu();
    }

    function openTableMenu() {
        if (!_tableBtn) return;
        if (!_tableMenu) buildTableMenu();

        const rect = _tableBtn.getBoundingClientRect();
        _tableMenu.style.left = rect.left + 'px';
        _tableMenu.style.top = (rect.bottom + 4) + 'px';
        _tableMenu.style.display = 'block';
        _tableOpen = true;

        const cells = _tableMenu.querySelectorAll('.tb-table-cell');
        cells.forEach(c => c.classList.remove('hl'));
        const label = _tableMenu.querySelector('.tb-table-label');
        if (label) label.textContent = T('table', '插入表格');
    }

    function closeTableMenu() {
        if (_tableMenu) _tableMenu.style.display = 'none';
        _tableOpen = false;
    }

    function buildTableMenu() {
        const MAX_R = 8, MAX_C = 8;
        const menu = document.createElement('div');
        menu.className = 'tb-table-menu';

        const grid = document.createElement('div');
        grid.className = 'tb-table-grid';
        grid.style.gridTemplateColumns = 'repeat(' + MAX_C + ', 16px)';

        const label = document.createElement('div');
        label.className = 'tb-table-label';
        label.textContent = T('table', '插入表格');

        const cells = [];
        for (let r = 0; r < MAX_R; r++) {
            for (let c = 0; c < MAX_C; c++) {
                const cell = document.createElement('div');
                cell.className = 'tb-table-cell';
                cell.dataset.r = String(r);
                cell.dataset.c = String(c);
                cell.addEventListener('mouseenter', () => {
                    const rr = r + 1, cc = c + 1;
                    cells.forEach(x => {
                        const xr = parseInt(x.dataset.r, 10);
                        const xc = parseInt(x.dataset.c, 10);
                        x.classList.toggle('hl', xr <= r && xc <= c);
                    });
                    label.textContent = rr + ' × ' + cc;
                });
                cell.addEventListener('click', (e) => {
                    e.stopPropagation();
                    insertTable(view, r + 1, c + 1);
                    closeTableMenu();
                });
                cells.push(cell);
                grid.appendChild(cell);
            }
        }

        menu.appendChild(grid);
        menu.appendChild(label);
        document.body.appendChild(menu);
        _tableMenu = menu;

        grid.addEventListener('mouseleave', () => {
            cells.forEach(c => c.classList.remove('hl'));
            label.textContent = T('table', '插入表格');
        });
    }

    function insertTable(editorView, rows, cols) {
        if (!editorView || !_IH) return;
        restoreSavedSelection();
        const state = editorView.state;
        const range = state.selection.main;

        const header = '| ' +
            Array.from({ length: cols }, (_, i) => 'Col' + (i + 1)).join(' | ') +
            ' |';
        const sep = '| ' + Array.from({ length: cols }, () => '---').join(' | ') + ' |';
        const bodyRows = [];
        for (let r = 0; r < rows - 1; r++) {
            bodyRows.push('| ' + Array.from({ length: cols }, () => '  ').join(' | ') + ' |');
        }
        const tableText = [header, sep, ...bodyRows].join('\n');

        const doc = state.doc.toString();
        let insert = tableText;
        const before = doc.slice(Math.max(0, range.from - 2), range.from);
        if (range.from > 0 && !/\n\s*$/.test(before)) insert = '\n\n' + insert;
        if (range.to < doc.length && !/^\s*\n/.test(doc.slice(range.to, range.to + 2))) {
            insert = insert + '\n\n';
        }

        editorView.dispatch({
            changes: { from: range.from, to: range.to, insert },
            selection: { anchor: range.from + insert.length },
            annotations: [_IH.of('full')],
        });
        editorView.focus();
    }

    // ============================================================
    //  折叠/展开
    // ============================================================
    function handleCollapse() {
        if (!view || !_IH) return;
        restoreSavedSelection();
        const state = view.state;
        const range = state.selection.main;

        if (range.empty) {
            setStatusHint('折叠：请先选中要折叠的多行文本');
            return;
        }

        const text = state.sliceDoc(range.from, range.to);
        const trimmed = text.trim();

        const foldRe = /^<details>\s*\n<summary>([\s\S]*?)<\/summary>\s*\n+([\s\S]*?)\n+<\/details>$/;
        const m = foldRe.exec(trimmed);

        if (m) {
            const summary = (m[1] || '').trim();
            const body = (m[2] || '').trim();
            const unfolded = summary ? (summary + '\n\n' + body).trim() : body;
            view.dispatch({
                changes: { from: range.from, to: range.to, insert: unfolded },
                annotations: [_IH.of('full')],
            });
            view.focus();
            forceRefreshPreview();
            return;
        }

        const lines = text.split('\n');
        let summary = '展开';
        let body = '';

        if (lines.length > 1) {
            summary = lines[0].replace(/^#+\s*/, '').trim() || '展开';
            body = lines.slice(1).join('\n').replace(/^\n+/, '').replace(/\n+$/, '');
        } else {
            summary = lines[0].replace(/^#+\s*/, '').trim() || '展开';
            body = '';
        }

        let folded = '<details>\n<summary>' + summary + '</summary>\n\n';
        if (body) folded += body + '\n\n';
        folded += '</details>';

        view.dispatch({
            changes: { from: range.from, to: range.to, insert: folded },
            annotations: [_IH.of('full')],
        });
        view.focus();
        forceRefreshPreview();
    }

    // ============================================================
    //  插入链接弹窗
    // ============================================================
    function openLinkDialog() {
        ensureLinkModalBuilt();
        if (!_linkModal) return;

        const urlInput = _linkModal.querySelector('.tb-link-url');
        const nameInput = _linkModal.querySelector('.tb-link-name');
        const iconCheck = _linkModal.querySelector('.tb-link-icon');

        const selText = getCurrentSelectionText();

        urlInput.value = '';
        nameInput.value = selText || '';
        iconCheck.checked = false;

        _linkModal.classList.remove('hidden');
        _linkModal.style.display = '';

        setTimeout(() => {
            urlInput.focus();
            if (selText) {
                urlInput.select();
            } else {
                nameInput.select();
            }
        }, 20);
    }

    function closeLinkDialog() {
        if (_linkModal) {
            _linkModal.classList.add('hidden');
            _linkModal.style.display = 'none';
        }
    }

    function escapeAttr(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;');
    }

    function escapeTextContent(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function ensureLinkModalBuilt() {
        if (_linkModalBuilt) return;
        _linkModalBuilt = true;

        if (!document.getElementById('tb-link-modal-style')) {
            const style = document.createElement('style');
            style.id = 'tb-link-modal-style';
            style.textContent = `
.tb-link-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; z-index: 20000; }
.tb-link-modal.hidden { display: none !important; }
.tb-link-modal-inner { background: #fff; border-radius: 8px; box-shadow: 0 12px 40px rgba(0,0,0,0.28); padding: 18px 20px; min-width: 420px; max-width: 90vw; font-family: "Microsoft YaHei", sans-serif; font-size: 13px; color: #24292f; }
.tb-link-modal-inner h3 { margin: 0 0 12px; font-size: 14px; font-weight: 600; }
.tb-link-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.tb-link-row > label { width: 60px; flex-shrink: 0; font-size: 13px; color: #57606a; }
.tb-link-row input[type="text"] { flex: 1; min-width: 0; padding: 5px 9px; border: 1px solid #d0d7de; border-radius: 5px; font-family: inherit; font-size: 13px; background: #fff; color: #24292f; outline: none; }
.tb-link-row input[type="text"]:focus { border-color: #0969da; box-shadow: 0 0 0 2px rgba(9,105,218,0.15); }
.tb-link-autofetch { padding: 5px 10px; border: 1px solid #d0d7de; border-radius: 5px; background: #f6f8fa; color: #24292f; cursor: pointer; font-size: 12px; font-family: inherit; flex-shrink: 0; white-space: nowrap; }
.tb-link-autofetch:hover { background: #eef4ff; border-color: #0969da; color: #0969da; }
.tb-link-autofetch:disabled { opacity: 0.5; cursor: default; }
.tb-link-checkbox-row > label { width: auto; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.tb-link-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 1px solid #e1e4e8; }
.tb-link-modal-actions button { padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; font-family: inherit; border: 1px solid #d0d7de; background: #f6f8fa; color: #24292f; }
.tb-link-modal-actions button:hover { background: #eef4ff; border-color: #0969da; color: #0969da; }
.tb-link-modal-actions .tb-link-confirm { background: #0969da; color: #fff; border-color: #0969da; }
.tb-link-modal-actions .tb-link-confirm:hover { background: #0759b8; }
.tb-link-modal-actions .tb-link-confirm:disabled { opacity: 0.6; cursor: default; }
body.dark .tb-link-modal-inner { background: #2a2a2a; color: #dcdcdc; }
body.dark .tb-link-modal-inner h3 { color: #e6edf3; }
body.dark .tb-link-row > label { color: #999; }
body.dark .tb-link-row input[type="text"] { background: #1e1e1e; border-color: #555; color: #dcdcdc; }
body.dark .tb-link-autofetch { background: #353535; border-color: #555; color: #dcdcdc; }
body.dark .tb-link-modal-actions { border-color: #444; }
body.dark .tb-link-modal-actions button { background: #353535; color: #dcdcdc; border-color: #555; }
body.dark .tb-link-modal-actions .tb-link-confirm { background: #1f6feb; color: #fff; border-color: #1f6feb; }
`;
            document.head.appendChild(style);
        }

        const modal = document.createElement('div');
        modal.className = 'tb-link-modal hidden';
        modal.id = 'tb-link-modal';

        modal.innerHTML = `
<div class="tb-link-modal-inner">
    <h3 data-i18n="insert_link">插入链接</h3>
    <div class="tb-link-row">
        <label data-i18n="link_url_label">网址</label>
        <input type="text" class="tb-link-url" placeholder="https://example.com" spellcheck="false">
    </div>
    <div class="tb-link-row">
        <label data-i18n="link_name_label">名称</label>
        <input type="text" class="tb-link-name" data-i18n-placeholder="link_text_placeholder" placeholder="显示名称" spellcheck="false">
        <button type="button" class="tb-link-autofetch" data-i18n="link_autofetch">自动获取</button>
    </div>
    <div class="tb-link-row tb-link-checkbox-row">
        <label>
            <input type="checkbox" class="tb-link-icon">
            <span data-i18n="link_show_icon">显示网站图标</span>
        </label>
    </div>
    <div class="tb-link-modal-actions">
        <button type="button" class="tb-link-cancel" data-i18n="cancel">取消</button>
        <button type="button" class="tb-link-confirm" data-i18n="link_insert">插入</button>
    </div>
</div>
`;

        document.body.appendChild(modal);
        _linkModal = modal;

        const urlInput = modal.querySelector('.tb-link-url');
        const nameInput = modal.querySelector('.tb-link-name');
        const iconCheck = modal.querySelector('.tb-link-icon');
        const fetchBtn = modal.querySelector('.tb-link-autofetch');
        const cancelBtn = modal.querySelector('.tb-link-cancel');
        const confirmBtn = modal.querySelector('.tb-link-confirm');

        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeLinkDialog();
        });

        cancelBtn.addEventListener('click', () => closeLinkDialog());

        fetchBtn.addEventListener('click', async () => {
            const url = urlInput.value.trim();
            if (!url) { setStatusHint('请输入网址'); return; }
            fetchBtn.disabled = true;
            const originalText = fetchBtn.textContent;
            fetchBtn.textContent = '...';
            try {
                if (window.pywebview && window.pywebview.api &&
                    window.pywebview.api.fetch_url_title) {
                    const r = await window.pywebview.api.fetch_url_title(url);
                    if (r && r.ok && r.title) {
                        nameInput.value = r.title;
                    }
                }
            } catch (e) { /* ignore */ } finally {
                fetchBtn.disabled = false;
                fetchBtn.textContent = originalText;
            }
        });

        confirmBtn.addEventListener('click', async () => {
            const url = urlInput.value.trim();
            const name = nameInput.value.trim() || url;
            const useIcon = iconCheck.checked;
            if (!url) return;

            let iconHtml = '';
            if (useIcon) {
                confirmBtn.disabled = true;
                try {
                    if (typeof externalHandlers.download_icon === 'function') {
                        let iconUrl = null;
                        if (window.pywebview && window.pywebview.api &&
                            window.pywebview.api.fetch_favicon_url) {
                            const r1 = await window.pywebview.api.fetch_favicon_url(url);
                            if (r1 && r1.ok && r1.url) iconUrl = r1.url;
                        }
                        if (iconUrl) {
                            const r2 = await externalHandlers.download_icon(iconUrl);
                            if (r2 && r2.ok && r2.md_path) {
                                iconHtml = '<img src="' + escapeAttr(r2.md_path) +
                                           '" alt="' + escapeAttr(name) +
                                           '" width="16" height="16">';
                            } else if (r2 && r2.conflict) {
                                iconHtml = '<img src="' + escapeAttr(iconUrl) +
                                           '" alt="' + escapeAttr(name) +
                                           '" width="16" height="16">';
                            }
                        }
                    }
                } catch (e) { /* ignore */ }
                confirmBtn.disabled = false;
            }

            insertLinkWithData(url, name, iconHtml);
            closeLinkDialog();
        });

        modal.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.tagName === 'INPUT' &&
                e.target.type !== 'checkbox') {
                e.preventDefault();
                confirmBtn.click();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                closeLinkDialog();
            }
        });

        if (window.I18N && window.I18N.applyToDOM) {
            window.I18N.applyToDOM(modal);
        }
    }

    function insertLinkWithData(url, name, iconHtml) {
        if (!view || !_IH) return;
        restoreSavedSelection();

        let normalizedUrl = url;
        if (!/^[a-z]+:\/\//i.test(normalizedUrl) && !/^mailto:/i.test(normalizedUrl)) {
            normalizedUrl = 'https://' + normalizedUrl;
        }

        const safeUrl = escapeAttr(normalizedUrl);
        const safeName = escapeTextContent(name);

        let linkMd;
        if (iconHtml) {
            linkMd = '<a href="' + safeUrl + '">' + iconHtml + safeName + '</a>';
        } else {
            linkMd = '<a href="' + safeUrl + '">' + safeName + '</a>';
        }

        const state = view.state;
        const range = state.selection.main;

        if (!range.empty) {
            view.dispatch({
                changes: { from: range.from, to: range.to, insert: linkMd },
                selection: { anchor: range.from + linkMd.length },
                annotations: [_IH.of('full')],
            });
        } else {
            view.dispatch({
                changes: { from: range.from, insert: linkMd },
                selection: { anchor: range.from + linkMd.length },
                annotations: [_IH.of('full')],
            });
        }
        view.focus();
        forceRefreshPreview();
    }

    // ============================================================
    //  工具栏自适应
    // ============================================================
    function setupOverflow() {
        const el = document.getElementById('toolbar');
        if (!el) return;

        _allButtons = Array.from(el.querySelectorAll('.tb-btn, .tb-sep, .tb-h-wrap'))
            .filter(x => x !== _overflowBtn);

        _overflowMenu = document.createElement('div');
        _overflowMenu.className = 'tb-overflow-menu';
        _overflowMenu.style.display = 'none';
        document.body.appendChild(_overflowMenu);

        _overflowBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            toggleOverflowMenu();
        });

        if (window.ResizeObserver) {
            _resizeObserver = new ResizeObserver(() => layoutToolbar());
            _resizeObserver.observe(el);
        }
        window.addEventListener('resize', layoutToolbar);

        setTimeout(layoutToolbar, 0);
    }

    function layoutToolbar() {
        const el = document.getElementById('toolbar');
        if (!el || !_overflowBtn) return;

        const totalW = el.clientWidth - 16;
        const overflowW = 32;

        _allButtons.forEach(b => { b.style.display = ''; });
        _overflowBtn.style.display = 'none';
        _overflowMenu.style.display = 'none';
        _overflowOpen = false;

        const widths = [];
        let totalUsed = 0;
        for (let i = 0; i < _allButtons.length; i++) {
            const b = _allButtons[i];
            const w = b.offsetWidth + 2;
            widths.push(w);
            totalUsed += w;
        }

        if (totalUsed <= totalW) return;

        const avail = totalW - overflowW;
        let sum = 0;
        let fromIdx = _allButtons.length;
        for (let i = 0; i < _allButtons.length; i++) {
            if (sum + widths[i] > avail) {
                fromIdx = i;
                break;
            }
            sum += widths[i];
        }

        for (let i = 0; i < _allButtons.length; i++) {
            _allButtons[i].style.display = (i < fromIdx) ? '' : 'none';
        }
        _overflowBtn.style.display = '';

        rebuildOverflowMenu(fromIdx);
    }

    function rebuildOverflowMenu(fromIdx) {
        if (!_overflowMenu) return;
        _overflowMenu.innerHTML = '';

        if (fromIdx >= _allButtons.length) return;

        for (let i = fromIdx; i < _allButtons.length; i++) {
            const b = _allButtons[i];
            if (b.classList.contains('tb-sep')) continue;

            if (b.classList.contains('tb-h-wrap')) {
                const item = document.createElement('div');
                item.className = 'tb-overflow-item';
                item.textContent = T('heading', '标题') + ' H1~H6';
                item.addEventListener('click', (e) => {
                    e.stopPropagation();
                    closeOverflowMenu();
                    openDropdown();
                });
                _overflowMenu.appendChild(item);
                continue;
            }

            const key = b.getAttribute('data-i18n-key');
            const label = key
                ? (T(key, b.getAttribute('data-tooltip')) + (b.getAttribute('data-i18n-suffix') || ''))
                : (b.getAttribute('data-tooltip') ||
                   b.dataset.fmt || b.dataset.action || b.dataset.tool || '');
            const iconSvg = b.querySelector('svg');
            const item = document.createElement('div');
            item.className = 'tb-overflow-item';
            if (iconSvg) {
                const wrap = document.createElement('span');
                wrap.className = 'tb-overflow-icon';
                wrap.innerHTML = iconSvg.outerHTML;
                item.appendChild(wrap);
            }
            const txt = document.createElement('span');
            txt.textContent = label;
            item.appendChild(txt);

            item.addEventListener('click', (e) => {
                e.stopPropagation();
                closeOverflowMenu();
                try { b.click(); } catch (err) { /* ignore */ }
            });
            _overflowMenu.appendChild(item);
        }
    }

    function toggleOverflowMenu() {
        if (_overflowOpen) closeOverflowMenu();
        else openOverflowMenu();
    }

    function openOverflowMenu() {
        if (!_overflowBtn || !_overflowMenu) return;
        const rect = _overflowBtn.getBoundingClientRect();
        _overflowMenu.style.left = Math.max(6, rect.right - 200) + 'px';
        _overflowMenu.style.top = (rect.bottom + 4) + 'px';
        _overflowMenu.style.display = 'block';
        _overflowOpen = true;
    }

    function closeOverflowMenu() {
        if (_overflowMenu) _overflowMenu.style.display = 'none';
        _overflowOpen = false;
    }

    // ============================================================
    //  i18n 刷新
    // ============================================================
    function refreshI18n() {
        const el = document.getElementById('toolbar');
        if (!el) return;

        el.querySelectorAll('.tb-btn[data-i18n-key]').forEach(btn => {
            const key = btn.getAttribute('data-i18n-key');
            const suffix = btn.getAttribute('data-i18n-suffix') || '';
            if (key) {
                btn.setAttribute('data-tooltip', T(key) + suffix);
            }
        });

        const hMain = el.querySelector('.tb-h-btn-main');
        const hCaret = el.querySelector('.tb-h-btn-caret');
        const hLabel = T('heading', '标题');
        if (hMain) hMain.setAttribute('data-tooltip', hLabel + '（H1~H6）');
        if (hCaret) hCaret.setAttribute('data-tooltip', hLabel + ' H1~H6');

        hideTooltip();

        if (_tableMenu) {
            const label = _tableMenu.querySelector('.tb-table-label');
            if (label) label.textContent = T('table', '插入表格');
        }

        if (_linkModal && window.I18N && window.I18N.applyToDOM) {
            window.I18N.applyToDOM(_linkModal);
        }

        if (_overflowOpen) {
            layoutToolbar();
            if (_overflowOpen) openOverflowMenu();
        }
    }

    // ============================================================
    //  模式按钮状态
    // ============================================================
    function setModeButtonState(mode) {
        document.querySelectorAll('.tb-btn[data-mode]').forEach(b => {
            b.classList.toggle('active', b.dataset.mode === mode);
        });
    }

    // ============================================================
    //  导出
    // ============================================================
    window.Toolbar = {
        init: initToolbar,
        refresh: refreshToolbarState,
        setModeButtonState: setModeButtonState,
        refreshThemeIcon: refreshThemeIcon,
        relayout: layoutToolbar,
        isPainterActive: () => _painter.active,
        refreshI18n: refreshI18n,
        insertFootnote: insertFootnote,
    };
})();