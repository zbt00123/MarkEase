// MarkEase 主逻辑（阶段 16-13 修复 2）
//   ★ 本轮修改：
//     1) 新增 extractLiInlineText：li 编辑时只提取 inline 内容
//     2) applyPreviewEdit 用 extractLiInlineText 处理 li
//     3) applyPreviewEdit 加三重异常防护（跨行 / 膨胀 / 无输入）
//     4) enterEditable 增加 _editableHadInput 标记
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

let isDirty = false;
let _lastSyncedDirty = null;

function setDirty(v) {
    isDirty = !!v;
    if (_lastSyncedDirty === isDirty) return;
    _lastSyncedDirty = isDirty;
    try {
        if (window.pywebview && window.pywebview.api &&
            window.pywebview.api.set_dirty) {
            window.pywebview.api.set_dirty(isDirty).catch(() => {});
        }
    } catch (e) { /* ignore */ }
}

let previewComposing = false;
let activeEditableEl = null;

// ★ 阶段 16-13：标记当前编辑元素是否真的被用户输入过
let _editableHadInput = false;

let currentLangChoice = 'system';
let lastUpdateInfo = null;

let _syncAnchors = [];
let _editorScrollRaf = null;
let _previewScrollRaf = null;
let _editorTocRaf = null;
let _scrollLock = null;
let _scrollLockTimer = null;

const SCROLL_LOCK_MS = 90;
const TOC_JUMP_LOCK_MS = 280;

let _lastPreviewUpdateTs = 0;
const MIN_PREVIEW_INTERVAL = 60;

let _tocScrolling = false;
let _lastActiveTocLine = null;

const themeCompartment = new Compartment();

const previewEl = document.getElementById('preview');
const mainEl = document.getElementById('main');
const filePathEl = document.getElementById('file-path');
const statusEl = document.getElementById('status-text');
const statsEl = document.getElementById('stats-text');
const tocEl = document.getElementById('toc');
const tocListEl = document.getElementById('toc-list');

let pendingDragConflict = null;

let _forceSaveAsNextTime = false;
let _openedOriginalContent = '';
let _openedFilePath = '';

let _footnoteRefsSnapshot = null;
let _footnoteCleanupTimer = null;

let _ctxMenuEl = null;

// ---------------- i18n 辅助 ----------------
function T(key, fallback) {
    try {
        if (window.I18N && typeof window.I18N.t === 'function') {
            return window.I18N.t(key);
        }
    } catch (e) { /* ignore */ }
    return fallback || key;
}

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
    if (window.__markEaseInitialized) {
        console.warn('[pywebviewready] skipped: already initialized');
        return;
    }
    window.__markEaseInitialized = true;

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
        setupEditorCtrlClick();
        setupEditorContextMenu();
        setupPreviewContextMenu();
        await loadSettings(settings);
        initZoomBar();

        await openStartupFileIfAny();

        _openedOriginalContent = getContent();
        _openedFilePath = currentFile || '';
        _forceSaveAsNextTime = false;

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

