/*
 * MarkEase 前端平台层（普通 <script>，暴露 window.MKPlatform）
 *
 * 目的：让同一份前端代码在 Windows / macOS / Linux 上都能正确显示
 * 快捷键文案（Ctrl / ⌘），并给后续平台差异（路径分隔符等）留统一入口。
 *
 * 注意：后端 app/platform/ 才是"能力"的唯一来源；本文件只负责展示与按键约定。
 */
(function () {
    'use strict';

    var ua = '';
    var navPlatform = '';
    try {
        ua = String(navigator.userAgent || '');
        navPlatform = String(navigator.platform || '');
    } catch (e) { /* ignore */ }

    var probe = navPlatform + ' ' + ua;
    var isMac = /Mac|iPhone|iPad|iPod/i.test(probe);
    var isWindows = !isMac && /Win/i.test(probe);
    var isLinux = !isMac && !isWindows;

    // 'Ctrl+S' -> '⌘S'；'Shift+Ctrl+Z' -> '⇧⌘Z'
    function label(combo) {
        if (!combo) return '';
        var text = String(combo);
        if (!isMac) return text;
        // 先替换分隔符两侧的 Ctrl / Shift / Alt，再兜底整体替换
        text = text.replace(/\bCtrl\b/g, '⌘')
                   .replace(/\bShift\b/g, '⇧')
                   .replace(/\bAlt\b/g, '⌥');
        return text.replace(/\+/g, '');
    }

    window.MKPlatform = {
        name: isMac ? 'macOS' : (isWindows ? 'Windows' : 'Linux'),
        isMac: isMac,
        isWindows: isWindows,
        isLinux: isLinux,
        // 事件对象上用哪个修饰键
        modifierKey: function () { return isMac ? 'metaKey' : 'ctrlKey'; },
        // 文案里显示哪个修饰键
        modifier: function () { return isMac ? '⌘' : 'Ctrl'; },
        // 把 'Ctrl+S' 这类文案转成当前平台习惯
        label: label,
        shortcut: label,
        // 路径显示辅助（Windows 反斜杠，其余斜杠）
        pathSep: function () { return isWindows ? '\\' : '/'; }
    };
})();
