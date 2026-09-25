// MarkEase 菜单栏逻辑（阶段 14 修订 2：支持二级子菜单 + i18n）
(function () {
    'use strict';

    let handlers = {};
    let activeMenuEl = null;
    let initialized = false;

    function initMenubar(actionHandlers) {
        if (initialized) return;
        initialized = true;

        handlers = actionHandlers || {};
        const menubar = document.getElementById('menubar');
        if (!menubar) {
            console.warn('[menubar] #menubar not found');
            return;
        }

        // 顶级菜单项
        menubar.querySelectorAll('.menu-item').forEach(item => {
            item.addEventListener('mouseenter', () => {
                if (activeMenuEl && activeMenuEl !== item) {
                    openMenu(item);
                }
            });
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                if (item.classList.contains('open')) {
                    closeMenu();
                } else {
                    openMenu(item);
                }
            });
        });

        // 所有可点击的动作项（包括子菜单里的）
        menubar.querySelectorAll('.menu-entry[data-action]').forEach(entry => {
            entry.addEventListener('click', (e) => {
                e.stopPropagation();
                if (entry.classList.contains('disabled')) return;
                const action = entry.getAttribute('data-action');
                closeMenu();
                if (action && typeof handlers[action] === 'function') {
                    try {
                        handlers[action]();
                    } catch (err) {
                        console.error('[menubar] action failed:', action, err);
                    }
                }
            });
        });

        // 二级菜单父项
        menubar.querySelectorAll('.menu-entry.has-submenu').forEach(parent => {
            parent.addEventListener('mouseenter', () => {
                openSubmenu(parent);
            });
            parent.addEventListener('mouseleave', () => {
                // 延迟关闭，允许鼠标移动到子菜单上
                setTimeout(() => {
                    if (!parent.matches(':hover')) closeSubmenu(parent);
                }, 180);
            });
            parent.addEventListener('click', (e) => {
                e.stopPropagation();
                if (parent.classList.contains('submenu-open')) {
                    closeSubmenu(parent);
                } else {
                    openSubmenu(parent);
                }
            });
        });

        document.addEventListener('click', (e) => {
            if (!menubar.contains(e.target)) closeMenu();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeMenu();
        });

        refreshI18n();
    }

    function openSubmenu(parent) {
        const menubar = document.getElementById('menubar');
        if (!menubar) return;
        menubar.querySelectorAll('.menu-entry.has-submenu.submenu-open').forEach(el => {
            if (el !== parent) el.classList.remove('submenu-open');
        });
        parent.classList.add('submenu-open');
    }

    function closeSubmenu(parent) {
        parent.classList.remove('submenu-open');
    }

    function closeAllSubmenus() {
        const menubar = document.getElementById('menubar');
        if (!menubar) return;
        menubar.querySelectorAll('.menu-entry.has-submenu.submenu-open').forEach(el => {
            el.classList.remove('submenu-open');
        });
    }

    // ---------- i18n 刷新 ----------
    function refreshI18n() {
        if (!window.I18N) return;
        const menubar = document.getElementById('menubar');
        if (menubar && typeof window.I18N.applyToDOM === 'function') {
            window.I18N.applyToDOM(menubar);
        }
        updateLanguageChecks();
    }

    function getCurrentLangChoice() {
        try {
            const raw = localStorage.getItem('markease_language');
            if (raw) return raw;
        } catch (e) { /* ignore */ }
        return 'system';
    }

    function updateLanguageChecks() {
        const choice = getCurrentLangChoice();
        document.querySelectorAll('.menu-entry[data-action^="lang_"]')
            .forEach(el => el.classList.remove('checked'));

        const key = (choice === 'system' || !choice)
            ? 'lang_system'
            : ('lang_' + choice);
        const target = document.querySelector(
            '.menu-entry[data-action="' + key + '"]');
        if (target) target.classList.add('checked');
    }

    function openMenu(item) {
        if (activeMenuEl === item) return;
        if (activeMenuEl) {
            activeMenuEl.classList.remove('open', 'active');
        }
        closeAllSubmenus();
        item.classList.add('open', 'active');
        activeMenuEl = item;
    }

    function closeMenu() {
        if (activeMenuEl) {
            activeMenuEl.classList.remove('open', 'active');
            activeMenuEl = null;
        }
        closeAllSubmenus();
    }

    function setMenuChecked(action, checked) {
        document.querySelectorAll(
            '.menu-entry[data-action="' + action + '"]'
        ).forEach(el => {
            el.classList.toggle('checked', !!checked);
        });
    }

    function setMenuEnabled(action, enabled) {
        document.querySelectorAll(
            '.menu-entry[data-action="' + action + '"]'
        ).forEach(el => {
            el.classList.toggle('disabled', !enabled);
        });
    }

    window.MenuBar = {
        init: initMenubar,
        setChecked: setMenuChecked,
        setEnabled: setMenuEnabled,
        closeAll: closeMenu,
        refreshI18n: refreshI18n,
    };
})();