async function openStartupFileIfAny() {
    if (!(window.pywebview && window.pywebview.api &&
          window.pywebview.api.get_startup_file)) {
        return;
    }
    try {
        const r = await window.pywebview.api.get_startup_file();
        if (!r) return;

        if (r.ok && r.content != null) {
            currentFile = r.path || '';
            currentDocDir = r.doc_dir
                ? String(r.doc_dir)
                : (r.path ? r.path.replace(/[\\/][^\\/]+$/, '') : '');
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

            console.log('[startup] opened:', r.path, 'docDir:', currentDocDir);
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
    if (editorView) {
        console.warn('[initEditor] skipped: already initialized');
        return;
    }

    const updateListener = EditorView.updateListener.of(update => {
        if (update.docChanged) {
            setDirty(true);
            if (!isSyncing) {
                if (!syncingFromPreview) {
                    updatePreview();
                }
                updateStats();
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.update_content(getContent());
                }
                if (!syncingFromPreview) {
                    scheduleFootnoteCleanup();
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

// ============================================================
//  脚注引用自动清理
// ============================================================
function scheduleFootnoteCleanup() {
    if (_footnoteCleanupTimer) clearTimeout(_footnoteCleanupTimer);
    _footnoteCleanupTimer = setTimeout(() => {
        _footnoteCleanupTimer = null;
        cleanupOrphanFootnotes();
    }, 200);
}

function cleanupOrphanFootnotes() {
    if (!editorView) return;
    if (syncingFromPreview || isSyncing) return;

    const doc = editorView.state.doc;
    const text = doc.toString();

    const refsNow = new Set();
    const refRe = /\[\^([^\]\s]+)\](?!:)/g;
    let m;
    while ((m = refRe.exec(text)) !== null) {
        refsNow.add(m[1]);
    }

    if (_footnoteRefsSnapshot === null) {
        _footnoteRefsSnapshot = refsNow;
        return;
    }

    const orphans = new Set();
    for (const key of _footnoteRefsSnapshot) {
        if (!refsNow.has(key)) orphans.add(key);
    }

    _footnoteRefsSnapshot = refsNow;

    if (orphans.size === 0) return;

    const changes = [];
    const lines = text.split('\n');
    let offset = 0;
    const defLineRe = /^[ \t]*\[\^([^\]\s]+)\]:/;
    for (const line of lines) {
        const dm = defLineRe.exec(line);
        if (dm && orphans.has(dm[1])) {
            const lineStart = offset;
            const lineEnd = offset + line.length;
            const hasNewline = lineEnd < text.length && text.charAt(lineEnd) === '\n';
            changes.push({
                from: lineStart,
                to: hasNewline ? lineEnd + 1 : lineEnd,
                insert: ''
            });
        }
        offset += line.length + 1;
    }

    if (changes.length === 0) return;

    changes.sort((a, b) => b.from - a.from);

    try {
        editorView.dispatch({
            changes,
            annotations: [isolateHistory.of('full')]
        });
    } catch (e) {
        console.warn('[footnote cleanup] dispatch failed', e);
    }
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
        import_html: onImportHtml,
        export_html: onExportHtml,
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
    const beforeDoc = editorView.state.doc.toString();
    undo({ state: editorView.state, dispatch: editorView.dispatch });
    const afterDoc = editorView.state.doc.toString();

    if (_openedFilePath && currentFile === _openedFilePath) {
        if (afterDoc !== beforeDoc) {
            _forceSaveAsNextTime = true;
        }
    }

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
    closeContextMenu();
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
    if (typeof window.__updateTocResizerPosition === 'function') {
        setTimeout(window.__updateTocResizerPosition, 60);
    }
    setTimeout(() => {
        if (mode === 'edit') updateTocByEditorScroll();
        else updateActiveTocByScroll();
    }, 80);
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
    if (typeof window.__updateTocResizerPosition === 'function') {
        window.__updateTocResizerPosition();
        setTimeout(window.__updateTocResizerPosition, 60);
    }
    if (!tocEl.classList.contains('hidden')) {
        setTimeout(() => {
            if (mode === 'edit') updateTocByEditorScroll();
            else updateActiveTocByScroll();
        }, 60);
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
    setDirty(false);
    _footnoteRefsSnapshot = null;
    updatePreview();
    updateStats();
    if (window.Toolbar) window.Toolbar.refresh();
}

// ---------------- 预览 ----------------
function updatePreview() {
    syncGlobalFileState();

    const previewContainer = previewEl.parentElement;
    const savedScrollTop = (!_tocScrolling && previewContainer)
        ? previewContainer.scrollTop
        : null;

    activeEditableEl = null;
    window.renderMarkdown(getContent(), {
        target: previewEl,
        docDir: currentDocDir
    });
    annotatePreviewBlocks();
    rebuildToc();
    updateSyncAnchors();
    updateActiveTocByScroll();

    if (savedScrollTop != null && previewContainer) {
        previewContainer.scrollTop = savedScrollTop;
    }
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
    const content = getContent();
    const lines = content.split('\n');

    const headings = [];
    for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
        if (m) {
            headings.push({
                level: m[1].length,
                text: m[2],
                line: i,
            });
        }
    }

    tocListEl.innerHTML = '';
    headings.forEach(h => {
        const el = document.createElement('div');
        el.className = 'toc-item toc-level-' + h.level;
        el.textContent = stripMdInline(h.text);
        el.dataset.line = String(h.line);
        el.addEventListener('click', () => scrollEditorToLine(h.line));
        tocListEl.appendChild(el);
    });

    _lastActiveTocLine = null;

    applyTocAnchors(headings);
}

function applyTocAnchors(headings) {
    if (!previewEl) return;

    previewEl.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(el => {
        el.removeAttribute('data-line');
    });

    if (!headings || headings.length === 0) return;

    const domHeads = Array.from(
        previewEl.querySelectorAll('h1,h2,h3,h4,h5,h6')
    );
    if (domHeads.length === 0) return;

    function norm(s) {
        return String(s || '')
            .replace(/<[^>]+>/g, '')
            .replace(/\s+/g, '')
            .toLowerCase();
    }

    let domIdx = 0;

    for (let hi = 0; hi < headings.length; hi++) {
        const h = headings[hi];
        const wantLevel = h.level;
        const wantText = norm(stripMdInline(h.text));

        for (let j = domIdx; j < domHeads.length; j++) {
            const el = domHeads[j];
            const elLevel = parseInt(el.tagName.substring(1), 10);
            if (elLevel !== wantLevel) continue;
            const elText = norm(el.textContent);
            if (elText === wantText) {
                el.setAttribute('data-line', String(h.line));
                domIdx = j + 1;
                break;
            }
        }
    }
}

function scrollEditorToLine(line) {
    if (!editorView) return;
    const doc = editorView.state.doc;
    if (line < 0 || line >= doc.lines) return;

    try { updateSyncAnchors(); } catch (e) { /* ignore */ }

    if (mode !== 'preview') {
        try {
            const lineInfo = doc.line(line + 1);
            editorView.dispatch({
                selection: { anchor: lineInfo.from }
            });

            requestAnimationFrame(() => {
                try {
                    const block = editorView.lineBlockAt(lineInfo.from);
                    const scroller = document.querySelector('#editor .cm-scroller');
                    if (scroller && block) {
                        const h = scroller.clientHeight;
                        const target = block.top - h / 3;
                        scroller.scrollTop = Math.max(0, target);
                    }
                } catch (e) { /* ignore */ }
            });
        } catch (e) { /* ignore */ }
    }

    const previewContainer = previewEl.parentElement;
    if (!previewContainer) {
        if (mode !== 'preview') editorView.focus();
        return;
    }

    _acquireScrollLockLong('editor');
    _tocScrolling = true;

    const doPreviewScroll = () => {
        try {
            const target = previewEl.querySelector('[data-line="' + line + '"]');
            if (!target) return;
            const containerRect = previewContainer.getBoundingClientRect();
            const targetRect = target.getBoundingClientRect();
            const targetTop = targetRect.top - containerRect.top +
                              previewContainer.scrollTop;
            const h = previewContainer.clientHeight;
            const desired = targetTop - h / 3;
            previewContainer.scrollTop = Math.max(0, desired);
        } catch (e) { /* ignore */ }
    };

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            doPreviewScroll();
            setTimeout(() => {
                _setActiveTocItem(String(line), true);
                _tocScrolling = false;
                try { updateSyncAnchors(); } catch (e) { /* ignore */ }
            }, 60);
        });
    });

    if (mode !== 'preview') {
        editorView.focus();
    }
}

function _setActiveTocItem(lineStr, forceScroll) {
    if (lineStr == null) return;
    if (lineStr === _lastActiveTocLine && !forceScroll) return;

    document.querySelectorAll('.toc-item').forEach(el => {
        el.classList.toggle('active', el.dataset.line === lineStr);
    });

    _lastActiveTocLine = lineStr;

    scrollTocToActive();
}

function scrollTocToActive() {
    if (!tocEl || !tocListEl) return;
    if (tocEl.classList.contains('hidden')) return;

    const activeEl = tocListEl.querySelector('.toc-item.active');
    if (!activeEl) return;

    const tocRect = tocEl.getBoundingClientRect();
    const itemRect = activeEl.getBoundingClientRect();

    if (itemRect.top >= tocRect.top && itemRect.bottom <= tocRect.bottom) {
        return;
    }

    const itemTopRel = itemRect.top - tocRect.top + tocEl.scrollTop;
    const desired = itemTopRel - (tocEl.clientHeight - itemRect.height) / 2;
    const maxTop = tocEl.scrollHeight - tocEl.clientHeight;
    tocEl.scrollTop = Math.max(0, Math.min(maxTop, desired));
}

function updateActiveTocByScroll() {
    if (!previewEl || !previewEl.parentElement) return;

    const heads = previewEl.querySelectorAll('[data-line]');
    if (heads.length === 0) {
        _setActiveTocItem(null);
        return;
    }

    const containerRect = previewEl.parentElement.getBoundingClientRect();
    const pivot = containerRect.top + containerRect.height / 2;

    let activeLine = null;

    for (let i = 0; i < heads.length; i++) {
        const rect = heads[i].getBoundingClientRect();
        if (rect.top < pivot) {
            activeLine = heads[i].getAttribute('data-line');
        } else {
            break;
        }
    }

    if (activeLine == null) {
        activeLine = heads[0].getAttribute('data-line');
    }

    _setActiveTocItem(activeLine);
}

function updateTocByEditorScroll() {
    if (!editorView) return;

    const scroller = document.querySelector('#editor .cm-scroller');
    if (!scroller) return;

    let block;
    try {
        block = editorView.lineBlockAtHeight(
            scroller.scrollTop + scroller.clientHeight / 2
        );
    } catch (e) { return; }
    if (!block) return;

    const pivotPos = block.from;

    const tocItems = document.querySelectorAll('.toc-item');
    if (tocItems.length === 0) return;

    const doc = editorView.state.doc;
    let activeLine = null;

    for (let i = 0; i < tocItems.length; i++) {
        const line = parseInt(tocItems[i].dataset.line, 10);
        if (!Number.isFinite(line)) continue;
        try {
            const lineFrom = doc.line(line + 1).from;
            if (lineFrom < pivotPos) {
                activeLine = tocItems[i].dataset.line;
            } else {
                break;
            }
        } catch (e) { /* ignore */ }
    }

    if (activeLine == null && tocItems.length > 0) {
        activeLine = tocItems[0].dataset.line;
    }

    _setActiveTocItem(activeLine);
}

// ---------------- 目录宽度拖动 ----------------
function setupTocResizer() {
    const resizer = document.getElementById('toc-resizer');
    if (!resizer || !tocEl) return;

    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    function updateResizerPosition() {
        if (!resizer || !tocEl || !mainEl) return;
        if (tocEl.classList.contains('hidden')) {
            resizer.style.display = 'none';
            return;
        }
        resizer.style.display = '';
        const tocRect = tocEl.getBoundingClientRect();
        const mainRect = mainEl.getBoundingClientRect();
        const leftPx = tocRect.right - mainRect.left;
        resizer.style.left = leftPx + 'px';
    }

    updateResizerPosition();

    if (window.ResizeObserver) {
        const ro = new ResizeObserver(() => updateResizerPosition());
        ro.observe(tocEl);
    }

    window.addEventListener('resize', updateResizerPosition);

    window.__updateTocResizerPosition = updateResizerPosition;

    resizer.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        startX = e.clientX;
        startWidth = tocEl.clientWidth;
        e.preventDefault();
        e.stopPropagation();
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        resizer.classList.add('dragging');
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const dx = e.clientX - startX;
        const newW = Math.max(120, Math.min(600, startWidth + dx));
        tocEl.style.width = newW + 'px';
        updateResizerPosition();
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        resizer.classList.remove('dragging');
        updateResizerPosition();
        if (window.Toolbar && typeof window.Toolbar.relayout === 'function') {
            window.Toolbar.relayout();
        }
        updateSyncAnchors();
    });
}

// ============================================================
//  同步滚动
// ============================================================
function _acquireScrollLock(src) {
    _scrollLock = src;
    if (_scrollLockTimer) clearTimeout(_scrollLockTimer);
    _scrollLockTimer = setTimeout(() => {
        if (_scrollLock === src) _scrollLock = null;
        _scrollLockTimer = null;
    }, SCROLL_LOCK_MS);
}

function _acquireScrollLockLong(src) {
    _scrollLock = src;
    if (_scrollLockTimer) clearTimeout(_scrollLockTimer);
    _scrollLockTimer = setTimeout(() => {
        if (_scrollLock === src) _scrollLock = null;
        _scrollLockTimer = null;
    }, TOC_JUMP_LOCK_MS);
}

function _releaseScrollLockSoon(src) {
    if (_scrollLockTimer) clearTimeout(_scrollLockTimer);
    _scrollLockTimer = setTimeout(() => {
        if (_scrollLock === src) _scrollLock = null;
        _scrollLockTimer = null;
    }, SCROLL_LOCK_MS);
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
    if (mode === 'edit') {
        if (_editorTocRaf) return;
        _editorTocRaf = requestAnimationFrame(() => {
            _editorTocRaf = null;
            updateTocByEditorScroll();
        });
        return;
    }

    if (mode !== 'split') return;
    if (_scrollLock === 'preview') return;

    _acquireScrollLock('editor');
    if (_editorScrollRaf) return;
    _editorScrollRaf = requestAnimationFrame(() => {
        _editorScrollRaf = null;
        try { syncEditorToPreview(); } catch (e) { console.warn('[sync e→p]', e); }
        _releaseScrollLockSoon('editor');

        requestAnimationFrame(() => {
            try { updateActiveTocByScroll(); } catch (e) { /* ignore */ }
        });
    });
}

