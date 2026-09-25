// MarkEase 主逻辑（阶段 15 修订 10：修复图片路径 + 防抖 + 关于窗口热刷新）
import { EditorState, Compartment, EditorSelection, StateField, StateEffect } from './vendor/state.mjs';
import { EditorView, keymap, lineNumbers, highlightActiveLineGutter, Decoration } from './vendor/view.mjs';
import { defaultKeymap, history, historyKeymap, undo, redo, isolateHistory } from './vendor/commands.mjs';
import { markdown } from './vendor/lang-markdown.mjs';
import { syntaxHighlighting, HighlightStyle, syntaxTree } from './vendor/language.mjs';
import { tags } from './vendor/lezer-highlight.mjs';

// ---------------- HighlightStyle ----------------
const lightHighlight = HighlightStyle.define([
    { tag: tags.heading1, color: '#0550ae', fontWeight: 'bold', fontSize: '1.4em' },
    { tag: tags.heading2, color: '#0550ae', fontWeight: 'bold', fontSize: '1.2em' },
    { tag: tags.heading3, color: '#0550ae', fontWeight: 'bold', fontSize: '1.1em' },
    { tag: [tags.heading4, tags.heading5, tags.heading6], color: '#0550ae', fontWeight: 'bold' },
    { tag: tags.strong, color: '#24292f', fontWeight: 'bold' },
    { tag: tags.emphasis, color: '#24292f', fontStyle: 'italic' },
    { tag: tags.strikethrough, color: '#6a737d', textDecoration: 'line-through' },
    { tag: tags.link, color: '#0969da', textDecoration: 'underline' },
    { tag: tags.url, color: '#0969da' },
    { tag: tags.monospace, color: '#cf222e' },
    { tag: tags.quote, color: '#6a737d', fontStyle: 'italic' },
    { tag: tags.meta, color: '#6a737d' },
    { tag: tags.processingInstruction, color: '#6a737d' },
    { tag: tags.contentSeparator, color: '#6a737d' },
    { tag: tags.list, color: '#e36209' },
    { tag: tags.keyword, color: '#cf222e' },
    { tag: tags.string, color: '#0a3069' },
    { tag: tags.comment, color: '#6a737d', fontStyle: 'italic' },
    { tag: tags.number, color: '#0550ae' },
    { tag: tags.operator, color: '#cf222e' },
    { tag: tags.bool, color: '#0550ae' },
    { tag: tags.null, color: '#0550ae' },
    { tag: tags.function(tags.variableName), color: '#8250df' },
    { tag: tags.className, color: '#953800' },
    { tag: tags.definition(tags.variableName), color: '#24292f' },
    { tag: tags.definition(tags.propertyName), color: '#24292f' }
]);

const darkHighlight = HighlightStyle.define([
    { tag: tags.heading1, color: '#79c0ff', fontWeight: 'bold', fontSize: '1.4em' },
    { tag: tags.heading2, color: '#79c0ff', fontWeight: 'bold', fontSize: '1.2em' },
    { tag: tags.heading3, color: '#79c0ff', fontWeight: 'bold', fontSize: '1.1em' },
    { tag: [tags.heading4, tags.heading5, tags.heading6], color: '#79c0ff', fontWeight: 'bold' },
    { tag: tags.strong, color: '#e6edf3', fontWeight: 'bold' },
    { tag: tags.emphasis, color: '#e6edf3', fontStyle: 'italic' },
    { tag: tags.strikethrough, color: '#adbac7', textDecoration: 'line-through' },
    { tag: tags.link, color: '#58a6ff', textDecoration: 'underline' },
    { tag: tags.url, color: '#58a6ff' },
    { tag: tags.monospace, color: '#ff7b72' },
    { tag: tags.quote, color: '#9ecbff', fontStyle: 'italic' },
    { tag: tags.meta, color: '#adbac7' },
    { tag: tags.processingInstruction, color: '#adbac7' },
    { tag: tags.contentSeparator, color: '#adbac7' },
    { tag: tags.list, color: '#ffa657' },
    { tag: tags.keyword, color: '#ff7b72' },
    { tag: tags.string, color: '#a5d6ff' },
    { tag: tags.comment, color: '#8b949e', fontStyle: 'italic' },
    { tag: tags.number, color: '#79c0ff' },
    { tag: tags.operator, color: '#ff7b72' },
    { tag: tags.bool, color: '#79c0ff' },
    { tag: tags.null, color: '#79c0ff' },
    { tag: tags.function(tags.variableName), color: '#d2a8ff' },
    { tag: tags.className, color: '#ffa657' },
    { tag: tags.definition(tags.variableName), color: '#e6edf3' },
    { tag: tags.definition(tags.propertyName), color: '#e6edf3' }
]);

// ---------------- 状态 ----------------
let editorView = null;
let isSyncing = false;
let syncingFromPreview = false;
let currentFile = '';
let currentDocDir = '';
let mode = 'split';
let zoomLevel = 100;

// ★ 阶段 15 修订 6：脏标记（是否有未保存的修改）
let isDirty = false;

let previewComposing = false;
let activeEditableEl = null;

let currentLangChoice = 'system';
let lastUpdateInfo = null;

// 阶段 15：同步滚动状态
let _syncAnchors = [];
let _editorScrollRaf = null;
let _previewScrollRaf = null;
let _scrollLock = null;
let _scrollLockTimer = null;

// ★ 阶段 15 修订 10：预览防抖
let _lastPreviewUpdateTs = 0;
const MIN_PREVIEW_INTERVAL = 60;

const themeCompartment = new Compartment();

const previewEl = document.getElementById('preview');
const mainEl = document.getElementById('main');
const filePathEl = document.getElementById('file-path');
const statusEl = document.getElementById('status-text');
const statsEl = document.getElementById('stats-text');
const tocEl = document.getElementById('toc');
const tocListEl = document.getElementById('toc-list');

let pendingDragConflict = null;

// ---------------- i18n 辅助 ----------------
function T(key, fallback) {
    try {
        if (window.I18N && typeof window.I18N.t === 'function') {
            return window.I18N.t(key);
        }
    } catch (e) { /* ignore */ }
    return fallback || key;
}

// ★ 阶段 15 修订 10：同步文件状态到 window，供 render.js 兜底使用
function syncGlobalFileState() {
    window.__currentDocDir = currentDocDir || '';
    window.__currentFile = currentFile || '';
}

// ---------------- 搜索高亮 ----------------
const setSearchMatches = StateEffect.define();

const searchMatchesField = StateField.define({
    create() { return Decoration.none; },
    update(deco, tr) {
        for (const e of tr.effects) {
            if (e.is(setSearchMatches)) {
                return e.value;
            }
        }
        if (tr.docChanged) {
            return deco.map(tr.changes);
        }
        return deco;
    },
    provide: f => EditorView.decorations.from(f)
});

function buildSearchDeco(matches, currentIdx) {
    if (!matches || matches.length === 0) return Decoration.none;
    const ranges = [];
    for (let i = 0; i < matches.length; i++) {
        const m = matches[i];
        const isCurrent = (i === currentIdx);
        ranges.push(Decoration.mark({
            class: isCurrent ? 'cm-search-match-current' : 'cm-search-match'
        }).range(m.from, m.to));
    }
    ranges.sort((a, b) => a.from - b.from);
    return Decoration.set(ranges);
}

window.SearchHighlight = {
    update(matches, currentIdx) {
        if (!editorView) return;
        try {
            const deco = buildSearchDeco(matches, currentIdx);
            editorView.dispatch({ effects: setSearchMatches.of(deco) });
        } catch (e) {
            console.warn('[search highlight]', e);
        }
    },
    clear() {
        if (!editorView) return;
        try {
            editorView.dispatch({ effects: setSearchMatches.of(Decoration.none) });
        } catch (e) { /* ignore */ }
    }
};

// ---------------- 启动 ----------------
window.addEventListener('pywebviewready', async () => {
    try {
        try {
            const r = await window.pywebview.api.get_asset_base_url();
            if (r && r.ok && r.url) {
                window.__assetBaseUrl = r.url;
                console.log('[MarkEase] asset server:', r.url);
            }
        } catch (e) {
            console.warn('获取 asset server URL 失败', e);
        }

        let settings = {};
        try {
            settings = await window.pywebview.api.get_settings() || {};
        } catch (e) {
            console.warn('加载设置失败', e);
        }
        currentLangChoice = settings.language || 'system';
        try {
            localStorage.setItem('markease_language', currentLangChoice);
        } catch (e) { /* ignore */ }

        if (window.I18N) {
            try {
                await window.I18N.init(currentLangChoice);
                window.I18N.onChange(() => {
                    onLanguageChanged();
                });
            } catch (e) {
                console.warn('[i18n] init failed', e);
            }
        }

        initEditor();
        initMenubarByHandlers();
        initToolbarByHandlers();
        if (window.FindBar) window.FindBar.init(editorView);
        setupScrollSync();
        setupPreviewEditing();
        setupPreviewCopy();
        setupTaskListClick();
        setupGlobalKeyboard();
        setupDragDrop();
        setupDragConflictModal();
        setupFilePathClick();
        setupTocResizer();
        setupUpdateModal();
        setupMessageModal();
        await loadSettings(settings);
        initZoomBar();

        // ★ 阶段 15 修订 4：检查启动时传入的文件（双击 .md 场景）
        await openStartupFileIfAny();

        setMode('split');
        updatePreview();
        updateStats();
        if (window.Toolbar) {
            window.Toolbar.refresh();
            if (window.Toolbar.refreshI18n) window.Toolbar.refreshI18n();
        }
        if (window.MenuBar && window.MenuBar.refreshI18n) {
            window.MenuBar.refreshI18n();
        }
        setStatus(T('ready', '就绪'));
        console.log('[MarkEase] 初始化完成');

        if (window.__markEaseSplashFallback) {
            clearTimeout(window.__markEaseSplashFallback.soft);
            clearTimeout(window.__markEaseSplashFallback.hard);
            window.__markEaseSplashFallback = null;
        }

        hideSplash();

        try {
            if (window.pywebview && window.pywebview.api &&
                window.pywebview.api.frontend_ready) {
                await window.pywebview.api.frontend_ready();
            }
        } catch (e) {
            console.warn('frontend_ready 调用失败', e);
        }

        scheduleSilentUpdateCheck();
    } catch (err) {
        console.error('[MarkEase] 初始化失败', err);
        setStatus('Init failed: ' + (err && err.message ? err.message : err));
        if (window.__markEaseSplashFallback) {
            clearTimeout(window.__markEaseSplashFallback.soft);
            clearTimeout(window.__markEaseSplashFallback.hard);
            window.__markEaseSplashFallback = null;
        }
        hideSplash();
        try {
            if (window.pywebview && window.pywebview.api &&
                window.pywebview.api.frontend_ready) {
                await window.pywebview.api.frontend_ready();
            }
        } catch (e) { /* ignore */ }
    }
});

