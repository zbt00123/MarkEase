// MarkEase 关于窗口前端（阶段 15 修订：标题本地化 + 支持主窗口热刷新）
(function () {
    'use strict';

    let api = null;

    function T(key, fallback) {
        try {
            if (window.I18N && typeof window.I18N.t === 'function') {
                const v = window.I18N.t(key);
                if (v && v !== key) return v;
            }
        } catch (e) { /* ignore */ }
        return fallback || key;
    }

    async function applyThemeFromSettings(settings) {
        try {
            const theme = (settings && settings.theme) || 'system';
            let dark = false;
            if (theme === 'dark') dark = true;
            else if (theme === 'light') dark = false;
            else dark = !!(window.matchMedia &&
                window.matchMedia('(prefers-color-scheme: dark)').matches);
            document.body.classList.toggle('dark', dark);
            document.documentElement.classList.toggle('dark', dark);
        } catch (e) {
            console.warn('[about] applyTheme failed', e);
        }
    }

    async function loadVersion() {
        try {
            const v = await api.get_version();
            if (v && v.ok) {
                const el = document.getElementById('about-version');
                if (el) el.textContent = 'v' + (v.version || '1.0.0');
            }
        } catch (e) {
            console.warn('[about] loadVersion failed', e);
        }
    }

    async function loadIcon() {
        try {
            const r = await api.get_icon_url();
            if (r && r.ok && r.url) {
                const img = document.getElementById('about-logo-img');
                const wrap = document.getElementById('about-logo');
                if (img && wrap) {
                    img.onload = () => {
                        img.style.display = 'block';
                        wrap.classList.add('has-icon');
                    };
                    img.onerror = () => {
                        img.style.display = 'none';
                        wrap.classList.remove('has-icon');
                    };
                    img.src = r.url;
                }
            }
        } catch (e) {
            console.warn('[about] loadIcon failed', e);
        }
    }

    // ★ 新增：把 about_title 同步到原生窗口标题 + document.title
    async function updateWindowTitle() {
        const title = T('about_title', '关于 MarkEase');
        try {
            document.title = title;
        } catch (e) { /* ignore */ }

        if (api && api.set_window_title) {
            try {
                await api.set_window_title(title);
            } catch (e) {
                console.warn('[about] set_window_title failed', e);
            }
        }
    }

    // ★ 语言：以主程序设置为准
    async function initI18n(settings) {
        if (!window.I18N) return;

        let choice = 'system';
        try {
            if (settings && settings.language) {
                choice = settings.language;
            } else {
                const stored = localStorage.getItem('markease_language');
                if (stored) choice = stored;
            }
        } catch (e) { /* ignore */ }

        try {
            await window.I18N.init(choice);
        } catch (e) {
            console.warn('[about] i18n init failed', e);
        }
    }

    // ★ 新增：主窗口通过 notify_about_refresh 触发本函数
    window.__refreshFromMain = async function () {
        try {
            let settings = {};
            try {
                settings = await api.get_settings() || {};
            } catch (e) {
                console.warn('[about] refresh get_settings failed', e);
            }

            // 1) 主题
            await applyThemeFromSettings(settings);

            // 2) 语言（重新加载词典并刷新 DOM）
            if (window.I18N) {
                const choice = settings.language || 'system';
                try {
                    await window.I18N.setLanguage(choice);
                } catch (e) {
                    console.warn('[about] refresh setLanguage failed', e);
                }
                if (window.I18N.applyToDOM) {
                    window.I18N.applyToDOM(document);
                }
            }

            // 3) 窗口标题（本地化）
            await updateWindowTitle();

            // 4) 版本/图标保持
            await loadVersion();
            await loadIcon();
        } catch (e) {
            console.warn('[about] __refreshFromMain failed', e);
        }
    };

    async function init() {
        if (!window.pywebview || !window.pywebview.api) {
            await new Promise(res =>
                window.addEventListener('pywebviewready', res, { once: true }));
        }
        api = window.pywebview.api;

        // 先加载设置
        let settings = {};
        try {
            settings = await api.get_settings() || {};
        } catch (e) {
            console.warn('[about] get_settings failed', e);
        }

        // 主题
        await applyThemeFromSettings(settings);

        // 多语言
        await initI18n(settings);
        if (window.I18N && window.I18N.applyToDOM) {
            window.I18N.applyToDOM(document);
        }

        // ★ 窗口标题本地化
        await updateWindowTitle();

        // 版本 & 图标
        await loadVersion();
        await loadIcon();

        // 关闭按钮
        const closeBtn = document.getElementById('about-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => api.close_window());
        }

        // 外部链接
        document.querySelectorAll('[data-external-url]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const url = el.getAttribute('data-external-url');
                if (url && api.open_external_url) {
                    api.open_external_url(url);
                }
            });
        });

        // Esc 关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') api.close_window();
        });
    }

    init().catch(e => console.error('[about] init failed', e));
})();