function onPreviewScrollEvent() {
    if (mode !== 'preview' && mode !== 'split') return;
    if (mode === 'split' && _scrollLock === 'editor') return;

    _acquireScrollLock('preview');
    if (_previewScrollRaf) return;
    _previewScrollRaf = requestAnimationFrame(() => {
        _previewScrollRaf = null;
        try {
            if (mode === 'split') syncPreviewToEditor();
        } catch (e) { console.warn('[sync p→e]', e); }
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

// ============================================================
//  Ctrl+点击脚注双向跳转
// ============================================================
function setupEditorCtrlClick() {
    if (!editorView) return;
    editorView.dom.addEventListener('mousedown', (e) => {
        if (!(e.ctrlKey || e.metaKey)) return;
        if (e.button !== 0) return;

        let pos;
        try {
            pos = editorView.posAtCoords({ x: e.clientX, y: e.clientY });
        } catch (err) { return; }
        if (pos == null) return;

        const doc = editorView.state.doc;
        const line = doc.lineAt(pos);
        const lineText = line.text;

        const defRe = /^([ \t]*)(\[\^([^\]\s]+)\]:)/;
        const dm = defRe.exec(lineText);
        if (dm) {
            const indentLen = dm[1].length;
            const bracketStart = line.from + indentLen;
            const bracketEnd = line.from + indentLen + dm[2].length;
            if (pos >= bracketStart && pos <= bracketEnd) {
                const key = dm[3];
                const jumpPos = findFirstFootnoteRefPos(doc, key);
                if (jumpPos == null) {
                    setStatus('未找到脚注 [^' + key + '] 的引用');
                    return;
                }
                e.preventDefault();
                e.stopPropagation();

                const targetLine = doc.lineAt(jumpPos);
                editorView.dispatch({
                    selection: { anchor: targetLine.from, head: targetLine.to }
                });
                editorView.focus();

                requestAnimationFrame(() => {
                    try {
                        const block = editorView.lineBlockAt(targetLine.from);
                        const scroller = document.querySelector('#editor .cm-scroller');
                        if (scroller && block) {
                            const h = scroller.clientHeight;
                            const targetTop = block.top - h / 3;
                            scroller.scrollTop = Math.max(0, targetTop);
                        }
                    } catch (err) { /* ignore */ }
                });

                setStatus('已回到脚注 [^' + key + '] 引用位置');
                return;
            }
        }

        const refRe = /\[\^([^\]\s]+)\](?!:)/g;
        let m;
        let matchedKey = null;
        while ((m = refRe.exec(lineText)) !== null) {
            const absStart = line.from + m.index;
            const absEnd = absStart + m[0].length;
            if (pos >= absStart && pos <= absEnd) {
                matchedKey = m[1];
                break;
            }
        }
        if (!matchedKey) return;

        const allLines = doc.toString().split('\n');
        let targetLineNum = -1;
        const defLineRe = /^[ \t]*\[\^([^\]\s]+)\]:/;
        for (let i = 0; i < allLines.length; i++) {
            const d = defLineRe.exec(allLines[i]);
            if (d && d[1] === matchedKey) {
                targetLineNum = i;
                break;
            }
        }

        if (targetLineNum < 0) {
            setStatus('未找到脚注 [^' + matchedKey + '] 的定义');
            return;
        }

        e.preventDefault();
        e.stopPropagation();

        const targetLine = doc.line(targetLineNum + 1);
        editorView.dispatch({
            selection: { anchor: targetLine.from, head: targetLine.to }
        });
        editorView.focus();

        requestAnimationFrame(() => {
            try {
                const block = editorView.lineBlockAt(targetLine.from);
                const scroller = document.querySelector('#editor .cm-scroller');
                if (scroller && block) {
                    const h = scroller.clientHeight;
                    const targetTop = block.top - h / 3;
                    scroller.scrollTop = Math.max(0, targetTop);
                }
            } catch (err) { /* ignore */ }
        });

        setStatus('已跳转到脚注 [^' + matchedKey + ']');
    }, true);
}

function findFirstFootnoteRefPos(doc, key) {
    const refPattern = '[^' + key + ']';
    const defLineRe = /^[ \t]*\[\^([^\]\s]+)\]:/;

    for (let ln = 1; ln <= doc.lines; ln++) {
        const line = doc.line(ln);
        const text = line.text;

        if (defLineRe.test(text)) continue;

        let idx = 0;
        while ((idx = text.indexOf(refPattern, idx)) >= 0) {
            const after = text.charAt(idx + refPattern.length);
            if (after !== ':') {
                return line.from + idx;
            }
            idx += refPattern.length;
        }
    }
    return null;
}

// ============================================================
//  右键菜单
// ============================================================
function closeContextMenu() {
    if (_ctxMenuEl && _ctxMenuEl.parentNode) {
        _ctxMenuEl.parentNode.removeChild(_ctxMenuEl);
    }
    _ctxMenuEl = null;
}

function _renderContextMenu(x, y, items) {
    closeContextMenu();

    const menu = document.createElement('div');
    menu.className = 'mk-context-menu';
    menu.style.position = 'fixed';
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    menu.style.zIndex = '50000';

    for (const item of items) {
        if (!item) continue;
        if (item.type === 'sep') {
            const sep = document.createElement('div');
            sep.className = 'mk-context-sep';
            menu.appendChild(sep);
            continue;
        }

        const row = document.createElement('div');
        row.className = 'mk-context-item';
        if (item.key) row.setAttribute('data-ctx-action', item.key);

        const labelSpan = document.createElement('span');
        labelSpan.className = 'mk-context-label';
        labelSpan.textContent = T(item.labelKey, item.fallback);

        const shortcutSpan = document.createElement('span');
        shortcutSpan.className = 'mk-context-shortcut';
        shortcutSpan.textContent = item.shortcut || '';

        row.appendChild(labelSpan);
        row.appendChild(shortcutSpan);

        row.addEventListener('mousedown', (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
        });
        row.addEventListener('click', (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            const fn = item.action;
            closeContextMenu();
            try { if (typeof fn === 'function') fn(); }
            catch (err) { console.warn('[ctx menu]', err); }
        });

        menu.appendChild(row);
    }

    document.body.appendChild(menu);
    _ctxMenuEl = menu;

    requestAnimationFrame(() => {
        if (!_ctxMenuEl) return;
        const rect = menu.getBoundingClientRect();
        const maxX = window.innerWidth - rect.width - 4;
        const maxY = window.innerHeight - rect.height - 4;
        let nx = x, ny = y;
        if (nx > maxX) nx = Math.max(4, maxX);
        if (ny > maxY) ny = Math.max(4, maxY);
        menu.style.left = nx + 'px';
        menu.style.top = ny + 'px';
    });
}

function showEditorContextMenu(x, y) {
    const items = [
        { key: 'undo', labelKey: 'undo', fallback: '撤销', shortcut: 'Ctrl+Z', action: () => onUndo() },
        { key: 'redo', labelKey: 'redo', fallback: '重做', shortcut: 'Ctrl+Y', action: () => onRedo() },
        { type: 'sep' },
        { key: 'cut', labelKey: 'cut', fallback: '剪切', shortcut: 'Ctrl+X', action: () => document.execCommand('cut') },
        { key: 'copy', labelKey: 'copy', fallback: '复制', shortcut: 'Ctrl+C', action: () => document.execCommand('copy') },
        { key: 'paste', labelKey: 'paste', fallback: '粘贴', shortcut: 'Ctrl+V', action: () => document.execCommand('paste') },
        { type: 'sep' },
        {
            key: 'select_all', labelKey: 'select_all', fallback: '全选', shortcut: 'Ctrl+A',
            action: () => {
                if (editorView) {
                    editorView.dispatch({
                        selection: { anchor: 0, head: editorView.state.doc.length }
                    });
                    editorView.focus();
                }
            }
        },
        {
            key: 'find', labelKey: 'find', fallback: '查找', shortcut: 'Ctrl+F',
            action: () => { if (window.FindBar) window.FindBar.open(false); }
        },
    ];
    _renderContextMenu(x, y, items);
}

function showPreviewContextMenu(x, y, hasSelection) {
    const items = [];

    if (hasSelection) {
        items.push({
            key: 'copy', labelKey: 'copy', fallback: '复制', shortcut: 'Ctrl+C',
            action: () => { try { document.execCommand('copy'); } catch (e) { /* ignore */ } }
        });
    }

    items.push({
        key: 'select_all', labelKey: 'select_all', fallback: '全选', shortcut: 'Ctrl+A',
        action: () => {
            if (previewEl) {
                const range = document.createRange();
                range.selectNodeContents(previewEl);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            }
        }
    });

    items.push({ type: 'sep' });
    items.push({
        key: 'find', labelKey: 'find', fallback: '查找', shortcut: 'Ctrl+F',
        action: () => { if (window.FindBar) window.FindBar.open(false); }
    });

    _renderContextMenu(x, y, items);
}

function setupEditorContextMenu() {
    if (!editorView) return;

    editorView.dom.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        showEditorContextMenu(e.clientX, e.clientY);
    });

    document.addEventListener('mousedown', (e) => {
        if (!_ctxMenuEl) return;
        if (_ctxMenuEl.contains(e.target)) return;
        closeContextMenu();
    }, true);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && _ctxMenuEl) {
            e.preventDefault();
            e.stopPropagation();
            closeContextMenu();
        }
    }, true);

    window.addEventListener('blur', () => {
        closeContextMenu();
    });

    window.addEventListener('resize', () => {
        closeContextMenu();
    });
}

