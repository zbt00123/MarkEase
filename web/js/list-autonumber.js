// ============================================================
//  MarkEase 有序列表自动编号（v2.1.7）
//  - 手动修改某一项编号：保留该项编号，后续同级项依次 +1
//  - 删除整行列表项：后续同级项从上一项 +1 续号；删除首项则从 1 重排
//  - 只影响当前列表段落、当前层级；全 1. 列表默认按手动处理
//  - 自动重排后显示 ⚡，可切换“保持自动 / 转为手动”
// ============================================================
import { EditorState, StateField, StateEffect } from './vendor/state.mjs';
import { ViewPlugin } from './vendor/view.mjs';

const addPrompt = StateEffect.define();
const removePrompt = StateEffect.define();
const addManual = StateEffect.define();
const removeManual = StateEffect.define();

const ITEM_RE = /^([ \t]*)((?:>[ \t]*)*)(\d{1,9})([.)])[ \t]+/;

function rangeOverlaps(a, b) {
    return a.from < b.to && b.from < a.to;
}

function mapRange(range, changes) {
    const from = changes.mapPos(range.from, -1);
    const to = changes.mapPos(range.to, 1);
    if (to <= from) return null;
    return { from: from, to: to };
}

function mapPrompt(prompt, changes) {
    const range = mapRange(prompt, changes);
    if (!range) return null;
    const targets = [];
    for (const t of prompt.targets || []) {
        const from = changes.mapPos(t.from, -1);
        const to = changes.mapPos(t.to, 1);
        if (to > from) {
            targets.push({
                from: from,
                to: to,
                oldText: t.oldText,
                newText: t.newText
            });
        }
    }
    return {
        from: range.from,
        to: range.to,
        manual: !!prompt.manual,
        targets: targets
    };
}

export const listAutoField = StateField.define({
    create() {
        return { prompts: [], manual: [] };
    },
    update(value, tr) {
        let prompts = [];
        for (const p of value.prompts) {
            const mapped = mapPrompt(p, tr.changes);
            if (mapped) prompts.push(mapped);
        }
        // 撤销 / 重做后，旧的自动重排提示已不可靠，直接清掉
        if (tr.isUserEvent('undo') || tr.isUserEvent('redo')) {
            prompts = [];
        }
        let manual = [];
        for (const r of value.manual) {
            const mapped = mapRange(r, tr.changes);
            if (mapped) manual.push(mapped);
        }

        // 整篇文档被替换（打开文件 / 新建 / 全选粘贴）时，
        // 上一份文档的手动编号状态不应带到新文档里。
        if (isFullDocumentReplace(tr)) {
            prompts = [];
            manual = [];
        }

        for (const effect of tr.effects) {
            if (effect.is(addPrompt)) {
                const p = effect.value;
                prompts = prompts.filter(function (x) {
                    return !rangeOverlaps(x, p);
                });
                prompts.push(p);
            } else if (effect.is(removePrompt)) {
                const r = effect.value;
                prompts = prompts.filter(function (x) {
                    return !rangeOverlaps(x, r);
                });
            } else if (effect.is(addManual)) {
                const r = effect.value;
                manual = manual.filter(function (x) {
                    return !rangeOverlaps(x, r);
                });
                manual.push(r);
            } else if (effect.is(removeManual)) {
                const r = effect.value;
                manual = manual.filter(function (x) {
                    return !rangeOverlaps(x, r);
                });
            }
        }

        return { prompts: prompts, manual: manual };
    }
});

function isUserEdit(tr) {
    if (tr.isUserEvent('input.paste') || tr.isUserEvent('input.drop')) {
        return false;
    }
    return tr.isUserEvent('input') || tr.isUserEvent('delete');
}