// ★ 阶段 15 修订 10：先设路径，后 setContent
async function openStartupFileIfAny() {
    if (!(window.pywebview && window.pywebview.api &&
          window.pywebview.api.get_startup_file)) {
        return;
    }
    try {
        const r = await window.pywebview.api.get_startup_file();
        if (!r) return;

        if (r.ok && r.content != null) {
            // ★★★ 关键修复：先设 currentFile / currentDocDir，再 setContent ★★★
            //    因为 setContent 内部会立即触发 updatePreview，
            //    若 docDir 为空，img 相对路径就无法改写为 asset URL。
            currentFile = r.path || '';
            currentDocDir = r.path
                ? r.path.replace(/[\\/][^\\/]+$/, '')
                : '';
            syncGlobalFileState();

            setContent(r.content);

            if (r.path) {
                setFilePathDisplay(r.path);
            } else if (r.source_pdf) {
                setFilePathDisplay('', '（来自 PDF）');
            } else {
                setFilePathDisplay('');
            }

            if (r.imported) {
                setStatus('已从 PDF 导入');
            } else if (r.encoding && r.encoding !== 'utf-8') {
                setStatus('已打开（编码: ' + r.encoding + '）');
            } else {
                setStatus('已打开');
            }

            try {
                await window.pywebview.api.set_current_file(currentFile || '');
            } catch (e) { /* ignore */ }

            console.log('[startup] opened:', r.path,
                        'docDir:', currentDocDir);
        } else if (!r.ok && r.path && r.error) {
            setStatus('打开启动文件失败: ' + r.error);
            console.warn('[startup] open failed:', r.error);
        }
    } catch (e) {
        console.warn('[startup] get_startup_file failed', e);
    }
}

function hideSplash() {
    const splash = document.getElementById('splash');
    if (!splash) return;
    splash.classList.add('hidden');
    setTimeout(() => {
        if (splash.parentNode) splash.parentNode.removeChild(splash);
    }, 320);
}

function initEditor() {
    const updateListener = EditorView.updateListener.of(update => {
        // ★ 阶段 15 修订 6：任何文档改动都标记为脏
        if (update.docChanged) {
            isDirty = true;
            if (!isSyncing) {
                if (!syncingFromPreview) {
                    updatePreview();
                }
                updateStats();
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.update_content(getContent());
                }
            }
        }
        if (update.docChanged || update.selectionSet || update.focusChanged) {
            if (window.Toolbar) window.Toolbar.refresh();
        }
        if (update.docChanged && window.FindBar && window.FindBar.isOpen()) {
            window.FindBar.refresh();
        }
    });

    editorView = new EditorView({
        state: EditorState.create({
            doc: '',
            extensions: [
                lineNumbers(),
                highlightActiveLineGutter(),
                history(),
                keymap.of([...defaultKeymap, ...historyKeymap]),
                markdown(),
                themeCompartment.of(syntaxHighlighting(lightHighlight)),
                EditorView.lineWrapping,
                EditorState.allowMultipleSelections.of(true),
                searchMatchesField,
                updateListener
            ]
        }),
        parent: document.getElementById('editor')
    });
}

// ---------------- 菜单栏集成 ----------------
function initMenubarByHandlers() {
    window.MenuBar.init({
        new: onNew,
        open: onOpen,
        save: onSave,
        save_as: onSaveAs,
        insert_image: onInsertImage,
        import_pdf: onImportPdf,
        export_pdf: onExportPdf,
        exit: onExit,
        undo: onUndo,
        redo: onRedo,
        cut: () => document.execCommand('cut'),
        copy: () => document.execCommand('copy'),
        paste: () => document.execCommand('paste'),
        select_all: () => {
            if (editorView) {
                editorView.dispatch({
                    selection: { anchor: 0, head: editorView.state.doc.length }
                });
                editorView.focus();
            }
        },
        find: () => { if (window.FindBar) window.FindBar.open(false); },
        mode_edit:    () => setMode('edit'),
        mode_split:   () => setMode('split'),
        mode_preview: () => setMode('preview'),
        toggle_toc:   () => toggleToc(),
        zoom_in:      () => zoomIn(),
        zoom_out:     () => zoomOut(),
        zoom_reset:   () => zoomReset(),
        toggle_theme: () => toggleTheme(),

        lang_system: () => onSetLanguage('system'),
        lang_zh_CN:  () => onSetLanguage('zh_CN'),
        lang_zh_TW:  () => onSetLanguage('zh_TW'),
        lang_en_US:  () => onSetLanguage('en_US'),
        lang_ja_JP:  () => onSetLanguage('ja_JP'),
        lang_ko_KR:  () => onSetLanguage('ko_KR'),

        about: onAbout,
        check_update: () => onCheckUpdate(false),

        set_default_program: onSetDefaultProgram,
        register_shell_new:  onRegisterShellNew,
    });

    window.MenuBar.setChecked('toggle_toc', !tocEl.classList.contains('hidden'));
}

// ---------------- 文件关联 handlers ----------------
async function onSetDefaultProgram() {
    if (!(window.pywebview && window.pywebview.api &&
          window.pywebview.api.set_as_default_program)) {
        setStatus('文件关联接口未就绪');
        return;
    }
    setStatus('正在设置默认程序...');
    try {
        const r = await window.pywebview.api.set_as_default_program();
        setStatus(T('ready', '就绪'));
        if (r && r.ok) {
            let msg = T('set_default_program_success_msg',
                'MarkEase 已设为 .md / .markdown 文件的默认打开程序。');
            const warnings = (r.warnings || []);
            if (warnings.length > 0) {
                msg += '\n\n⚠ ' + warnings.join('\n⚠ ');
            }
            showMessage(T('set_default_program_success_title', '设置成功'), msg);
        } else {
            showMessage(
                T('set_default_program_failed_title', '设置失败'),
                T('set_default_program_failed_msg', '无法完成设置：{error}')
                    .replace('{error}', (r && r.error) || '未知错误')
            );
        }
    } catch (e) {
        setStatus(T('ready', '就绪'));
        showMessage(
            T('set_default_program_failed_title', '设置失败'),
            T('set_default_program_failed_msg', '无法完成设置：{error}')
                .replace('{error}', (e && e.message) || String(e))
        );
    }
}

async function onRegisterShellNew() {
    if (!(window.pywebview && window.pywebview.api &&
          window.pywebview.api.register_shell_new)) {
        setStatus('文件关联接口未就绪');
        return;
    }
    setStatus('正在注册「新建」菜单...');
    try {
        const r = await window.pywebview.api.register_shell_new();
        setStatus(T('ready', '就绪'));
        if (r && r.ok) {
            const name = r.name || 'Markdown File';
            showMessage(
                T('register_shell_new_success_title', '注册成功'),
                T('register_shell_new_success_msg', '已在桌面右键 → 新建中添加「{name}」。')
                    .replace('{name}', name)
            );
        } else {
            showMessage(
                T('register_shell_new_failed_title', '注册失败'),
                T('register_shell_new_failed_msg', '无法写入注册表：{error}')
                    .replace('{error}', (r && r.error) || '未知错误')
            );
        }
    } catch (e) {
        setStatus(T('ready', '就绪'));
        showMessage(
            T('register_shell_new_failed_title', '注册失败'),
            T('register_shell_new_failed_msg', '无法写入注册表：{error}')
                .replace('{error}', (e && e.message) || String(e))
        );
    }
}

// ---------------- 工具栏集成 ----------------
function initToolbarByHandlers() {
    window.Toolbar.init(
        editorView,
        {
            new: onNew,
            open: onOpen,
            save: onSave,
            undo: onUndo,
            redo: onRedo,
            insert_image: onInsertImage,
            setMode: (m) => setMode(m),
            toggle: (key) => {
                if (key === 'theme') toggleTheme();
                else if (key === 'toc') toggleToc();
            },
            status: (msg) => setStatus(msg),
            refreshPreview: () => {
                updatePreview();
                updateStats();
                try { editorView.requestMeasure(); } catch (e) { /* ignore */ }
            },
            download_icon: async (url) => {
                try {
                    const r = await window.pywebview.api.download_icon(url);
                    return r;
                } catch (e) {
                    return { ok: false, error: String(e) };
                }
            },
        },
        {
            EditorSelection: EditorSelection,
            isolateHistory: isolateHistory,
            syntaxTree: syntaxTree,
        }
    );
    window.Toolbar.setModeButtonState(mode);
}

function onUndo() {
    if (!editorView) return;
    undo({ state: editorView.state, dispatch: editorView.dispatch });
    setTimeout(() => {
        updatePreview();
        if (window.Toolbar) window.Toolbar.refresh();
    }, 0);
    editorView.focus();
}

function onRedo() {
    if (!editorView) return;
    redo({ state: editorView.state, dispatch: editorView.dispatch });
    setTimeout(() => {
        updatePreview();
        if (window.Toolbar) window.Toolbar.refresh();
    }, 0);
    editorView.focus();
}

function onExit() {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.close_window().catch(() => {});
    }
}

function onAbout() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_about_window) {
        window.pywebview.api.open_about_window().catch(() => {});
    }
}

// ---------------- 语言切换 ----------------
async function onSetLanguage(lang) {
    currentLangChoice = lang || 'system';
    try {
        localStorage.setItem('markease_language', currentLangChoice);
    } catch (e) { /* ignore */ }

    if (window.I18N) {
        try {
            await window.I18N.setLanguage(currentLangChoice);
        } catch (e) {
            console.warn('[i18n] setLanguage failed', e);
        }
    }

    if (window.MenuBar && window.MenuBar.refreshI18n) {
        window.MenuBar.refreshI18n();
    }
    if (window.Toolbar && window.Toolbar.refreshI18n) {
        window.Toolbar.refreshI18n();
    }

    // ★ 阶段 15 修订 6：通知关于窗口刷新语言
    try {
        if (window.pywebview && window.pywebview.api &&
            window.pywebview.api.notify_about_refresh) {
            window.pywebview.api.notify_about_refresh().catch(() => {});
        }
    } catch (e) { /* ignore */ }
}

