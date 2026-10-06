// MarkEase 安全过滤：把 marked 输出进行白名单清洗
// 阶段 15 修订：span 白名单加 data-md-task-* 属性（任务列表用）
// 阶段 15 修订 5：KaTeX 子树内放行 style 属性（值需通过安全清洗），
//                修复块级公式（aligned/矩阵/分数等）文字重叠
// 阶段 16 第 4 批：修复 style fall through bug
// 阶段 16-10：新增脚注相关标签/属性白名单
//   - section（脚注区容器）
//   - sup / li / a 上放行 data-footnote-* 属性
//   - GLOBAL_ATTRS 补 role / aria-label（ARIA 无障碍）
// 阶段 16-13：★ 新增 <ins> 标签（GitHub 风格下划线）
(function (global) {
    'use strict';

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    var ALLOWED_TAGS = {
        'a': 1, 'p': 1, 'br': 1, 'hr': 1,
        'strong': 1, 'b': 1, 'em': 1, 'i': 1,
        'u': 1,
        // ★ 阶段 16-13：GitHub 风格下划线
        'ins': 1,
        'del': 1, 's': 1, 'mark': 1,
        'code': 1, 'pre': 1, 'kbd': 1, 'samp': 1, 'var': 1,
        'blockquote': 1,
        'ul': 1, 'ol': 1, 'li': 1,
        'table': 1, 'thead': 1, 'tbody': 1, 'tfoot': 1,
        'tr': 1, 'th': 1, 'td': 1, 'caption': 1,
        'h1': 1, 'h2': 1, 'h3': 1, 'h4': 1, 'h5': 1, 'h6': 1,
        'img': 1, 'span': 1, 'div': 1, 'input': 1,
        'sup': 1, 'sub': 1, 'abbr': 1,
        'details': 1, 'summary': 1,
        'figure': 1, 'figcaption': 1,
        'dl': 1, 'dt': 1, 'dd': 1,
        'section': 1,
        'math': 1, 'semantics': 1, 'annotation': 1,
        'mrow': 1, 'mi': 1, 'mo': 1, 'mn': 1, 'mtext': 1, 'mspace': 1,
        'msup': 1, 'msub': 1, 'msubsup': 1,
        'mfrac': 1, 'msqrt': 1, 'mroot': 1,
        'mtable': 1, 'mtr': 1, 'mtd': 1,
        'mover': 1, 'munder': 1, 'munderover': 1,
        'mstyle': 1, 'menclose': 1, 'mpadded': 1, 'mphantom': 1,
        'mmultiscripts': 1, 'mprescripts': 1, 'none': 1
    };

    var DANGEROUS_TAGS = {
        'script': 1, 'style': 1, 'iframe': 1, 'object': 1,
        'embed': 1, 'applet': 1, 'frame': 1, 'frameset': 1,
        'noscript': 1, 'template': 1,
        'base': 1, 'meta': 1, 'link': 1, 'title': 1, 'head': 1,
        'form': 1, 'button': 1, 'select': 1, 'textarea': 1,
        'option': 1, 'optgroup': 1, 'fieldset': 1, 'legend': 1,
        'svg': 1,
        'audio': 1, 'video': 1, 'source': 1, 'track': 1,
        'canvas': 1, 'map': 1, 'area': 1
    };

    var GLOBAL_ATTRS = {
        'class': 1, 'id': 1, 'title': 1, 'aria-hidden': 1,
        'role': 1, 'aria-label': 1,
    };

    var TAG_ATTRS = {
        'a':     {
            'href': 1, 'title': 1, 'target': 1, 'rel': 1,
            'data-footnote-backref': 1,
            'role': 1, 'aria-label': 1,
        },
        'img':   { 'src': 1, 'alt': 1, 'title': 1, 'width': 1, 'height': 1 },
        'input': { 'type': 1, 'checked': 1, 'disabled': 1 },
        'td':    { 'align': 1, 'colspan': 1, 'rowspan': 1 },
        'th':    { 'align': 1, 'colspan': 1, 'rowspan': 1 },
        'ol':    { 'start': 1, 'type': 1 },
        'code':  { 'class': 1 },
        'pre':   { 'class': 1 },
        'div':   { 'class': 1, 'data-tex': 1, 'data-line': 1 },
        'span':  {
            'class': 1,
            'data-line': 1,
            'data-md-task-index': 1,
            'data-md-task-checked': 1,
            'data-md-task-bullet': 1,
            'role': 1,
            'aria-checked': 1,
            'contenteditable': 1
        },
        'sup':   {
            'class': 1,
            'id': 1,
            'data-footnote-ref': 1,
            'data-footnote-index': 1,
            'role': 1,
            'aria-label': 1,
        },
        'li':    {
            'class': 1,
            'id': 1,
            'data-footnote-item': 1,
            'data-footnote-index': 1,
        },
        'section': {
            'class': 1,
            'id': 1,
            'data-footnotes': 1,
            'role': 1,
            'aria-label': 1,
        },
        'h1':    { 'data-line': 1 }, 'h2': { 'data-line': 1 },
        'h3':    { 'data-line': 1 }, 'h4': { 'data-line': 1 },
        'h5':    { 'data-line': 1 }, 'h6': { 'data-line': 1 }
    };

    var MATHML_TAGS = {
        'math': 1, 'semantics': 1, 'annotation': 1,
        'mrow': 1, 'mi': 1, 'mo': 1, 'mn': 1, 'mtext': 1, 'mspace': 1,
        'msup': 1, 'msub': 1, 'msubsup': 1,
        'mfrac': 1, 'msqrt': 1, 'mroot': 1,
        'mtable': 1, 'mtr': 1, 'mtd': 1,
        'mover': 1, 'munder': 1, 'munderover': 1,
        'mstyle': 1, 'menclose': 1, 'mpadded': 1, 'mphantom': 1,
        'mmultiscripts': 1, 'mprescripts': 1, 'none': 1
    };

    var MATHML_ATTRS = {
        'xmlns': 1, 'encoding': 1, 'display': 1, 'mathvariant': 1,
        'stretchy': 1, 'fence': 1, 'separator': 1,
        'lspace': 1, 'rspace': 1, 'scriptlevel': 1,
        'linethickness': 1, 'columnalign': 1, 'rowalign': 1,
        'columnspacing': 1, 'rowspacing': 1, 'notation': 1,
        'width': 1, 'height': 1, 'depth': 1, 'voffset': 1,
        'minsize': 1, 'maxsize': 1, 'movablelimits': 1, 'accent': 1,
        'accentunder': 1, 'form': 1, 'largeop': 1, 'symmetric': 1,
        'numalign': 1, 'denomalign': 1, 'bevelled': 1,
        'open': 1, 'close': 1, 'separators': 1,
        'actiontype': 1, 'selection': 1
    };

    var SAFE_PROTOCOLS = ['http:', 'https:', 'mailto:', 'tel:', 'file:', 'ftp:', 'ftps:'];

    function isSafeUrl(url) {
        if (!url) return true;
        var cleaned = String(url).replace(/[\u0000-\u001F\u007F\s]/g, '').toLowerCase();
        if (cleaned.indexOf(':') === -1) return true;
        if (/^[a-z]:[\/\\]/.test(cleaned)) return true;
        for (var i = 0; i < SAFE_PROTOCOLS.length; i++) {
            if (cleaned.indexOf(SAFE_PROTOCOLS[i]) === 0) return true;
        }
        return false;
    }

    function isStyleSafe(value) {
        if (!value) return false;
        var s = String(value).toLowerCase();
        if (s.indexOf('expression') !== -1) return false;
        if (s.indexOf('javascript:') !== -1) return false;
        if (s.indexOf('vbscript:') !== -1) return false;
        if (s.indexOf('behavior') !== -1) return false;
        if (s.indexOf('-moz-binding') !== -1) return false;
        if (s.indexOf('@import') !== -1) return false;
        if (s.indexOf('url(') !== -1) return false;
        return true;
    }

    function isInKatexSubtree(node, root) {
        var cur = node;
        while (cur && cur !== root) {
            if (cur.nodeType === 1) {
                var cls = '';
                if (typeof cur.className === 'string') {
                    cls = cur.className;
                } else if (cur.getAttribute) {
                    cls = cur.getAttribute('class') || '';
                }
                if (cls && cls.indexOf('katex') !== -1) return true;
            }
            cur = cur.parentNode;
        }
        return false;
    }

    function sanitizeHtml(html) {
        if (!html) return '';
        if (typeof DOMParser === 'undefined') return escapeHtml(html);

        var doc;
        try {
            doc = new DOMParser().parseFromString(
                '<div id="__sanitize_root__">' + html + '</div>',
                'text/html'
            );
        } catch (e) {
            return escapeHtml(html);
        }

        var root = doc.getElementById('__sanitize_root__');
        if (!root) return escapeHtml(html);

        function cleanNode(node) {
            if (!node) return;
            if (node.nodeType === 3) return;
            if (node.nodeType !== 1) {
                if (node.parentNode) node.parentNode.removeChild(node);
                return;
            }

            var tagName = node.tagName ? node.tagName.toLowerCase() : '';

            if (DANGEROUS_TAGS[tagName]) {
                if (node.parentNode) node.parentNode.removeChild(node);
                return;
            }

            if (!ALLOWED_TAGS[tagName]) {
                var children = [];
                for (var c = 0; c < node.childNodes.length; c++) {
                    children.push(node.childNodes[c]);
                }
                for (var ci = 0; ci < children.length; ci++) {
                    cleanNode(children[ci]);
                }
                if (node.parentNode) {
                    while (node.firstChild) {
                        node.parentNode.insertBefore(node.firstChild, node);
                    }
                    node.parentNode.removeChild(node);
                }
                return;
            }

            var katexNode = isInKatexSubtree(node, root);

            var attrs = node.attributes;
            var toRemove = [];
            for (var i = 0; i < attrs.length; i++) {
                var attr = attrs[i];
                var attrName = attr.name.toLowerCase();
                var attrValue = attr.value;

                if (attrName.indexOf('on') === 0) {
                    toRemove.push(attr.name); continue;
                }

                if (attrName === 'style') {
                    if (!katexNode || !isStyleSafe(attrValue)) {
                        toRemove.push(attr.name);
                    }
                    continue;
                }

                if (attrName.indexOf('xlink:') === 0 ||
                    attrName.indexOf('xml:') === 0) {
                    toRemove.push(attr.name); continue;
                }

                var allowed = GLOBAL_ATTRS[attrName] ||
                              (TAG_ATTRS[tagName] && TAG_ATTRS[tagName][attrName]) ||
                              (MATHML_TAGS[tagName] && MATHML_ATTRS[attrName]);
                if (!allowed) {
                    toRemove.push(attr.name); continue;
                }
                if (attrName === 'href' || attrName === 'src') {
                    if (!isSafeUrl(attrValue)) {
                        toRemove.push(attr.name); continue;
                    }
                }
                if (tagName === 'input' && attrName === 'type') {
                    if (String(attrValue).toLowerCase() !== 'checkbox') {
                        toRemove.push(attr.name); continue;
                    }
                }
            }
            for (var k = 0; k < toRemove.length; k++) {
                node.removeAttribute(toRemove[k]);
            }

            if (tagName === 'input') {
                var t = (node.getAttribute('type') || '').toLowerCase();
                if (t !== 'checkbox') {
                    if (node.parentNode) node.parentNode.removeChild(node);
                    return;
                }
            }

            if (tagName === 'a' && node.hasAttribute('href')) {
                node.setAttribute('rel', 'noopener noreferrer');
            }

            var kids = [];
            for (var m = 0; m < node.childNodes.length; m++) {
                kids.push(node.childNodes[m]);
            }
            for (var mi = 0; mi < kids.length; mi++) {
                cleanNode(kids[mi]);
            }
        }

        var rootKids = [];
        for (var rk = 0; rk < root.childNodes.length; rk++) {
            rootKids.push(root.childNodes[rk]);
        }
        for (var rki = 0; rki < rootKids.length; rki++) {
            cleanNode(rootKids[rki]);
        }

        return root.innerHTML;
    }

    global.escapeHtml = escapeHtml;
    global.sanitizeHtml = sanitizeHtml;
    global.isSafeUrl = isSafeUrl;
})(window);