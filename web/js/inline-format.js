// MarkEase 内联格式继承与边界控制（阶段 9）
// 职责：
//   1. 合并浏览器产生的相邻同类标签（<strong>a</strong><strong>b</strong> → <strong>ab</strong>）
//   2. 清理空标签（避免 ****）
//   3. Backspace / Delete 在格式标签边界处避免误删格式标记
//   4. 选区替换时保留内联格式标签（尤其 <a>），兼容 IME
(function (global) {
    'use strict';

    // 与 render.js 中 domToMarkdown 的白名单一致
    var FORMAT_TAGS = {
        'strong': 1, 'b': 1,
        'em': 1, 'i': 1,
        'del': 1, 's': 1,
        'code': 1,
        'a': 1
    };

    var FORMAT_SELECTOR = 'strong, b, em, i, del, s, code, a';

    // 上一次选区所覆盖的格式标签上下文（用于 IME 破坏后恢复）
    var _lastFormatContext = null;

    // ---------- 工具函数 ----------

    function getFormatAncestor(node, root) {
        var current = node;
        while (current && current !== root) {
            if (current.nodeType === 1) {
                var tag = current.tagName.toLowerCase();
                if (FORMAT_TAGS[tag]) return current;
            }
            current = current.parentNode;
        }
        return null;
    }

    function hasContentBefore(node, root) {
        var current = node;
        while (current && current !== root) {
            var sib = current.previousSibling;
            while (sib) {
                if (sib.nodeType === 3 && sib.nodeValue && sib.nodeValue.length) {
                    return true;
                }
                if (sib.nodeType === 1) {
                    var tag = sib.tagName.toLowerCase();
                    if (tag === 'br') return true;
                    if (tag === 'img') return true;
                    if (sib.textContent && sib.textContent.length) return true;
                }
                sib = sib.previousSibling;
            }
            current = current.parentNode;
        }
        return false;
    }

    function hasContentAfter(node, root) {
        var current = node;
        while (current && current !== root) {
            var sib = current.nextSibling;
            while (sib) {
                if (sib.nodeType === 3 && sib.nodeValue && sib.nodeValue.length) {
                    return true;
                }
                if (sib.nodeType === 1) {
                    var tag = sib.tagName.toLowerCase();
                    if (tag === 'br') return true;
                    if (tag === 'img') return true;
                    if (sib.textContent && sib.textContent.length) return true;
                }
                sib = sib.nextSibling;
            }
            current = current.parentNode;
        }
        return false;
    }

    function sameAttributes(a, b) {
        var attrsA = a.attributes, attrsB = b.attributes;
        if (attrsA.length !== attrsB.length) return false;
        for (var i = 0; i < attrsA.length; i++) {
            var name = attrsA[i].name;
            if (a.getAttribute(name) !== b.getAttribute(name)) return false;
        }
        return true;
    }

    // ---------- DOM 规范化 ----------

    function mergeAdjacentTags(root, selector) {
        var groups = root.querySelectorAll(selector);
        for (var i = groups.length - 1; i >= 0; i--) {
            var el = groups[i];
            if (!el.parentNode) continue;

            var prev = el.previousSibling;
            var empties = [];
            while (prev && prev.nodeType === 3 && prev.nodeValue.length === 0) {
                empties.push(prev);
                prev = prev.previousSibling;
            }

            if (prev && prev.nodeType === 1 &&
                prev.tagName.toLowerCase() === el.tagName.toLowerCase() &&
                sameAttributes(prev, el)) {
                for (var k = 0; k < empties.length; k++) {
                    empties[k].remove();
                }
                while (el.firstChild) {
                    prev.appendChild(el.firstChild);
                }
                el.remove();
            }
        }
    }

    function removeEmptyFormatTags(root) {
        var els = root.querySelectorAll(FORMAT_SELECTOR);
        for (var i = els.length - 1; i >= 0; i--) {
            var el = els[i];
            if (!el.parentNode) continue;
            var tag = el.tagName.toLowerCase();
            // <a> 保留（用户可能想保留空链接占位）
            if (tag === 'a') continue;
            var hasText = el.textContent && el.textContent.length > 0;
            var hasImg = !!el.querySelector('img');
            if (!hasText && !hasImg) {
                el.remove();
            }
        }
    }

    function normalizeInlineFormat(root) {
        if (!root) return;
        var maxIter = 6;
        for (var i = 0; i < maxIter; i++) {
            var beforeCount = root.querySelectorAll(FORMAT_SELECTOR).length;
            removeEmptyFormatTags(root);
            mergeAdjacentTags(root, 'strong');
            mergeAdjacentTags(root, 'b');
            mergeAdjacentTags(root, 'em');
            mergeAdjacentTags(root, 'i');
            mergeAdjacentTags(root, 'del');
            mergeAdjacentTags(root, 's');
            mergeAdjacentTags(root, 'code');
            var afterCount = root.querySelectorAll(FORMAT_SELECTOR).length;
            if (beforeCount === afterCount) break;
        }
    }

    // ---------- 字符级删除（保留标签结构） ----------

    function findFirstTextNode(el) {
        var first = null;
        (function walk(node) {
            if (first) return;
            if (node.nodeType === 3 && node.nodeValue.length > 0) {
                first = node;
                return;
            }
            for (var i = 0; i < node.childNodes.length; i++) {
                walk(node.childNodes[i]);
                if (first) return;
            }
        })(el);
        return first;
    }

    function findLastTextNode(el) {
        var last = null;
        (function walk(node) {
            if (node.nodeType === 3 && node.nodeValue.length > 0) {
                last = node;
            }
            for (var i = 0; i < node.childNodes.length; i++) {
                walk(node.childNodes[i]);
            }
        })(el);
        return last;
    }

    function placeCaret(node, offset) {
        try {
            var sel = window.getSelection();
            var range = document.createRange();
            range.setStart(node, offset);
            range.collapse(true);
            sel.removeAllRanges();
            sel.addRange(range);
        } catch (e) { /* ignore */ }
    }

    function deleteLastCharOf(el, targetRoot) {
        var lastNode = findLastTextNode(el);
        if (!lastNode) return;
        var len = lastNode.nodeValue.length;
        if (len > 0) {
            lastNode.nodeValue = lastNode.nodeValue.slice(0, -1);
        }
        if (targetRoot) normalizeInlineFormat(targetRoot);
        placeCaret(lastNode, lastNode.nodeValue.length);
        notifyInput(targetRoot || el);
    }

    function deleteFirstCharOf(el, targetRoot) {
        var firstNode = findFirstTextNode(el);
        if (!firstNode) return;
        var len = firstNode.nodeValue.length;
        if (len > 0) {
            firstNode.nodeValue = firstNode.nodeValue.slice(1);
        }
        if (targetRoot) normalizeInlineFormat(targetRoot);
        placeCaret(firstNode, 0);
        notifyInput(targetRoot || el);
    }

    function notifyInput(el) {
        try {
            var ev = new Event('input', { bubbles: true });
            el.dispatchEvent(ev);
        } catch (e) { /* ignore */ }
    }

    // ---------- Backspace / Delete 边界 ----------

    function handleBackspace(e, rootEl) {
        var sel = window.getSelection();
        if (!sel.rangeCount) return;
        var range = sel.getRangeAt(0);
        if (!range.collapsed) return;

        var node = range.startContainer;
        var offset = range.startOffset;

        if (node === rootEl) {
            if (offset === 0) {
                e.preventDefault();
                return;
            }
            var prevNode = rootEl.childNodes[offset - 1];
            while (prevNode && prevNode.nodeType === 3 && prevNode.nodeValue.length === 0) {
                prevNode = prevNode.previousSibling;
            }
            if (prevNode && prevNode.nodeType === 1) {
                var tagA = prevNode.tagName.toLowerCase();
                if (FORMAT_TAGS[tagA]) {
                    e.preventDefault();
                    deleteLastCharOf(prevNode, rootEl);
                }
            }
            return;
        }

        if (node.nodeType === 3) {
            var formatAncestor = getFormatAncestor(node, rootEl);
            if (formatAncestor && offset === 0) {
                if (!hasContentBefore(formatAncestor, rootEl)) {
                    e.preventDefault();
                    return;
                }
            }
        }
    }

    function handleDelete(e, rootEl) {
        var sel = window.getSelection();
        if (!sel.rangeCount) return;
        var range = sel.getRangeAt(0);
        if (!range.collapsed) return;

        var node = range.startContainer;
        var offset = range.startOffset;

        if (node === rootEl) {
            if (offset >= rootEl.childNodes.length) {
                e.preventDefault();
                return;
            }
            var nextNode = rootEl.childNodes[offset];
            while (nextNode && nextNode.nodeType === 3 && nextNode.nodeValue.length === 0) {
                nextNode = nextNode.nextSibling;
            }
            if (nextNode && nextNode.nodeType === 1) {
                var tagA = nextNode.tagName.toLowerCase();
                if (FORMAT_TAGS[tagA]) {
                    e.preventDefault();
                    deleteFirstCharOf(nextNode, rootEl);
                }
            }
            return;
        }

        if (node.nodeType === 3) {
            var len = node.nodeValue.length;
            var formatAncestor = getFormatAncestor(node, rootEl);
            if (formatAncestor && offset === len) {
                if (!hasContentAfter(formatAncestor, rootEl)) {
                    e.preventDefault();
                }
            }
        }
    }

    // ---------- 记录 / 恢复选区所在的格式标签 ----------

    // 若选区非折叠且完全覆盖某个内联格式标签的所有文本，则记录该标签上下文
    function recordFormatContext(rootEl) {
        var sel = window.getSelection();
        if (!sel.rangeCount) return;
        var range = sel.getRangeAt(0);
        if (range.collapsed) return;

        var startAncestor = getFormatAncestor(range.startContainer, rootEl);
        var endAncestor = getFormatAncestor(range.endContainer, rootEl);
        if (!startAncestor || startAncestor !== endAncestor) return;

        var tagText = startAncestor.textContent || '';
        var selText = range.toString();
        if (!tagText || selText !== tagText) return;

        var attrs = [];
        for (var i = 0; i < startAncestor.attributes.length; i++) {
            var a = startAncestor.attributes[i];
            attrs.push({ name: a.name, value: a.value });
        }

        _lastFormatContext = {
            tag: startAncestor.tagName.toLowerCase(),
            attrs: attrs,
            text: tagText,
            timestamp: Date.now()
        };
    }

    // 检查段落中是否已存在记录里同样属性的标签
    function sameFormatExists(rootEl, ctx) {
        var candidates = rootEl.querySelectorAll(ctx.tag);
        for (var i = 0; i < candidates.length; i++) {
            var same = true;
            for (var j = 0; j < ctx.attrs.length; j++) {
                if (candidates[i].getAttribute(ctx.attrs[j].name) !== ctx.attrs[j].value) {
                    same = false;
                    break;
                }
            }
            if (same) return true;
        }
        return false;
    }

    // 用 newText 重新包裹被破坏的格式标签
    function tryRestoreFormat(rootEl, newText) {
        if (!_lastFormatContext) return false;
        var ctx = _lastFormatContext;

        // 上下文过旧则忽略
        if (Date.now() - ctx.timestamp > 8000) {
            _lastFormatContext = null;
            return false;
        }

        // 段落里仍有该标签 → 无需恢复
        if (sameFormatExists(rootEl, ctx)) {
            _lastFormatContext = null;
            return false;
        }

        _lastFormatContext = null;

        if (!newText) return false;

        // 在段落中查找新插入的文本位置
        var walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null);
        var textNode;
        while ((textNode = walker.nextNode())) {
            var idx = textNode.nodeValue.indexOf(newText);
            if (idx < 0) continue;

            // 若该文本已在某个格式标签内，不再处理
            var insideFormat = getFormatAncestor(textNode, rootEl);
            if (insideFormat) continue;

            var before = textNode.nodeValue.slice(0, idx);
            var after = textNode.nodeValue.slice(idx + newText.length);
            var parent = textNode.parentNode;

            var newTag = document.createElement(ctx.tag);
            for (var k = 0; k < ctx.attrs.length; k++) {
                newTag.setAttribute(ctx.attrs[k].name, ctx.attrs[k].value);
            }
            newTag.textContent = newText;

            if (before) {
                parent.insertBefore(document.createTextNode(before), textNode);
            }
            parent.insertBefore(newTag, textNode);
            if (after) {
                parent.insertBefore(document.createTextNode(after), textNode);
            }
            parent.removeChild(textNode);

            normalizeInlineFormat(rootEl);
            notifyInput(rootEl);
            return true;
        }
        return false;
    }

    // ---------- 主入口 ----------

    function setupInlineFormat(previewEl, options) {
        options = options || {};
        var isComposing = options.isComposing || function () { return false; };

        // 1. beforeinput：记录上下文；非 IME 的 insertText 手动替换选区（保留标签）
        previewEl.addEventListener('beforeinput', function (e) {
            var target = e.target;
            var rootEl = target && target.closest &&
                         target.closest('[data-md-editable="1"]');
            if (!rootEl) return;

            // 记录即将被删除的格式标签上下文（为 IME 破坏恢复做准备）
            recordFormatContext(rootEl);

            // 非 IME 的普通文本插入：手动替换以保留标签
            if (!isComposing() && !e.isComposing &&
                e.inputType === 'insertText' && e.data != null) {
                var sel = window.getSelection();
                if (sel.rangeCount) {
                    var range = sel.getRangeAt(0);
                    if (!range.collapsed) {
                        var sa = getFormatAncestor(range.startContainer, rootEl);
                        var ea = getFormatAncestor(range.endContainer, rootEl);
                        if (sa && sa === ea) {
                            e.preventDefault();
                            range.deleteContents();
                            var textNode = document.createTextNode(e.data);
                            range.insertNode(textNode);

                            var newRange = document.createRange();
                            newRange.setStart(textNode, textNode.nodeValue.length);
                            newRange.collapse(true);
                            sel.removeAllRanges();
                            sel.addRange(newRange);

                            normalizeInlineFormat(rootEl);
                            notifyInput(rootEl);
                            _lastFormatContext = null;
                        }
                    }
                }
            }
        }, true);

        // 2. input 后：规范化 DOM（跳过 IME）
        previewEl.addEventListener('input', function (e) {
            var target = e.target;
            var rootEl = target && target.closest &&
                         target.closest('[data-md-editable="1"]');
            if (!rootEl) return;
            if (isComposing() || e.isComposing) return;
            normalizeInlineFormat(rootEl);
        });

        // 3. compositionend 后：检查并尝试恢复被 IME 破坏的格式标签
        previewEl.addEventListener('compositionend', function (e) {
            var target = e.target;
            var rootEl = target && target.closest &&
                         target.closest('[data-md-editable="1"]');
            if (!rootEl) return;
            var finalText = e.data || '';
            setTimeout(function () {
                normalizeInlineFormat(rootEl);
                if (_lastFormatContext && finalText) {
                    tryRestoreFormat(rootEl, finalText);
                }
            }, 0);
        });

        // 4. Backspace / Delete 边界（沿用阶段 9 逻辑）
        previewEl.addEventListener('keydown', function (e) {
            if (isComposing() || e.isComposing) return;
            var target = e.target;
            var rootEl = target && target.closest &&
                         target.closest('[data-md-editable="1"]');
            if (!rootEl) return;
            if (e.key === 'Backspace') {
                handleBackspace(e, rootEl);
            } else if (e.key === 'Delete') {
                handleDelete(e, rootEl);
            }
        }, true);

        // 5. blur 时清理上下文，避免跨会话误触发
        previewEl.addEventListener('blur', function (e) {
            var target = e.target;
            if (target && target.matches &&
                target.matches('[data-md-editable="1"]')) {
                _lastFormatContext = null;
            }
        }, true);
    }

    global.setupInlineFormat = setupInlineFormat;
    global.normalizeInlineFormat = normalizeInlineFormat;
})(window);