function onLanguageChanged() {
    if (window.MenuBar && window.MenuBar.refreshI18n) {
        window.MenuBar.refreshI18n();
    }
    if (window.Toolbar && window.Toolbar.refreshI18n) {
        window.Toolbar.refreshI18n();
    }
    setStatus(T('ready', '就绪'));
    updateStats();
    const tocTitle = document.querySelector('#toc .toc-title');
    if (tocTitle) tocTitle.textContent = T('toc_title', '目录');
    if (window.I18N && window.I18N.applyToDOM) {
        window.I18N.applyToDOM(document);
    }
}

// ---------------- 缩放 ----------------
function applyZoomValue(pct) {
    zoomLevel = pct;
    const scale = pct / 100;
    if (mainEl) mainEl.style.zoom = String(scale);
    if (tocEl) tocEl.style.zoom = String(1 / scale);
}

function initZoomBar() {
    if (!window.ZoomBar) return;
    window.ZoomBar.init({
        initialPct: zoomLevel,
        onChange: (pct) => {
            applyZoomValue(pct);
            setStatus(T('zoom', '缩放') + ': ' + pct + '%');
            try {
                window.pywebview.api.set_setting('zoom_percent', pct);
            } catch (e) { /* ignore */ }
        },
    });
    applyZoomValue(window.ZoomBar.getValue());
}

function zoomIn() {
    if (!window.ZoomBar) return;
    const cur = window.ZoomBar.getValue();
    window.ZoomBar.setValue(cur + 10);
}
function zoomOut() {
    if (!window.ZoomBar) return;
    const cur = window.ZoomBar.getValue();
    window.ZoomBar.setValue(cur - 10);
}
function zoomReset() {
    if (!window.ZoomBar) return;
    window.ZoomBar.setValue(100);
}

// ---------------- 模式 ----------------
function setMode(newMode) {
    mode = newMode;
    mainEl.setAttribute('data-mode', mode);
    if (window.Toolbar) {
        window.Toolbar.setModeButtonState(mode);
        if (typeof window.Toolbar.relayout === 'function') {
            window.Toolbar.relayout();
        }
    }
    if (mode === 'preview') setTimeout(() => updatePreview(), 30);
    if (mode === 'split') setTimeout(() => { updateSyncAnchors(); }, 30);
}

function toggleToc() {
    tocEl.classList.toggle('hidden');
    if (!tocEl.classList.contains('hidden')) rebuildToc();
    if (window.MenuBar) {
        window.MenuBar.setChecked('toggle_toc', !tocEl.classList.contains('hidden'));
    }
    if (window.Toolbar && typeof window.Toolbar.relayout === 'function') {
        setTimeout(() => window.Toolbar.relayout(), 30);
    }
}

// ---------------- 编辑器内容 ----------------
function getContent() {
    return editorView ? editorView.state.doc.toString() : '';
}

function setContent(text) {
    if (!editorView) return;
    isSyncing = true;
    editorView.dispatch({
        changes: { from: 0, to: editorView.state.doc.length, insert: text }
    });
    isSyncing = false;
    // ★ 阶段 15 修订 6：程序化设置内容 → 不算未保存修改
    isDirty = false;
    updatePreview();
    updateStats();
    if (window.Toolbar) window.Toolbar.refresh();
}

// ---------------- 预览 ----------------
// ★ 阶段 15 修订 10：每次渲染前同步全局文件状态（防时序问题）
function updatePreview() {
    syncGlobalFileState();

    const previewContainer = previewEl.parentElement;
    const scrollTop = previewContainer ? previewContainer.scrollTop : 0;

    activeEditableEl = null;
    window.renderMarkdown(getContent(), {
        target: previewEl,
        docDir: currentDocDir
    });
    annotatePreviewBlocks();
    rebuildToc();
    updateSyncAnchors();
    updateActiveTocByScroll();

    if (previewContainer) previewContainer.scrollTop = scrollTop;
}

function updateStats() {
    const text = getContent();
    statsEl.textContent = T('words', '字数') + ': ' + text.length +
                          ' | ' + T('lines', '行数') + ': ' +
                          text.split('\n').length;
}

