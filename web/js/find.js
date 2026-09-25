// MarkEase 查找与替换（阶段 12 修订 4：内联样式兜底）
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
    min-width: 420px;
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
    white-space: nowrap;
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

    // ---------------- 初始化 ----------------
    function initFindBar(editorView) {
        view = editorView;

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
        _bar.classList.add('hidden');
        _bar.style.display = 'none';
        _matches = [];
        _currentIdx = -1;
        if (_countEl) _countEl.textContent = '0/0';
        if (window.SearchHighlight) window.SearchHighlight.clear();
        if (view) view.focus();
    }

    function isOpen() {
        return _bar && !_bar.classList.contains('hidden');
    }

    // ---------------- 搜索核心 ----------------
    function runSearch(resetIndex) {
        if (!view) return;
        const q = _input.value;
        if (!q) {
            _matches = [];
            _currentIdx = -1;
            if (_countEl) _countEl.textContent = '0/0';
            if (window.SearchHighlight) window.SearchHighlight.clear();
            return;
        }

        const text = view.state.doc.toString();
        const matches = [];
        const caseSensitive = _caseCheckbox && _caseCheckbox.checked;

        if (caseSensitive) {
            let from = 0;
            while (from <= text.length) {
                const idx = text.indexOf(q, from);
                if (idx < 0) break;
                matches.push({ from: idx, to: idx + q.length });
                from = idx + q.length;
                if (matches.length > 10000) break;
            }
        } else {
            const lowerText = text.toLowerCase();
            const lowerQ = q.toLowerCase();
            let from = 0;
            while (from <= lowerText.length) {
                const idx = lowerText.indexOf(lowerQ, from);
                if (idx < 0) break;
                matches.push({ from: idx, to: idx + q.length });
                from = idx + q.length;
                if (matches.length > 10000) break;
            }
        }

        _matches = matches;

        if (matches.length === 0) {
            _currentIdx = -1;
        } else if (resetIndex || _currentIdx < 0 || _currentIdx >= matches.length) {
            const cursor = view.state.selection.main.head;
            let best = 0;
            for (let i = 0; i < matches.length; i++) {
                if (matches[i].from >= cursor) { best = i; break; }
                best = i;
            }
            _currentIdx = best;
        }

        updateCount();
        updateHighlight();
        if (_currentIdx >= 0) scrollToMatch(_currentIdx);
    }

    function updateCount() {
        if (!_countEl) return;
        if (_matches.length === 0) {
            _countEl.textContent = '0/0';
        } else {
            _countEl.textContent = (_currentIdx + 1) + '/' + _matches.length;
        }
    }

    function updateHighlight() {
        if (window.SearchHighlight) {
            window.SearchHighlight.update(_matches, _currentIdx);
        }
    }

    function scrollToMatch(idx) {
        if (!view || idx < 0 || idx >= _matches.length) return;
        const m = _matches[idx];
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
                showToast('无匹配内容');
                return;
            }
            return;
        }
        if (_currentIdx === _matches.length - 1) {
            showToast('已经是最后一个');
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
                showToast('无匹配内容');
                return;
            }
            return;
        }
        if (_currentIdx === 0) {
            showToast('已经是第一个');
            return;
        }
        _currentIdx--;
        updateCount();
        updateHighlight();
        scrollToMatch(_currentIdx);
    }

    // ---------------- 替换 ----------------
    function replaceOne() {
        if (!view || _matches.length === 0 || _currentIdx < 0) return;
        const replacement = _replaceInput.value;
        const m = _matches[_currentIdx];
        if (!m) return;

        view.dispatch({
            changes: { from: m.from, to: m.to, insert: replacement }
        });

        setTimeout(() => { runSearch(true); }, 0);
    }

    function replaceAll() {
        if (!view || _matches.length === 0) {
            showToast('无匹配内容');
            return;
        }
        const replacement = _replaceInput.value;
        const count = _matches.length;

        const changes = _matches.slice().reverse().map(m => ({
            from: m.from, to: m.to, insert: replacement
        }));

        view.dispatch({ changes });
        setTimeout(() => {
            runSearch(true);
            showToast('已替换 ' + count + ' 处');
        }, 0);
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
    };
})();