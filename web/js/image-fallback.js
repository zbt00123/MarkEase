// MarkEase 图片加载失败处理
// - 图片失败时显示占位符
// - 点击占位符手动重试（最多 3 次）
// - ★ 阶段 15 修订 10：移除 5 秒定时重试，避免图片持续失败时周期性刷新
(function () {
    'use strict';

    const FALLBACK_SVG =
        'data:image/svg+xml;utf8,' + encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="80" viewBox="0 0 140 80">' +
            '<rect x="0.5" y="0.5" width="139" height="79" fill="#f6f6f6" stroke="#d0d0d0" stroke-dasharray="4 3" rx="4"/>' +
            '<text x="70" y="38" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#888">图片加载失败</text>' +
            '<text x="70" y="56" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#aaa">点击重试</text>' +
            '</svg>'
        );

    const MAX_RETRY = 3;

    function _markFailed(img) {
        const src = img.dataset.mefOriginal || img.src;
        if (!src || src === FALLBACK_SVG) return;
        if (img.dataset.mefFallback === '1') return;

        img.dataset.mefFallback = '1';
        img.dataset.mefOriginal = src;

        img.src = FALLBACK_SVG;

        const tries = parseInt(img.dataset.mefRetryCount || '0', 10);
        if (tries >= MAX_RETRY) {
            img.title = '图片加载失败（已重试 ' + MAX_RETRY +
                        ' 次）：' + src + '（点击可再试）';
        } else {
            img.title = '图片加载失败：' + src + '（点击重试）';
        }
        img.style.cursor = 'pointer';

        if (!img.dataset.mefClickBound) {
            img.dataset.mefClickBound = '1';
            img.addEventListener('click', () => _retry(img), true);
        }
    }

    function _retry(img) {
        const original = img.dataset.mefOriginal;
        if (!original) return;

        const tries = parseInt(img.dataset.mefRetryCount || '0', 10);
        if (tries >= MAX_RETRY) {
            // 已经重试 3 次，再点也不会有更好结果了
            img.title = '图片加载失败（已重试 ' + MAX_RETRY +
                        ' 次）：' + original;
            return;
        }
        img.dataset.mefRetryCount = String(tries + 1);

        delete img.dataset.mefFallback;

        const sep = original.includes('?') ? '&' : '?';
        // 加时间戳绕过缓存
        img.src = original + sep + '_r=' + Date.now();
    }

    function _onImgError(e) {
        const img = e.target;
        if (!img || img.tagName !== 'IMG') return;
        // 占位符自身加载失败 → 忽略
        if (img.src && img.src.startsWith('data:image/svg+xml')) return;
        _markFailed(img);
    }

    function _setup() {
        // 捕获阶段监听所有 img 的 error 事件
        document.addEventListener('error', _onImgError, true);
        // ★ 不再使用 setInterval 定时重试
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _setup);
    } else {
        _setup();
    }

    window.ImageFallback = {
        retryAll: function () {
            document.querySelectorAll('img[data-mef-fallback="1"]')
                .forEach(_retry);
        },
        failedCount: function () {
            return document.querySelectorAll('img[data-mef-fallback="1"]').length;
        },
    };
})();