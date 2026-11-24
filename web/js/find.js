// MarkEase 查找与替换（v2.1.6：预览高亮 / 分屏同步 / 预览替换 / 模糊搜索）
(function () {
    'use strict';

    let view = null;

    let _matches = [];
    let _currentIdx = -1;

    let _bar = null;
    let _input = null;
    let _replaceInput = null;
    let _countEl = null;
    let _caseCheckbox = null;
    let _prevBtn = null;
    let _nextBtn = null;
    let _closeBtn = null;
    let _replaceOneBtn = null;
    let _replaceAllBtn = null;
    let _toastEl = null;
    let _toastTimer = null;

    // ★ v2.1.6：预览查找 / 模式感知
    let _returnFocusEl = null;
    let _returnFocusPanel = 'editor';
    let _unsupportedToastShown = false;
    let _refreshTimer = null;
    let _modeTimer = null;

    // ★ 模糊搜索 / 精确-模糊分类
    let _fuzzyCheckbox = null;
    let _breakdownEl = null;
    let _hintEl = null;

    // ============================================================
    //  动态注入样式（不依赖 find.css 是否被正确引入）
    // ============================================================
    function injectStyles() {
        if (document.getElementById('markease-find-inline-style')) return;
        const style = document.createElement('style');
        style.id = 'markease-find-inline-style';
        style.textContent = `
/* ---- 查找栏 ---- */
#findbar {
    position: absolute;
    top: 76px;
    right: 24px;
    z-index: 900;
    background: #fff;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(140, 149, 159, 0.25);
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 460px;
}
#findbar.hidden { display: none !important; }

.find-row { display: flex; align-items: center; gap: 6px; }

#find-input,
#replace-input {
    flex: 1;
    min-width: 0;
    padding: 5px 9px;
    font-size: 13px;
    font-family: inherit;
    border: 1px solid #d0d7de;
    border-radius: 5px;
    background: #fff;
    color: #24292f;
    outline: none;
}
#find-input:focus,
#replace-input:focus {
    border-color: #0969da;
    box-shadow: 0 0 0 2px rgba(9, 105, 218, 0.15);
}

.find-count {
    font-size: 12px;
    color: #6e7781;
    min-width: 40px;
    text-align: center;
    font-variant-numeric: tabular-nums;
    user-select: none;
}
.find-count.fuzzy { color: #cf222e; font-weight: 600; }

.find-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 11px;
    line-height: 1.45;
    min-height: 0;
}
.find-breakdown {
    color: #6e7781;
    user-select: none;
}
.find-hint {
    color: #9a6700;
    user-select: none;
}
.find-hint:empty { display: none; }
.find-hint.warn { color: #9a6700; }
.find-hint.flash {
    animation: findHintFlash 0.9s ease-out;
}
@keyframes findHintFlash {
    0%, 25% { background: rgba(255, 152, 0, 0.22); }
    100% { background: transparent; }
}

.find-opt {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 4px 7px;
    border: 1px solid #d0d7de;
    border-radius: 5px;
    background: #f6f8fa;
    font-size: 12px;
    color: #24292f;
    cursor: pointer;
    user-select: none;
    flex-shrink: 0;
    line-height: 1;
}
.find-opt:hover { background: #eef4ff; border-color: #0969da; color: #0969da; }
.find-opt input[type="checkbox"] {
    width: 13px; height: 13px; margin: 0;
    accent-color: #0969da; cursor: pointer;
}
.find-opt:has(input:checked) {
    background: #cfe3ff;
    border-color: #0969da;
    color: #0969da;
}

.fb-btn {
    width: 26px; height: 26px; padding: 0;
    border: 1px solid #d0d7de;
    border-radius: 5px;
    background: #f6f8fa;
    color: #24292f;
    cursor: pointer;
    font-size: 11px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; user-select: none;
}
.fb-btn:hover { background: #eef4ff; border-color: #0969da; color: #0969da; }
.fb-btn:active { background: #cfe3ff; }
.fb-btn:disabled { opacity: 0.4; cursor: default; }

.fb-btn-text {
    padding: 5px 12px;
    border: 1px solid #d0d7de;
    border-radius: 5px;
    background: #f6f8fa;
    color: #24292f;
    cursor: pointer;
    font-size: 12px;
    font-family: inherit;
    flex-shrink: 0;
}
.fb-btn-text:hover { background: #eef4ff; border-color: #0969da; color: #0969da; }
.fb-btn-text:active { background: #cfe3ff; }
.fb-btn-text:disabled { opacity: 0.4; cursor: default; }

.find-toast {
    position: absolute;
    bottom: 100%;
    right: 0;
    margin-bottom: 8px;
    padding: 6px 14px;
    background: rgba(28, 32, 38, 0.94);
    color: #fff;
    font-size: 12px;
    border-radius: 4px;
    max-width: 460px;
    white-space: normal;
    line-height: 1.5;
    text-align: left;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.28);
    pointer-events: none;
    opacity: 1;
    transition: opacity 0.3s ease;
    z-index: 1000;
}
.find-toast.hidden { display: none !important; }
.find-toast.fade { opacity: 0; }
.find-toast::after {
    content: '';
    position: absolute;
    top: 100%;
    right: 20px;
    border: 5px solid transparent;
    border-top-color: rgba(28, 32, 38, 0.94);
}

/* ---- 编辑器内匹配高亮 ---- */
.cm-search-match {
    background: rgba(255, 235, 59, 0.55);
    border-radius: 2px;
}
.cm-search-match-current {
    background: rgba(255, 152, 0, 0.75);
    outline: 1px solid rgba(200, 80, 0, 0.9);
    border-radius: 2px;
}

/* ---- 深色模式 ---- */
body.dark #findbar {
    background: #2a2a2a;
    border-color: #444;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.55);
}
body.dark #find-input,
body.dark #replace-input {
    background: #1e1e1e;
    color: #dcdcdc;
    border-color: #555;
}
body.dark #find-input:focus,
body.dark #replace-input:focus {
    border-color: #58a6ff;
    box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.2);
}
body.dark .find-count { color: #888; }
body.dark .find-count.fuzzy { color: #ff7b72; }
body.dark .find-breakdown { color: #888; }
body.dark .find-hint { color: #d29922; }
body.dark .find-hint.warn { color: #d29922; }

body.dark .find-opt {
    background: #353535;
    color: #dcdcdc;
    border-color: #555;
}
body.dark .find-opt:hover {
    background: #404040;
    color: #58a6ff;
    border-color: #58a6ff;
}
body.dark .find-opt:has(input:checked) {
    background: #1a3a5c;
    border-color: #58a6ff;
    color: #58a6ff;
}
body.dark .find-opt input[type="checkbox"] {
    accent-color: #58a6ff;
}

body.dark .fb-btn,
body.dark .fb-btn-text {
    background: #353535;
    color: #dcdcdc;
    border-color: #555;
}
body.dark .fb-btn:hover,
body.dark .fb-btn-text:hover {
    background: #404040;
    color: #58a6ff;
    border-color: #58a6ff;
}
body.dark .fb-btn:active,
body.dark .fb-btn-text:active { background: #1a3a5c; }

body.dark .find-toast { background: rgba(60, 65, 72, 0.96); }
body.dark .find-toast::after { border-top-color: rgba(60, 65, 72, 0.96); }

body.dark .cm-search-match {
    background: rgba(187, 128, 9, 0.4);
}
body.dark .cm-search-match-current {
    background: rgba(255, 165, 0, 0.55);
    outline: 1px solid rgba(255, 200, 120, 0.9);
}
`;
        document.head.appendChild(style);
    }

    // ============================================================
    //  模式 / 预览 / i18n 辅助
    // ============================================================
    function getMode() {
        const main = document.getElementById('main');
        return (main && main.getAttribute('data-mode')) || 'edit';
    }

    function T(key, fallback, vars) {
        let s = null;
        try {
            if (window.I18N && typeof window.I18N.t === 'function') {
                const v = window.I18N.t(key, vars);
                if (v && v !== key) s = v;
            }
        } catch (e) { /* ignore */ }

        if (s == null) s = (fallback != null) ? fallback : key;
        if (vars && typeof s === 'string') {
            Object.keys(vars).forEach(k => {
                s = s.split('{' + k + '}').join(String(vars[k]));
            });
        }
        return s;
    }

    function previewContainer() {
        const p = document.getElementById('preview');
        return p ? p.parentElement : null;
    }

    function commitPreviewEdit() {
        try {
            if (window.MKPreviewEdit &&
                typeof window.MKPreviewEdit.commit === 'function') {
                window.MKPreviewEdit.commit();
            }
        } catch (e) { /* ignore */ }
    }

    function notifyUnsupportedOnce() {
        if (_unsupportedToastShown) return;
        _unsupportedToastShown = true;
        showToast(T('find_preview_unsupported',
            '当前环境不支持预览高亮，请更新 WebView 运行时'));
    }

    function previewSearchSupported() {
        return !!(window.PreviewSearch &&
            typeof window.PreviewSearch.isSupported === 'function' &&
            window.PreviewSearch.isSupported());
    }

    function isFuzzyEnabled() {
        return !!(_fuzzyCheckbox && _fuzzyCheckbox.checked);
    }

    function countKinds() {
        let exact = 0;
        let fuzzy = 0;
        for (let i = 0; i < _matches.length; i++) {
            if (_matches[i].kind === 'fuzzy') fuzzy++;
            else exact++;
        }
        return { exact: exact, fuzzy: fuzzy };
    }

    function inspectDangerous(slice) {
        const reasons = [];
        const s = String(slice || '');
        if (/!\[[^\]]*\]\(/.test(s)) reasons.push('image');
        if (/\[[^\]]*\]\(/.test(s)) reasons.push('link');
        if (/<\/?[A-Za-z][^>]*>/.test(s)) reasons.push('html');
        if (/\$[^$]*\$|\\\(|\\\[/.test(s)) reasons.push('math');
        return reasons;
    }

    function sourceSnippet(slice, maxLen) {
        const s = String(slice == null ? '' : slice);
        const max = maxLen || 180;
        if (s.length <= max) return s;
        return s.slice(0, max) + '…';
    }

    function showFuzzyReplaceConfirm(match, replacement) {
        const sourceText = view ? view.state.doc.toString() : '';
        const slice = sourceText.slice(match.from, match.to);
        const snippet = sourceSnippet(slice);
        const reasons = inspectDangerous(slice);

        let msg = T('find_fuzzy_replace_message',
            '将替换源码片段：\n{source}\n\n替换为：\n{replacement}\n\n格式标记会一并替换。',
            { source: snippet, replacement: replacement });
        if (reasons.length > 0) {
            msg += '\n\n' + T('find_fuzzy_danger_warning',
                '警告：该片段包含链接地址、图片、HTML 标签或公式，替换会删除这些结构。');
        }

        if (!window.MKConfirm) return Promise.resolve(false);
        return window.MKConfirm(
            T('find_fuzzy_replace_title', '替换跨格式匹配'),
            msg,
            {
                okText: T('replace_btn', '替换'),
                cancelText: T('cancel', '取消')
            }
        );
    }

    function showPreviewFuzzyBlocked() {
        if (!window.MKConfirm) {
            showToast(T('find_fuzzy_need_checkbox',
                '跨格式匹配需要勾选「模糊」后才能替换'));
            return;
        }
        window.MKConfirm(
            T('find_preview_fuzzy_blocked_title', '无法在预览中替换'),
            T('find_preview_fuzzy_blocked_message',
                '这是跨格式的模糊匹配，当前未勾选「模糊」。请勾选「模糊」后替换，或切换到分屏手动修改。'),
            {
                okText: T('find_switch_to_split', '切换到分屏'),
                cancelText: T('cancel', '取消')
            }
        ).then((ok) => {
            if (ok && typeof window.MKSetMode === 'function') {
                window.MKSetMode('split');
            }
        });
    }

    function flashFuzzyHint() {
        if (!_hintEl) return;
        _hintEl.classList.remove('flash');
        void _hintEl.offsetWidth;
        _hintEl.classList.add('flash');
        setTimeout(() => {
            if (_hintEl) _hintEl.classList.remove('flash');
        }, 900);
    }

    function updateHint() {
        if (!_hintEl) return;
        const counts = countKinds();
        _hintEl.textContent = '';
        _hintEl.classList.remove('warn');
        if (_matches.length === 0) return;

        if (counts.fuzzy > 0 && !isFuzzyEnabled()) {
            _hintEl.textContent = T('find_fuzzy_hint',
                '检测到 {count} 处跨格式匹配；勾选「模糊」后可替换，或在编辑区手动修改。',
                { count: counts.fuzzy });
            _hintEl.classList.add('warn');
        } else if (counts.fuzzy > 0 && isFuzzyEnabled()) {
            _hintEl.textContent = T('find_fuzzy_replace_note',
                '模糊匹配替换时会连同格式标记一起替换。');
        }
    }

    function rememberFocusPanel() {
        const ae = document.activeElement;
        _returnFocusEl = ae;
        _returnFocusPanel = (ae && ae.closest &&
            ae.closest('#preview-container')) ? 'preview' : 'editor';
    }

    function isElementVisible(el) {
        if (!el || !el.isConnected) return false;
        try {
            const r = el.getBoundingClientRect();
            return !!(r.width || r.height);
        } catch (e) {
            return false;
        }
    }

    function restoreFocus() {
        let el = _returnFocusEl;
        _returnFocusEl = null;

        if (el === document.body || el === document.documentElement) el = null;

        if (el && el.isConnected && !el.closest('#findbar') &&
            isElementVisible(el) && typeof el.focus === 'function') {
            try {
                el.focus({ preventScroll: true });
                return;
            } catch (e) { /* fallback */ }
        }

        const mode = getMode();
        if (mode === 'preview' || _returnFocusPanel === 'preview') {
            const pc = previewContainer();
            if (pc && mode !== 'edit' && typeof pc.focus === 'function') {
                try {
                    pc.focus({ preventScroll: true });
                    return;
                } catch (e) { /* fallback */ }
            }
        }

        if (view) {
            try { view.focus(); } catch (e) { /* ignore */ }
        }
    }

    // 预览重渲染后，等 DOM/布局稳定再重新搜索并恢复高亮
    function refreshAfterRender() {
        if (!isOpen()) return;
        if (_refreshTimer) clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(() => {
            _refreshTimer = null;
            if (!isOpen()) return;
            runSearch(false);
        }, 30);
    }

    function onModeChanged(mode) {
        if (!isOpen()) return;
        if (_modeTimer) clearTimeout(_modeTimer);
        _modeTimer = setTimeout(() => {
            _modeTimer = null;
            if (!isOpen() || !_input.value) return;
            // ★ 模式切换会改变搜索面（编辑=源码 / 分屏+预览=渲染文字），必须重算
            runSearch(false);
        }, 100);
    }

    // ---------------- 初始化 ----------------
    function initFindBar(editorView) {
        view = editorView;

        const pc = previewContainer();
        if (pc) {
            if (!pc.hasAttribute('tabindex')) pc.setAttribute('tabindex', '-1');
            pc.style.outline = 'none';
        }

        injectStyles();   // ★ 关键：注入样式

        _bar = document.getElementById('findbar');
        _input = document.getElementById('find-input');
        _replaceInput = document.getElementById('replace-input');
        _countEl = document.getElementById('find-count');
        _caseCheckbox = document.getElementById('find-case');
        _prevBtn = document.getElementById('find-prev');
        _nextBtn = document.getElementById('find-next');
        _closeBtn = document.getElementById('find-close');
        _replaceOneBtn = document.getElementById('replace-one');
        _replaceAllBtn = document.getElementById('replace-all');
        _toastEl = document.getElementById('find-toast');
        _fuzzyCheckbox = document.getElementById('find-fuzzy');
        _breakdownEl = document.getElementById('find-breakdown');
        _hintEl = document.getElementById('find-hint');

        if (!_bar) {
            console.warn('[find] #findbar not found');
            return;
        }

        // 初始即隐藏
        _bar.classList.add('hidden');
        _bar.style.display = 'none';

        _input.addEventListener('input', () => runSearch(true));
        _input.addEventListener('keydown', onInputKeydown);
        _replaceInput.addEventListener('keydown', onInputKeydown);

        if (_caseCheckbox) {
            _caseCheckbox.addEventListener('change', () => {
                runSearch(true);
            });
        }
        if (_fuzzyCheckbox) {
            _fuzzyCheckbox.addEventListener('change', () => {
                runSearch(true);
            });
        }

        _nextBtn.addEventListener('click', () => findNext());
        _prevBtn.addEventListener('click', () => findPrev());
        _closeBtn.addEventListener('click', () => closeFindBar());
        _replaceOneBtn.addEventListener('click', () => replaceOne());
        _replaceAllBtn.addEventListener('click', () => replaceAll());
    }

    function onInputKeydown(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            e.stopPropagation();
            if (e.shiftKey) findPrev();
            else findNext();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            closeFindBar();
        }
    }

    // ---------------- 打开 / 关闭 ----------------
    function openFindBar(focusReplace) {
        if (!_bar) return;

        // ★ v2.1.6：预览编辑态先提交，保证搜索基于最新 Markdown
        rememberFocusPanel();
        commitPreviewEdit();

        _bar.classList.remove('hidden');
        _bar.style.display = 'flex';
        setTimeout(() => {
            if (focusReplace) {
                _replaceInput.focus();
                _replaceInput.select();
            } else {
                _input.focus();
                _input.select();
            }
            if (_input.value) runSearch(true);
        }, 10);
    }

    function closeFindBar() {
        if (!_bar) return;
        if (_refreshTimer) {
            clearTimeout(_refreshTimer);
            _refreshTimer = null;
        }
        if (_modeTimer) {
            clearTimeout(_modeTimer);
            _modeTimer = null;
        }
        _bar.classList.add('hidden');
        _bar.style.display = 'none';
        _matches = [];
        _currentIdx = -1;
        if (_countEl) _countEl.textContent = '0/0';
        if (window.SearchHighlight) window.SearchHighlight.clear();
        if (window.PreviewSearch) window.PreviewSearch.clear();
        restoreFocus();
    }

    function isOpen() {
        return _bar && !_bar.classList.contains('hidden');
    }

    // ---------------- 搜索核心 ----------------
    function runSearch(resetIndex, forcedIndex) {
        if (!view) return;
        const q = _input.value;
        if (!q) {
            _matches = [];
            _currentIdx = -1;
            updateCount();
            if (window.SearchHighlight) window.SearchHighlight.clear();
            if (window.PreviewSearch) window.PreviewSearch.clear();
            return;
        }

        const text = view.state.doc.toString();
        const exactMatches = [];
        const caseSensitive = _caseCheckbox && _caseCheckbox.checked;

        if (caseSensitive) {
            let from = 0;
            while (from <= text.length) {
                const idx = text.indexOf(q, from);
                if (idx < 0) break;
                exactMatches.push({ from: idx, to: idx + q.length, kind: 'exact' });
                from = idx + q.length;
                if (exactMatches.length > 10000) break;
            }
        } else {
            const lowerText = text.toLowerCase();
            const lowerQ = q.toLowerCase();
            let from = 0;
            while (from <= lowerText.length) {
                const idx = lowerText.indexOf(lowerQ, from);
                if (idx < 0) break;
                exactMatches.push({ from: idx, to: idx + q.length, kind: 'exact' });
                from = idx + q.length;
                if (exactMatches.length > 10000) break;
            }
        }

        if (window.PreviewSearch) {
            window.PreviewSearch.setSource(text);
        }

        const mode = getMode();
        const needFuzzy = isFuzzyEnabled() || mode !== 'edit';
        let fuzzyMatches = [];
        if (needFuzzy && window.PreviewSearch &&
            typeof window.PreviewSearch.findFuzzyMatches === 'function') {
            try {
                fuzzyMatches = window.PreviewSearch.findFuzzyMatches(
                    text, q, !!caseSensitive);
            } catch (e) {
                console.warn('[find] fuzzy search failed', e);
                fuzzyMatches = [];
            }
        }

        let matches = exactMatches.concat(fuzzyMatches);

        // 纯预览只保留“渲染后确实可见”的命中
        if (mode === 'preview' && window.PreviewSearch &&
            typeof window.PreviewSearch.isSourceSpanVisible === 'function') {
            matches = matches.filter((m) =>
                window.PreviewSearch.isSourceSpanVisible(m.from, m.to));
        }

        // 精确命中优先；同跨度的模糊项去重
        matches.sort((a, b) =>
            a.from - b.from || a.to - b.to ||
            (a.kind === 'exact' ? -1 : 1));
        const dedup = [];
        for (let i = 0; i < matches.length; i++) {
            const m = matches[i];
            const last = dedup[dedup.length - 1];
            if (last && last.from === m.from && last.to === m.to) {
                if (last.kind !== 'exact' && m.kind === 'exact') {
                    dedup[dedup.length - 1] = m;
                }
                continue;
            }
            dedup.push(m);
        }
        matches = dedup;

        _matches = matches;

        if (matches.length === 0) {
            _currentIdx = -1;
        } else if (typeof forcedIndex === 'number' && isFinite(forcedIndex)) {
            _currentIdx = Math.max(0, Math.min(forcedIndex, matches.length - 1));
        } else if (resetIndex || _currentIdx < 0 || _currentIdx >= matches.length) {
            if (getMode() === 'preview' && window.PreviewSearch &&
                typeof window.PreviewSearch.getStartIndex === 'function') {
                _currentIdx = window.PreviewSearch.getStartIndex(matches);
            } else {
                const cursor = view.state.selection.main.head;
                let best = 0;
                for (let i = 0; i < matches.length; i++) {
                    if (matches[i].from >= cursor) { best = i; break; }
                    best = i;
                }
                _currentIdx = best;
            }
        }

        updateCount();
        updateHighlight();
        if (_currentIdx >= 0) scrollToMatch(_currentIdx);
    }

    function updateCount() {
        if (!_countEl) return;

        const counts = countKinds();
        const current = (_currentIdx >= 0 && _currentIdx < _matches.length)
            ? _matches[_currentIdx] : null;

        if (_matches.length === 0) {
            _countEl.textContent = '0/0';
        } else {
            _countEl.textContent = (_currentIdx + 1) + '/' + _matches.length;
        }
        _countEl.classList.toggle('fuzzy',
            !!(current && current.kind === 'fuzzy'));

        if (_breakdownEl) {
            if (_matches.length === 0) {
                _breakdownEl.textContent = '';
            } else if (counts.fuzzy > 0) {
                _breakdownEl.textContent =
                    T('find_exact_count', '精确 {count}', { count: counts.exact }) +
                    ' · ' +
                    T('find_fuzzy_count', '模糊 {count}', { count: counts.fuzzy });
            } else {
                _breakdownEl.textContent =
                    T('find_exact_count', '精确 {count}', { count: counts.exact });
            }
        }

        updateHint();
    }

    function updateHighlight() {
        if (window.SearchHighlight) {
            window.SearchHighlight.update(_matches, _currentIdx);
        }

        const mode = getMode();
        if (window.PreviewSearch) {
            if (mode === 'edit') {
                window.PreviewSearch.clearHighlights();
            } else {
                window.PreviewSearch.update(_matches, _currentIdx);
                if (!previewSearchSupported()) notifyUnsupportedOnce();
            }
        }
    }

    function scrollToMatch(idx) {
        if (!view || idx < 0 || idx >= _matches.length) return;
        const m = _matches[idx];
        const mode = getMode();

        if (mode === 'preview') {
            view.dispatch({
                selection: { anchor: m.from, head: m.to },
                scrollIntoView: false
            });
            let r = null;
            if (window.PreviewSearch) {
                r = window.PreviewSearch.scrollToIndex(idx, {
                    align: 0.35,
                    flash: true
                });
            }
            if (r && r.visible === false && previewSearchSupported()) {
                showToast(T('find_preview_invisible', '该处在预览中不可见'));
            }
            return;
        }

        if (mode === 'split') {
            if (window.MKScrollSync && typeof window.MKScrollSync.lock === 'function') {
                window.MKScrollSync.lock('find', 600);
            }
            view.dispatch({
                selection: { anchor: m.from, head: m.to },
                scrollIntoView: true
            });
            // 等编辑器滚动与高亮绘制稳定后再定位预览，避免被滚动锚定/同步覆盖
            setTimeout(() => {
                if (window.PreviewSearch) {
                    window.PreviewSearch.scrollToIndex(idx, {
                        align: 0.35,
                        flash: true
                    });
                }
            }, 80);
            return;
        }

        view.dispatch({
            selection: { anchor: m.from, head: m.to },
            scrollIntoView: true
        });
    }

    // ---------------- 上一个 / 下一个 ----------------
    function findNext() {
        if (_matches.length === 0) {
            runSearch(true);
            if (_matches.length === 0) {
                showToast(T('find_no_match', '无匹配内容'));
                return;
            }
            return;
        }
        if (_currentIdx === _matches.length - 1) {
            showToast(T('find_last', '已经是最后一个'));
            return;
        }
        _currentIdx++;
        updateCount();
        updateHighlight();
        scrollToMatch(_currentIdx);
    }

    function findPrev() {
        if (_matches.length === 0) {
            runSearch(true);
            if (_matches.length === 0) {
                showToast(T('find_no_match', '无匹配内容'));
                return;
            }
            return;
        }
        if (_currentIdx === 0) {
            showToast(T('find_first', '已经是第一个'));
            return;
        }
        _currentIdx--;
        updateCount();
        updateHighlight();
        scrollToMatch(_currentIdx);
    }

    // ---------------- 替换 ----------------
    function performReplaceOne(m, replacement, mode) {
        const wasVisible = (mode === 'edit' || !window.PreviewSearch)
            ? true
            : window.PreviewSearch.isVisible(_currentIdx);
        const replacedFrom = m.from;
        const replacedIdx = _currentIdx;
        const isFuzzy = m.kind === 'fuzzy';

        view.dispatch({
            changes: { from: m.from, to: m.to, insert: replacement }
        });

        if (isFuzzy) {
            showToast(T('find_fuzzy_replace_done', '已替换 1 处模糊匹配'));
        } else if (mode !== 'edit') {
            showToast(wasVisible
                ? T('find_replaced_one', '已替换 1 处')
                : T('find_replaced_one_hidden',
                    '已替换 1 处（该处在预览中不可见）'));
        }

        setTimeout(() => {
            if (mode !== 'edit' && window.PreviewSearch &&
                typeof window.PreviewSearch.expandAtSource === 'function') {
                try { window.PreviewSearch.expandAtSource(replacedFrom); }
                catch (e) { /* ignore */ }
            }
            if (mode === 'preview') {
                runSearch(false, replacedIdx);
            } else {
                runSearch(true);
            }
        }, 0);
    }

    async function replaceOne() {
        const mode = getMode();
        commitPreviewEdit();

        if (!view || _matches.length === 0 || _currentIdx < 0) return;
        const replacement = _replaceInput.value;
        const m = _matches[_currentIdx];
        if (!m) return;

        if (m.kind === 'fuzzy') {
            if (!isFuzzyEnabled()) {
                if (mode === 'preview') {
                    showPreviewFuzzyBlocked();
                } else {
                    showToast(T('find_fuzzy_need_checkbox',
                        '跨格式匹配需要勾选「模糊」后才能替换'));
                    flashFuzzyHint();
                }
                return;
            }

            const ok = await showFuzzyReplaceConfirm(m, replacement);
            if (!ok) return;
            // 弹窗期间匹配集合可能被外部操作刷新
            if (_matches[_currentIdx] !== m) return;
            performReplaceOne(m, replacement, mode);
            return;
        }

        performReplaceOne(m, replacement, mode);
    }

    function showFuzzyReplaceAllConfirm(count, dangerousCount) {
        let msg = T('find_fuzzy_replace_all_message',
            '将替换 {count} 处模糊匹配，格式标记会一并替换。',
            { count: count });
        if (dangerousCount > 0) {
            msg += '\n\n' + T('find_fuzzy_danger_warning_all',
                '其中 {dangerous} 处包含链接地址、图片、HTML 标签或公式，替换会删除这些结构。',
                { dangerous: dangerousCount });
        }
        if (!window.MKConfirm) return Promise.resolve(false);
        return window.MKConfirm(
            T('find_fuzzy_replace_all_title', '替换全部跨格式匹配'),
            msg,
            {
                okText: T('replace_all', '全部替换'),
                cancelText: T('cancel', '取消')
            }
        );
    }

    function performReplaceAll(targets, replacement, mode, meta) {
        meta = meta || {};
        const count = targets.length;
        if (count === 0) {
            if (meta.skippedFuzzy) {
                showToast(T('find_fuzzy_need_checkbox',
                    '跨格式匹配需要勾选「模糊」后才能替换'));
                flashFuzzyHint();
            }
            return;
        }

        let hidden = 0;
        if (mode !== 'edit' && window.PreviewSearch &&
            typeof window.PreviewSearch.isVisible === 'function') {
            for (let i = 0; i < targets.length; i++) {
                const idx = _matches.indexOf(targets[i]);
                if (idx >= 0 && !window.PreviewSearch.isVisible(idx)) hidden++;
            }
        }

        const changes = targets.slice().reverse().map(m => ({
            from: m.from, to: m.to, insert: replacement
        }));

        view.dispatch({ changes });
        setTimeout(() => {
            if (mode === 'preview') {
                runSearch(false, 0);
            } else {
                runSearch(true);
            }

            let msg;
            if (meta.skippedFuzzy > 0) {
                msg = T('find_fuzzy_not_replaced',
                    '已替换 {exact} 处精确匹配；{fuzzy} 处模糊匹配未替换。',
                    { exact: count, fuzzy: meta.skippedFuzzy });
            } else if (meta.fuzzyCount > 0) {
                msg = T('find_fuzzy_replace_all_done',
                    '已替换 {count} 处（其中 {fuzzy} 处模糊匹配）。',
                    { count: count, fuzzy: meta.fuzzyCount });
            } else {
                msg = T('replaced_count', '已替换 {count} 处', { count: count });
            }

            if (hidden > 0) {
                msg += T('find_replaced_hidden_suffix',
                    '（其中 {hidden} 处在预览中不可见）', { hidden: hidden });
            }
            showToast(msg);
        }, 0);
    }

    async function replaceAll() {
        const mode = getMode();
        commitPreviewEdit();

        if (!view || _matches.length === 0) {
            showToast(T('find_no_match', '无匹配内容'));
            return;
        }
        const replacement = _replaceInput.value;
        const exactTargets = [];
        const fuzzyTargets = [];
        for (let i = 0; i < _matches.length; i++) {
            if (_matches[i].kind === 'fuzzy') fuzzyTargets.push(_matches[i]);
            else exactTargets.push(_matches[i]);
        }

        if (fuzzyTargets.length > 0 && !isFuzzyEnabled()) {
            if (exactTargets.length === 0) {
                if (mode === 'preview') {
                    showPreviewFuzzyBlocked();
                } else {
                    showToast(T('find_fuzzy_need_checkbox',
                        '跨格式匹配需要勾选「模糊」后才能替换'));
                    flashFuzzyHint();
                }
                return;
            }
            performReplaceAll(exactTargets, replacement, mode, {
                skippedFuzzy: fuzzyTargets.length
            });
            return;
        }

        if (fuzzyTargets.length > 0) {
            let dangerous = 0;
            const sourceText = view.state.doc.toString();
            for (let i = 0; i < fuzzyTargets.length; i++) {
                const f = fuzzyTargets[i];
                if (inspectDangerous(sourceText.slice(f.from, f.to)).length > 0) {
                    dangerous++;
                }
            }
            const ok = await showFuzzyReplaceAllConfirm(
                fuzzyTargets.length, dangerous);
            if (!ok) return;
        }

        performReplaceAll(_matches.slice(), replacement, mode, {
            fuzzyCount: fuzzyTargets.length
        });
    }

    // ---------------- 外部调用 ----------------
    function refresh() {
        if (!isOpen()) return;
        runSearch(false);
    }

    // ---------------- Toast 提示 ----------------
    function showToast(msg) {
        if (!_toastEl) return;
        _toastEl.textContent = msg;
        _toastEl.classList.remove('hidden', 'fade');
        _toastEl.style.display = 'block';
        if (_toastTimer) clearTimeout(_toastTimer);
        _toastTimer = setTimeout(() => {
            _toastEl.classList.add('fade');
            setTimeout(() => {
                _toastEl.classList.add('hidden');
                _toastEl.classList.remove('fade');
                _toastEl.style.display = 'none';
            }, 300);
        }, 1400);
    }

    // ---------------- 导出 ----------------
    window.FindBar = {
        init: initFindBar,
        open: openFindBar,
        close: closeFindBar,
        isOpen: isOpen,
        refresh: refresh,
        refreshAfterRender: refreshAfterRender,
        onModeChanged: onModeChanged,
    };
})();