// ---------------- 目录 ----------------
function stripMdInline(text) {
    let s = String(text == null ? '' : text);
    s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1');
    s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
    s = s.replace(/\[([^\]]+)\]\[[^\]]*\]/g, '$1');
    s = s.replace(/`([^`]+)`/g, '$1');
    s = s.replace(/\*\*(.+?)\*\*/g, '$1');
    s = s.replace(/__(.+?)__/g, '$1');
    s = s.replace(/~~(.+?)~~/g, '$1');
    s = s.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, '$1$2');
    s = s.replace(/(^|[^_])_([^_\n]+?)_(?!_)/g, '$1$2');
    s = s.replace(/<[^>]+>/g, '');
    s = s.replace(/&amp;/g, '&')
         .replace(/&lt;/g, '<')
         .replace(/&gt;/g, '>')
         .replace(/&quot;/g, '"')
         .replace(/&#39;/g, "'")
         .replace(/&nbsp;/g, ' ');
    return s.trim();
}

function rebuildToc() {
    const lines = getContent().split('\n');
    const headings = [];
    for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
        if (m) headings.push({ level: m[1].length, text: m[2], line: i });
    }
    tocListEl.innerHTML = '';
    headings.forEach(h => {
        const el = document.createElement('div');
        el.className = 'toc-item toc-level-' + h.level;
        el.textContent = stripMdInline(h.text);
        el.dataset.line = h.line;
        el.addEventListener('click', () => scrollEditorToLine(h.line));
        tocListEl.appendChild(el);
    });
    previewEl.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach((el, i) => {
        if (headings[i]) el.setAttribute('data-line', headings[i].line);
    });
}

function scrollEditorToLine(line) {
    if (!editorView) return;
    const doc = editorView.state.doc;
    if (line < 0 || line >= doc.lines) return;
    const lineInfo = doc.line(line + 1);
    editorView.dispatch({
        selection: { anchor: lineInfo.from },
        scrollIntoView: true
    });
    editorView.focus();
    const target = previewEl.querySelector('[data-line="' + line + '"]');
    if (target) {
        _acquireScrollLock('editor');
        target.scrollIntoView({ behavior: 'auto', block: 'start' });
        _releaseScrollLockSoon('editor');
    }
}

function updateActiveTocByScroll() {
    const heads = previewEl.querySelectorAll('[data-line]');
    let activeLine = -1;
    for (let i = 0; i < heads.length; i++) {
        const rect = heads[i].getBoundingClientRect();
        const containerRect = previewEl.parentElement.getBoundingClientRect();
        if (rect.top - containerRect.top <= 60) activeLine = heads[i].getAttribute('data-line');
        else break;
    }
    document.querySelectorAll('.toc-item').forEach(el => {
        el.classList.toggle('active', el.dataset.line == activeLine);
    });
}

// ---------------- 目录宽度拖动 ----------------
function setupTocResizer() {
    const resizer = document.getElementById('toc-resizer');
    if (!resizer || !tocEl) return;

    let dragging = false;
    let startX = 0;
    let startW = 0;

    resizer.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        startX = e.clientX;
        startW = tocEl.offsetWidth;
        e.preventDefault();
        e.stopPropagation();
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        resizer.classList.add('dragging');
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const dx = e.clientX - startX;
        const newW = Math.max(120, Math.min(600, startW + dx));
        tocEl.style.width = newW + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        resizer.classList.remove('dragging');
        if (window.Toolbar && typeof window.Toolbar.relayout === 'function') {
            window.Toolbar.relayout();
        }
    });
}

// ============================================================
//  同步滚动（源位置映射 + RAF 节流 + 方向锁）
// ============================================================
function _acquireScrollLock(src) {
    _scrollLock = src;
    if (_scrollLockTimer) clearTimeout(_scrollLockTimer);
    _scrollLockTimer = setTimeout(() => {
        if (_scrollLock === src) _scrollLock = null;
        _scrollLockTimer = null;
    }, 90);
}

function _releaseScrollLockSoon(src) {
    if (_scrollLockTimer) clearTimeout(_scrollLockTimer);
    _scrollLockTimer = setTimeout(() => {
        if (_scrollLock === src) _scrollLock = null;
        _scrollLockTimer = null;
    }, 90);
}

function annotatePreviewBlocks() {
    if (!previewEl || !editorView) return;
    const totalLen = editorView.state.doc.length;
    const BLOCK_RE = /^(p|h[1-6]|ul|ol|pre|blockquote|table|hr|div|details)$/;

    const blocks = [];
    for (let i = 0; i < previewEl.children.length; i++) {
        const el = previewEl.children[i];
        if (el.nodeType !== 1) continue;
        if (!BLOCK_RE.test(el.tagName.toLowerCase())) continue;
        blocks.push(el);
    }

    let prevEnd = 0;
    for (let i = 0; i < blocks.length; i++) {
        const el = blocks[i];

        let startAttr = el.getAttribute('data-md-start');
        let startNum = startAttr != null ? parseInt(startAttr, 10) : NaN;
        if (!Number.isFinite(startNum) || startNum < 0) {
            startNum = prevEnd;
            el.setAttribute('data-md-start', String(startNum));
        }

        let endAttr = el.getAttribute('data-md-end');
        let endNum = endAttr != null ? parseInt(endAttr, 10) : NaN;
        if (!Number.isFinite(endNum) || endNum < startNum) {
            let nextStart = totalLen;
            for (let j = i + 1; j < blocks.length; j++) {
                const ns = blocks[j].getAttribute('data-md-start');
                if (ns != null) {
                    const n = parseInt(ns, 10);
                    if (Number.isFinite(n) && n > startNum) { nextStart = n; break; }
                }
            }
            endNum = Math.max(startNum, nextStart);
            el.setAttribute('data-md-end', String(endNum));
        }

        prevEnd = endNum;
    }
}

function buildPreviewAnchors() {
    if (!editorView || !previewEl) return [];
    const scroller = previewEl.parentElement;
    if (!scroller) return [];

    const scrollerRect = scroller.getBoundingClientRect();
    const scrollTop = scroller.scrollTop;
    const doc = editorView.state.doc;

    const raw = [];
    const els = previewEl.querySelectorAll('[data-md-start], [data-line]');
    for (let i = 0; i < els.length; i++) {
        const el = els[i];
        let pos = -1;

        const s = el.getAttribute('data-md-start');
        if (s != null) {
            const n = parseInt(s, 10);
            if (Number.isFinite(n) && n >= 0) pos = n;
        }
        if (pos < 0) {
            const l = el.getAttribute('data-line');
            if (l != null) {
                const lineNum = parseInt(l, 10);
                if (Number.isFinite(lineNum) && lineNum >= 0 && lineNum < doc.lines) {
                    pos = doc.line(lineNum + 1).from;
                }
            }
        }
        if (pos < 0) continue;

        const r = el.getBoundingClientRect();
        const top = r.top - scrollerRect.top + scrollTop;
        raw.push({ pos, top, el });
    }

    raw.sort((a, b) => a.pos - b.pos || a.top - b.top);

    const out = [];
    for (let i = 0; i < raw.length; i++) {
        if (out.length > 0 && out[out.length - 1].pos === raw[i].pos) continue;
        out.push(raw[i]);
    }
    return out;
}

function updateSyncAnchors() {
    try {
        _syncAnchors = buildPreviewAnchors();
    } catch (e) {
        console.warn('[sync] build anchors failed', e);
        _syncAnchors = [];
    }
}

function _editorPosToPreviewTop(pos, anchors) {
    if (!anchors || anchors.length === 0) return null;
    if (pos <= anchors[0].pos) return anchors[0].top;
    const last = anchors[anchors.length - 1];
    if (pos >= last.pos) return last.top;

    let lo = 0, hi = anchors.length - 1;
    while (lo + 1 < hi) {
        const mid = (lo + hi) >> 1;
        if (anchors[mid].pos <= pos) lo = mid;
        else hi = mid;
    }
    const a = anchors[lo], b = anchors[hi];
    if (a.pos === b.pos) return a.top;
    const t = (pos - a.pos) / (b.pos - a.pos);
    return a.top + (b.top - a.top) * t;
}

function _previewTopToEditorPos(top, anchors) {
    if (!anchors || anchors.length === 0) return null;
    if (top <= anchors[0].top) return anchors[0].pos;
    const last = anchors[anchors.length - 1];
    if (top >= last.top) return last.pos;

    let lo = 0, hi = anchors.length - 1;
    while (lo + 1 < hi) {
        const mid = (lo + hi) >> 1;
        if (anchors[mid].top <= top) lo = mid;
        else hi = mid;
    }
    const a = anchors[lo], b = anchors[hi];
    if (a.top === b.top) return a.pos;
    const t = (top - a.top) / (b.top - a.top);
    return a.pos + (b.pos - a.pos) * t;
}

function syncEditorToPreview() {
    if (mode !== 'split' || !editorView || !previewEl) return;
    const editorScroller = document.querySelector('#editor .cm-scroller');
    const previewScroller = previewEl.parentElement;
    if (!editorScroller || !previewScroller) return;

    const editorMax = editorScroller.scrollHeight - editorScroller.clientHeight;
    const previewMax = previewScroller.scrollHeight - previewScroller.clientHeight;

    if (editorScroller.scrollTop <= 1) {
        if (previewScroller.scrollTop > 0) previewScroller.scrollTop = 0;
        return;
    }
    if (editorMax > 0 && editorScroller.scrollTop >= editorMax - 2) {
        if (previewMax > 0 && Math.abs(previewScroller.scrollTop - previewMax) > 1) {
            previewScroller.scrollTop = previewMax;
        }
        return;
    }

    let block;
    try { block = editorView.lineBlockAtHeight(editorScroller.scrollTop + 1); }
    catch (e) { return; }
    if (!block) return;

    const targetTop = _editorPosToPreviewTop(block.from, _syncAnchors);
    if (targetTop == null) return;

    const clamped = Math.max(0, Math.min(previewMax, targetTop));
    if (Math.abs(previewScroller.scrollTop - clamped) < 1) return;
    previewScroller.scrollTop = clamped;
}

function syncPreviewToEditor() {
    if (mode !== 'split' || !editorView || !previewEl) return;
    const editorScroller = document.querySelector('#editor .cm-scroller');
    const previewScroller = previewEl.parentElement;
    if (!editorScroller || !previewScroller) return;

    const editorMax = editorScroller.scrollHeight - editorScroller.clientHeight;
    const previewMax = previewScroller.scrollHeight - previewScroller.clientHeight;

    if (previewScroller.scrollTop <= 1) {
        if (editorScroller.scrollTop > 0) editorScroller.scrollTop = 0;
        return;
    }
    if (previewMax > 0 && previewScroller.scrollTop >= previewMax - 2) {
        if (editorMax > 0 && Math.abs(editorScroller.scrollTop - editorMax) > 1) {
            editorScroller.scrollTop = editorMax;
        }
        return;
    }

    const targetPos = _previewTopToEditorPos(previewScroller.scrollTop, _syncAnchors);
    if (targetPos == null) return;

    let targetBlock;
    try {
        const doc = editorView.state.doc;
        const lineInfo = doc.lineAt(targetPos);
        targetBlock = editorView.lineBlockAt(lineInfo.from);
    } catch (e) { return; }
    if (!targetBlock) return;

    const targetTop = Math.max(0, Math.min(editorMax, targetBlock.top));
    if (Math.abs(editorScroller.scrollTop - targetTop) < 1) return;
    editorScroller.scrollTop = targetTop;
}

function onEditorScrollEvent() {
    if (mode !== 'split') return;
    if (_scrollLock === 'preview') return;
    _acquireScrollLock('editor');
    if (_editorScrollRaf) return;
    _editorScrollRaf = requestAnimationFrame(() => {
        _editorScrollRaf = null;
        try { syncEditorToPreview(); } catch (e) { console.warn('[sync e→p]', e); }
        _releaseScrollLockSoon('editor');
    });
}

function onPreviewScrollEvent() {
    if (mode !== 'split') return;
    if (_scrollLock === 'editor') return;
    _acquireScrollLock('preview');
    if (_previewScrollRaf) return;
    _previewScrollRaf = requestAnimationFrame(() => {
        _previewScrollRaf = null;
        try { syncPreviewToEditor(); } catch (e) { console.warn('[sync p→e]', e); }
        updateActiveTocByScroll();
        _releaseScrollLockSoon('preview');
    });
}

function setupScrollSync() {
    const editorScroller = () => document.querySelector('#editor .cm-scroller');
    const previewScroller = previewEl.parentElement;

    setTimeout(() => {
        const sc = editorScroller();
        if (sc) sc.addEventListener('scroll', onEditorScrollEvent, { passive: true });
        if (previewScroller) {
            previewScroller.addEventListener('scroll', onPreviewScrollEvent, { passive: true });
        }
        updateSyncAnchors();
    }, 200);

    window.addEventListener('resize', () => {
        setTimeout(updateSyncAnchors, 120);
    });
}

// ============================================================
//  任务列表点击切换
// ============================================================
const TASK_LINE_RE = /^(\s*(?:>[ \t]*)?[-*+][ \t]+)\[([ xX])\]/;

function setupTaskListClick() {
    previewEl.addEventListener('click', (e) => {
        const target = e.target && e.target.closest
            ? e.target.closest('.task-list-checkbox')
            : null;
        if (!target) return;
        const idxStr = target.getAttribute('data-md-task-index');
        if (idxStr == null) return;
        const idx = parseInt(idxStr, 10);
        if (!Number.isFinite(idx)) return;
        e.preventDefault();
        e.stopPropagation();
        toggleTaskCheckbox(idx);
    }, true);

    if (!editorView) return;

    editorView.dom.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;

        let pos;
        try {
            pos = editorView.posAtCoords({ x: e.clientX, y: e.clientY });
        } catch (err) { return; }
        if (pos == null) return;

        const state = editorView.state;
        const sel = state.selection.main;

        if (sel.empty) return;

        const selStartLine = state.doc.lineAt(sel.from).number;
        const selEndLine = state.doc.lineAt(sel.to).number;
        if (selStartLine === selEndLine) return;

        const line = state.doc.lineAt(pos);
        const text = line.text;
        const m = TASK_LINE_RE.exec(text);
        if (!m) return;

        const bracketStart = line.from + m[1].length;
        const bracketEnd = bracketStart + 3;
        if (pos < bracketStart || pos > bracketEnd) return;

        e.preventDefault();
        e.stopPropagation();

        const clickedChecked = (m[2] === 'x' || m[2] === 'X');
        const target = clickedChecked ? ' ' : 'x';

        batchToggleTaskCheckbox(selStartLine, selEndLine, target);
    }, true);

    editorView.dom.addEventListener('click', (e) => {
        let pos;
        try {
            pos = editorView.posAtCoords({ x: e.clientX, y: e.clientY });
        } catch (err) { return; }
        if (pos == null) return;

        const state = editorView.state;
        const line = state.doc.lineAt(pos);
        const text = line.text;
        const m = TASK_LINE_RE.exec(text);
        if (!m) return;

        const bracketStart = line.from + m[1].length;
        const bracketEnd = bracketStart + 3;
        if (pos < bracketStart || pos > bracketEnd) return;

        const sel = state.selection.main;
        if (!sel.empty) {
            const selStartLine = state.doc.lineAt(sel.from).number;
            const selEndLine = state.doc.lineAt(sel.to).number;
            if (selStartLine !== selEndLine) return;
        }

        e.preventDefault();
        e.stopPropagation();
        toggleTaskCheckbox(bracketStart);
    }, true);
}

function toggleTaskCheckbox(bracketPos) {
    if (!editorView) return;
    const doc = editorView.state.doc;
    if (bracketPos < 0 || bracketPos + 3 > doc.length) return;

    const slice = doc.sliceString(bracketPos, bracketPos + 3);
    if (!/^\[[ xX]\]$/.test(slice)) return;

    const cur = slice[1];
    const next = (cur === ' ') ? 'x' : ' ';

    editorView.dispatch({
        changes: {
            from: bracketPos + 1,
            to: bracketPos + 2,
            insert: next
        },
        annotations: [isolateHistory.of('full')]
    });

    setTimeout(() => {
        updatePreview();
        if (window.Toolbar) window.Toolbar.refresh();
    }, 0);
}

function batchToggleTaskCheckbox(startLine, endLine, target) {
    if (!editorView) return;
    const doc = editorView.state.doc;
    const changes = [];

    for (let ln = startLine; ln <= endLine; ln++) {
        if (ln < 1 || ln > doc.lines) continue;
        const line = doc.line(ln);
        const m = TASK_LINE_RE.exec(line.text);
        if (!m) continue;
        if (m[2].toLowerCase() === target.toLowerCase()) continue;
        const bracketContentPos = line.from + m[1].length + 1;
        changes.push({
            from: bracketContentPos,
            to: bracketContentPos + 1,
            insert: target,
        });
    }

    if (changes.length === 0) return;

    editorView.dispatch({
        changes,
        annotations: [isolateHistory.of('full')]
    });

    setTimeout(() => {
        updatePreview();
        if (window.Toolbar) window.Toolbar.refresh();
    }, 0);
}

// ---------------- 拖拽导入图片 ----------------
function setupDragDrop() {
    const targets = [
        document.getElementById('editor-container'),
        document.getElementById('preview-container'),
        previewEl,
    ];

    targets.forEach(el => {
        if (!el) return;

        el.addEventListener('dragover', (e) => {
            if (!e.dataTransfer) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        });

        el.addEventListener('drop', async (e) => {
            if (!e.dataTransfer) return;
            e.preventDefault();
            await handleImageDrop(e.dataTransfer);
        });
    });
}

async function handleImageDrop(dt) {
    const files = dt.files;
    if (files && files.length > 0) {
        const imageFiles = Array.from(files).filter(f =>
            /^image\//.test(f.type) ||
            /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i.test(f.name)
        );
        if (imageFiles.length === 0) {
            setStatus('拖入的文件不是图片');
            return;
        }
        for (const f of imageFiles) {
            await importDroppedLocalFile(f);
        }
        return;
    }

    const html = dt.getData('text/html');
    if (html) {
        const m = html.match(/<img[^>]+\bsrc\s*=\s*["']([^"']+)["']/i);
        if (m && m[1]) {
            await importDroppedUrl(m[1]);
            return;
        }
    }

    let url = dt.getData('text/uri-list') || dt.getData('text/plain') || '';
    url = String(url).split(/\r?\n/)[0].trim();
    if (url && /^https?:\/\//i.test(url)) {
        await importDroppedUrl(url);
        return;
    }

    setStatus('未能识别拖入内容');
}

async function importDroppedLocalFile(file) {
    setStatus('正在导入本地图片...');

    let path = file.path || '';
    if (path) {
        try {
            const r = await window.pywebview.api.import_dropped_file(path);
            if (r && r.conflict) {
                showDragConflictModal(r);
                return;
            }
            if (r && r.ok) {
                insertImageMarkdown(r.md_path, r.unsaved);
                return;
            }
            if (r && r.error) {
                setStatus('导入失败: ' + r.error);
                return;
            }
        } catch (e) {
            console.warn('import_dropped_file 失败，改走字节流', e);
        }
    }

    try {
        const buf = await file.arrayBuffer();
        const bytes = Array.from(new Uint8Array(buf));
        const r = await window.pywebview.api.import_dropped_bytes(file.name, bytes);
        if (r && r.conflict) {
            showDragConflictModal(r);
            return;
        }
        if (r && r.ok) {
            insertImageMarkdown(r.md_path, r.unsaved);
        } else {
            setStatus('导入失败: ' + ((r && r.error) || '未知错误'));
        }
    } catch (e) {
        setStatus('导入异常: ' + (e && e.message ? e.message : e));
    }
}

async function importDroppedUrl(url) {
    setStatus('正在下载网络图片...');
    try {
        const r = await window.pywebview.api.import_dropped_url(url);
        if (r && r.ok) {
            insertImageMarkdown(r.md_path, r.unsaved);
        } else {
            setStatus('下载失败: ' + ((r && r.error) || '未知错误'));
        }
    } catch (e) {
        setStatus('下载异常: ' + (e && e.message ? e.message : e));
    }
}

function insertImageMarkdown(mdPath, unsaved) {
    if (!editorView || !mdPath) return;
    const src = /[\s()<>]/.test(mdPath) && !mdPath.startsWith('<')
        ? '<' + mdPath + '>'
        : mdPath;
    const mdText = `![](${src})`;

    const cursor = editorView.state.selection.main.head;
    const doc = editorView.state.doc.toString();
    let insert = mdText;
    const before = doc.slice(Math.max(0, cursor - 2), cursor);
    if (cursor > 0 && !/\n\s*$/.test(before)) {
        insert = '\n\n' + insert;
    }
    if (cursor < doc.length && !/^\s*\n/.test(doc.slice(cursor, cursor + 2))) {
        insert = insert + '\n\n';
    }

    editorView.dispatch({
        changes: { from: cursor, to: cursor, insert },
        selection: { anchor: cursor + insert.length },
    });
    editorView.focus();
    updatePreview();

    if (unsaved) {
        setStatus('图片已插入（文档未保存，使用绝对路径）');
    } else {
        setStatus('图片已插入');
    }
}

// ---------------- 拖拽冲突弹窗 ----------------
function setupDragConflictModal() {
    const modal = document.getElementById('drag-conflict-modal');
    document.getElementById('drag-conflict-cancel')
        .addEventListener('click', () => resolveDragConflict('cancel'));
    document.getElementById('drag-conflict-keep-both')
        .addEventListener('click', () => resolveDragConflict('keep_both'));
    document.getElementById('drag-conflict-replace')
        .addEventListener('click', () => resolveDragConflict('replace'));
    if (modal) modal.addEventListener('click', (e) => {
        if (e.target === modal) resolveDragConflict('cancel');
    });
}

function fileUrlForPreview(absPath) {
    if (!window.__assetBaseUrl || !absPath) return '';
    const normalized = String(absPath).replace(/\\/g, '/');
    return window.__assetBaseUrl + '/fs/' + encodeURIComponent(normalized);
}

function _formatSize(bytes) {
    if (bytes == null) return '';
    const b = Number(bytes);
    if (!isFinite(b) || b <= 0) return b === 0 ? '0 B' : '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0, v = b;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + ' ' + units[i];
}

function showDragConflictModal(info) {
    pendingDragConflict = { src_path: info.src_path };
    document.getElementById('drag-conflict-src-img').src =
        fileUrlForPreview(info.src_path);
    document.getElementById('drag-conflict-src-name').textContent =
        info.src_name || '';
    document.getElementById('drag-conflict-src-size').textContent =
        _formatSize(info.src_size);
    document.getElementById('drag-conflict-target-img').src =
        fileUrlForPreview(info.target_path);
    document.getElementById('drag-conflict-target-name').textContent =
        info.target_name || '';
    document.getElementById('drag-conflict-target-size').textContent =
        _formatSize(info.target_size);
    document.getElementById('drag-conflict-modal').classList.remove('hidden');
}

function hideDragConflictModal() {
    document.getElementById('drag-conflict-modal').classList.add('hidden');
    pendingDragConflict = null;
}

async function resolveDragConflict(action) {
    if (!pendingDragConflict) return;
    const src = pendingDragConflict.src_path;
    try {
        const r = await window.pywebview.api.resolve_dropped_conflict(src, action);
        hideDragConflictModal();
        if (r && r.ok) {
            insertImageMarkdown(r.md_path, r.unsaved);
        } else if (r && r.cancelled) {
            setStatus('已取消');
        } else {
            setStatus('操作失败: ' + ((r && r.error) || '未知错误'));
        }
    } catch (e) {
        hideDragConflictModal();
        setStatus('操作异常: ' + (e && e.message ? e.message : e));
    }
}

// ---------------- 预览编辑（含表格单元格） ----------------
let _linkClickTimer = null;

function setupPreviewEditing() {
    previewEl.addEventListener('click', (e) => {
        const a = e.target.closest && e.target.closest('a[href]');
        if (!a) return;
        if (a.closest('[contenteditable="true"]')) return;

        e.preventDefault();
        e.stopPropagation();

        if (_linkClickTimer) {
            clearTimeout(_linkClickTimer);
            _linkClickTimer = null;
            return;
        }

        _linkClickTimer = setTimeout(() => {
            _linkClickTimer = null;
            const href = a.getAttribute('href');
            if (!href) return;
            if (/^(https?:|mailto:)/i.test(href)) {
                if (window.pywebview && window.pywebview.api &&
                    window.pywebview.api.open_external_url) {
                    window.pywebview.api.open_external_url(href).catch(() => {});
                } else {
                    setStatus('无法打开外部链接：pywebview.api 未就绪');
                }
            } else {
                setStatus('不支持此链接协议：' + href);
            }
        }, 250);
    }, true);

    previewEl.addEventListener('dblclick', (e) => {
        const cell = e.target.closest && e.target.closest(
            'td[data-md-editable="1"], th[data-md-editable="1"]');
        if (cell) {
            startTableCellEdit(cell, e);
            return;
        }
        const el = e.target.closest && e.target.closest('[data-md-editable="1"]');
        if (!el) return;
        if (el.getAttribute('contenteditable') === 'true') return;

        if (activeEditableEl && activeEditableEl !== el) {
            exitEditable(activeEditableEl);
        }

        el.setAttribute('contenteditable', 'true');
        el.classList.add('preview-editing');
        activeEditableEl = el;
        el.focus();

        if (document.caretRangeFromPoint) {
            const range = document.caretRangeFromPoint(e.clientX, e.clientY);
            if (range) {
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            }
        }
    });

    previewEl.addEventListener('keydown', (e) => {
        const cell = e.target.closest && e.target.closest(
            'td[contenteditable="true"], th[contenteditable="true"]');
        if (!cell) return;
        if (e.key === 'Enter' || e.key === 'Tab' || e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            exitEditable(cell);
        }
    }, true);

    previewEl.addEventListener('blur', (e) => {
        const el = e.target;
        if (!el || !el.matches) return;
        if (!el.matches('[data-md-editable="1"]')) return;
        if (el.getAttribute('contenteditable') !== 'true') return;
        exitEditable(el);
    }, true);

    previewEl.addEventListener('compositionstart', () => {
        previewComposing = true;
    });
    previewEl.addEventListener('compositionend', () => {
        previewComposing = false;
    });

    previewEl.addEventListener('input', () => {
        if (previewComposing) return;
    });

    if (window.setupInlineFormat) {
        window.setupInlineFormat(previewEl, {
            isComposing: function () { return previewComposing; }
        });
    }
}

// ---------- 表格单元格编辑：启动 ----------
function startTableCellEdit(cell, e) {
    if (!cell) return;
    if (cell.getAttribute('contenteditable') === 'true') return;

    if (activeEditableEl && activeEditableEl !== cell) {
        exitEditable(activeEditableEl);
    }

    cell.setAttribute('contenteditable', 'true');
    cell.classList.add('preview-editing', 'table-cell-editing');
    activeEditableEl = cell;
    cell.focus();

    if (document.caretRangeFromPoint) {
        const range = document.caretRangeFromPoint(e.clientX, e.clientY);
        if (range) {
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        }
    }
}

// ---------- 表格单元格编辑：提交 ----------
function applyTableCellEdit(cell) {
    if (!cell || !cell.getAttribute) return;
    if (cell.getAttribute('data-md-editable') !== '1') return;
    if (!editorView) return;

    const oldText = cell.getAttribute('data-md-old-text') || '';
    const newText = cellToMarkdown(cell);
    if (newText === oldText) return;

    const tableEl = cell.closest('table');
    if (!tableEl) return;

    const rowIdx = parseInt(cell.getAttribute('data-md-row'), 10);
    const colIdx = parseInt(cell.getAttribute('data-md-col'), 10);
    if (!Number.isFinite(rowIdx) || !Number.isFinite(colIdx)) return;

    const tableStart = parseInt(tableEl.getAttribute('data-md-table-start'), 10);
    const tableEnd = parseInt(tableEl.getAttribute('data-md-table-end'), 10);
    if (!Number.isFinite(tableStart) || !Number.isFinite(tableEnd)) return;

    const md = getContent();
    if (tableStart < 0 || tableEnd > md.length || tableStart >= tableEnd) return;

    const tableSrc = md.slice(tableStart, tableEnd);
    const parsed = parseMarkdownTable(tableSrc);
    if (!parsed) {
        setStatus('表格解析失败，已放弃本次同步');
        return;
    }
    if (rowIdx >= parsed.rows.length || colIdx >= parsed.rows[rowIdx].length) {
        setStatus('表格单元格越界，已放弃本次同步');
        return;
    }

    parsed.rows[rowIdx][colIdx] = newText;
    const newTableSrc = serializeMarkdownTable(parsed);
    if (newTableSrc === tableSrc) return;

    const newMd = md.slice(0, tableStart) + newTableSrc + md.slice(tableEnd);
    const change = computeMinimalChange(md, newMd);

    syncingFromPreview = true;
    isSyncing = true;
    editorView.dispatch({
        changes: {
            from: change.from,
            to: change.to,
            insert: change.insert
        },
        annotations: [isolateHistory.of('full')]
    });
    isSyncing = false;
    syncingFromPreview = false;

    setStatus('表格编辑已同步到 Markdown');
}

// ---------- 表格编辑工具函数 ----------
function splitTableRow(line) {
    let s = String(line).trim();
    if (s.startsWith('|')) s = s.slice(1);
    if (s.endsWith('|')) s = s.slice(0, -1);

    const cells = [];
    let cur = '';
    for (let i = 0; i < s.length; i++) {
        const ch = s[i];
        if (ch === '\\' && i + 1 < s.length && s[i + 1] === '|') {
            cur += '|';
            i++;
        } else if (ch === '|') {
            cells.push(cur);
            cur = '';
        } else {
            cur += ch;
        }
    }
    cells.push(cur);
    return cells.map(c => c.trim());
}

function parseMarkdownTable(src) {
    const lines = String(src).split('\n').filter(l => l.trim() !== '');
    if (lines.length < 2) return null;

    const SEP_RE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/;
    if (!SEP_RE.test(lines[1])) return null;

    const rows = [];
    for (let i = 0; i < lines.length; i++) {
        if (i === 1) continue;
        rows.push(splitTableRow(lines[i]));
    }

    return {
        rows: rows,
        sepLine: lines[1],
        hasLeadingPipe: /^\s*\|/.test(lines[0]),
        hasTrailingPipe: /\|\s*$/.test(lines[0]),
    };
}

function serializeMarkdownTable(parsed) {
    const out = [];
    for (let r = 0; r < parsed.rows.length; r++) {
        const row = parsed.rows[r];
        out.push('| ' + row.join(' | ') + ' |');
        if (r === 0) {
            out.push(parsed.sepLine.trim());
        }
    }
    return out.join('\n');
}

function escapePipeForTable(s) {
    let out = '';
    for (let i = 0; i < s.length; i++) {
        const ch = s[i];
        if (ch === '|' && (i === 0 || s[i - 1] !== '\\')) {
            out += '\\|';
        } else {
            out += ch;
        }
    }
    return out;
}

function cellToMarkdown(cell) {
    let md = window.domToMarkdown ? window.domToMarkdown(cell) : cell.textContent;
    md = String(md).replace(/\s*\n\s*/g, ' ').replace(/\s+/g, ' ').trim();
    md = escapePipeForTable(md);
    return md;
}

// ---------------- 预览跨段选复制 ----------------
function setupPreviewCopy() {
    previewEl.addEventListener('copy', (e) => {
        const sel = window.getSelection();
        if (!sel || !sel.rangeCount || sel.isCollapsed) return;

        if (isInsideContentEditable(sel.anchorNode) ||
            isInsideContentEditable(sel.focusNode)) {
            return;
        }

        const range = sel.getRangeAt(0);
        if (!previewEl.contains(range.commonAncestorContainer) &&
            !previewEl.contains(sel.anchorNode)) {
            return;
        }

        try {
            const fragment = range.cloneContents();
            const wrap = document.createElement('div');
            wrap.appendChild(fragment);

            const md = fragmentToMarkdown(wrap);
            const plain = sel.toString();

            if (e.clipboardData) {
                if (md) {
                    e.clipboardData.setData('text/plain', md);
                } else {
                    e.clipboardData.setData('text/plain', plain);
                }
                e.clipboardData.setData('text/html', wrap.innerHTML);
                e.preventDefault();
                setStatus('已复制选中内容（Markdown 格式）');
            }
        } catch (err) {
            console.warn('[preview copy]', err);
        }
    });
}

function isInsideContentEditable(node) {
    if (!node) return false;
    let el = node.nodeType === 1 ? node : node.parentElement;
    while (el) {
        if (el.getAttribute && el.getAttribute('contenteditable') === 'true') {
            return true;
        }
        el = el.parentElement;
    }
    return false;
}

function fragmentToMarkdown(node) {
    let out = '';
    const children = node.childNodes;
    for (let i = 0; i < children.length; i++) {
        const child = children[i];
        if (child.nodeType === 3) {
            out += child.nodeValue;
            continue;
        }
        if (child.nodeType !== 1) continue;

        const tag = child.tagName.toLowerCase();

        if (/^h[1-6]$/.test(tag)) {
            const level = parseInt(tag[1], 10);
            out += '#'.repeat(level) + ' ' +
                   (window.domToMarkdown ? window.domToMarkdown(child) : child.textContent) +
                   '\n\n';
        } else if (tag === 'p') {
            out += (window.domToMarkdown ? window.domToMarkdown(child) : child.textContent) + '\n\n';
        } else if (tag === 'br') {
            out += '\n';
        } else if (tag === 'hr') {
            out += '---\n\n';
        } else if (tag === 'ul' || tag === 'ol') {
            const ordered = (tag === 'ol');
            let idx = 1;
            for (const li of child.children) {
                if (li.tagName.toLowerCase() !== 'li') continue;

                let prefix;
                if (li.classList && li.classList.contains('task-list-item')) {
                    const cb = li.querySelector('.task-list-checkbox');
                    const checked = cb && cb.getAttribute('data-md-task-checked') === '1';
                    prefix = '- ' + (checked ? '[x] ' : '[ ] ');
                } else if (ordered) {
                    prefix = (idx + '. ');
                    idx++;
                } else {
                    prefix = '- ';
                }

                const clone = li.cloneNode(true);
                const cbClone = clone.querySelector('.task-list-checkbox');
                if (cbClone) cbClone.remove();
                const bulletClone = clone.querySelector('.task-list-bullet');
                if (bulletClone) bulletClone.remove();

                let liText;
                let nested = '';
                const nestedList = clone.querySelector(':scope > ul, :scope > ol');
                if (nestedList) {
                    const nestedClone = nestedList.cloneNode(true);
                    nestedList.remove();
                    liText = window.domToMarkdown
                        ? window.domToMarkdown(clone)
                        : clone.textContent;
                    nested = fragmentToMarkdown(nestedClone);
                } else {
                    liText = window.domToMarkdown
                        ? window.domToMarkdown(clone)
                        : clone.textContent;
                }

                out += prefix + liText.trim() + '\n';
                if (nested) {
                    out += nested.split('\n').filter(l => l).map(l => '  ' + l).join('\n') + '\n';
                }
            }
            out += '\n';
        } else if (tag === 'blockquote') {
            const inner = fragmentToMarkdown(child);
            const lines = inner.split('\n');
            out += lines.map(l => l ? '> ' + l : '>').join('\n') + '\n\n';
        } else if (tag === 'pre') {
            const codeEl = child.querySelector('code');
            const text = codeEl ? codeEl.textContent : child.textContent;
            let lang = '';
            if (codeEl && codeEl.className) {
                const m = /language-([\w-]+)/.exec(codeEl.className);
                if (m) lang = m[1];
            }
            out += '```' + lang + '\n' + text.replace(/\n$/, '') + '\n```\n\n';
        } else if (tag === 'table') {
            out += tableToMarkdown(child) + '\n\n';
        } else if (tag === 'details') {
            const summary = child.querySelector(':scope > summary');
            const title = summary ? summary.textContent.trim() : '展开';
            let body = '';
            for (const sub of child.childNodes) {
                if (sub === summary) continue;
                const tmp = document.createElement('div');
                tmp.appendChild(sub.cloneNode(true));
                body += fragmentToMarkdown(tmp);
            }
            out += '<details>\n<summary>' + title + '</summary>\n\n' +
                   body.trim() + '\n\n</details>\n\n';
        } else if (tag === 'div' && child.classList &&
                   (child.classList.contains('math-block') ||
                    child.querySelector('.math-block'))) {
            const mb = child.classList.contains('math-block')
                ? child : child.querySelector('.math-block');
            if (mb) {
                const tex = mb.getAttribute('data-tex');
                if (tex) {
                    try {
                        const decoded = decodeURIComponent(tex);
                        out += '$$\n' + decoded + '\n$$\n\n';
                    } catch (e2) { /* ignore */ }
                }
            }
        } else if (child.querySelector && child.querySelector('.katex-inline, .math-block')) {
            out += fragmentToMarkdown(child);
        } else {
            out += window.domToMarkdown
                ? window.domToMarkdown(child)
                : child.textContent;
        }
    }
    return out.replace(/\n{3,}/g, '\n\n').replace(/^\n+|\n+$/g, '');
}

function tableToMarkdown(table) {
    const rows = [];
    const trs = table.querySelectorAll('tr');
    for (const tr of trs) {
        const cells = [];
        const childEls = tr.children;
        for (let i = 0; i < childEls.length; i++) {
            const c = childEls[i];
            const txt = window.domToMarkdown
                ? window.domToMarkdown(c)
                : c.textContent;
            cells.push(String(txt).replace(/\|/g, '\\|').replace(/\n/g, ' ').trim());
        }
        rows.push('| ' + cells.join(' | ') + ' |');
        if (rows.length === 1) {
            rows.push('| ' + cells.map(() => '---').join(' | ') + ' |');
        }
    }
    return rows.join('\n');
}

// ---------------- 状态栏路径点击 ----------------
function setupFilePathClick() {
    if (!filePathEl) return;
    filePathEl.addEventListener('click', async () => {
        const p = filePathEl.dataset.path || '';
        if (!p) {
            setStatus('当前文档尚未保存，无法定位所在位置');
            return;
        }
        if (!(window.pywebview && window.pywebview.api &&
              window.pywebview.api.reveal_in_explorer)) {
            setStatus('文件管理器接口未就绪');
            return;
        }
        try {
            const r = await window.pywebview.api.reveal_in_explorer(p);
            if (r && !r.ok) setStatus('无法打开目录: ' + (r.error || ''));
        } catch (e) {
            setStatus('打开目录失败: ' + (e && e.message ? e.message : e));
        }
    });
}

function setFilePathDisplay(path, customText) {
    if (!filePathEl) return;
    if (path) {
        filePathEl.textContent = path;
        filePathEl.title = path;
        filePathEl.classList.remove('no-file');
        filePathEl.dataset.path = path;
    } else {
        const txt = customText || '未命名';
        filePathEl.textContent = txt;
        filePathEl.title = txt;
        filePathEl.classList.add('no-file');
        filePathEl.dataset.path = '';
    }
}

// ---------------- 全局键盘 ----------------
function setupGlobalKeyboard() {
    document.addEventListener('keydown', (e) => {
        const isCtrl = e.ctrlKey || e.metaKey;
        if (!isCtrl) return;

        const k = (e.key || '').toLowerCase();

        const isUndo = (k === 'z' && !e.shiftKey);
        const isRedo = (k === 'y') || (k === 'z' && e.shiftKey);
        if (isUndo || isRedo) {
            const activeEl = document.activeElement;
            if (activeEl && activeEl.closest &&
                (activeEl.closest('#editor') || activeEl.closest('.cm-editor'))) {
                return;
            }
            e.preventDefault();
            e.stopPropagation();
            if (isUndo) onUndo(); else onRedo();
            return;
        }

        if (k === 'n' && !e.shiftKey) {
            e.preventDefault(); onNew(); return;
        }
        if (k === 'o' && !e.shiftKey) {
            e.preventDefault(); onOpen(); return;
        }
        if (k === 's') {
            e.preventDefault();
            if (e.shiftKey) onSaveAs(); else onSave();
            return;
        }
        if (k === 'q' && !e.shiftKey) {
            e.preventDefault(); onExit(); return;
        }
        if (k === 'w') {
            e.preventDefault();
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.close_window().catch(() => {});
            }
            return;
        }
        if (k === '1') { e.preventDefault(); setMode('edit'); return; }
        if (k === '2') { e.preventDefault(); setMode('split'); return; }
        if (k === '3') { e.preventDefault(); setMode('preview'); return; }
        if (k === 'b') { e.preventDefault(); toggleToc(); return; }
        if (k === '=' || k === '+') { e.preventDefault(); zoomIn(); return; }
        if (k === '-') { e.preventDefault(); zoomOut(); return; }
        if (k === '0') { e.preventDefault(); zoomReset(); return; }
        if (k === 'i' && e.shiftKey) {
            e.preventDefault(); onInsertImage(); return;
        }
        if (k === 'f' && !e.shiftKey) {
            e.preventDefault();
            if (window.FindBar) window.FindBar.open(false);
            return;
        }
        if (k === 'h' && !e.shiftKey) {
            e.preventDefault();
            if (window.FindBar) window.FindBar.open(true);
            return;
        }
    }, true);
}

// ---------------- 退出预览编辑（分派） ----------------
function exitEditable(el) {
    if (!el) return;

    const tag = (el.tagName || '').toLowerCase();
    const isTableCell = (tag === 'td' || tag === 'th') &&
        el.getAttribute('data-md-table-index') != null;

    if (isTableCell) {
        applyTableCellEdit(el);
    } else {
        applyPreviewEdit(el);
    }

    el.setAttribute('contenteditable', 'false');
    el.classList.remove('preview-editing', 'table-cell-editing');
    if (activeEditableEl === el) activeEditableEl = null;
    updatePreview();
}

function computeMinimalChange(oldStr, newStr) {
    let start = 0;
    const oldLen = oldStr.length;
    const newLen = newStr.length;
    while (start < oldLen && start < newLen &&
           oldStr.charCodeAt(start) === newStr.charCodeAt(start)) {
        start++;
    }
    let oldEnd = oldLen;
    let newEnd = newLen;
    while (oldEnd > start && newEnd > start &&
           oldStr.charCodeAt(oldEnd - 1) === newStr.charCodeAt(newEnd - 1)) {
        oldEnd--;
        newEnd--;
    }
    return {
        from: start,
        to: oldEnd,
        insert: newStr.slice(start, newEnd)
    };
}

function applyPreviewEdit(el) {
    if (!el || !el.getAttribute) return;
    if (el.getAttribute('data-md-editable') !== '1') return;

    const startStr = el.getAttribute('data-md-start');
    const endStr = el.getAttribute('data-md-end');
    const oldText = el.getAttribute('data-md-old-text') || '';
    if (startStr == null || endStr == null) return;

    const start = parseInt(startStr, 10);
    const end = parseInt(endStr, 10);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return;

    const newText = window.domToMarkdown
        ? window.domToMarkdown(el)
        : (window.getEditableText ? window.getEditableText(el) : el.textContent);

    function stripWs(s) { return String(s).replace(/\s+/g, ''); }
    if (stripWs(newText) === stripWs(oldText)) return;

    const md = getContent();

    if (md.slice(start, end) !== oldText) {
        setStatus('预览编辑与源文本已不一致，已放弃本次同步');
        return;
    }

    const newMd = md.slice(0, start) + newText + md.slice(end);
    const change = computeMinimalChange(md, newMd);

    syncingFromPreview = true;
    isSyncing = true;
    editorView.dispatch({
        changes: {
            from: change.from,
            to: change.to,
            insert: change.insert
        },
        annotations: [isolateHistory.of('full')]
    });
    isSyncing = false;
    syncingFromPreview = false;

    const newEnd = start + newText.length;
    el.setAttribute('data-md-old-text', newText);
    el.setAttribute('data-md-end', String(newEnd));

    updateStats();
    setStatus('预览编辑已同步到 Markdown');
}

// ---------------- 文件 ----------------
// ★ 阶段 15 修订 6：新建（脏标记驱动，自定义确认弹窗）
async function onNew() {
    if (isDirty) {
        const ok = await showConfirm(
            T('unsaved_content_title', '未保存的内容'),
            T('unsaved_content_warning', '未保存的内容将丢失，继续？')
        );
        if (!ok) return;
    }

    currentFile = '';
    currentDocDir = '';
    syncGlobalFileState();          // ★ 阶段 15 修订 10

    setContent('');
    setFilePathDisplay('');
    setStatus('新建文档');
    try { await window.pywebview.api.set_current_file(''); } catch (e) {}
}

// ★ 阶段 15 修订 10：先设路径，后 setContent
async function onOpen() {
    const result = await window.pywebview.api.open_file_dialog();
    if (!result.ok) {
        if (!result.cancelled) setStatus('打开失败: ' + (result.error || ''));
        return;
    }

    // ★★★ 先设路径，再 setContent ★★★
    currentFile = result.path || '';
    currentDocDir = result.path
        ? result.path.replace(/[\\/][^\\/]+$/, '')
        : '';
    syncGlobalFileState();

    setContent(result.content);

    if (result.path) {
        setFilePathDisplay(result.path);
    } else if (result.source_pdf) {
        setFilePathDisplay('', '（来自 PDF）');
    } else {
        setFilePathDisplay('');
    }
    if (result.imported) {
        setStatus('已从 PDF 导入');
    } else {
        setStatus('已打开');
    }
    try { await window.pywebview.api.set_current_file(currentFile || ''); } catch (e) {}
}

async function onSave() {
    const result = await window.pywebview.api.save_file(getContent());
    if (!result.ok) {
        if (!result.cancelled) setStatus('保存失败: ' + (result.error || ''));
        return;
    }
    if (result.path && result.path.toLowerCase().endsWith('.pdf')) {
        currentFile = '';
        currentDocDir = '';
        syncGlobalFileState();      // ★ 阶段 15 修订 10
        setFilePathDisplay('', '（已导出 PDF）');
        setStatus('已导出 PDF：' + result.path);
        return;
    }
    currentFile = result.path;
    currentDocDir = result.path.replace(/[\\/][^\\/]+$/, '');
    syncGlobalFileState();          // ★ 阶段 15 修订 10
    setFilePathDisplay(result.path);
    setStatus('已保存');
    // ★ 阶段 15 修订 6：保存成功 → 清除脏标记
    isDirty = false;
    try { await window.pywebview.api.set_current_file(currentFile || ''); } catch (e) {}
}

async function onSaveAs() {
    const result = await window.pywebview.api.save_file_as(getContent());
    if (!result.ok) {
        if (!result.cancelled) setStatus('保存失败: ' + (result.error || ''));
        return;
    }
    if (result.path && result.path.toLowerCase().endsWith('.pdf')) {
        currentFile = '';
        currentDocDir = '';
        syncGlobalFileState();      // ★ 阶段 15 修订 10
        setFilePathDisplay('', '（已导出 PDF）');
        setStatus('已导出 PDF：' + result.path);
        return;
    }
    currentFile = result.path;
    currentDocDir = result.path.replace(/[\\/][^\\/]+$/, '');
    syncGlobalFileState();          // ★ 阶段 15 修订 10
    setFilePathDisplay(result.path);
    setStatus('已另存为');
    // ★ 阶段 15 修订 6：另存成功 → 清除脏标记
    isDirty = false;
    try { await window.pywebview.api.set_current_file(currentFile || ''); } catch (e) {}
}

// ---------------- 插入图片 ----------------
async function onInsertImage() {
    try {
        const result = await window.pywebview.api.open_image_picker();
        if (!result || !result.ok) {
            setStatus('打开图片选择器失败: ' + ((result && result.error) || '未知错误'));
        } else {
            setStatus('请选择图片...');
        }
    } catch (e) {
        setStatus('打开图片选择器异常: ' + (e && e.message ? e.message : e));
    }
}

window.onImagePickerResult = function (payload) {
    if (!payload) return;
    if (typeof payload === 'string') {
        insertImageMarkdown_fromText(payload, false);
        return;
    }
    const md = payload.md || '';
    const unsaved = !!payload.unsaved;
    insertImageMarkdown_fromText(md, unsaved);
};

function insertImageMarkdown_fromText(mdText, unsaved) {
    if (!editorView || !mdText) return;
    const cursor = editorView.state.selection.main.head;
    const doc = editorView.state.doc.toString();
    let insert = mdText;
    const before = doc.slice(Math.max(0, cursor - 2), cursor);
    if (cursor > 0 && !/\n\s*$/.test(before)) {
        insert = '\n\n' + insert;
    }
    if (cursor < doc.length && !/^\s*\n/.test(doc.slice(cursor, cursor + 2))) {
        insert = insert + '\n\n';
    }
    editorView.dispatch({
        changes: { from: cursor, to: cursor, insert: insert },
        selection: { anchor: cursor + insert.length },
    });
    editorView.focus();
    updatePreview();
    setStatus(unsaved
        ? '图片已插入（文档未保存，使用绝对路径）'
        : '图片已插入');
}

// ---------------- PDF ----------------
// ★ 阶段 15 修订 10：先设路径，后 setContent
async function onImportPdf() {
    setStatus('正在导入 PDF...');
    const result = await window.pywebview.api.import_pdf_dialog();
    if (!result.ok) {
        if (!result.cancelled) setStatus('PDF 导入失败: ' + (result.error || ''));
        return;
    }

    currentFile = '';
    currentDocDir = result.source_pdf
        ? result.source_pdf.replace(/[\\/][^\\/]+$/, '')
        : '';
    syncGlobalFileState();

    setContent(result.content);
    setFilePathDisplay('', '（来自 PDF）');
    setStatus('PDF 导入完成');
    try { await window.pywebview.api.set_current_file(''); } catch (e) {}
}

async function onExportPdf() {
    setStatus('正在导出 PDF...');
    const result = await window.pywebview.api.export_pdf(getContent());
    if (!result.ok) {
        if (!result.cancelled) setStatus('PDF 导出失败: ' + (result.error || ''));
        return;
    }
    let msg = `PDF 导出成功: ${result.path}（${result.size} 字节）`;
    if (result.embedded) msg += '，已嵌入 Markdown 源';
    setStatus(msg);
}

// ============================================================
//  通用消息弹窗
// ============================================================
function setupMessageModal() {
    const modal = document.getElementById('message-modal');
    if (!modal) return;
    const okBtn = document.getElementById('message-modal-ok');
    if (okBtn) {
        okBtn.addEventListener('click', () => {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        });
    }
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        }
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        }
    });
}

function showMessage(title, body) {
    const modal = document.getElementById('message-modal');
    if (!modal) return;
    const titleEl = document.getElementById('message-modal-title');
    const bodyEl = document.getElementById('message-modal-body');
    if (titleEl) titleEl.textContent = title || '';
    if (bodyEl) bodyEl.textContent = body || '';
    modal.style.display = '';
    modal.classList.remove('hidden');
}

// ============================================================
//  ★ 阶段 15 修订 6：通用「确认」弹窗（Promise 化）
//  —— 替代 window.confirm()，避免出现 "127.0.0.1:6237 显示" 原生弹窗
// ============================================================
function showConfirm(title, message) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';

        const modal = document.createElement('div');
        modal.className = 'modal message-modal';
        modal.style.maxWidth = '440px';
        modal.style.width = '92%';

        const h3 = document.createElement('h3');
        h3.textContent = title || '';

        const p = document.createElement('p');
        p.className = 'message-modal-body';
        p.textContent = message || '';

        const actions = document.createElement('div');
        actions.className = 'modal-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn-plain';
        cancelBtn.textContent = T('cancel', '取消');

        const okBtn = document.createElement('button');
        okBtn.type = 'button';
        okBtn.className = 'btn-primary';
        okBtn.textContent = T('confirm', '确定');

        actions.appendChild(cancelBtn);
        actions.appendChild(okBtn);
        modal.appendChild(h3);
        modal.appendChild(p);
        modal.appendChild(actions);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        let done = false;
        function finish(result) {
            if (done) return;
            done = true;
            document.removeEventListener('keydown', onKey, true);
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            resolve(result);
        }
        function onKey(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                finish(false);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                e.stopPropagation();
                finish(true);
            }
        }

        cancelBtn.addEventListener('click', () => finish(false));
        okBtn.addEventListener('click', () => finish(true));
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) finish(false);
        });
        document.addEventListener('keydown', onKey, true);

        setTimeout(() => okBtn.focus(), 20);
    });
}

// ============================================================
//  检查更新
// ============================================================
function setupUpdateModal() {
    const modal = document.getElementById('update-modal');
    if (!modal) return;

    const openBtn = document.getElementById('update-open');
    const laterBtn = document.getElementById('update-later');

    if (laterBtn) {
        laterBtn.addEventListener('click', () => {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        });
    }
    if (openBtn) {
        openBtn.addEventListener('click', () => {
            const url = modal.dataset.url || 'https://github.com/zbt00123/MarkEase/releases';
            if (window.pywebview && window.pywebview.api &&
                window.pywebview.api.open_external_url) {
                window.pywebview.api.open_external_url(url).catch(() => {});
            }
            modal.classList.add('hidden');
            modal.style.display = 'none';
        });
    }
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        }
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        }
    });
}

function renderUpdateNotes(notes, target) {
    if (!target) return;
    target.innerHTML = '';
    const text = String(notes || '').trim();
    if (!text) return;

    try {
        if (window.renderMarkdown) {
            window.renderMarkdown(text, { target: target, docDir: '' });
        } else {
            target.textContent = text;
        }
    } catch (e) {
        console.warn('[update] render notes failed', e);
        target.textContent = text;
    }
}

function showUpdateModal(info) {
    const modal = document.getElementById('update-modal');
    if (!modal) return;

    lastUpdateInfo = info;

    const titleEl = document.getElementById('update-modal-title');
    if (titleEl) titleEl.textContent = T('update_available_title', '发现新版本');

    const curEl = document.getElementById('update-current-version');
    const latestEl = document.getElementById('update-latest-version');
    if (curEl) curEl.textContent = 'v' + (info.current_version || '-');
    if (latestEl) latestEl.textContent = 'v' + (info.latest_version || '-');

    const notesEl = document.getElementById('update-notes');
    renderUpdateNotes(info.notes, notesEl);

    modal.dataset.url = info.html_url || 'https://github.com/zbt00123/MarkEase/releases';

    if (window.I18N && window.I18N.applyToDOM) {
        window.I18N.applyToDOM(modal);
    }
    if (titleEl) titleEl.textContent = T('update_available_title', '发现新版本');

    modal.style.display = '';
    modal.classList.remove('hidden');
}

async function onCheckUpdate(silent) {
    if (!silent) {
        setStatus(T('checking', '检查中...'));
    }

    try {
        const r = await window.pywebview.api.check_update(false);

        if (!r || !r.ok) {
            if (!silent) {
                setStatus(T('ready', '就绪'));
                showMessage(
                    T('update_error_title', '检查更新失败'),
                    T('update_error_message', '无法连接到 GitHub，请稍后重试。')
                );
            }
            return;
        }

        if (r.has_update) {
            showUpdateModal(r);
            if (!silent) setStatus(T('update_available_title', '发现新版本'));
        } else {
            if (!silent) {
                setStatus(T('ready', '就绪'));
                const msg = T('update_latest_message', '当前已是最新版本（v{version}）。')
                    .replace('{version}', r.current_version || '');
                showMessage(T('update_latest_title', '已是最新版本'), msg);
            }
        }
    } catch (e) {
        if (!silent) {
            setStatus(T('ready', '就绪'));
            showMessage(
                T('update_error_title', '检查更新失败'),
                T('update_error_message', '无法连接到 GitHub，请稍后重试。')
            );
            console.warn('[update] check failed', e);
        }
    }
}

function scheduleSilentUpdateCheck() {
    setTimeout(async () => {
        try {
            const r = await window.pywebview.api.maybe_check_update();
            if (!r) return;
            if (r.skipped) return;
            if (r.ok && r.has_update) {
                showUpdateModal(r);
            }
        } catch (e) {
            console.warn('[update] silent check failed', e);
        }
    }, 5000);
}

// ---------------- 主题 ----------------
async function loadSettings(preloaded) {
    let settings = preloaded;
    try {
        if (!settings) {
            settings = await window.pywebview.api.get_settings();
        }
        applyTheme(settings.theme || 'system');
        const zp = parseInt(settings.zoom_percent, 10);
        if (Number.isFinite(zp) && zp >= 10 && zp <= 500) {
            zoomLevel = zp;
        }
    } catch (e) {
        console.warn('加载设置失败', e);
    }
}

function isDarkTheme(theme) {
    if (theme === 'dark') return true;
    if (theme === 'light') return false;
    return window.matchMedia &&
        window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function applyTheme(theme) {
    const dark = isDarkTheme(theme);
    document.documentElement.classList.toggle('dark', dark);
    document.body.classList.toggle('dark', dark);
    reconfigureEditorTheme(dark);
    try {
        localStorage.setItem('markease_theme', theme);
    } catch (e) { /* ignore */ }

    // ★ 阶段 15 修订 6：通知关于窗口刷新主题（若未打开则自动跳过）
    try {
        if (window.pywebview && window.pywebview.api &&
            window.pywebview.api.notify_about_refresh) {
            window.pywebview.api.notify_about_refresh().catch(() => {});
        }
    } catch (e) { /* ignore */ }
}

function reconfigureEditorTheme(dark) {
    if (!editorView) return;
    const style = dark ? darkHighlight : lightHighlight;
    editorView.dispatch({
        effects: themeCompartment.reconfigure(syntaxHighlighting(style))
    });
}

function toggleTheme() {
    const isDark = document.body.classList.contains('dark');
    const newTheme = isDark ? 'light' : 'dark';
    applyTheme(newTheme);
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.set_theme(newTheme);
    }
}

function setStatus(text) { statusEl.textContent = text; }