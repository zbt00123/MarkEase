// MarkEase SVG 图标库（阶段 13 修订 3）
(function () {
    'use strict';
    const _O = '<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
    const _C = '</svg>';
    const w = (p) => _O + p + _C;

    window.ICONS = {
        // 文件
        newFile: w('<path d="M9.5 2H4a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6L9.5 2z"/><path d="M9.5 2v4H13"/>'),
        open: w('<path d="M2 4.5A1.5 1.5 0 0 1 3.5 3h2.6l1.4 1.8h5A1.5 1.5 0 0 1 14 6.3v5.2a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5v-7z"/>'),
        save: w('<path d="M3.5 2h7L13 4.5v9a.5.5 0 0 1-.5.5h-9a.5.5 0 0 1-.5-.5v-11a.5.5 0 0 1 .5-.5z"/><path d="M5 2v4h5V2M5 12h6"/>'),
        saveAs: w('<path d="M3.5 2h7L13 4.5v5"/><path d="M5 2v4h5V2"/><path d="M3 8.5v5a.5.5 0 0 0 .5.5h7"/><path d="M11 12.5h4M13 10.5v4"/>'),
        importPdf: w('<path d="M9.5 2H4a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6L9.5 2z"/><path d="M9.5 2v4H13"/><path d="M8 7v5M6 10l2 2 2-2"/>'),
        exportPdf: w('<path d="M9.5 2H4a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6L9.5 2z"/><path d="M9.5 2v4H13"/><path d="M8 12V7M6 9l2-2 2 2"/>'),
        insertImage: w('<rect x="2" y="3" width="12" height="10" rx="1.5"/><circle cx="5.5" cy="6.5" r="1"/><path d="M2 11l3.5-3 3 2.5L11.5 8l2.5 3"/>'),

        // 历史
        undo: w('<path d="M3 8h7a3.5 3.5 0 1 1 0 7H7"/><path d="M6 5L3 8l3 3"/>'),
        redo: w('<path d="M13 8H6a3.5 3.5 0 1 0 0 7h3"/><path d="M10 5l3 3-3 3"/>'),

        // 格式
        bold: w('<path d="M5 3h4.5a2.5 2.5 0 0 1 0 5H5z"/><path d="M5 8h5a2.5 2.5 0 0 1 0 5H5z"/>'),
        italic: w('<path d="M10 3H6M10 13H6M9 3L7 13"/>'),
        strike: w('<path d="M3 8h10"/><path d="M11 5c0-1.1-1.3-2-3-2S5 3.9 5 5c0 .7.4 1.3 1.2 1.7"/><path d="M5 11c0 1.1 1.3 2 3 2s3-.9 3-2c0-.7-.4-1.3-1.2-1.7"/>'),
        h1: w('<path d="M3 4v8M9 4v8M3 8h6"/><path d="M11 6.5L13 5v7"/>'),
        h2: w('<path d="M2 4v8M7 4v8M2 8h5"/><path d="M9 7.5c0-1 .8-1.7 2-1.7s1.8.8 1.8 1.7c0 1.6-3.8 3-3.8 4.5H13"/>'),
        h3: w('<path d="M2 4v8M7 4v8M2 8h5"/><path d="M9 5.8h3.5L10.8 8a2 2 0 1 1-1.5 3.4"/>'),
        h4: w('<path d="M2 4v8M7 4v8M2 8h5"/><path d="M13 4L9 9h4M13 4v8"/>'),
        h5: w('<path d="M2 4v8M7 4v8M2 8h5"/><path d="M9 4v3h3l-.5 5H9"/>'),
        h6: w('<path d="M2 4v8M7 4v8M2 8h5"/><path d="M9 10.5a2 2 0 1 0 2-2 2 2 0 0 0-1.6.8L9 6h4"/>'),
        ul: w('<circle cx="3" cy="4" r="1" fill="currentColor" stroke="none"/><circle cx="3" cy="8" r="1" fill="currentColor" stroke="none"/><circle cx="3" cy="12" r="1" fill="currentColor" stroke="none"/><path d="M6 4h7M6 8h7M6 12h7"/>'),
        ol: w('<path d="M2 3h2v2M2 7h2v2M2 11h2v2M6 4h7M6 8h7M6 12h7"/>'),
        taskList: w('<rect x="1.5" y="2.5" width="3" height="3" rx="0.5"/><path d="M2 4l.7.7L4 3.3"/><rect x="1.5" y="10.5" width="3" height="3" rx="0.5"/><path d="M6 4h7M6 12h7"/>'),

        // ★ 引用图标：改为"左侧竖线 + 三条横线"（不再像眼睛）
        quote: w('<path d="M3.5 3v10" stroke-width="2" stroke-linecap="round"/><path d="M7 5h6M7 8h6M7 11h4"/>'),

        inlineCode: w('<path d="M5.5 4L2 8l3.5 4M10.5 4L14 8l-3.5 4"/>'),
        codeBlock: w('<rect x="1.5" y="2.5" width="13" height="11" rx="1"/><path d="M5.5 6L3.8 8l1.7 2M10.5 6L12.2 8l-1.7 2"/>'),
        link: w('<path d="M6.5 9.5l3-3"/><path d="M7 4.5l1.5-1.5a2.5 2.5 0 1 1 3.5 3.5L10.5 8"/><path d="M9 11.5L7.5 13a2.5 2.5 0 1 1-3.5-3.5L5.5 8"/>'),
        image: w('<rect x="1.5" y="3" width="13" height="10" rx="1"/><circle cx="5.5" cy="6.5" r="1"/><path d="M1.5 11l4-3.5 3 2.5L11.5 8l3 3"/>'),

        // 视图
        editMode: w('<path d="M10.5 2.5l3 3L5 14H2v-3z"/>'),
        splitMode: w('<rect x="1.5" y="3" width="13" height="10" rx="1"/><path d="M8 3v10"/>'),
        previewMode: w('<path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>'),
        sun: w('<circle cx="8" cy="8" r="3"/><path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M13 3l-1 1M4 12l-1 1"/>'),
        moon: w('<path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5 5.5 5.5 0 1 0 13.5 9.5z"/>'),
        toc: w('<path d="M2 4h2M6 4h8M4 8h2M8 8h6M2 12h2M6 12h8"/>'),

        // 帮助
        info: w('<circle cx="8" cy="8" r="6.5"/><path d="M8 11.5V7M8 5v.01"/>'),
        close: w('<path d="M3 3l10 10M13 3L3 13"/>'),
        check: w('<path d="M3 8l3.5 3.5L13 5"/>'),
        chevronDown: w('<path d="M4 6l4 4 4-4"/>'),

        // 阶段 13
        formatPainter: w('<path d="M3 13h4v-2H3z"/><path d="M4 11V8.5A1.5 1.5 0 0 1 5.5 7h5A1.5 1.5 0 0 1 12 8.5V11"/><rect x="6" y="2.5" width="4" height="4" rx="0.6"/><path d="M8 2.5V1.5"/>'),
        eraser: w('<path d="M9.5 3L13 6.5 7.5 12H4l-1.5-1.5z"/><path d="M3 12h10"/><path d="M7 8l3 3"/>'),
        table: w('<rect x="1.5" y="3" width="13" height="10" rx="1"/><path d="M1.5 6.5h13M1.5 9.8h13M5.5 3v10M10.5 3v10"/>'),
        collapse: w('<path d="M2 4h5M2 8h8M2 12h12"/><path d="M13 3l-3 3 3 3" transform="rotate(180 11.5 4.5)"/>'),
        chevronRight: w('<path d="M6 3l5 5-5 5"/>'),
        chevronDownSmall: w('<path d="M3 6l5 5 5-5"/>'),
        // 链接弹窗用
        fetch: w('<path d="M13.5 2.5A4 4 0 0 0 8 2.5L6 4.5a4 4 0 0 0 5.7 5.7l.3-.3"/><path d="M2.5 13.5A4 4 0 0 0 8 13.5l2-2a4 4 0 0 0-5.7-5.7l-.3.3"/><path d="M11 5l3 3-3 3"/><path d="M5 11l-3-3 3-3"/>'),

        github: '<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>',
    };
})();