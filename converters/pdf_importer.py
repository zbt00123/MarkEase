# -*- coding: utf-8 -*-
"""
PDF 转 Markdown 转换器

优先读取 PDF 里内嵌的 MarkEase 原始 Markdown 附件；
若无，则走解析逻辑。
"""

import os
import re

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None


class PdfImporter:
    SIZE_EPSILON = 0.1
    HEADING_RATIO = 1.15
    HEADING_DOMINANT_RATIO = 0.7
    INDENT_WIDTH = 24.0
    LINE_Y_TOL = 20.0
    EMBED_NAME = "markease_source.md"

    TEXT_BULLET_CHARS = frozenset('•·◦‣⁃∙▪▫◾◽■□▢▣▲△▼▽★☆')
    CHECKBOX_CHARS = frozenset('☑☐✓✔☒✗✘')
    CHECKMARK_CHARS = frozenset('✓✔☑√✗✘×☒')

    CN_HEADING_RE = re.compile(r'^\s*[一二三四五六七八九十]+\s*[、.．]\s*\S')
    CN_HEADING_INLINE_RE = re.compile(r'\s+[一二三四五六七八九十]+\s*[、.．]\s*\S')

    @staticmethod
    def is_available() -> bool:
        return fitz is not None

    # ==================== 入口 ====================
    @staticmethod
    def convert(path: str, image_placeholder: str = "[图片]") -> str:
        if fitz is None:
            raise RuntimeError("未安装 PyMuPDF，请先运行: pip install PyMuPDF")
        doc = fitz.open(path)
        try:
            # 优先读取内嵌 Markdown
            try:
                names = doc.embfile_names()
                if PdfImporter.EMBED_NAME in names:
                    data = doc.embfile_get(PdfImporter.EMBED_NAME)
                    if data:
                        return data.decode("utf-8")
            except Exception:
                pass
            return PdfImporter._convert_doc(doc, path, image_placeholder)
        finally:
            doc.close()

    @staticmethod
    def _convert_doc(doc, source_path, image_placeholder):
        img_dir = None
        if source_path:
            try:
                base_name = os.path.splitext(os.path.basename(source_path))[0]
                parent = os.path.dirname(os.path.abspath(source_path))
                img_dir = os.path.join(parent, f"{base_name}_images")
            except Exception:
                img_dir = None

        pages_data = [PdfImporter._extract_page(p, doc) for p in doc]

        body_size = PdfImporter._detect_body_size(pages_data)
        threshold = body_size * PdfImporter.HEADING_RATIO

        all_sizes = set()
        for pd in pages_data:
            for line in pd['lines']:
                for c in line['chars']:
                    if c['c'].strip():
                        all_sizes.add(c['size'])
        heading_sizes = sorted([s for s in all_sizes if s > threshold], reverse=True)
        size_to_level = {s: min(i + 1, 6) for i, s in enumerate(heading_sizes)}

        output_lines = []
        img_counter = [0]
        img_dir_created = [False]
        ordered_counters = {}

        for pd in pages_data:
            PdfImporter._process_page(
                pd, size_to_level, body_size, threshold,
                output_lines, img_dir, img_counter, img_dir_created,
                image_placeholder, ordered_counters
            )
            output_lines.append('')

        md_text = '\n'.join(output_lines)
        md_text = re.sub(r'\n{3,}', '\n\n', md_text)
        return md_text.strip() + '\n'

    # ==================== 判断字符是否是普通 bullet ====================
    @staticmethod
    def _is_bullet_char(c):
        ch = c['c']
        if ch in PdfImporter.TEXT_BULLET_CHARS:
            return True
        # Symbol / Wingdings 字体的私有区域
        font = (c.get('font') or '').lower()
        if 'symbol' in font or 'wingding' in font:
            code = ord(ch)
            if 0xF000 <= code <= 0xF0FF:
                return True
        return False

    # ==================== 正文字号 ====================
    @staticmethod
    def _detect_body_size(pages_data):
        counter = {}
        for pd in pages_data:
            for line in pd['lines']:
                for c in line['chars']:
                    if not c['c'].strip():
                        continue
                    counter[c['size']] = counter.get(c['size'], 0) + 1
        if not counter:
            return 11.0
        return max(counter.items(), key=lambda kv: kv[1])[0]

    # ==================== 页面提取 ====================
    @staticmethod
    def _extract_page(page, doc):
        result = {'lines': [], 'images': [], 'links': [],
                  'tables': [], 'bullets': [], 'strike_lines': []}

        try:
            for tab in page.find_tables():
                try:
                    data = tab.extract()
                    if not data:
                        continue
                    total_chars = sum(len(str(c).strip()) for row in data for c in row if c)
                    if len(data) == 1 and total_chars < 15:
                        continue
                    if total_chars < 8:
                        continue
                    if len(data) == 1:
                        max_cell_len = max((len(str(c).strip()) for c in data[0] if c), default=0)
                        if max_cell_len <= 2:
                            continue
                    result['tables'].append({'bbox': tuple(tab.bbox), 'data': data})
                except Exception:
                    pass
        except Exception:
            pass

        try:
            raw = page.get_text("rawdict")
        except Exception:
            raw = {}

        for block in raw.get('blocks', []):
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                chars = []
                for span in line.get('spans', []):
                    size = round(float(span.get('size', 0)), 1)
                    flags = span.get('flags', 0)
                    font_name = span.get('font', '') or ''
                    bold = bool(flags & 16)
                    italic = bool(flags & 2)
                    if not bold:
                        fn_lower = font_name.lower()
                        if ('bold' in fn_lower or 'heavy' in fn_lower
                                or 'black' in fn_lower or 'semibold' in fn_lower
                                or 'demibold' in fn_lower
                                or '黑体' in font_name or '加粗' in font_name):
                            bold = True
                    for ch in span.get('chars', []):
                        c = ch.get('c', '')
                        if not c:
                            continue
                        bbox = ch.get('bbox', (0, 0, 0, 0))
                        chars.append({
                            'c': c, 'size': size, 'bold': bold, 'italic': italic,
                            'font': font_name,
                            'x0': float(bbox[0]), 'y0': float(bbox[1]),
                            'x1': float(bbox[2]), 'y1': float(bbox[3]),
                            'strike': False,
                        })
                if not chars:
                    continue
                x0 = min(c['x0'] for c in chars)
                y0 = min(c['y0'] for c in chars)
                x1 = max(c['x1'] for c in chars)
                y1 = max(c['y1'] for c in chars)
                result['lines'].append({
                    'chars': chars, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
                    'bbox': (x0, y0, x1, y1),
                })

        try:
            for img_info in page.get_image_info():
                bbox = img_info.get('bbox')
                xref = img_info.get('xref', 0)
                if not bbox or not xref:
                    continue
                try:
                    base = doc.extract_image(xref)
                    if not base or not base.get('image'):
                        continue
                    result['images'].append({
                        'y0': float(bbox[1]), 'image': base['image'],
                        'ext': base.get('ext', 'png'),
                    })
                except Exception:
                    continue
        except Exception:
            pass

        try:
            for link in page.get_links():
                uri = link.get('uri', '')
                rect = link.get('from')
                if uri and rect:
                    result['links'].append({
                        'bbox': (rect.x0, rect.y0, rect.x1, rect.y1),
                        'uri': uri,
                    })
        except Exception:
            pass

        try:
            for d in page.get_drawings():
                rect = d.get('rect')
                if rect is None:
                    continue
                w = float(rect.width)
                h = float(rect.height)
                if w >= 8 and h <= 2.5:
                    result['strike_lines'].append({
                        'y': float((rect.y0 + rect.y1) / 2),
                        'x0': float(rect.x0), 'x1': float(rect.x1),
                    })
                    continue
                if not (2 <= w <= 20 and 2 <= h <= 20):
                    continue
                if abs(w - h) > 10:
                    continue
                items = d.get('items', [])
                codes = [it[0] for it in items if it]
                if 're' in codes:
                    shape = 'rect'
                elif 'l' in codes and 'c' in codes:
                    shape = 'rect'
                elif 'c' in codes and 'l' not in codes:
                    shape = 'circle'
                elif 'l' in codes:
                    shape = 'line'
                else:
                    shape = 'unknown'
                fill = d.get('fill')
                fill_color = None
                if isinstance(fill, (tuple, list)) and len(fill) >= 3:
                    fill_color = (float(fill[0]), float(fill[1]), float(fill[2]))
                result['bullets'].append({
                    'bbox': (float(rect.x0), float(rect.y0),
                             float(rect.x1), float(rect.y1)),
                    'shape': shape, 'fill_color': fill_color,
                    'cx': float((rect.x0 + rect.x1) / 2),
                    'cy': float((rect.y0 + rect.y1) / 2),
                })
        except Exception:
            pass

        if result['strike_lines']:
            for line in result['lines']:
                for c in line['chars']:
                    ch_cy = (c['y0'] + c['y1']) / 2
                    ch_cx = (c['x0'] + c['x1']) / 2
                    ch_h = c['y1'] - c['y0']
                    if ch_h <= 0:
                        continue
                    for sl in result['strike_lines']:
                        if (sl['x0'] - 1 <= ch_cx <= sl['x1'] + 1
                                and abs(sl['y'] - ch_cy) < ch_h * 0.6):
                            c['strike'] = True
                            break

        return result

    # ==================== 页面处理 ====================
    @staticmethod
    def _process_page(pd, size_to_level, body_size, threshold,
                      output_lines, img_dir, img_counter, img_dir_created,
                      image_placeholder, ordered_counters):
        text_lines = []
        for l in pd['lines']:
            if PdfImporter._inside_table(l['bbox'], pd['tables']):
                continue
            text = ''.join(c['c'] for c in l['chars']).strip()
            if text and all(ch in PdfImporter.CHECKMARK_CHARS for ch in text):
                continue
            text_lines.append(l)

        if not text_lines and not pd['bullets'] and not pd['images'] and not pd['tables']:
            return

        bullets_by_line = {}
        for b in pd['bullets']:
            b_cy = (b['bbox'][1] + b['bbox'][3]) / 2
            best_i = None
            best_d = PdfImporter.LINE_Y_TOL
            for i, line in enumerate(text_lines):
                if b['cx'] > line['x1'] + 20:
                    continue
                line_cy = (line['y0'] + line['y1']) / 2
                d = abs(b_cy - line_cy)
                if d < best_d:
                    best_d = d
                    best_i = i
            if best_i is not None:
                bullets_by_line.setdefault(best_i, []).append(b)

        for i, blist in list(bullets_by_line.items()):
            has_rect = any(b.get('shape') == 'rect' for b in blist)
            if has_rect and len(blist) > 1:
                bullets_by_line[i] = [b for b in blist if b.get('shape') == 'rect']

        all_bullet_xs = [b['cx'] for b in pd['bullets']]
        for line in text_lines:
            for c in line['chars']:
                if PdfImporter._is_bullet_char(c):
                    all_bullet_xs.append(c['x0'])
        base_bullet_x = min(all_bullet_xs) if all_bullet_xs else 0.0

        items = []
        for i, line in enumerate(text_lines):
            items.append(('line', line['y0'], line, bullets_by_line.get(i, [])))
        for img in pd['images']:
            items.append(('image', img['y0'], img, None))
        for tab in pd['tables']:
            items.append(('table', tab['bbox'][1], tab, None))
        items.sort(key=lambda x: x[1])

        current_segments = []

        def flush_para():
            if not current_segments:
                return
            merged = PdfImporter._merge_segments(current_segments)
            line_out = PdfImporter._segments_to_md(merged)
            if line_out:
                parts = PdfImporter._split_inline_cn_heading(line_out)
                output_lines.extend(parts)
            current_segments.clear()

        for item_type, _, item, line_bullets in items:
            if item_type == 'image':
                flush_para()
                img_counter[0] += 1
                ref = PdfImporter._handle_image(
                    item, img_dir, img_counter[0],
                    img_dir_created, image_placeholder
                )
                output_lines.append(ref)

            elif item_type == 'table':
                flush_para()
                md = PdfImporter._table_to_md(item['data'])
                if md:
                    output_lines.extend(md)
                    output_lines.append('')

            else:
                results = PdfImporter._process_line(
                    item, line_bullets, size_to_level, body_size, threshold,
                    base_bullet_x, pd['links']
                )
                for r in results:
                    if r['type'] == 'heading':
                        flush_para()
                        output_lines.append('#' * r['level'] + ' ' + r['text'])
                        ordered_counters.clear()
                    elif r['type'] == 'list_item':
                        flush_para()
                        level = r['level']
                        content = r['text']
                        checkbox = r.get('checkbox')
                        if checkbox == 'checked':
                            prefix = '  ' * level + '- [x] '
                        elif checkbox == 'unchecked':
                            prefix = '  ' * level + '- [ ] '
                        elif r['ordered']:
                            for lv in list(ordered_counters.keys()):
                                if lv > level:
                                    del ordered_counters[lv]
                            ordered_counters[level] = ordered_counters.get(level, 0) + 1
                            prefix = '  ' * level + f"{ordered_counters[level]}. "
                        else:
                            ordered_counters.clear()
                            prefix = '  ' * level + '- '
                        output_lines.append(prefix + content)
                    else:
                        current_segments.extend(r['segments'])

        flush_para()

    @staticmethod
    def _split_inline_cn_heading(text):
        if not text:
            return []
        positions = [m.start() for m in PdfImporter.CN_HEADING_INLINE_RE.finditer(text)]
        if not positions:
            return [text]
        parts = []
        prev = 0
        for pos in positions:
            chunk = text[prev:pos].strip()
            if chunk:
                parts.append(chunk)
            prev = pos
        tail = text[prev:].strip()
        if tail:
            parts.append(tail)
        return parts

    @staticmethod
    def _inside_table(bbox, tables):
        if not tables:
            return False
        x0, y0, x1, y1 = bbox
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        for tab in tables:
            tx0, ty0, tx1, ty1 = tab['bbox']
            if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
                return True
        return False

    # ==================== 单行处理 ====================
    @staticmethod
    def _process_line(line, line_bullets, size_to_level, body_size, threshold,
                      base_bullet_x, page_links):
        chars = line['chars']
        if not chars:
            return []
        text = ''.join(c['c'] for c in chars)
        if not text.strip():
            return []
        stripped = text.strip()
        if stripped and all(ch in PdfImporter.CHECKMARK_CHARS for ch in stripped):
            return []

        bullet_results = PdfImporter._split_by_all_bullets(
            line, line_bullets, size_to_level, body_size, threshold,
            base_bullet_x, page_links
        )
        if bullet_results:
            return bullet_results

        markers = PdfImporter._find_list_markers(text)
        if len(markers) >= 1:
            results = []
            for i, (ms, me, ordered) in enumerate(markers):
                content_end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
                seg_chars = chars[me:content_end]
                raw = ''.join(c['c'] for c in seg_chars)
                if not raw.strip():
                    continue
                lead = len(raw) - len(raw.lstrip())
                trail = len(raw) - len(raw.rstrip())
                seg_chars = seg_chars[lead:len(seg_chars) - trail]
                if not seg_chars:
                    continue
                segs = PdfImporter._chars_to_segments(seg_chars, body_size, page_links)
                merged = PdfImporter._merge_segments(segs)
                content_md = PdfImporter._segments_to_md(merged)
                results.append({
                    'type': 'list_item', 'ordered': ordered,
                    'level': 0, 'text': content_md,
                })
            return results

        if PdfImporter._is_heading_line(chars, threshold, size_to_level):
            dom_size = PdfImporter._dominant_size(chars)
            level = size_to_level[dom_size]
            return [{'type': 'heading', 'level': level, 'text': stripped}]

        if len(stripped) <= 30 and PdfImporter.CN_HEADING_RE.match(stripped):
            max_size = PdfImporter._max_size(chars)
            if max_size in size_to_level:
                level = size_to_level[max_size]
            elif max_size > threshold:
                level = 2
            else:
                level = 3
            return [{'type': 'heading', 'level': level, 'text': stripped}]

        segs = PdfImporter._chars_to_segments(chars, body_size, page_links)
        if not segs:
            return []
        return [{'type': 'paragraph', 'segments': segs}]

    # ==================== 统一 bullet 处理 ====================
    @staticmethod
    def _split_by_all_bullets(line, line_bullets, size_to_level, body_size,
                              threshold, base_bullet_x, page_links):
        chars = line['chars']

        # 收集 bullet 事件（按 x 排序）
        bullet_events = []
        for b in line_bullets:
            bullet_events.append((b['cx'], 'vector', b))
        for i, c in enumerate(chars):
            if PdfImporter._is_bullet_char(c):
                # 排除前面紧邻英文字母的情况
                prev = None
                for j in range(i - 1, -1, -1):
                    if chars[j]['c'].strip():
                        prev = chars[j]['c']
                        break
                if prev is not None and prev.isascii() and prev.isalpha():
                    continue
                bullet_events.append((c['x0'], 'text', i))
        bullet_events.sort(key=lambda e: e[0])

        if not bullet_events:
            return []

        # 分配字符：每个字符归属"它左侧最近的 bullet"
        groups = [{'event': ev, 'chars': []} for ev in bullet_events]
        prefix_chars = []

        for i, c in enumerate(chars):
            is_bullet = False
            for ev in bullet_events:
                if ev[1] == 'text' and ev[2] == i:
                    is_bullet = True
                    break
            if is_bullet:
                continue
            cx = (c['x0'] + c['x1']) / 2
            best_gi = None
            for gi, ev in enumerate(bullet_events):
                # 字符在 bullet 右侧（+3容差）
                if ev[0] <= cx + 3:
                    best_gi = gi
                else:
                    break
            if best_gi is None:
                prefix_chars.append(c)
            else:
                groups[best_gi]['chars'].append(c)

        results = []

        # 前缀
        prefix_text = ''.join(c['c'] for c in prefix_chars).strip()
        if prefix_text:
            if len(prefix_text) <= 30 and PdfImporter.CN_HEADING_RE.match(prefix_text):
                max_size = PdfImporter._max_size(prefix_chars)
                if max_size in size_to_level:
                    level = size_to_level[max_size]
                elif max_size > threshold:
                    level = 2
                else:
                    level = 3
                results.append({'type': 'heading', 'level': level, 'text': prefix_text})
            else:
                segs = PdfImporter._chars_to_segments(prefix_chars, body_size, page_links)
                merged = PdfImporter._merge_segments(segs)
                if merged:
                    results.append({'type': 'paragraph', 'segments': merged})

        # 各 bullet 组
        for g in groups:
            ev = g['event']
            gc = g['chars']
            if not gc:
                continue

            # 去前后空白
            raw = ''.join(c['c'] for c in gc)
            if not raw.strip():
                continue
            lead = len(raw) - len(raw.lstrip())
            trail = len(raw) - len(raw.rstrip())
            gc = gc[lead:len(gc) - trail]
            if not gc:
                continue

            x, kind, obj = ev
            level = int((x - base_bullet_x + 5) // PdfImporter.INDENT_WIDTH)
            if level < 0:
                level = 0

            # 复选框：先看矢量 bullet 本身
            checkbox = None
            if kind == 'vector':
                checkbox = PdfImporter._bullet_checkbox_state(obj, ''.join(c['c'] for c in gc))

            # 从内容开头剥离 checkbox 字符
            if checkbox is None and gc:
                first_ch = gc[0]['c']
                if first_ch in PdfImporter.CHECKBOX_CHARS:
                    if first_ch in ('☑', '✓', '✔', '☒'):
                        checkbox = 'checked'
                    else:
                        checkbox = 'unchecked'
                    gc = gc[1:]
                    while gc and not gc[0]['c'].strip():
                        gc = gc[1:]
                    if not gc:
                        continue

            segs = PdfImporter._chars_to_segments(gc, body_size, page_links)
            merged = PdfImporter._merge_segments(segs)
            content_md = PdfImporter._segments_to_md(merged)
            if not content_md:
                continue

            results.append({
                'type': 'list_item', 'ordered': False,
                'level': level, 'text': content_md, 'checkbox': checkbox,
            })

        return results

    @staticmethod
    def _bullet_checkbox_state(bullet, content_text):
        if bullet.get('shape') != 'rect':
            return None
        if content_text and any(ch in content_text for ch in PdfImporter.CHECKMARK_CHARS):
            return 'checked'
        fc = bullet.get('fill_color')
        if fc is not None:
            brightness = sum(fc) / 3
            if brightness < 0.9:
                return 'checked'
        return 'unchecked'

    # ==================== 标题判定 ====================
    @staticmethod
    def _dominant_size(chars):
        counter = {}
        for c in chars:
            if not c['c'].strip():
                continue
            counter[c['size']] = counter.get(c['size'], 0) + 1
        if not counter:
            return None
        return max(counter.items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def _max_size(chars):
        sizes = [c['size'] for c in chars if c['c'].strip()]
        return max(sizes) if sizes else None

    @staticmethod
    def _is_heading_line(chars, threshold, size_to_level):
        counter = {}
        for c in chars:
            if not c['c'].strip():
                continue
            counter[c['size']] = counter.get(c['size'], 0) + 1
        if not counter:
            return False
        total = sum(counter.values())
        dom_size, dom_count = max(counter.items(), key=lambda kv: kv[1])
        if dom_count / total < PdfImporter.HEADING_DOMINANT_RATIO:
            return False
        if dom_size <= threshold:
            return False
        return dom_size in size_to_level

    @staticmethod
    def _find_list_markers(text):
        markers = []
        for m in re.finditer(r'(?<![\d])(\d{1,3})\s*[.、)）]\s+', text):
            markers.append((m.start(), m.end(), True))
        for m in re.finditer(r'[（(]\s*\d{1,3}\s*[）)]\s+', text):
            markers.append((m.start(), m.end(), True))
        for m in re.finditer(r'[①-⑳]\s*', text):
            if m.end() > m.start():
                markers.append((m.start(), m.end(), True))
        markers.sort()
        filtered = []
        last_end = -1
        for ms, me, ordered in markers:
            if ms >= last_end:
                filtered.append((ms, me, ordered))
                last_end = me
        return filtered

    # ==================== 字符 → Segment ====================
    @staticmethod
    def _chars_to_segments(chars, body_size, page_links):
        if not chars:
            return []
        valid_sizes = [c['size'] for c in chars if c['c'].strip()]
        line_min = min(valid_sizes) if valid_sizes else body_size
        segments = []
        i = 0
        n = len(chars)
        while i < n:
            base = chars[i]
            base_strike = base.get('strike', False)
            j = i + 1
            while (j < n
                   and chars[j]['size'] == base['size']
                   and chars[j]['bold'] == base['bold']
                   and chars[j]['italic'] == base['italic']
                   and chars[j].get('strike', False) == base_strike):
                j += 1
            seg_text = ''.join(c['c'] for c in chars[i:j])
            if not seg_text:
                i = j
                continue
            link_uri = None
            if page_links:
                bbox = (base['x0'], base['y0'], chars[j - 1]['x1'], chars[j - 1]['y1'])
                link_uri = PdfImporter._find_link(bbox, page_links)
            bold = base['bold']
            italic = base['italic']
            if base['size'] > line_min + PdfImporter.SIZE_EPSILON:
                bold = True
            segments.append((seg_text, {
                'bold': bold, 'italic': italic,
                'link': link_uri, 'strike': base_strike,
            }))
            i = j
        return segments

    @staticmethod
    def _merge_segments(segments):
        if not segments:
            return []
        merged = []
        for seg_text, fmt in segments:
            if not seg_text:
                continue
            if not merged:
                merged.append([seg_text, fmt])
                continue
            prev_text, prev_fmt = merged[-1]
            if (prev_fmt.get('bold') == fmt.get('bold')
                    and prev_fmt.get('italic') == fmt.get('italic')
                    and prev_fmt.get('link') == fmt.get('link')
                    and prev_fmt.get('strike') == fmt.get('strike')):
                if PdfImporter._need_space(prev_text, seg_text):
                    merged[-1][0] = prev_text + ' ' + seg_text
                else:
                    merged[-1][0] = prev_text + seg_text
            else:
                merged.append([seg_text, fmt])
        return [(t, f) for t, f in merged]

    @staticmethod
    def _need_space(prev_text, curr_text):
        if not prev_text or not curr_text:
            return False
        return (PdfImporter._is_word_char(prev_text[-1])
                and PdfImporter._is_word_char(curr_text[0]))

    @staticmethod
    def _is_word_char(ch):
        if not ch:
            return False
        return ch.isascii() and ch.isalnum()

    @staticmethod
    def _segments_to_md(segments):
        parts = []
        for text, fmt in segments:
            if fmt.get('link'):
                parts.append(f"[{text}]({fmt['link']})")
                continue
            bold = fmt['bold']
            italic = fmt['italic']
            strike = fmt.get('strike', False)
            if not text.strip():
                parts.append(text)
                continue
            inner = text
            if bold and italic:
                inner = "***" + inner + "***"
            elif bold:
                inner = "**" + inner + "**"
            elif italic:
                inner = "*" + inner + "*"
            if strike:
                inner = "~~" + inner + "~~"
            parts.append(inner)
        result = ''.join(parts).strip()
        result = re.sub(r'\s*[•·◦‣⁃∙▪▫◾◽■□▢▣]\s*$', '', result)
        return PdfImporter._normalize_punctuation(result)

    @staticmethod
    def _find_link(bbox, page_links):
        if not page_links:
            return None
        sx0, sy0, sx1, sy1 = bbox
        for link in page_links:
            lx0, ly0, lx1, ly1 = link['bbox']
            if sx0 < lx1 and sx1 > lx0 and sy0 < ly1 and sy1 > ly0:
                return link['uri']
        return None

    # ==================== 图片 ====================
    @staticmethod
    def _handle_image(item, img_dir, counter, img_dir_created, placeholder):
        if img_dir:
            try:
                if not img_dir_created[0]:
                    os.makedirs(img_dir, exist_ok=True)
                    img_dir_created[0] = True
                ext = (item.get('ext') or 'png').lower()
                if ext not in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
                    ext = 'png'
                filename = f"image_{counter:03d}.{ext}"
                path = os.path.join(img_dir, filename)
                with open(path, 'wb') as f:
                    f.write(item['image'])
                return f"![]({path})"
            except Exception:
                pass
        return placeholder

    # ==================== 表格 ====================
    @staticmethod
    def _table_to_md(data):
        if not data:
            return []
        max_cols = max(len(row) for row in data)
        if max_cols == 0:
            return []
        rows = []
        for row in data:
            r = [str(c).replace('\n', ' ').replace('|', '\\|').strip() if c else ''
                 for c in row]
            while len(r) < max_cols:
                r.append('')
            rows.append(r)
        lines = ['| ' + ' | '.join(rows[0]) + ' |',
                 '| ' + ' | '.join(['---'] * max_cols) + ' |']
        for row in rows[1:]:
            lines.append('| ' + ' | '.join(row) + ' |')
        return lines

    @staticmethod
    def _normalize_punctuation(text):
        if not text:
            return text
        text = text.replace("......", "……")
        text = text.replace("...", "…")
        return text