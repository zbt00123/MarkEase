// MarkEase 多语言模块（阶段 14）
//   ★ v2.1.2：FALLBACK 增加 logs 相关键
// 普通 script 加载，挂 window.I18N
(function (global) {
    'use strict';

    let _dict = {};
    let _lang = 'zh_CN';
    let _callbacks = [];
    let _ready = false;

    const FALLBACK = {
        file: '文件',
        new: '新建',
        open: '打开',
        save: '保存',
        save_as: '另存为',
        export_pdf: '导出为 PDF',
        exit: '退出',
        edit: '编辑',
        view: '查看',
        help: '帮助',
        undo: '撤销',
        redo: '重做',
        cut: '剪切',
        copy: '复制',
        paste: '粘贴',
        find: '查找',
        replace: '替换',
        find_no_match: '无匹配内容',
        find_first: '已经是第一个',
        find_last: '已经是最后一个',
        find_replaced_one: '已替换 1 处',
        find_replaced_one_hidden: '已替换 1 处（该处在预览中不可见）',
        find_replaced_hidden_suffix: '（其中 {hidden} 处在预览中不可见）',
        find_preview_invisible: '该处在预览中不可见',
        find_preview_unsupported: '当前环境不支持预览高亮，请更新 WebView 运行时',
        fuzzy: '模糊',
        fuzzy_search: '跨 Markdown 行内标记搜索（忽略 **、*、~~、反引号等）',
        find_exact_count: '精确 {count}',
        find_fuzzy_count: '模糊 {count}',
        find_fuzzy_hint: '检测到 {count} 处跨格式匹配；勾选「模糊」后可替换，或在编辑区手动修改。',
        find_fuzzy_replace_note: '模糊匹配替换时会连同格式标记一起替换。',
        find_fuzzy_replace_title: '替换跨格式匹配',
        find_fuzzy_replace_message: '将替换源码片段：\n{source}\n\n替换为：\n{replacement}\n\n格式标记会一并替换。',
        find_fuzzy_danger_warning: '警告：该片段包含链接地址、图片、HTML 标签或公式，替换会删除这些结构。',
        find_fuzzy_replace_all_title: '替换全部跨格式匹配',
        find_fuzzy_replace_all_message: '将替换 {count} 处模糊匹配，格式标记会一并替换。',
        find_fuzzy_danger_warning_all: '其中 {dangerous} 处包含链接地址、图片、HTML 标签或公式，替换会删除这些结构。',
        find_fuzzy_replace_done: '已替换 1 处模糊匹配',
        find_fuzzy_replace_all_done: '已替换 {count} 处（其中 {fuzzy} 处模糊匹配）。',
        find_fuzzy_not_replaced: '已替换 {exact} 处精确匹配；{fuzzy} 处模糊匹配未替换。',
        find_preview_fuzzy_blocked_title: '无法在预览中替换',
        find_preview_fuzzy_blocked_message: '这是跨格式的模糊匹配，当前未勾选「模糊」。请勾选「模糊」后替换，或切换到分屏手动修改。',
        find_switch_to_split: '切换到分屏',
        find_fuzzy_need_checkbox: '跨格式匹配需要勾选「模糊」后才能替换',
        edit_mode: '编辑模式',
        preview_mode: '预览模式',
        split_mode: '分屏模式',
        show_toc: '显示目录',
        close_toc: '关闭目录',
        zoom_in: '放大',
        zoom_out: '缩小',
        reset_zoom: '重置缩放',
        toggle_theme: '切换主题',
        theme: '主题',
        language: '语言',
        system: '跟随系统',
        light: '浅色',
        dark: '深色',
        about: '关于 MarkEase',
        check_update: '检查更新',
        close: '关闭',
        cancel: '取消',
        discard: '不保存',
        later: '稍后',
        open_download_page: '打开发布页',
        update_notes: '更新内容',
        current_version: '当前版本',
        latest_version: '最新版本',
        update_available_title: '发现新版本',
        update_latest_title: '已是最新版本',
        update_error_title: '检查更新失败',
        update_error_message: '无法连接到 GitHub，请稍后重试。',
        update_latest_message: '当前已是最新版本（v{version}）。',
        format_painter: '格式刷',
        eraser: '橡皮擦',
        collapse: '折叠/展开',
        table: '插入表格',
        insert_link: '插入链接',
        insert_image: '插入图片',
        bold: '加粗',
        italic: '斜体',
        strikethrough: '删除线',
        clear_format: '清除格式',
        quote: '引用',
        inline_code: '行内代码',
        code_block: '代码块',
        unordered_list: '无序列表',
        ordered_list: '有序列表',
        task_list: '任务列表',
        heading: '标题',
        toolbar_more: '更多',
        heading_1: '一级标题',
        heading_2: '二级标题',
        heading_3: '三级标题',
        heading_4: '四级标题',
        heading_5: '五级标题',
        heading_6: '六级标题',
        toc_title: '目录',
        ready: '就绪',
        words: '字数',
        lines: '行数',
        ok: '确定',

        // ★ 关闭未保存文档提示
        unsaved_content_title: '未保存的内容',
        unsaved_message: '当前文档有未保存的修改，是否保存？',
        recovered_after_crash: '界面异常后已恢复编辑内容',

        // ★ v2.1.2：帮助菜单 - 日志
        logs: '日志',
        logs_opened: '已打开日志目录',
        logs_open_failed: '打开日志目录失败',
        logs_open_failed_title: '打开日志目录失败',
        logs_unavailable: '日志接口未就绪',
    };

    function normalizeLang(lang) {
        if (!lang) return 'zh_CN';
        const s = String(lang).trim().replace('-', '_');
        const low = s.toLowerCase();

        if (low === 'system') return 'system';

        const map = {
            zh_cn: 'zh_CN',
            zh_hans: 'zh_CN',
            zh_sg: 'zh_CN',
            zh_tw: 'zh_TW',
            zh_hk: 'zh_TW',
            zh_hant: 'zh_TW',
            en: 'en_US',
            en_us: 'en_US',
            en_gb: 'en_US',
            ja: 'ja_JP',
            ja_jp: 'ja_JP',
            ko: 'ko_KR',
            ko_kr: 'ko_KR',
        };
        if (map[low]) return map[low];

        if (low.startsWith('zh')) return 'zh_CN';
        if (low.startsWith('en')) return 'en_US';
        if (low.startsWith('ja')) return 'ja_JP';
        if (low.startsWith('ko')) return 'ko_KR';
        return 'zh_CN';
    }

    function detectSystemLang() {
        const nav = global.navigator || {};
        const raw = nav.language || nav.userLanguage || 'zh-CN';
        return normalizeLang(raw);
    }

    async function ensureApi() {
        if (global.pywebview && global.pywebview.api) return global.pywebview.api;
        await new Promise(resolve => {
            global.addEventListener('pywebviewready', resolve, { once: true });
        });
        return global.pywebview.api;
    }

    async function loadDict(lang) {
        const api = await ensureApi();
        if (!api || !api.get_translations) {
            _dict = Object.assign({}, FALLBACK);
            return;
        }
        try {
            const r = await api.get_translations(lang);
            if (r && r.ok && r.dict) {
                _dict = Object.assign({}, FALLBACK, r.dict);
                _lang = r.lang || lang;
            } else {
                _dict = Object.assign({}, FALLBACK);
            }
        } catch (e) {
            console.warn('[i18n] load failed', e);
            _dict = Object.assign({}, FALLBACK);
        }
    }

    async function init(lang) {
        const requested = normalizeLang(lang || 'system');
        const realLang = requested === 'system' ? detectSystemLang() : requested;
        _lang = realLang;
        await loadDict(realLang);
        applyToDOM(document);
        _ready = true;
        return _lang;
    }

    function t(key, vars) {
        let s = _dict[key];
        if (s == null) s = FALLBACK[key];
        if (s == null) s = key;
        if (vars && typeof s === 'string') {
            Object.keys(vars).forEach(k => {
                s = s.split('{' + k + '}').join(String(vars[k]));
            });
        }
        return s;
    }

    function applyToDOM(root) {
        const scope = root || document;

        scope.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (!key) return;
            el.textContent = t(key);
        });

        scope.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            if (!key) return;
            el.setAttribute('title', t(key));
        });

        scope.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            if (!key) return;
            el.setAttribute('placeholder', t(key));
        });

        scope.querySelectorAll('[data-i18n-tooltip]').forEach(el => {
            const key = el.getAttribute('data-i18n-tooltip');
            if (!key) return;
            el.setAttribute('data-tooltip', t(key));
        });

        scope.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
            const key = el.getAttribute('data-i18n-aria-label');
            if (!key) return;
            el.setAttribute('aria-label', t(key));
        });
    }

    async function setLanguage(lang) {
        const requested = normalizeLang(lang || 'system');
        const realLang = requested === 'system' ? detectSystemLang() : requested;
        _lang = realLang;
        await loadDict(realLang);

        try {
            const api = await ensureApi();
            if (api && api.set_language) {
                await api.set_language(requested);
            }
        } catch (e) {
            console.warn('[i18n] set_language failed', e);
        }

        applyToDOM(document);
        _callbacks.forEach(cb => {
            try { cb(_lang); } catch (e) { console.warn('[i18n] callback', e); }
        });
        return _lang;
    }

    function onChange(cb) {
        if (typeof cb === 'function') _callbacks.push(cb);
    }

    function getLanguage() {
        return _lang;
    }

    function isReady() {
        return _ready;
    }

    global.I18N = {
        init,
        t,
        setLanguage,
        getLanguage,
        applyToDOM,
        onChange,
        normalizeLang,
        isReady,
    };
})(window);