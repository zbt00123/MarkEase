// MarkEase 图片选择弹窗前端（阶段 10 修订 8：图标视图排序按钮）
(function () {
    'use strict';

    let api = null;
    let ASSET_BASE = '';

    const nav = {
        history: [],
        index: -1,
        current: '',
        listing: null,
        selected: null,
    };

    let pendingConflict = null;
    let viewMode = 'grid';     // 'grid' | 'list'
    let iconSize = 2;          // 1 | 2 | 3
    let sortKey = 'type';      // ★ 默认按“类别”排列
    let sortAsc = true;

    // ---------- DOM ----------
    const tabButtons = document.querySelectorAll('.tab');
    const panels = {
        local: document.getElementById('panel-local'),
        remote: document.getElementById('panel-remote'),
    };
    const sideShortcuts = document.getElementById('side-shortcuts');
    const sideDrives = document.getElementById('side-drives');
    const breadcrumb = document.getElementById('breadcrumb');
    const grid = document.getElementById('local-grid');
    const listHeader = document.getElementById('list-header');
    const btnBack = document.getElementById('btn-back');
    const btnForward = document.getElementById('btn-forward');
    const btnUp = document.getElementById('btn-up');
    const btnViewGrid = document.getElementById('btn-view-grid');
    const btnViewList = document.getElementById('btn-view-list');
    const sizeSlider = document.getElementById('size-slider');
    const sortControl = document.getElementById('sort-control');
    const sortSelect = document.getElementById('sort-select');
    const btnLocalCancel = document.getElementById('btn-local-cancel');
    const btnLocalConfirm = document.getElementById('btn-local-confirm');
    const localSelected = document.getElementById('local-selected');

    const remoteUrl = document.getElementById('remote-url');
    const remoteStatus = document.getElementById('remote-status');
    const btnRemoteCancel = document.getElementById('btn-remote-cancel');
    const btnRemoteImport = document.getElementById('btn-remote-import');

    const conflictModal = document.getElementById('conflict-modal');
    const conflictSrcImg = document.getElementById('conflict-src-img');
    const conflictSrcName = document.getElementById('conflict-src-name');
    const conflictSrcSize = document.getElementById('conflict-src-size');
    const conflictTargetImg = document.getElementById('conflict-target-img');
    const conflictTargetName = document.getElementById('conflict-target-name');
    const conflictTargetSize = document.getElementById('conflict-target-size');
    const conflictCancel = document.getElementById('conflict-cancel');
    const conflictKeepBoth = document.getElementById('conflict-keep-both');
    const conflictReplace = document.getElementById('conflict-replace');

    // ---------- 工具函数 ----------
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function fsUrl(absPath) {
        if (!absPath || !ASSET_BASE) return '';
        const normalized = String(absPath).replace(/\\/g, '/');
        return ASSET_BASE + '/fs/' + encodeURIComponent(normalized);
    }

    function setStatus(el, text, kind) {
        el.textContent = text || '';
        el.className = 'status' + (kind ? ' ' + kind : '');
    }

    function samePath(a, b) {
        if (!a || !b) return false;
        const na = a.replace(/\\/g, '/').toLowerCase().replace(/\/+$/, '');
        const nb = b.replace(/\\/g, '/').toLowerCase().replace(/\/+$/, '');
        return na === nb;
    }

    function formatSize(bytes) {
        if (bytes == null) return '';
        const b = Number(bytes);
        if (!isFinite(b) || b <= 0) return b === 0 ? '0 B' : '';
        const units = ['B', 'KB', 'MB', 'GB'];
        let i = 0, v = b;
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
        return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + ' ' + units[i];
    }

    function getFileType(ext) {
        if (!ext) return '文件';
        const e = ext.toLowerCase();
        if (e === '.png') return 'PNG 图片';
        if (e === '.jpg' || e === '.jpeg') return 'JPEG 图片';
        if (e === '.gif') return 'GIF 图片';
        if (e === '.webp') return 'WebP 图片';
        if (e === '.svg') return 'SVG 图片';
        if (e === '.bmp') return 'BMP 图片';
        if (e === '.ico') return '图标';
        return (e.slice(1).toUpperCase() || '文件') + ' 文件';
    }

    const FOLDER_SVG =
        '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">' +
        '  <path d="M2 10 Q2 6 6 6 L22 6 L27 11 L58 11 Q62 11 62 15 L62 20 L2 20 Z" fill="#d98e00"/>' +
        '  <path d="M2 16 L62 16 L62 56 Q62 60 58 60 L6 60 Q2 60 2 56 Z" fill="#ffc107" stroke="#e0a000" stroke-width="0.5"/>' +
        '  <path d="M2 16 L62 16 L62 22 L2 22 Z" fill="rgba(255,255,255,0.3)"/>' +
        '</svg>';

    // ---------- 主题 ----------
    async function applyTheme() {
        try {
            const s = await api.get_settings();
            const theme = (s && s.theme) || 'system';
            let dark = false;
            if (theme === 'dark') dark = true;
            else if (theme === 'light') dark = false;
            else dark = !!(window.matchMedia &&
                window.matchMedia('(prefers-color-scheme: dark)').matches);
            document.body.classList.toggle('dark', dark);
        } catch (e) {
            console.warn('applyTheme failed', e);
        }
    }

    // ---------- 视图控制 ----------
    function applyViewMode() {
        if (viewMode === 'list') {
            grid.classList.add('list-view');
            if (listHeader) listHeader.classList.remove('hidden');
            if (sortControl) sortControl.classList.add('hidden');
            if (btnViewList) btnViewList.classList.add('active');
            if (btnViewGrid) btnViewGrid.classList.remove('active');
            if (sizeSlider) sizeSlider.disabled = true;
        } else {
            grid.classList.remove('list-view');
            if (listHeader) listHeader.classList.add('hidden');
            if (sortControl) sortControl.classList.remove('hidden');
            if (btnViewGrid) btnViewGrid.classList.add('active');
            if (btnViewList) btnViewList.classList.remove('active');
            if (sizeSlider) sizeSlider.disabled = false;
        }
        try { localStorage.setItem('markease.ip.view', viewMode); } catch (_) {}
    }

    function applyIconSize(v) {
        iconSize = v;
        grid.setAttribute('data-size', String(v));
        if (sizeSlider) sizeSlider.value = String(v);
        try { localStorage.setItem('markease.ip.size', String(v)); } catch (_) {}
    }

    // ★ 统一设置排序方式并刷新
    function setSort(key, asc) {
        if (key) sortKey = key;
        if (typeof asc === 'boolean') sortAsc = asc;
        if (sortSelect) sortSelect.value = sortKey;
        try {
            localStorage.setItem('markease.ip.sort', sortKey);
            localStorage.setItem('markease.ip.sortAsc', sortAsc ? '1' : '0');
        } catch (_) {}
        if (nav.listing) renderListing(nav.listing);
    }

    function loadPreferences() {
        try {
            const v = localStorage.getItem('markease.ip.view');
            if (v === 'grid' || v === 'list') viewMode = v;

            const s = parseInt(localStorage.getItem('markease.ip.size'), 10);
            if (s >= 1 && s <= 3) iconSize = s;

            const sk = localStorage.getItem('markease.ip.sort');
            if (sk === 'name' || sk === 'type' || sk === 'size') sortKey = sk;

            const sa = localStorage.getItem('markease.ip.sortAsc');
            if (sa === '0') sortAsc = false;
            if (sa === '1') sortAsc = true;
        } catch (_) {}
        applyViewMode();
        applyIconSize(iconSize);
        if (sortSelect) sortSelect.value = sortKey;
    }

    // ---------- Tabs ----------
    function switchTab(name) {
        tabButtons.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
        Object.entries(panels).forEach(([k, el]) => {
            if (el) el.classList.toggle('active', k === name);
        });
        if (name === 'remote') {
            setTimeout(() => remoteUrl && remoteUrl.focus(), 50);
        }
    }

    // ---------- 导航 ----------
    async function navigate(path, opts) {
        opts = opts || {};
        if (!path) return;
        const result = await api.list_directory(path);
        if (!result.ok) {
            setStatus(localSelected, '无法打开: ' + (result.error || ''), 'error');
            return;
        }

        const isSame = samePath(result.path, nav.current);

        if (opts.replaceHistory) {
            nav.history = [result.path];
            nav.index = 0;
        } else if (opts.fromHistory) {
            // 不改
        } else if (isSame) {
            // 相同路径不污染历史
        } else {
            if (nav.index < nav.history.length - 1) {
                nav.history = nav.history.slice(0, nav.index + 1);
            }
            nav.history.push(result.path);
            nav.index = nav.history.length - 1;
        }

        nav.current = result.path;
        nav.listing = result;
        nav.selected = null;

        renderListing(result);
        renderBreadcrumb(result.path);
        renderSidebarActive();
        updateNavButtons();
        updateConfirm();
        localSelected.textContent = '未选择';
        localSelected.classList.remove('error');
    }

    // ---------- 排序 + 渲染 ----------
    function compareItems(a, b, key, dir) {
        const cmpStr = (x, y) => String(x == null ? '' : x)
            .toLowerCase().localeCompare(String(y == null ? '' : y));
        let c = 0;
        if (key === 'type') {
            c = cmpStr(a.ext || '', b.ext || '');
            if (c === 0) c = cmpStr(a.name, b.name);
        } else if (key === 'size') {
            const sa = a.size || 0;
            const sb = b.size || 0;
            c = sa - sb;
            if (c === 0) c = cmpStr(a.name, b.name);
        } else { // name
            c = cmpStr(a.name, b.name);
        }
        return dir * c;
    }

    function renderListing(listing) {
        grid.innerHTML = '';

        const items = [];

        (listing.folders || []).forEach(f => {
            items.push({
                name: f.name,
                path: f.path,
                isFolder: true,
                ext: '',
                size: 0,
            });
        });

        (listing.images || []).forEach(i => {
            items.push({
                name: i.name,
                path: i.path,
                isFolder: false,
                ext: i.ext || '',
                size: i.size || 0,
            });
        });

        const dir = sortAsc ? 1 : -1;
        items.sort((a, b) => compareItems(a, b, sortKey, dir));

        items.forEach(item => {
            grid.appendChild(item.isFolder
                ? makeFolderCell(item)
                : makeImageCell(item));
        });

        if (items.length === 0) {
            const empty = document.createElement('div');
            empty.style.cssText =
                'grid-column:1/-1;text-align:center;color:#999;padding:40px;';
            empty.textContent = '此目录下没有文件夹或图片';
            grid.appendChild(empty);
        }

        updateSortArrows();
    }

    function updateSortArrows() {
        if (!listHeader) return;
        listHeader.querySelectorAll('.lh-col').forEach(col => {
            const arrow = col.querySelector('.sort-arrow');
            if (!arrow) return;
            if (col.dataset.sort === sortKey) {
                arrow.textContent = sortAsc ? '▲' : '▼';
            } else {
                arrow.textContent = '';
            }
        });
    }

    function makeFolderCell(folder) {
        const el = document.createElement('div');
        el.className = 'cell';
        el.innerHTML =
            `<div class="thumb"><span class="icon">${FOLDER_SVG}</span></div>` +
            `<div class="name" title="${esc(folder.name)}">${esc(folder.name)}</div>` +
            `<div class="type">文件夹</div>` +
            `<div class="size"></div>`;
        el.addEventListener('click', () => {
            selectCell(el, { path: folder.path, name: folder.name, isFolder: true });
        });
        el.addEventListener('dblclick', () => navigate(folder.path));
        return el;
    }

    function makeImageCell(img) {
        const el = document.createElement('div');
        el.className = 'cell';
        const url = fsUrl(img.path);
        el.innerHTML =
            `<div class="thumb"><img loading="lazy" src="${esc(url)}" alt=""></div>` +
            `<div class="name" title="${esc(img.name)}">${esc(img.name)}</div>` +
            `<div class="type">${esc(getFileType(img.ext))}</div>` +
            `<div class="size">${esc(formatSize(img.size))}</div>`;
        const imgEl = el.querySelector('img');
        imgEl.addEventListener('error', () => {
            const t = el.querySelector('.thumb');
            if (t) t.innerHTML = '<span class="icon">🖼</span>';
        });
        el.addEventListener('click', () => {
            selectCell(el, { path: img.path, name: img.name, isFolder: false });
        });
        el.addEventListener('dblclick', () => {
            selectCell(el, { path: img.path, name: img.name, isFolder: false });
            confirmLocal();
        });
        return el;
    }

    function selectCell(cellEl, info) {
        grid.querySelectorAll('.cell.selected')
            .forEach(c => c.classList.remove('selected'));
        cellEl.classList.add('selected');
        nav.selected = info;
        localSelected.textContent = info.isFolder
            ? '文件夹: ' + info.name
            : '图片: ' + info.name;
        localSelected.classList.remove('error');
        updateConfirm();
    }

    function updateConfirm() {
        const ok = !!(nav.selected && !nav.selected.isFolder);
        btnLocalConfirm.disabled = !ok;
    }

    // ---------- 面包屑 ----------
    function renderBreadcrumb(path) {
        breadcrumb.innerHTML = '';
        const normalized = String(path).replace(/\\/g, '/');
        const parts = normalized.split('/').filter(Boolean);
        if (parts.length === 0) return;

        const first = parts[0];
        const rest = parts.slice(1);

        const rootPath = first + '/';
        const rootCrumb = document.createElement('span');
        rootCrumb.className = 'crumb' + (rest.length === 0 ? ' last' : '');
        rootCrumb.textContent = first + '/';
        if (rest.length > 0) {
            rootCrumb.addEventListener('click', () => navigate(rootPath));
        }
        breadcrumb.appendChild(rootCrumb);

        rest.forEach((p, idx) => {
            const isLast = idx === rest.length - 1;

            const sep = document.createElement('span');
            sep.className = 'sep';
            sep.textContent = '›';
            breadcrumb.appendChild(sep);

            const crumbPath = [first].concat(rest.slice(0, idx + 1)).join('/');

            const crumb = document.createElement('span');
            crumb.className = 'crumb' + (isLast ? ' last' : '');
            crumb.textContent = p;
            if (!isLast) {
                crumb.addEventListener('click', () => navigate(crumbPath));
            }
            breadcrumb.appendChild(crumb);
        });
    }

    function renderSidebarActive() {
        document.querySelectorAll('.side-item').forEach(el => {
            const p = el.dataset.path;
            el.classList.toggle('active', p && samePath(p, nav.current));
        });
    }

    function updateNavButtons() {
        btnBack.disabled = nav.index <= 0;
        btnForward.disabled = nav.index >= nav.history.length - 1;
        btnUp.disabled = !(nav.listing && nav.listing.parent);
    }

    // ---------- 侧栏 / 驱动器 ----------
    function renderShortcuts(list) {
        sideShortcuts.innerHTML = '';
        list.forEach(s => {
            const el = document.createElement('div');
            el.className = 'side-item';
            el.dataset.path = s.path;
            el.innerHTML =
                `<span class="icon">📁</span><span>${esc(s.name)}</span>`;
            el.addEventListener('click', () => navigate(s.path));
            sideShortcuts.appendChild(el);
        });
    }

    function renderDrives(list) {
        sideDrives.innerHTML = '';
        list.forEach(d => {
            const el = document.createElement('div');
            el.className = 'side-item';
            el.dataset.path = d.path;
            el.innerHTML =
                `<span class="icon">💾</span><span>${esc(d.name)}</span>`;
            el.addEventListener('click', () => navigate(d.path));
            sideDrives.appendChild(el);
        });
    }

    // ---------- 本地确认 ----------
    async function confirmLocal() {
        if (!nav.selected || nav.selected.isFolder) return;
        btnLocalConfirm.disabled = true;
        try {
            const r = await api.select_local_image(nav.selected.path, 'probe');
            console.log('[image_picker] probe result:', r);
            if (r && r.conflict) {
                showConflictModal(r);
                return;
            }
            if (!r || !r.ok) {
                if (!(r && r.cancelled)) {
                    localSelected.textContent =
                        '选择失败: ' + ((r && r.error) || '未知错误');
                    localSelected.classList.add('error');
                }
                btnLocalConfirm.disabled = false;
            }
        } catch (e) {
            localSelected.textContent = '异常: ' + (e && e.message ? e.message : e);
            localSelected.classList.add('error');
            btnLocalConfirm.disabled = false;
        }
    }

    // ---------- 冲突弹窗 ----------
    function showConflictModal(info) {
        pendingConflict = { src_path: info.src_path };
        conflictSrcImg.src = fsUrl(info.src_path);
        conflictSrcName.textContent = info.src_name || '';
        conflictSrcSize.textContent = formatSize(info.src_size);
        conflictTargetImg.src = fsUrl(info.target_path);
        conflictTargetName.textContent = info.target_name || '';
        conflictTargetSize.textContent = formatSize(info.target_size);
        conflictModal.classList.remove('hidden');
    }

    function hideConflictModal() {
        conflictModal.classList.add('hidden');
        pendingConflict = null;
        btnLocalConfirm.disabled = false;
    }

    async function resolveConflict(action) {
        if (!pendingConflict) return;
        const src = pendingConflict.src_path;
        conflictCancel.disabled = true;
        conflictKeepBoth.disabled = true;
        conflictReplace.disabled = true;
        try {
            const r = await api.select_local_image(src, action);
            console.log('[image_picker] resolve result:', r);
            if (r && r.ok) {
                hideConflictModal();
            } else if (r && r.cancelled) {
                hideConflictModal();
            } else {
                hideConflictModal();
                localSelected.textContent =
                    '操作失败: ' + ((r && r.error) || '未知错误');
                localSelected.classList.add('error');
            }
        } catch (e) {
            hideConflictModal();
            localSelected.textContent =
                '异常: ' + (e && e.message ? e.message : e);
            localSelected.classList.add('error');
        } finally {
            conflictCancel.disabled = false;
            conflictKeepBoth.disabled = false;
            conflictReplace.disabled = false;
        }
    }

    // ---------- 网络 ----------
    async function onRemoteImport() {
        const url = remoteUrl.value.trim();
        if (!url) {
            setStatus(remoteStatus, '请输入图片 URL', 'error');
            return;
        }
        if (!/^https?:\/\//i.test(url)) {
            setStatus(remoteStatus, '仅支持 http/https 链接', 'error');
            return;
        }
        btnRemoteImport.disabled = true;
        setStatus(remoteStatus, '正在下载...', '');
        try {
            const r = await api.import_network_image(url);
            if (!r || !r.ok) {
                setStatus(remoteStatus,
                    '导入失败: ' + ((r && r.error) || '未知错误'), 'error');
                btnRemoteImport.disabled = false;
            }
        } catch (e) {
            setStatus(remoteStatus,
                '导入异常: ' + (e && e.message ? e.message : e), 'error');
            btnRemoteImport.disabled = false;
        }
    }

    // ---------- 初始化 ----------
    async function init() {
        if (!window.pywebview || !window.pywebview.api) {
            await new Promise(res =>
                window.addEventListener('pywebviewready', res, { once: true }));
        }
        api = window.pywebview.api;

        await applyTheme();
        loadPreferences();

        const state = await api.get_initial_state();
        if (!state || !state.ok) {
            localSelected.textContent = '初始化失败';
            localSelected.classList.add('error');
            return;
        }
        ASSET_BASE = state.asset_base || '';
        window.__assetBase = ASSET_BASE;

        renderShortcuts(state.shortcuts || []);
        renderDrives(state.drives || []);

        // Tabs
        tabButtons.forEach(b =>
            b.addEventListener('click', () => switchTab(b.dataset.tab)));

        // 导航按钮
        btnBack.addEventListener('click', () => {
            if (nav.index > 0) {
                nav.index--;
                navigate(nav.history[nav.index], { fromHistory: true });
            }
        });
        btnForward.addEventListener('click', () => {
            if (nav.index < nav.history.length - 1) {
                nav.index++;
                navigate(nav.history[nav.index], { fromHistory: true });
            }
        });
        btnUp.addEventListener('click', () => {
            if (nav.listing && nav.listing.parent) {
                navigate(nav.listing.parent);
            }
        });

        // 视图切换
        btnViewGrid.addEventListener('click', () => {
            viewMode = 'grid';
            applyViewMode();
        });
        btnViewList.addEventListener('click', () => {
            viewMode = 'list';
            applyViewMode();
        });
        sizeSlider.addEventListener('input', (e) => {
            if (sizeSlider.disabled) return;
            applyIconSize(parseInt(e.target.value, 10));
        });

        // ★ 图标视图排序下拉
        if (sortSelect) {
            sortSelect.value = sortKey;
            sortSelect.addEventListener('change', () => {
                setSort(sortSelect.value, true);
            });
        }

        // 列表视图表头：事件委托
        if (listHeader) {
            listHeader.addEventListener('click', (e) => {
                const col = e.target.closest && e.target.closest('.lh-col');
                if (!col) return;
                const key = col.dataset.sort;
                if (!key) return;
                if (sortKey === key) {
                    setSort(key, !sortAsc);
                } else {
                    setSort(key, true);
                }
            });
        }

        // 本地按钮
        btnLocalCancel.addEventListener('click', () => api.close_window());
        btnLocalConfirm.addEventListener('click', confirmLocal);

        // 冲突弹窗
        conflictCancel.addEventListener('click', () => resolveConflict('cancel'));
        conflictKeepBoth.addEventListener('click', () => resolveConflict('keep_both'));
        conflictReplace.addEventListener('click', () => resolveConflict('replace'));

        // 网络按钮
        btnRemoteCancel.addEventListener('click', () => api.close_window());
        btnRemoteImport.addEventListener('click', onRemoteImport);
        remoteUrl.addEventListener('keydown', e => {
            if (e.key === 'Enter') onRemoteImport();
        });

        if (state.starting_folder) {
            await navigate(state.starting_folder, { replaceHistory: true });
        }
    }

    init().catch(err => {
        console.error('[image_picker] init failed', err);
    });
})();