// 普通正文里敲字不需要解析整篇列表，先做一个低成本过滤。
function mayAffectList(tr) {
    const doc = tr.startState.doc;
    let hit = false;
    tr.changes.iterChanges(function (fromA, toA, fromB, toB, inserted) {
        if (hit) return;
        if (inserted.toString().indexOf('\n') >= 0) {
            hit = true;
            return;
        }
        if (toA > fromA &&
            doc.sliceString(fromA, toA).indexOf('\n') >= 0) {
            hit = true;
            return;
        }
        const line = doc.lineAt(Math.min(fromA, doc.length));
        if (ITEM_RE.test(line.text)) hit = true;
    });
    return hit;
}

function touchesManual(tr, manualRanges) {
    if (!manualRanges.length) return false;
    let hit = false;
    tr.changes.iterChangedRanges(function (fromA, toA) {
        if (hit) return;
        for (const r of manualRanges) {
            if (fromA < r.to && (toA > r.from ||
                (fromA === toA && fromA >= r.from && fromA <= r.to))) {
                hit = true;
                return;
            }
        }
    });
    return hit;
}

function isFullDocumentReplace(tr) {
    const oldLen = tr.startState.doc.length;
    let count = 0;
    let full = false;
    tr.changes.iterChanges(function (fromA, toA) {
        count++;
        full = (count === 1 && fromA === 0 && toA === oldLen);
    });
    return count === 1 && full;
}

// ---------------- 行级解析 ----------------

function indentCols(text) {
    let cols = 0;
    for (let i = 0; i < text.length; i++) {
        const ch = text.charAt(i);
        if (ch === ' ') cols++;
        else if (ch === '\t') cols += 4 - (cols % 4);
        else break;
    }
    return cols;
}

function lineInfo(text) {
    let rest = text;
    let quote = '';
    // 去掉 blockquote 前缀，记录引用层级
    const qm = /^((?:[ \t]*>[ \t]?)+)/.exec(text);
    if (qm) {
        quote = qm[1].replace(/[ \t]+/g, ' ').trim();
        rest = text.slice(qm[1].length);
    }
    return { quote: quote, indent: indentCols(rest), rest: rest };
}