function setupPreviewContextMenu() {
    const container = (previewEl && previewEl.parentElement) || previewEl;
    if (!container) return;

    container.addEventListener('contextmenu', (e) => {
        if (isInsideContentEditable(e.target)) {
            return;
        }

        e.preventDefault();
        e.stopPropagation();

        const sel = window.getSelection();
        const hasSel = !!(sel && sel.rangeCount > 0 && !sel.isCollapsed &&
            !isInsideContentEditable(sel.anchorNode) &&
            !isInsideContentEditable(sel.focusNode));

        showPreviewContextMenu(e.clientX, e.clientY, hasSel);
    });
}

// ============================================================
//  拖拽导入
// ============================================================
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
    const uriList = dt.getData('text/uri-list');
    if (uriList) {
        const firstUrl = String(uriList).split(/\r?\n/)[0].trim();
        if (firstUrl && !firstUrl.startsWith('#') && /^https?:\/\//i.test(firstUrl)) {
            console.log('[drag] uri-list URL:', firstUrl);
            await importDroppedUrl(firstUrl);
            return;
        }
    }

    const plainText = (dt.getData('text/plain') || '').trim();
    if (plainText && /^https?:\/\/\S+$/i.test(plainText)) {
        console.log('[drag] text/plain URL:', plainText);
        await importDroppedUrl(plainText);
        return;
    }

    const html = dt.getData('text/html');
    if (html) {
        let imgSrc = null;
        const m1 = html.match(/<img[^>]+\bsrc\s*=\s*["']([^"']+)["']/i);
        if (m1 && m1[1]) imgSrc = m1[1];

        if (imgSrc && /^(blob:|data:)/i.test(imgSrc)) {
            const m2 = html.match(/\bdata-original\s*=\s*["']([^"']+)["']/i) ||
                       html.match(/\bdata-src\s*=\s*["']([^"']+)["']/i) ||
                       html.match(/\bdata-lazy-src\s*=\s*["']([^"']+)["']/i);
            if (m2 && m2[1]) imgSrc = m2[1];
        }

        if (imgSrc && /^https?:\/\//i.test(imgSrc)) {
            console.log('[drag] text/html img src:', imgSrc);
            await importDroppedUrl(imgSrc);
            return;
        }
    }

    const files = dt.files;
    if (files && files.length > 0) {
        console.log('[drag] files:', Array.from(files).map(f => ({
            name: f.name, type: f.type, size: f.size,
            hasPath: !!f.path,
        })));

        for (const f of files) {
            const name = (f.name || '').toLowerCase();

            if (name.endsWith('.pdf')) {
                await _handleDroppedPdf(f);
                continue;
            }
            if (name.endsWith('.html') || name.endsWith('.htm')) {
                await _handleDroppedHtml(f);
                continue;
            }
            if (name.endsWith('.md') || name.endsWith('.markdown') ||
                name.endsWith('.txt')) {
                await _handleDroppedMarkdown(f);
                continue;
            }
            if (/^image\//.test(f.type) ||
                /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i.test(f.name)) {
                await importDroppedLocalFile(f);
                continue;
            }
            setStatus('不支持的文件类型: ' + (f.name || ''));
        }
        return;
    }

    if (plainText && /^https?:\/\//i.test(plainText)) {
        await importDroppedUrl(plainText);
        return;
    }

    setStatus('未能识别拖入内容');
}

async function _handleDroppedPdf(file) {
    if (isDirty) {
        const ok = await showConfirm(
            T('unsaved_content_title', '未保存的内容'),
            T('unsaved_content_warning', '未保存的内容将丢失，继续？')
        );
        if (!ok) return;
    }

    const path = file.path || '';

    if (path) {
        setStatus('正在导入 PDF...');
        try {
            const r = await window.pywebview.api.import_dropped_pdf(path);
            if (!r || !r.ok) {
                setStatus('PDF 导入失败: ' + ((r && r.error) || '未知错误'));
                return;
            }
            await _applyDroppedPdfResult(r, path);
        } catch (e) {
            setStatus('PDF 导入异常: ' + (e && e.message ? e.message : e));
        }
        return;
    }

    setStatus('正在读取 PDF...');
    let buf;
    try {
        buf = await file.arrayBuffer();
    } catch (e) {
        setStatus('读取 PDF 失败: ' + (e && e.message ? e.message : e));
        return;
    }
    if (!buf || buf.byteLength === 0) {
        setStatus('PDF 文件为空');
        return;
    }

    const sizeKB = Math.round(buf.byteLength / 1024);
    setStatus('正在解析 PDF（' + sizeKB + ' KB）...');

    let b64;
    try {
        b64 = arrayBufferToBase64(buf);
    } catch (e) {
        setStatus('PDF 编码失败: ' + (e && e.message ? e.message : e));
        return;
    }

    try {
        const r = await window.pywebview.api.import_dropped_pdf_bytes(
            file.name || 'dropped.pdf', b64);
        if (!r || !r.ok) {
            setStatus('PDF 导入失败: ' + ((r && r.error) || '未知错误'));
            return;
        }
        await _applyDroppedPdfResult(r, '');
    } catch (e) {
        setStatus('PDF 导入异常: ' + (e && e.message ? e.message : e));
    }
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const CHUNK = 0x8000;
    let binary = '';
    for (let i = 0; i < bytes.length; i += CHUNK) {
        const sub = bytes.subarray(i, i + CHUNK);
        binary += String.fromCharCode.apply(null, sub);
    }
    return btoa(binary);
}

async function _applyDroppedPdfResult(r, path) {
    currentFile = '';
    currentDocDir = (r && r.doc_dir) ? String(r.doc_dir) : '';
    syncGlobalFileState();
    setContent(r.content);
    setFilePathDisplay('', T('imported_from_pdf', '（来自 PDF）'));
    setStatus('PDF 导入完成');
    try { await window.pywebview.api.set_current_file(''); } catch (e) {}

    _openedOriginalContent = getContent();
    _openedFilePath = '';
    _forceSaveAsNextTime = false;
}

function extractMarkEaseMeta(htmlText) {
    if (!htmlText) return null;
    try {
        const parser = new DOMParser();
        const doc = parser.parseFromString(htmlText, 'text/html');

        const mdMeta = doc.querySelector('meta[name="markease-source-md"]');
        if (!mdMeta) return null;

        const mdB64 = mdMeta.getAttribute('content') || '';
        if (!mdB64) return null;

        const dirMeta = doc.querySelector('meta[name="markease-source-doc-dir"]');
        const dirB64 = dirMeta ? (dirMeta.getAttribute('content') || '') : '';

        function decodeB64Utf8(b64) {
            if (!b64) return '';
            const binary = atob(b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i);
            }
            try {
                return new TextDecoder('utf-8').decode(bytes);
            } catch (e) {
                return binary;
            }
        }

        return {
            markdown: decodeB64Utf8(mdB64),
            docDir: dirB64 ? decodeB64Utf8(dirB64) : '',
        };
    } catch (e) {
        console.warn('[extractMarkEaseMeta]', e);
        return null;
    }
}

async function _handleDroppedHtml(file) {
    console.log('[drag html] name=', file.name, 'path=', file.path);

    if (isDirty) {
        const ok = await showConfirm(
            T('unsaved_content_title', '未保存的内容'),
            T('unsaved_content_warning', '未保存的内容将丢失，继续？')
        );
        if (!ok) return;
    }

    const path = file.path || '';

    if (!path) {
        let text;
        try {
            text = await file.text();
        } catch (e) {
            setStatus('无法读取 HTML 文件');
            return;
        }

        const meta = extractMarkEaseMeta(text);
        if (meta && meta.markdown) {
            let content = meta.markdown;
            const docDir = meta.docDir || '';

            try {
                if (window.pywebview && window.pywebview.api &&
                    window.pywebview.api.recover_missing_images) {
                    const rr = await window.pywebview.api.recover_missing_images(
                        docDir, content, text);
                    if (rr && rr.ok && rr.content != null) {
                        content = rr.content;
                        if (rr.recovered > 0) {
                            console.log('[drag html] 从 HTML 恢复图片:',
                                rr.recovered);
                        }
                    }
                }
            } catch (e) {
                console.warn('[drag html] recover failed', e);
            }

            currentFile = '';
            currentDocDir = docDir;
            syncGlobalFileState();

            setContent(content);
            setFilePathDisplay('', T('imported_from_html', '（来自 HTML）'));
            setStatus(T('import_html_success_roundtrip',
                'HTML 导入完成（无损还原）'));
            try { await window.pywebview.api.set_current_file(''); } catch (e) {}

            _openedOriginalContent = getContent();
            _openedFilePath = '';
            _forceSaveAsNextTime = false;
            return;
        }

        let content = convertHtmlToMarkdown(text);
        if (content == null) {
            setStatus('HTML 解析失败：无法提取内容');
            return;
        }

        let docDir = '';
        if (file.name) {
            docDir = currentDocDir || '';
        }

        if (docDir) {
            try {
                const fr = await window.pywebview.api.finalize_imported_html(
                    docDir, content);
                if (fr && fr.ok && fr.content != null) {
                    content = fr.content;
                    if (fr.migrated_images > 0) {
                        console.log('[html] data URL 图片落盘:',
                            fr.migrated_images);
                    }
                }
            } catch (e) {
                console.warn('[html] finalize_imported_html failed', e);
            }
        }

        currentFile = '';
        currentDocDir = docDir;
        syncGlobalFileState();
        setContent(content);
        setFilePathDisplay('', T('imported_from_html', '（来自 HTML）'));
        setStatus(T('import_html_success', 'HTML 导入完成'));
        try { await window.pywebview.api.set_current_file(''); } catch (e) {}

        _openedOriginalContent = getContent();
        _openedFilePath = '';
        _forceSaveAsNextTime = false;
        return;
    }

    setStatus('正在导入 HTML...');
    try {
        const r = await window.pywebview.api.import_dropped_html(path);
        if (!r || !r.ok) {
            setStatus('HTML 导入失败: ' + ((r && r.error) || '未知错误'));
            return;
        }
        await _applyImportedHtmlResult(r, /* dirtyChecked */ true);
    } catch (e) {
        setStatus('HTML 导入异常: ' + (e && e.message ? e.message : e));
    }
}

async function _handleDroppedMarkdown(file) {
    console.log('[drag md] name=', file.name, 'path=', file.path);

    if (isDirty) {
        const ok = await showConfirm(
            T('unsaved_content_title', '未保存的内容'),
            T('unsaved_content_warning', '未保存的内容将丢失，继续？')
        );
        if (!ok) return;
    }

    let path = file.path || '';
    let content = '';

    try {
        content = await file.text();
    } catch (e) {
        setStatus('读取文件失败: ' + (e && e.message ? e.message : e));
        return;
    }

    currentFile = path || '';
    currentDocDir = path ? path.replace(/[\\/][^\\/]+$/, '') : '';
    syncGlobalFileState();

    setContent(content);

    if (path) {
        setFilePathDisplay(path);
    } else {
        setFilePathDisplay('', '（来自拖拽）');
    }
    setStatus('已打开');

    try {
        await window.pywebview.api.set_current_file(currentFile || '');
    } catch (e) { /* ignore */ }

    _openedOriginalContent = getContent();
    _openedFilePath = currentFile || '';
    _forceSaveAsNextTime = false;
}

async function importDroppedLocalFile(file) {
    setStatus('正在导入本地图片...');

    const path = file.path || '';
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
    if (!url) {
        setStatus('未能识别拖入内容');
        return;
    }

    let cleanUrl = String(url).trim();
    if (cleanUrl.startsWith('<') && cleanUrl.endsWith('>')) {
        cleanUrl = cleanUrl.slice(1, -1);
    }

    if (!/^https?:\/\//i.test(cleanUrl)) {
        setStatus('不支持的图片地址: ' + cleanUrl.slice(0, 60));
        return;
    }

    insertImageMarkdown(cleanUrl, false);
    setStatus('已插入网络图片链接');
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

// ============================================================
//  预览编辑
// ============================================================
let _linkClickTimer = null;

function enterEditable(el, e) {
    if (!el) return;
    if (el.getAttribute('contenteditable') === 'true') return;

    e.preventDefault();
    e.stopPropagation();

    if (activeEditableEl && activeEditableEl !== el) {
        exitEditable(activeEditableEl);
    }

    el.setAttribute('contenteditable', 'true');
    el.classList.add('preview-editing');
    activeEditableEl = el;

    // ★ 阶段 16-13：重置输入标记
    _editableHadInput = false;

    // ★ 阶段 16-13：监听 input 事件
    const onInput = () => { _editableHadInput = true; };
    el.addEventListener('input', onInput);
    el.__mkInputHandler = onInput;

    const isLi = el.tagName && el.tagName.toLowerCase() === 'li';
    if (isLi) {
        el.querySelectorAll('ul, ol').forEach(list => {
            if (list.getAttribute('contenteditable') !== 'false') {
                list.setAttribute('data-md-tmp-cedisabled', '1');
                list.setAttribute('contenteditable', 'false');
            }
        });
    }

    el.querySelectorAll('[contenteditable="false"]').forEach(sub => {
        if (sub.getAttribute && sub.getAttribute('data-no-edit') === '1') {
            return;
        }
        if (sub.classList &&
            (sub.classList.contains('task-list-bullet') ||
             sub.classList.contains('task-list-checkbox'))) {
            return;
        }
        if (sub.tagName &&
            (sub.tagName.toLowerCase() === 'ul' ||
             sub.tagName.toLowerCase() === 'ol')) {
            return;
        }
        sub.setAttribute('data-md-ce-was-false', '1');
        sub.setAttribute('contenteditable', 'true');
    });

    el.focus();

    if (e && document.caretRangeFromPoint) {
        try {
            const range = document.caretRangeFromPoint(e.clientX, e.clientY);
            if (range) {
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
            }
        } catch (err) { /* ignore */ }
    }
}

function findFootnoteLiByY(section, clientY) {
    if (!section) return null;
    const lis = section.querySelectorAll('li[data-footnote-item]');
    if (lis.length === 0) return null;
    for (let i = 0; i < lis.length; i++) {
        const r = lis[i].getBoundingClientRect();
        if (clientY >= r.top && clientY <= r.bottom) return lis[i];
    }
    const first = lis[0];
    const last = lis[lis.length - 1];
    const fr = first.getBoundingClientRect();
    const lr = last.getBoundingClientRect();
    if (clientY < fr.top) return first;
    if (clientY > lr.bottom) return last;
    return null;
}

function setupPreviewEditing() {

    // ★ 新增：点击预览区非编辑区域时，主动退出编辑（修复现象 1）
    const previewContainerEl = previewEl.parentElement;
    if (previewContainerEl) {
        previewContainerEl.addEventListener('mousedown', (e) => {
            if (!activeEditableEl) return;
            if (e.button !== 0) return;
            if (activeEditableEl.contains(e.target)) return;
            const el = activeEditableEl;
            setTimeout(() => {
                if (activeEditableEl === el) exitEditable(el);
            }, 0);
        });
    }

    // ★ 新增：拦截粘贴，列表内只粘贴行内内容（修复现象 2）
    previewEl.addEventListener('paste', (e) => {
        const target = e.target;
        if (!target || !target.closest) return;
        const editable = target.closest('[contenteditable="true"]');
        if (!editable) return;

        const html = e.clipboardData && e.clipboardData.getData('text/html');
        if (!html) return;

        // 只有粘贴内容中带列表结构时才处理
        if (!/<(ul|ol|li)[\s>]/i.test(html)) return;

        const inline = extractInlineFromListHtml(html);
        if (!inline) return;

        e.preventDefault();
        insertHtmlAtCursor(inline);
        try {
            editable.dispatchEvent(new Event('input', { bubbles: true }));
        } catch (err) { /* ignore */ }
        _editableHadInput = true;
    }, true);

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

        if (e.target.closest && e.target.closest('a[data-footnote-backref="1"]')) {
            return;
        }

        let fnLi = e.target.closest && e.target.closest('li[data-footnote-item]');
        if (!fnLi) {
            const sec = e.target.closest && e.target.closest('section.footnotes');
            if (sec) {
                fnLi = findFootnoteLiByY(sec, e.clientY);
            }
        }
        if (fnLi) {
            const fnP = fnLi.querySelector('p[data-md-editable="footnote"]');
            if (fnP) {
                enterEditable(fnP, e);
                return;
            }
        }

        const el = e.target.closest && e.target.closest(
            '[data-md-editable="1"], [data-md-editable="footnote"]');
        if (!el) return;
        if (el.getAttribute('contenteditable') === 'true') return;

        enterEditable(el, e);
    });

    previewEl.addEventListener('keydown', (e) => {
        const cell = e.target.closest && e.target.closest(
            'td[contenteditable="true"], th[contenteditable="true"]');
        if (cell) {
            if (e.key === 'Enter' || e.key === 'Tab' || e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                exitEditable(cell);
            }
            return;
        }

        if (e.key === 'Escape') {
            const el = e.target.closest && e.target.closest(
                '[data-md-editable="1"][contenteditable="true"], ' +
                '[data-md-editable="footnote"][contenteditable="true"]');
            if (el) {
                e.preventDefault();
                e.stopPropagation();
                exitEditable(el);
            }
        }
    }, true);

    previewEl.addEventListener('blur', (e) => {
        const el = e.target;
        if (!el || !el.matches) return;
        if (!el.matches('[data-md-editable="1"], [data-md-editable="footnote"]')) return;
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

// ★ 新增：从剪贴板 HTML 中提取列表里的行内内容（丢掉序号、缩进、外层列表）
function extractInlineFromListHtml(html) {
    let doc;
    try {
        const parser = new DOMParser();
        doc = parser.parseFromString(html, 'text/html');
    } catch (err) {
        return '';
    }
    if (!doc || !doc.body) return '';

    const body = doc.body;

    // 优先找顶层 ul / ol
    const topLists = [];
    for (let i = 0; i < body.childNodes.length; i++) {
        const c = body.childNodes[i];
        if (c.nodeType === 1) {
            const tag = c.tagName.toLowerCase();
            if (tag === 'ul' || tag === 'ol') topLists.push(c);
        }
    }

    const out = [];

    if (topLists.length > 0) {
        for (let i = 0; i < topLists.length; i++) {
            const lis = topLists[i].children;
            for (let j = 0; j < lis.length; j++) {
                const li = lis[j];
                if (li.tagName.toLowerCase() !== 'li') continue;
                const s = getLiInlineHtml(li);
                if (s) out.push(s);
            }
        }
    } else {
        // 兜底：直接找所有 li
        const lis = body.querySelectorAll('li');
        for (let i = 0; i < lis.length; i++) {
            const s = getLiInlineHtml(lis[i]);
            if (s) out.push(s);
        }
    }

    return out.join('<br>');
}

// ★ 新增：递归提取 li 的行内 HTML，跳过嵌套列表
function getLiInlineHtml(li) {
    let out = '';
    const nodes = li.childNodes;
    const INLINE = {
        'strong': 1, 'b': 1, 'em': 1, 'i': 1, 'ins': 1, 'u': 1,
        'del': 1, 's': 1, 'code': 1, 'span': 1, 'sub': 1, 'sup': 1,
        'mark': 1, 'small': 1, 'big': 1, 'tt': 1, 'kbd': 1, 'var': 1,
        'samp': 1, 'abbr': 1, 'cite': 1, 'q': 1, 'dfn': 1, 'time': 1
    };
    for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        if (node.nodeType === 3) {
            out += escapeHtmlText(node.nodeValue);
            continue;
        }
        if (node.nodeType !== 1) continue;
        const tag = node.tagName.toLowerCase();

        // 跳过嵌套列表（不粘贴子列表）
        if (tag === 'ul' || tag === 'ol') continue;

        if (tag === 'a') {
            const href = node.getAttribute('href') || '';
            const inner = getLiInlineHtml(node);
            out += '<a href="' + escapeHtmlAttr(href) + '">' + inner + '</a>';
            continue;
        }
        if (INLINE[tag]) {
            const inner = getLiInlineHtml(node);
            out += '<' + tag + '>' + inner + '</' + tag + '>';
            continue;
        }
        // p / div 等：递归进去，但内容仍按行内处理
        out += getLiInlineHtml(node);
    }
    return out;
}

function escapeHtmlText(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function escapeHtmlAttr(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ★ 新增：在当前选区插入 HTML
function insertHtmlAtCursor(html) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    range.deleteContents();
    let fragment;
    try {
        fragment = range.createContextualFragment(html);
    } catch (e) {
        return;
    }
    range.insertNode(fragment);
    // 光标移到插入内容之后
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
}

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
        } else if (tag === 'ins' || tag === 'u') {
            const inner = fragmentToMarkdown(child);
            out += '<ins>' + inner + '</ins>';
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
                const annotation = mb.querySelector('annotation[encoding="application/x-tex"]');
                if (annotation) {
                    out += '\n\n$$' + annotation.textContent + '$$\n\n';
                } else {
                    const tex = mb.getAttribute('data-tex');
                    if (tex) {
                        try {
                            const decoded = decodeURIComponent(tex);
                            out += '\n\n$$\n' + decoded + '\n$$\n\n';
                        } catch (e2) { /* ignore */ }
                    }
                }
            }
        } else if (child.querySelector && child.querySelector('.katex-inline, .katex, .math-block')) {
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

// ---------------- 退出预览编辑 ----------------
function exitEditable(el) {
    if (!el) return;
    // ★ 防止重复退出（blur + mousedown 双重触发）
    if (el.getAttribute('contenteditable') !== 'true') return;

    const tag = (el.tagName || '').toLowerCase();
    const isTableCell = (tag === 'td' || tag === 'th') &&
        el.getAttribute('data-md-table-index') != null;

    if (isTableCell) {
        applyTableCellEdit(el);
    } else {
        el.querySelectorAll('[data-md-tmp-cedisabled="1"]').forEach(list => {
            list.removeAttribute('data-md-tmp-cedisabled');
            list.removeAttribute('contenteditable');
        });

        el.querySelectorAll('[data-md-ce-was-false="1"]').forEach(sub => {
            sub.removeAttribute('data-md-ce-was-false');
            sub.setAttribute('contenteditable', 'false');
        });
        applyPreviewEdit(el);
    }

    // ★ 清理 input 监听
    if (el.__mkInputHandler) {
        try { el.removeEventListener('input', el.__mkInputHandler); } catch (e) {}
        el.__mkInputHandler = null;
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

// ★ 新增：从 <pre> 中提取纯代码文本（保留换行，去掉尾部空行）
function extractPreText(pre) {
    let out = '';
    function walk(node) {
        if (node.nodeType === 3) {
            out += node.nodeValue;
        } else if (node.nodeType === 1) {
            const tag = node.tagName.toLowerCase();
            if (tag === 'br') {
                out += '\n';
            } else {
                const kids = node.childNodes;
                for (let i = 0; i < kids.length; i++) {
                    walk(kids[i]);
                }
            }
        }
    }
    walk(pre);
    return out.replace(/\n+$/, '');
}

// ★ 阶段 16-13：专门从 li 提取 inline 文本，跳过块级子元素
function extractLiInlineText(li) {
    let out = '';
    const nodes = li.childNodes;
    for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        if (node.nodeType === 3) {
            out += node.nodeValue;
            continue;
        }
        if (node.nodeType !== 1) continue;

        const tag = node.tagName.toLowerCase();

        // 跳过所有块级元素（列表、引用、代码块、表格、标题、折叠块、章节）
        if (tag === 'ul' || tag === 'ol' ||
            tag === 'blockquote' || tag === 'pre' || tag === 'table' ||
            tag === 'section' || tag === 'article' || tag === 'figure' ||
            tag === 'details' || tag === 'summary' ||
            /^h[1-6]$/.test(tag)) {
            continue;
        }

        // ★ 修复现象 1：浏览器有时会把外层 li 的内容包进 <p> / <div>，
        //   此时需要递归进去，而不是直接跳过。
        if (tag === 'p' || tag === 'div') {
            out += extractLiInlineText(node);
            continue;
        }

        // inline 元素
        if (tag === 'br') {
            out += '\n';
        } else if (tag === 'img') {
            const src = node.getAttribute('src') || '';
            const alt = node.getAttribute('alt') || '';
            let realSrc = src;
            if (/^http:\/\/127\.0\.0\.1:\d+\/proxy\?url=/i.test(src)) {
                try {
                    realSrc = decodeURIComponent(src.replace(
                        /^http:\/\/127\.0\.0\.1:\d+\/proxy\?url=/i, ''));
                } catch (e) { /* 保留 */ }
            } else if (/^http:\/\/127\.0\.0\.1:\d+\/fs\//i.test(src)) {
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
            if (/[\s()<>]/.test(realSrc) && !realSrc.startsWith('<')) {
                realSrc = '<' + realSrc + '>';
            }
            out += '![' + alt + '](' + realSrc + ')';
        } else if (tag === 'code') {
            out += '`' + node.textContent + '`';
        } else if (tag === 'strong' || tag === 'b') {
            out += '**' + extractLiInlineText(node) + '**';
        } else if (tag === 'em' || tag === 'i') {
            out += '*' + extractLiInlineText(node) + '*';
        } else if (tag === 'del' || tag === 's') {
            out += '~~' + extractLiInlineText(node) + '~~';
        } else if (tag === 'ins' || tag === 'u') {
            out += '<ins>' + extractLiInlineText(node) + '</ins>';
        } else if (tag === 'a') {
            const href = node.getAttribute('href') || '';
            const txt = extractLiInlineText(node);
            if (node.querySelector('img')) {
                out += '<a href="' + href + '">' + txt + '</a>';
            } else if (href) {
                out += '[' + txt + '](' + href + ')';
            } else {
                out += txt;
            }
        } else if (tag === 'sup' && node.getAttribute('data-footnote-ref') === '1') {
            const idx = node.getAttribute('data-footnote-index') || '';
            out += '[^' + idx + ']';
        } else if (tag === 'span') {
            if (node.classList && (
                node.classList.contains('task-list-bullet') ||
                node.classList.contains('task-list-checkbox'))) {
                continue;
            }
            out += extractLiInlineText(node);
        } else {
            out += extractLiInlineText(node);
        }
    }
    return out;
}

function applyPreviewEdit(el) {
    if (!el || !el.getAttribute) return;
    const editable = el.getAttribute('data-md-editable');
    if (editable !== '1' && editable !== 'footnote') return;

    const startStr = el.getAttribute('data-md-start');
    const endStr = el.getAttribute('data-md-end');
    const oldText = el.getAttribute('data-md-old-text') || '';
    if (startStr == null || endStr == null) return;

    const start = parseInt(startStr, 10);
    const end = parseInt(endStr, 10);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return;

    const tag = (el.tagName || '').toLowerCase();
    const isLi = (tag === 'li');
    const isPre = (tag === 'pre');

    // ★ 提取 newText
    let newText;
    if (isLi) {
        newText = extractLiInlineText(el).replace(/[\s\u200B\uFEFF]+$/g, '');
    } else if (isPre) {
        newText = extractPreText(el);
    } else {
        newText = window.domToMarkdown
            ? window.domToMarkdown(el)
            : (window.getEditableText ? window.getEditableText(el) : el.textContent);
    }

    // ★ 三重异常防护（仅 li，且放宽阈值）
    if (isLi) {
        // 防护 1：内容膨胀
        if (oldText && newText.length > oldText.length * 3 + 100) {
            setStatus('预览编辑异常（内容膨胀），已放弃本次同步');
            return;
        }
        // 防护 2：跨行污染（原本单行，现在跨行且行数过多）
        if (oldText.indexOf('\n') < 0 && newText.indexOf('\n') >= 0) {
            if (newText.split('\n').length > 3) {
                setStatus('预览编辑异常（跨行），已放弃本次同步');
                return;
            }
        }
        // 防护 3：未输入任何内容时，若内容确实没变才跳过
        if (!_editableHadInput) {
            const oldNorm = String(oldText).replace(/\s+/g, '');
            const newNorm = String(newText).replace(/\s+/g, '');
            if (oldNorm === newNorm) return;
        }
    }

    if (start === end && !newText && !oldText) return;

    function stripWs(s) { return String(s).replace(/\s+/g, ''); }
    if (start !== end && stripWs(newText) === stripWs(oldText)) return;

    const md = getContent();

    if (start !== end) {
        if (md.slice(start, end) !== oldText) {
            setStatus('预览编辑与源文本已不一致，已放弃本次同步');
            return;
        }
    } else {
        if (start < 0 || start > md.length) {
            setStatus('预览编辑位置越界，已放弃本次同步');
            return;
        }
    }

    const newMd = md.slice(0, start) + newText + md.slice(end);
    if (newMd === md) return;
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
    syncGlobalFileState();

    setContent('');
    setFilePathDisplay('');
    setStatus('新建文档');
    try { await window.pywebview.api.set_current_file(''); } catch (e) {}

    _openedOriginalContent = '';
    _openedFilePath = '';
    _forceSaveAsNextTime = false;
}

async function onOpen() {
    const result = await window.pywebview.api.open_file_dialog();
    if (!result.ok) {
        if (!result.cancelled) setStatus('打开失败: ' + (result.error || ''));
        return;
    }

    if (result.need_frontend_convert && result.html) {
        await _applyImportedHtmlResult(result, /* dirtyChecked */ false);
        return;
    }

    currentFile = result.path || '';
    currentDocDir = result.doc_dir
        ? String(result.doc_dir)
        : (result.path ? result.path.replace(/[\\/][^\\/]+$/, '') : '');
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

    _openedOriginalContent = getContent();
    _openedFilePath = currentFile || '';
    _forceSaveAsNextTime = false;
}

async function onSave() {
    if (_forceSaveAsNextTime) {
        _forceSaveAsNextTime = false;
        return await onSaveAs();
    }

    const result = await window.pywebview.api.save_file(getContent());
    if (!result.ok) {
        if (!result.cancelled) setStatus('保存失败: ' + (result.error || ''));
        return;
    }
    if (result.path && result.path.toLowerCase().endsWith('.pdf')) {
        currentFile = '';
        currentDocDir = '';
        syncGlobalFileState();
        setFilePathDisplay('', '（已导出 PDF）');
        setStatus('已导出 PDF：' + result.path);
        return;
    }

    if (result.content != null && result.content !== getContent()) {
        currentFile = result.path;
        currentDocDir = result.path.replace(/[\\/][^\\/]+$/, '');
        syncGlobalFileState();
        setContent(result.content);
        setFilePathDisplay(result.path);
        setDirty(false);
        const mig = result.migrated_images || 0;
        if (mig > 0) {
            setStatus('已保存（迁移 ' + mig + ' 张图片到 assets/）');
        } else {
            setStatus('已保存');
        }
        _openedOriginalContent = getContent();
        _openedFilePath = currentFile || '';
        try { await window.pywebview.api.set_current_file(currentFile || ''); } catch (e) {}
        return;
    }

    currentFile = result.path;
    currentDocDir = result.path.replace(/[\\/][^\\/]+$/, '');
    syncGlobalFileState();
    setFilePathDisplay(result.path);
    setStatus('已保存');
    setDirty(false);
    _openedOriginalContent = getContent();
    _openedFilePath = currentFile || '';
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
        syncGlobalFileState();
        setFilePathDisplay('', '（已导出 PDF）');
        setStatus('已导出 PDF：' + result.path);
        return;
    }

    if (result.content != null && result.content !== getContent()) {
        currentFile = result.path;
        currentDocDir = result.path.replace(/[\\/][^\\/]+$/, '');
        syncGlobalFileState();
        setContent(result.content);
        setFilePathDisplay(result.path);
        setDirty(false);
        const mig = result.migrated_images || 0;
        if (mig > 0) {
            setStatus('已另存为（迁移 ' + mig + ' 张图片到 assets/）');
        } else {
            setStatus('已另存为');
        }
        _openedOriginalContent = getContent();
        _openedFilePath = currentFile || '';
        _forceSaveAsNextTime = false;
        try { await window.pywebview.api.set_current_file(currentFile || ''); } catch (e) {}
        return;
    }

    currentFile = result.path;
    currentDocDir = result.path.replace(/[\\/][^\\/]+$/, '');
    syncGlobalFileState();
    setFilePathDisplay(result.path);
    setStatus('已另存为');
    setDirty(false);
    _openedOriginalContent = getContent();
    _openedFilePath = currentFile || '';
    _forceSaveAsNextTime = false;
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
async function onImportPdf() {
    setStatus('正在导入 PDF...');
    const result = await window.pywebview.api.import_pdf_dialog();
    if (!result.ok) {
        if (!result.cancelled) setStatus('PDF 导入失败: ' + (result.error || ''));
        return;
    }

    currentFile = '';
    currentDocDir = result.doc_dir
        ? String(result.doc_dir)
        : (result.source_pdf ? result.source_pdf.replace(/[\\/][^\\/]+$/, '') : '');
    syncGlobalFileState();

    setContent(result.content);
    setFilePathDisplay('', '（来自 PDF）');
    setStatus('PDF 导入完成');
    try { await window.pywebview.api.set_current_file(''); } catch (e) {}

    _openedOriginalContent = getContent();
    _openedFilePath = '';
    _forceSaveAsNextTime = false;
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
//  HTML 导入 / 导出
// ============================================================

async function onExportHtml() {
    if (!editorView) return;

    setStatus(T('exporting_html', '正在导出 HTML...'));

    try {
        updatePreview();

        await new Promise(r => requestAnimationFrame(r));
        await new Promise(r => requestAnimationFrame(r));

        const htmlFragment = previewEl ? previewEl.innerHTML : '';
        const markdown = getContent();

        const r = await window.pywebview.api.export_html({
            html: htmlFragment,
            markdown: markdown,
            title: currentFile
                ? currentFile.replace(/^.*[\\/]/, '').replace(/\.[^.]+$/, '')
                : 'MarkEase 导出',
            doc_dir: currentDocDir || '',
        });

        if (!r || !r.ok) {
            if (r && r.cancelled) {
                setStatus(T('ready', '就绪'));
                return;
            }
            setStatus(T('export_html_failed', '导出失败') + ': ' +
                      ((r && r.error) || '未知错误'));
            return;
        }

        const stats = r.stats || {};
        let msg = T('export_html_success', 'HTML 导出成功') + ': ' + r.path;
        const details = [];
        if (stats.embedded) details.push('内嵌图片 ' + stats.embedded);
        if (stats.transcoded) details.push('转码 ' + stats.transcoded);
        if (stats.compressed) details.push('压缩 ' + stats.compressed);
        if (stats.remote) details.push('保留网络图 ' + stats.remote);
        if (details.length > 0) msg += '（' + details.join('，') + '）';
        setStatus(msg);
    } catch (e) {
        setStatus(T('export_html_failed', '导出失败') + ': ' +
                  (e && e.message ? e.message : e));
        console.error('[export html]', e);
    }
}

async function onImportHtml() {
    setStatus(T('importing_html', '正在导入 HTML...'));
    try {
        const r = await window.pywebview.api.import_html_dialog();
        if (!r) {
            setStatus(T('ready', '就绪'));
            return;
        }
        if (!r.ok) {
            if (r.cancelled) {
                setStatus(T('ready', '就绪'));
                return;
            }
            setStatus(T('import_html_failed', '导入失败') + ': ' +
                      (r.error || '未知错误'));
            return;
        }

        await _applyImportedHtmlResult(r, /* dirtyChecked */ false);
    } catch (e) {
        setStatus(T('import_html_failed', '导入失败') + ': ' +
                  (e && e.message ? e.message : e));
        console.error('[import html]', e);
    }
}

async function _applyImportedHtmlResult(r, dirtyChecked) {
    if (!dirtyChecked && isDirty) {
        const ok = await showConfirm(
            T('unsaved_content_title', '未保存的内容'),
            T('unsaved_content_warning', '未保存的内容将丢失，继续？')
        );
        if (!ok) {
            setStatus(T('ready', '就绪'));
            return;
        }
    }

    let content = '';
    let sourceLabel = '';
    let docDir = '';

    if (r.source === 'markease' && r.content != null) {
        content = r.content;
        docDir = (r && r.doc_dir) ? String(r.doc_dir) : '';
        sourceLabel = T('import_html_success_roundtrip', 'HTML 导入完成（无损还原）');
    } else if (r.need_frontend_convert && r.html) {
        content = convertHtmlToMarkdown(r.html);
        docDir = (r && r.doc_dir) ? String(r.doc_dir) : '';

        if (docDir) {
            try {
                const fr = await window.pywebview.api.finalize_imported_html(
                    docDir, content);
                if (fr && fr.ok && fr.content != null) {
                    content = fr.content;
                    if (fr.migrated_images > 0) {
                        console.log('[html] data URL 图片落盘:', fr.migrated_images);
                    }
                }
            } catch (e) {
                console.warn('[html] finalize_imported_html failed', e);
            }
        }
        sourceLabel = T('import_html_success', 'HTML 导入完成');
    } else if (r.content != null) {
        content = r.content;
        docDir = (r && r.doc_dir) ? String(r.doc_dir) : '';
        sourceLabel = T('import_html_success', 'HTML 导入完成');
    }

    if (!content && content !== '') {
        setStatus(T('import_html_failed', '导入失败') + '：无法提取内容');
        return;
    }

    currentFile = '';
    currentDocDir = docDir;
    syncGlobalFileState();

    setContent(content);
    setFilePathDisplay('', T('imported_from_html', '（来自 HTML）'));
    setStatus(sourceLabel);
    try { await window.pywebview.api.set_current_file(''); } catch (e) {}

    _openedOriginalContent = getContent();
    _openedFilePath = '';
    _forceSaveAsNextTime = false;
}

// ---------------- HTML → Markdown 转换（第三方 HTML） ----------------
function convertHtmlToMarkdown(html) {
    try {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const body = doc.body;
        if (!body) return '';

        return htmlNodeToMarkdown(body).replace(/\n{3,}/g, '\n\n').trim();
    } catch (e) {
        console.error('[convertHtmlToMarkdown]', e);
        return '';
    }
}

function htmlNodeToMarkdown(node) {
    let out = '';
    const children = node.childNodes;
    for (let i = 0; i < children.length; i++) {
        out += htmlNodeOneToMarkdown(children[i]);
    }
    return out;
}

function extractKatexTex(node) {
    if (!node || !node.querySelector) return null;
    const ann = node.querySelector('annotation[encoding="application/x-tex"]');
    if (!ann) return null;
    return ann.textContent || '';
}

function htmlNodeOneToMarkdown(node) {
    if (node.nodeType === 3) {
        return node.nodeValue || '';
    }
    if (node.nodeType !== 1) return '';

    const tag = node.tagName.toLowerCase();

    if (node.classList &&
        (node.classList.contains('task-list-bullet') ||
         node.classList.contains('md-summary'))) {
        return '';
    }

    if (tag === 'script' || tag === 'style' || tag === 'noscript') {
        return '';
    }

    if (node.classList && node.classList.contains('math-block')) {
        const tex = extractKatexTex(node);
        if (tex != null && tex !== '') {
            return '\n\n$$' + tex + '$$\n\n';
        }
        const dataTex = node.getAttribute && node.getAttribute('data-tex');
        if (dataTex) {
            try {
                return '\n\n$$' + decodeURIComponent(dataTex) + '$$\n\n';
            } catch (e) { /* ignore */ }
        }
        return '';
    }
    if (node.classList && node.classList.contains('katex-display')) {
        const tex = extractKatexTex(node);
        if (tex != null && tex !== '') {
            return '\n\n$$' + tex + '$$\n\n';
        }
        return '';
    }
    if (node.classList && node.classList.contains('katex')) {
        const tex = extractKatexTex(node);
        if (tex != null && tex !== '') {
            return '$' + tex + '$';
        }
        return '';
    }
    if (node.classList &&
        (node.classList.contains('katex-mathml') ||
         node.classList.contains('katex-html'))) {
        return '';
    }

    if (/^h[1-6]$/.test(tag)) {
        const level = parseInt(tag[1], 10);
        const text = inlineChildrenToMarkdown(node).trim();
        return '#'.repeat(level) + ' ' + text + '\n\n';
    }

    if (tag === 'p') {
        const text = inlineChildrenToMarkdown(node).trim();
        if (!text) return '';
        return text + '\n\n';
    }

    if (tag === 'br') return '\n';

    if (tag === 'hr') return '\n---\n\n';

    if (tag === 'ul' || tag === 'ol') {
        return listToMarkdown(node, tag === 'ol', 0);
    }

    if (tag === 'blockquote') {
        const inner = htmlNodeToMarkdown(node);
        const lines = inner.split('\n');
        const quoted = lines.map(l => l ? '> ' + l : '>').join('\n');
        return quoted + '\n\n';
    }

    if (tag === 'pre') {
        const codeEl = node.querySelector('code');
        const text = codeEl ? (codeEl.textContent || '') : (node.textContent || '');
        let lang = '';
        if (codeEl) {
            const cls = codeEl.className || '';
            const m = /language-([\w-]+)/.exec(cls);
            if (m) lang = m[1];
        }
        return '```' + lang + '\n' + text.replace(/\n$/, '') + '\n```\n\n';
    }

    if (tag === 'code') {
        const text = node.textContent || '';
        if (!text) return '';
        return '`' + text + '`';
    }

    if (tag === 'table') {
        return tableToMarkdown(node) + '\n\n';
    }

    if (tag === 'img') {
        const src = node.getAttribute('src') || '';
        const alt = node.getAttribute('alt') || '';
        if (!src) return '';
        if (/[\s()<>]/.test(src) && !src.startsWith('<')) {
            return '![' + alt + '](<' + src + '>)';
        }
        return '![' + alt + '](' + src + ')';
    }

    if (tag === 'a') {
        const href = node.getAttribute('href') || '';
        const text = inlineChildrenToMarkdown(node);
        if (!href) return text;
        return '[' + text + '](' + href + ')';
    }

    if (tag === 'strong' || tag === 'b') {
        return '**' + inlineChildrenToMarkdown(node) + '**';
    }
    if (tag === 'em' || tag === 'i') {
        return '*' + inlineChildrenToMarkdown(node) + '*';
    }
    if (tag === 'del' || tag === 's' || tag === 'strike') {
        return '~~' + inlineChildrenToMarkdown(node) + '~~';
    }
    if (tag === 'ins' || tag === 'u') {
        return '<ins>' + inlineChildrenToMarkdown(node) + '</ins>';
    }

    if (tag === 'details') {
        const summary = node.querySelector(':scope > summary');
        const title = summary ? (summary.textContent || '').trim() : '展开';
        let body = '';
        for (const sub of node.childNodes) {
            if (sub === summary) continue;
            body += htmlNodeOneToMarkdown(sub);
        }
        return '<details>\n<summary>' + title + '</summary>\n\n' +
               body.trim() + '\n\n</details>\n\n';
    }

    if (tag === 'tr' || tag === 'td' || tag === 'th' ||
        tag === 'thead' || tag === 'tbody' || tag === 'tfoot') {
        return htmlNodeToMarkdown(node);
    }

    if (tag === 'div' || tag === 'section' || tag === 'article' ||
        tag === 'main' || tag === 'header' || tag === 'footer' ||
        tag === 'nav' || tag === 'aside' || tag === 'figure') {
        return htmlNodeToMarkdown(node);
    }

    return htmlNodeToMarkdown(node);
}

function inlineChildrenToMarkdown(node) {
    let out = '';
    for (const child of node.childNodes) {
        out += htmlNodeOneToMarkdown(child);
    }
    return out;
}

function listToMarkdown(listEl, ordered, depth) {
    let out = '';
    let idx = 1;
    const indent = '    '.repeat(depth);

    for (const li of listEl.children) {
        if (li.tagName.toLowerCase() !== 'li') continue;

        const checkbox = li.querySelector(':scope > .task-list-checkbox, :scope > input[type="checkbox"]');
        const isTask = !!checkbox ||
            (li.classList && li.classList.contains('task-list-item'));

        const clone = li.cloneNode(true);
        clone.querySelectorAll('.task-list-bullet, .task-list-checkbox').forEach(e => e.remove());
        const nestedLists = [];
        clone.querySelectorAll(':scope > ul, :scope > ol').forEach(n => {
            nestedLists.push(n);
            n.remove();
        });

        const text = inlineChildrenToMarkdown(clone).trim();
        let prefix;
        if (isTask) {
            const checked = checkbox &&
                (checkbox.getAttribute('data-md-task-checked') === '1' ||
                 checkbox.checked);
            prefix = '- [' + (checked ? 'x' : ' ') + '] ';
        } else if (ordered) {
            prefix = idx + '. ';
            idx++;
        } else {
            prefix = '- ';
        }

        out += indent + prefix + text + '\n';

        for (const nested of nestedLists) {
            const nTag = nested.tagName.toLowerCase();
            out += listToMarkdown(nested, nTag === 'ol', depth + 1);
        }
    }

    if (depth === 0) out += '\n';
    return out;
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

// ★ 新增：关闭前的未保存确认（由后端 closing 事件触发）
let _closeDialogOpen = false;
window.onCloseRequested = async function () {
    if (_closeDialogOpen) return;
    _closeDialogOpen = true;
    try {
        const ok = await showConfirm(
            T('unsaved_content_title', '未保存的内容'),
            T('unsaved_content_warning', '未保存的内容将丢失，继续？')
        );
        if (ok) {
            try {
                await window.pywebview.api.force_close();
            } catch (e) { /* ignore */ }
        }
    } finally {
        _closeDialogOpen = false;
    }
};

function setStatus(text) { statusEl.textContent = text; }