function parseItems(doc) {
    const items = [];
    let inFence = false;
    let fenceChar = '';
    let fenceLen = 0;
    let prevLine = '';

    for (let ln = 1; ln <= doc.lines; ln++) {
        const line = doc.line(ln);
        const text = line.text;
        const fence = /^[ \t]{0,3}(`{3,}|~{3,})/.exec(text);

        if (inFence) {
            if (fence && fence[1][0] === fenceChar &&
                fence[1].length >= fenceLen) {
                inFence = false;
            }
            prevLine = text;
            continue;
        }
        if (fence) {
            inFence = true;
            fenceChar = fence[1][0];
            fenceLen = fence[1].length;
            prevLine = text;
            continue;
        }

        const m = ITEM_RE.exec(text);
        if (!m) {
            prevLine = text;
            continue;
        }

        const indent = m[1] || '';
        const quote = m[2] || '';
        if (!quote && indent.length >= 4) {
            const prevIsList = /^[ \t]*[-*+][ \t]|^[ \t]*\d+[.)][ \t]/.test(prevLine);
            if (!prevIsList) {
                prevLine = text;
                continue;
            }
        }

        const markerFrom = line.from + indent.length + quote.length;
        const markerTo = markerFrom + m[3].length;

        items.push({
            lineNo: ln,
            from: line.from,
            to: line.to,
            number: parseInt(m[3], 10),
            markerFrom: markerFrom,
            markerTo: markerTo,
            delim: m[4],
            quote: quote,
            indentCols: indentCols(indent),
            key: quote + '|' + indentCols(indent) + '|' + m[4]
        });
        prevLine = text;
    }

    return items;
}

function sameKey(a, b) {
    return a.key === b.key;
}

function itemsByLine(items) {
    const map = new Map();
    for (const it of items) map.set(it.lineNo, it);
    return map;
}

function forwardSiblings(doc, items, anchor) {
    const byLine = itemsByLine(items);
    const out = [anchor];
    let ln = anchor.lineNo + 1;
    while (ln <= doc.lines) {
        const line = doc.line(ln);
        const text = line.text;
        // 空行视为分组边界：两组列表互不影响
        if (!text.trim()) break;
        const it = byLine.get(ln);
        if (it) {
            if (sameKey(it, anchor)) {
                out.push(it);
                ln++;
                continue;
            }
            if (it.indentCols > anchor.indentCols &&
                it.quote === anchor.quote) {
                ln++;
                continue;
            }
            break;
        }
        const info = lineInfo(text);
        if (info.quote !== anchor.quote) break;
        if (info.indent > anchor.indentCols) {
            ln++;
            continue;
        }
        break;
    }
    return out;
}

function backwardFirst(doc, items, anchor) {
    const byLine = itemsByLine(items);
    let first = anchor;
    let ln = anchor.lineNo - 1;
    while (ln >= 1) {
        const text = doc.line(ln).text;
        // 空行视为分组边界
        if (!text.trim()) break;
        const it = byLine.get(ln);
        if (it) {
            if (sameKey(it, anchor)) {
                first = it;
                ln--;
                continue;
            }
            if (it.indentCols > anchor.indentCols &&
                it.quote === anchor.quote) {
                ln--;
                continue;
            }
            break;
        }
        const info = lineInfo(text);
        if (info.quote !== anchor.quote) break;
        if (info.indent > anchor.indentCols) {
            ln--;
            continue;
        }
        break;
    }
    return first;
}

function isSequential(items) {
    if (items.length <= 1) return true;
    const sorted = items.slice().sort(function (a, b) {
        return a.lineNo - b.lineNo;
    });
    for (let i = 1; i < sorted.length; i++) {
        if (sorted[i].number !== sorted[i - 1].number + 1) return false;
    }
    return true;
}

// 判断 fromPos 到 anchor 之间是否已经隔了段落/标题等列表边界，
// 避免删掉本列表最后一项后误把下一组有序列表当成同组。
function hasListBoundary(doc, fromPos, anchor, items) {
    const byLine = itemsByLine(items);
    const startLine = doc.lineAt(Math.min(fromPos, doc.length)).number;
    for (let ln = startLine; ln < anchor.lineNo; ln++) {
        const text = doc.line(ln).text;
        // 空行已把列表分组，视为边界
        if (!text.trim()) return true;
        const it = byLine.get(ln);
        if (it) {
            if (it.indentCols > anchor.indentCols) continue;
            if (sameKey(it, anchor)) continue;
            return true;
        }
        const info = lineInfo(text);
        if (info.quote !== anchor.quote) return true;
        if (info.indent > anchor.indentCols) continue;
        return true;
    }
    return false;
}

function renumberChanges(doc, siblings, startNumber) {
    const changes = [];
    let n = startNumber;
    for (let i = 0; i < siblings.length; i++) {
        const it = siblings[i];
        if (i === 0) n = startNumber;
        if (it.number !== n) {
            changes.push({
                from: it.markerFrom,
                to: it.markerTo,
                insert: String(n)
            });
        }
        n++;
    }
    return changes;
}

function mapPosThroughChanges(pos, changes) {
    let delta = 0;
    for (const c of changes) {
        if (c.to <= pos) {
            delta += c.insert.length - (c.to - c.from);
        }
    }
    return pos + delta;
}

function buildResult(tr, changes, listFirst, listLast) {
    const sorted = changes.slice().sort(function (a, b) {
        return a.from - b.from;
    });
    let delta = 0;
    const targets = [];
    const out = [];

    for (const c of sorted) {
        const finalFrom = c.from + delta;
        const finalTo = finalFrom + c.insert.length;
        targets.push({
            from: finalFrom,
            to: finalTo,
            oldText: tr.newDoc.sliceString(c.from, c.to),
            newText: c.insert
        });
        out.push({ from: c.from, to: c.to, insert: c.insert });
        delta += c.insert.length - (c.to - c.from);
    }

    const from = mapPosThroughChanges(listFirst.from, sorted);
    const to = mapPosThroughChanges(listLast.to, sorted);
    if (to <= from) return null;

    return {
        changes: out,
        prompt: {
            from: from,
            to: to,
            manual: false,
            targets: targets
        }
    };
}

function computeAutoChanges(tr) {
    const oldDoc = tr.startState.doc;
    const newDoc = tr.newDoc;
    const oldItems = parseItems(oldDoc);
    const newItems = parseItems(newDoc);
    const edits = [];

    tr.changes.iterChanges(function (fromA, toA, fromB, toB, inserted) {
        edits.push({
            fromA: fromA,
            toA: toA,
            fromB: fromB,
            toB: toB,
            text: inserted.toString()
        });
    });

    // 1) 手动修改编号
    for (const e of edits) {
        if (e.text.indexOf('\n') >= 0) continue;
        const oldText = oldDoc.sliceString(e.fromA, e.toA);
        // 删除整行（包含换行）属于“删项”，交给下面的逻辑处理
        if (oldText.indexOf('\n') >= 0) continue;
        const oldItem = oldItems.find(function (it) {
            return it.lineNo === oldDoc.lineAt(e.fromA).number &&
                e.fromA <= it.markerTo && e.toA >= it.markerFrom;
        });
        if (!oldItem) continue;

        const newLineNo = newDoc.lineAt(
            tr.changes.mapPos(oldItem.from, -1)).number;
        const anchor = newItems.find(function (it) {
            return it.lineNo === newLineNo;
        });
        if (!anchor) continue;

        const first = backwardFirst(newDoc, newItems, anchor);
        const all = forwardSiblings(newDoc, newItems, first);
        const idx = all.findIndex(function (it) {
            return it.lineNo === anchor.lineNo;
        });
        if (idx < 0) continue;

        const siblings = all.slice(idx);
        const changes = renumberChanges(newDoc, siblings, anchor.number);
        if (!changes.length) continue;

        const last = all[all.length - 1];
        const result = buildResult(tr, changes, first, last);
        if (result) return result;
    }

    // 2) 删除完整列表项行
    for (const e of edits) {
        if (!(e.toA > e.fromA)) continue;

        const startLine = oldDoc.lineAt(e.fromA).number;
        const endLine = oldDoc.lineAt(
            Math.min(e.toA - 1, oldDoc.length)).number;
        const deleted = [];

        for (let ln = startLine; ln <= endLine; ln++) {
            const line = oldDoc.line(ln);
            const needTo = (ln < oldDoc.lines) ? line.to + 1 : line.to;
            if (e.fromA <= line.from && e.toA >= needTo) {
                const it = oldItems.find(function (x) {
                    return x.lineNo === ln;
                });
                if (it) deleted.push(it);
            }
        }
        if (!deleted.length) continue;

        const firstDeleted = deleted[0];
        const oldFirst = backwardFirst(oldDoc, oldItems, firstDeleted);
        const oldSiblings = forwardSiblings(oldDoc, oldItems, oldFirst);
        if (!isSequential(oldSiblings)) continue;

        const anchor = newItems.find(function (it) {
            return sameKey(it, firstDeleted) && it.from >= e.fromB;
        });
        if (!anchor) continue;
        if (hasListBoundary(newDoc, e.fromB, anchor, newItems)) continue;

        const first = backwardFirst(newDoc, newItems, anchor);
        const all = forwardSiblings(newDoc, newItems, first);
        const idx = all.findIndex(function (it) {
            return it.lineNo === anchor.lineNo;
        });
        if (idx < 0) continue;

        const siblings = all.slice(idx);
        const prev = idx > 0 ? all[idx - 1] : null;
        const startNumber = prev ? prev.number + 1 : 1;
        const changes = renumberChanges(newDoc, siblings, startNumber);
        if (!changes.length) continue;

        const last = all[all.length - 1];
        const result = buildResult(tr, changes, first, last);
        if (result) return result;
    }

    // 3) 删除列表项之间的空行：两项重新连起来后补齐序号
    //    例：1. 任务1 / 空行 / 3. 任务3 -> 删除空行 -> 1,2
    for (const e of edits) {
        if (!(e.toA > e.fromA)) continue;
        const removed = oldDoc.sliceString(e.fromA, e.toA);
        if (!/^[ \t\r\n]*$/.test(removed)) continue;
        if (removed.indexOf('\n') < 0) continue;

        let prev = null;
        let next = null;
        for (const it of newItems) {
            if (it.to <= e.fromB) {
                prev = it;
            } else if (it.from >= e.fromB) {
                next = it;
                break;
            }
        }
        if (!prev || !next) continue;
        if (prev.lineNo + 1 !== next.lineNo) continue;
        if (!sameKey(prev, next)) continue;
        // 只补“序号缺口”；下一组从 1 开始时属于另一组，不能动
        if (!(next.number > prev.number + 1)) continue;

        const first = backwardFirst(newDoc, newItems, prev);
        const all = forwardSiblings(newDoc, newItems, first);
        const idx = all.findIndex(function (it) {
            return it.lineNo === next.lineNo;
        });
        if (idx < 0) continue;

        const siblings = all.slice(idx);
        const changes = renumberChanges(newDoc, siblings, prev.number + 1);
        if (!changes.length) continue;

        const last = all[all.length - 1];
        const result = buildResult(tr, changes, first, last);
        if (result) return result;
    }

    return null;
}

// ---------------- 菜单与动作 ----------------

let menuEl = null;
let menuCleanup = null;

function closeMenu() {
    if (menuEl && menuEl.parentNode) menuEl.parentNode.removeChild(menuEl);
    menuEl = null;
    if (menuCleanup) {
        menuCleanup();
        menuCleanup = null;
    }
}

function applyManual(view, info) {
    const changes = [];
    const prompt = info.prompt;
    if (prompt) {
        for (const t of prompt.targets || []) {
            if (t.from < 0 || t.to > view.state.doc.length) continue;
            if (view.state.sliceDoc(t.from, t.to) !== t.newText) continue;
            changes.push({ from: t.from, to: t.to, insert: t.oldText });
        }
    }
    changes.sort(function (a, b) { return a.from - b.from; });

    const from = mapPosThroughChanges(info.range.from, changes);
    const to = mapPosThroughChanges(info.range.to, changes);

    view.dispatch({
        changes: changes,
        effects: [
            removePrompt.of({ from: info.range.from, to: info.range.to }),
            addManual.of({ from: from, to: to })
        ]
    });
}

function applyKeepAuto(view, info) {
    view.dispatch({
        effects: [
            removePrompt.of({ from: info.range.from, to: info.range.to }),
            removeManual.of({ from: info.range.from, to: info.range.to })
        ]
    });
}

function applyRestoreAuto(view, info) {
    const doc = view.state.doc;
    const items = parseItems(doc);
    const first = items.find(function (it) {
        return it.lineNo === doc.lineAt(info.range.from).number;
    }) || items.find(function (it) {
        return it.from >= info.range.from;
    });

    if (!first) {
        view.dispatch({ effects: [
            removePrompt.of({ from: info.range.from, to: info.range.to }),
            removeManual.of({ from: info.range.from, to: info.range.to })
        ] });
        return;
    }

    const siblings = forwardSiblings(doc, items, first);
    const changes = renumberChanges(doc, siblings, first.number);
    const from = mapPosThroughChanges(info.range.from, changes);
    const to = mapPosThroughChanges(info.range.to, changes);
    view.dispatch({
        changes: changes,
        effects: [
            removePrompt.of({ from: from, to: to }),
            removeManual.of({ from: from, to: to })
        ]
    });
}

function menuButton(text, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'list-auto-menu-item';
    btn.textContent = text;
    btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        closeMenu();
        onClick();
    });
    return btn;
}

function openMenu(view, info, anchorEl) {
    closeMenu();

    const menu = document.createElement('div');
    menu.className = 'list-auto-menu';
    menu.setAttribute('role', 'menu');

    const title = document.createElement('div');
    title.className = 'list-auto-menu-title';
    title.textContent = '有序列表编号';
    menu.appendChild(title);

    if (info.manual) {
        menu.appendChild(menuButton('恢复自动编号', function () {
            applyRestoreAuto(view, info);
        }));
        menu.appendChild(menuButton('保持手动编号', function () {}));
    } else {
        menu.appendChild(menuButton('保持当前自动编号', function () {
            applyKeepAuto(view, info);
        }));
        menu.appendChild(menuButton('不自动编号（保持手动编号）', function () {
            applyManual(view, info);
        }));
    }

    document.body.appendChild(menu);
    menuEl = menu;

    const rect = anchorEl.getBoundingClientRect();
    const mw = menu.offsetWidth;
    const mh = menu.offsetHeight;
    let left = rect.right + 8;
    let top = rect.top - 4;
    if (left + mw > window.innerWidth - 8) left = rect.left - mw - 8;
    if (top + mh > window.innerHeight - 8) top = window.innerHeight - mh - 8;
    if (top < 8) top = 8;
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = top + 'px';

    const onDocDown = function (e) {
        if (menu && !menu.contains(e.target)) closeMenu();
    };
    const onKey = function (e) {
        if (e.key === 'Escape') closeMenu();
    };
    document.addEventListener('mousedown', onDocDown, true);
    document.addEventListener('keydown', onKey, true);
    menuCleanup = function () {
        document.removeEventListener('mousedown', onDocDown, true);
        document.removeEventListener('keydown', onKey, true);
    };
}

// 光标所在的有序列表项：用于把 ⚡ 定位到对应序号左侧
function itemContainsLine(doc, item, lineNo) {
    if (lineNo === item.lineNo) return true;
    for (let ln = item.lineNo + 1; ln <= lineNo; ln++) {
        const text = doc.line(ln).text;
        // 空行是分组边界，光标停在空行时不显示 ⚡
        if (!text.trim()) return false;
        const info = lineInfo(text);
        if (info.quote !== item.quote) return false;
        if (info.indent > item.indentCols) continue;
        return false;
    }
    return true;
}

function listAtCursor(view) {
    const doc = view.state.doc;
    const pos = view.state.selection.main.head;
    const items = parseItems(doc);
    if (!items.length) return null;

    const lineNo = doc.lineAt(pos).number;
    let item = items.find(function (it) {
        return it.lineNo === lineNo;
    }) || null;

    if (!item) {
        for (let i = items.length - 1; i >= 0; i--) {
            const cand = items[i];
            if (cand.lineNo >= lineNo) continue;
            if (itemContainsLine(doc, cand, lineNo)) {
                item = cand;
                break;
            }
        }
    }
    if (!item) return null;

    const first = backwardFirst(doc, items, item);
    const all = forwardSiblings(doc, items, first);
    const idx = all.findIndex(function (it) {
        return it.lineNo === item.lineNo;
    });
    if (idx < 0) return null;

    const last = all[all.length - 1];
    const range = { from: first.from, to: last.to };
    const state = view.state.field(listAutoField);
    const prompt = state.prompts.find(function (p) {
        return rangeOverlaps(p, range);
    }) || null;
    const explicitManual = state.manual.some(function (r) {
        return rangeOverlaps(r, range);
    });

    return {
        item: item,
        first: first,
        last: last,
        all: all,
        range: range,
        prompt: prompt,
        manual: explicitManual || !isSequential(all)
    };
}

const BUTTON_SIZE = 24;

class AutoButtonPlugin {
    constructor(view) {
        this.view = view;
        this.timer = 0;
        this.button = document.createElement('button');
        this.button.type = 'button';
        this.button.className = 'cm-list-auto-float';
        this.button.textContent = '⚡';
        this.button.title = '自动编号选项';
        this.button.setAttribute('aria-label', '自动编号选项');
        this.button.style.display = 'none';
        this.button.addEventListener('mousedown', function (e) {
            e.preventDefault();
            e.stopPropagation();
        });
        this.button.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.openMenu();
        });
        document.body.appendChild(this.button);

        this.onScroll = () => {
            if (menuEl) closeMenu();
            this.schedule();
        };
        view.scrollDOM.addEventListener('scroll', this.onScroll, { passive: true });
        window.addEventListener('resize', this.onScroll);
        if (typeof ResizeObserver !== 'undefined') {
            this.resizeObserver = new ResizeObserver(() => this.schedule());
            this.resizeObserver.observe(view.dom);
        }
        this.schedule();
    }

    schedule() {
        if (this.timer) return;
        this.timer = setTimeout(() => {
            this.timer = 0;
            this.updatePosition();
        }, 0);
    }

    update(update) {
        if (update.docChanged || update.selectionSet) {
            if (menuEl) closeMenu();
        }
        this.schedule();
    }

    hide() {
        this.button.style.display = 'none';
        if (menuEl) closeMenu();
    }

    updatePosition() {
        const info = listAtCursor(this.view);
        if (!info) {
            this.hide();
            return;
        }

        const coords = this.view.coordsAtPos(info.item.markerFrom);
        if (!coords) {
            this.hide();
            return;
        }
        const editorRect = this.view.dom.getBoundingClientRect();
        if (!editorRect.width || !editorRect.height) {
            this.hide();
            return;
        }
        if (coords.bottom < editorRect.top || coords.top > editorRect.bottom) {
            this.hide();
            return;
        }

        const left = Math.max(4, coords.left - BUTTON_SIZE - 3);
        const top = Math.max(2,
            (coords.top + coords.bottom) / 2 - BUTTON_SIZE / 2);

        this.button.style.display = 'flex';
        this.button.style.left = left + 'px';
        this.button.style.top = top + 'px';
    }

    openMenu() {
        const info = listAtCursor(this.view);
        if (!info) return;
        openMenu(this.view, info, this.button);
    }

    destroy() {
        if (this.timer) clearTimeout(this.timer);
        this.timer = 0;
        this.view.scrollDOM.removeEventListener('scroll', this.onScroll);
        window.removeEventListener('resize', this.onScroll);
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
        if (menuEl) closeMenu();
        if (this.button.parentNode) this.button.parentNode.removeChild(this.button);
    }
}

const listAutoOverlay = ViewPlugin.fromClass(AutoButtonPlugin);

// ---------------- 扩展入口 ----------------

export function orderedListAutoNumber() {
    return [listAutoField, autoFilter, listAutoOverlay];
}

const autoFilter = EditorState.transactionFilter.of(function (tr) {
    if (!tr.docChanged || !isUserEdit(tr)) return tr;
    if (!tr.startState.field(listAutoField)) return tr;
    if (!mayAffectList(tr)) return tr;

    const state = tr.startState.field(listAutoField);
    if (touchesManual(tr, state.manual)) return tr;

    let result = null;
    try {
        result = computeAutoChanges(tr);
    } catch (e) {
        console.warn('[list-autonumber] compute failed', e);
        return tr;
    }
    if (!result || !result.changes.length) return tr;

    return [
        {
            changes: tr.changes,
            selection: tr.selection,
            effects: tr.effects,
            annotations: tr.annotations,
            scrollIntoView: tr.scrollIntoView
        },
        {
            changes: result.changes,
            sequential: true,
            filter: false,
            effects: [addPrompt.of(result.prompt)]
        }
    ];
});
