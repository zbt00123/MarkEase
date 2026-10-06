# -*- coding: utf-8 -*-
"""
PDF 转 Markdown 转换器

优先读取 PDF 里内嵌的 MarkEase 原始 Markdown 附件；
若无，则走解析逻辑。

★ 阶段 16 第 7 批：
   1. convert() 新增 image_data_url_mode 参数。
      True 时把 PDF 内的图片直接编码为 data URL 嵌入 Markdown，
      用于「拖动 PDF 到窗口（无 path）」的场景，图片才能显示。
   2. 保留 extract_images 参数，走「菜单导入 PDF」时仍然落盘到
      <pdf_dir>/<basename>_images/。

★ 阶段 16 第 8 批：
   1. convert() 新增 image_dir_override 参数：
      - 提供时：图片落盘到该目录；MD 里用相对路径 assets/xxx.png
      - 不提供时：沿用原行为（<pdf_dir>/<basename>_images/；MD 里用绝对路径）

★ 本轮修订（导入 PDF 图片缺失恢复）：
   1. convert() 读到内嵌 markease_source.md 后，检查 Markdown 里所有
      本地图片路径是否存在。
   2. 缺失的图片从 PDF 页面按顺序提取，写入系统临时文件夹，替换
      Markdown 里的对应路径。
   3. 网络图片（http/https）不参与恢复，原样保留。
"""

import os
import re
import base64
import tempfile  # ★ 本轮新增

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None


# ★ 本轮新增：Markdown / HTML 图片正则（用于恢复缺失图片）
_MD_IMG_RE = re.compile(
    r'(!\[[^\]]*\]\()(\s*)(<[^>]*>|[^)\s]+)([^)]*)(\))'
)

_HTML_IMG_RE = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])([^"\']*)(\2[^>]*>)',
    re.IGNORECASE
)


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

    MIME_MAP = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
        'webp': 'image/webp',
    }

    @staticmethod
    def is_available() -> bool:
        return fitz is not None

    # ==================== 入口 ====================
    @staticmethod
    def convert(path: str,
                image_placeholder: str = "[图片]",
                extract_images: bool = True,
                image_data_url_mode: bool = False,
                max_image_bytes: int = 500 * 1024,
                max_total_bytes: int = 20 * 1024 * 1024,
                image_dir_override: str = None) -> str:
        """
        把 PDF 转成 Markdown。

        参数：
            path                  PDF 文件路径
            image_placeholder     图片占位符（如 "[图片]"）
            extract_images        True → 图片落盘
                                  False → 不落盘（除非 image_data_url_mode=True）
            image_data_url_mode   True → 图片直接编码成 data URL 嵌入 Markdown
            max_image_bytes       单张图最大字节数（超出则用 placeholder）
            max_total_bytes       所有 data URL 图片总字节上限
            image_dir_override    提供时：图片落盘到该目录；
                                  MD 里用相对路径 assets/xxx.png
        """
        if fitz is None:
            raise RuntimeError("未安装 PyMuPDF，请先运行: pip install PyMuPDF")
        doc = fitz.open(path)
        try:
            # 1) 优先读取内嵌 Markdown（导出自 MarkEase 的 PDF）
            try:
                names = doc.embfile_names()
                if PdfImporter.EMBED_NAME in names:
                    data = doc.embfile_get(PdfImporter.EMBED_NAME)
                    if data:
                        md = data.decode("utf-8")
                        # ★ 本轮新增：检查缺失图片，从 PDF 恢复
                        if path:
                            try:
                                md = PdfImporter._recover_missing_images(
                                    md, path, doc)
                            except Exception as e:
                                print(f'[pdf_importer] '
                                      f'recover_missing_images failed: {e}')
                        return md
            except Exception:
                pass

            # 2) 决定图片处理策略
            image_opts = {
                'data_url_mode': bool(image_data_url_mode),
                'max_image_bytes': int(max_image_bytes),
                'max_total_bytes': int(max_total_bytes),
                'total_bytes': [0],   # mutable accumulator
                'image_dir_override': image_dir_override,
            }

            # 无 path 时不能落盘
            if image_data_url_mode:
                source_path = ''
            else:
                source_path = path if extract_images else ''

            return PdfImporter._convert_doc(
                doc, source_path, image_placeholder, image_opts
            )
        finally:
            doc.close()

    # ==================== ★ 本轮新增：恢复缺失图片 ====================
    @staticmethod
    def _recover_missing_images(md, pdf_path, doc):
        """
        检查 Markdown 里所有本地图片路径是否存在；缺失的从 PDF 恢复。

        规则：
          - http(s):// / data: / blob: / file: → 跳过（原样保留）
          - 本地路径（绝对或相对）→ 检查文件是否存在
          - 不存在 → 从 PDF 页面按顺序提取图片，写入系统临时文件夹，
                     替换 Markdown 里对应的 URL
        """
        if not md:
            return md

        pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
        print(f'[pdf_importer] recover: pdf_path={pdf_path}')
        print(f'[pdf_importer] recover: pdf_dir={pdf_dir}')

        def is_local_and_missing(url):
            if not url:
                return False
            raw = url
            if raw.startswith('<') and raw.endswith('>'):
                raw = raw[1:-1]
            # 跳过非本地
            if re.match(r'^(https?:|data:|blob:|file:)', raw, re.IGNORECASE):
                return False
            # Windows 盘符绝对路径
            if re.match(r'^[A-Za-z]:[\\/]', raw):
                exists = os.path.isfile(raw)
                print(f'[pdf_importer]   check abs: {raw} exists={exists}')
                return not exists
            # Unix 绝对路径
            if raw.startswith('/'):
                exists = os.path.isfile(raw)
                print(f'[pdf_importer]   check unix: {raw} exists={exists}')
                return not exists
            # 相对路径
            full = os.path.join(pdf_dir, raw)
            exists = os.path.isfile(full)
            print(f'[pdf_importer]   check rel: {raw} -> {full} exists={exists}')
            return not exists

        # 收集 Markdown 里所有图片引用（按位置排序）
        matches = []
        for m in _MD_IMG_RE.finditer(md):
            matches.append((m, 3))
        for m in _HTML_IMG_RE.finditer(md):
            matches.append((m, 3))
        matches.sort(key=lambda x: x[0].start())

        print(f'[pdf_importer] total image refs in MD: {len(matches)}')

        # 过滤出「本地且缺失」的图片
        missing = [
            (m, g) for m, g in matches
            if is_local_and_missing(m.group(g))
        ]
        print(f'[pdf_importer] missing local images: {len(missing)}')

        if not missing:
            return md

        # 从 PDF 中按文档顺序提取所有图片
        extracted = PdfImporter._extract_all_images_in_order(doc)
        print(f'[pdf_importer] images extracted from PDF: {len(extracted)}')

        if not extracted:
            print('[pdf_importer] WARNING: PDF 中未提取到任何图片，'
                  '请检查 PDF 是否以图片形式包含图片对象')
            return md

        # 写入临时文件夹 + 替换路径
        temp_dir = tempfile.mkdtemp(prefix='markease_pdf_recovered_')
        print(f'[pdf_importer] temp dir: {temp_dir}')
        result = md
        recovered = 0

        # 从后往前替换，避免位置偏移
        for i in range(len(missing) - 1, -1, -1):
            if i >= len(extracted):
                continue
            m, g = missing[i]
            img_data, img_ext = extracted[i]
            ext = (img_ext or 'png').lower()
            if ext not in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
                ext = 'png'
            fname = f'recovered_{i:03d}.{ext}'
            fpath = os.path.join(temp_dir, fname)
            try:
                with open(fpath, 'wb') as f:
                    f.write(img_data)
            except Exception as e:
                print(f'[pdf_importer] write {fpath} failed: {e}')
                continue

            new_path = fpath.replace('\\', '/')
            orig_url = m.group(g)
            was_angle = orig_url.startswith('<') and orig_url.endswith('>')
            if was_angle or re.search(r'[\s()]', new_path):
                new_url = '<' + new_path + '>'
            else:
                new_url = new_path

            start = m.start(g)
            end = m.end(g)
            result = result[:start] + new_url + result[end:]
            recovered += 1
            print(f'[pdf_importer]   recovered #{i}: {orig_url} -> {new_path}')

        print(f'[pdf_importer] recover done: {recovered} images')
        return result

    @staticmethod
    def _extract_all_images_in_order(doc):
        """
        按文档顺序提取 PDF 里所有图片（页面顺序 + 页面内 y 坐标顺序）。

        优先用 page.get_image_info()；如果返回空（例如图片在 Form XObject
        或内联图片流里），则用 page.get_images(full=True) 作为后备。

        返回：[(img_bytes, ext), ...]
        """
        images = []
        try:
            page_count = len(doc)
        except Exception as e:
            print(f'[pdf_importer] len(doc) failed: {e}')
            return images

        print(f'[pdf_importer] extract pages: {page_count}')

        for page_num in range(page_count):
            try:
                page = doc[page_num]
            except Exception as e:
                print(f'[pdf_importer] page {page_num} open failed: {e}')
                continue

            page_items = []
            seen_xrefs = set()

            # ---------- 方法 1：get_image_info()，含显示位置 ----------
            try:
                infos = page.get_image_info()
                for img_info in infos:
                    xref = img_info.get('xref', 0)
                    if not xref:
                        continue
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    bbox = img_info.get('bbox') or (0, 0, 0, 0)
                    try:
                        y = float(bbox[1])
                        x = float(bbox[0])
                    except Exception:
                        y = 0.0
                        x = 0.0
                    page_items.append({
                        'y': y, 'x': x, 'xref': xref,
                    })
                print(f'[pdf_importer] page {page_num}: '
                      f'get_image_info -> {len(page_items)} entries')
            except Exception as e:
                print(f'[pdf_importer] get_image_info failed on page '
                      f'{page_num}: {e}')

            # ---------- 方法 2：后备——get_images(full=True) ----------
            if not page_items:
                try:
                    imgs = page.get_images(full=True)
                    for item in imgs:
                        xref = item[0]
                        if not xref or xref in seen_xrefs:
                            continue
                        seen_xrefs.add(xref)
                        y, x = 0.0, 0.0
                        try:
                            rects = page.get_image_rects(xref)
                            if rects:
                                r = rects[0]
                                try:
                                    y = float(r.y0)
                                    x = float(r.x0)
                                except Exception:
                                    try:
                                        y = float(r[1])
                                        x = float(r[0])
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        page_items.append({'y': y, 'x': x, 'xref': xref})
                    print(f'[pdf_importer] page {page_num}: '
                          f'get_images(full=True) -> {len(page_items)} entries')
                except Exception as e:
                    print(f'[pdf_importer] get_images failed on page '
                          f'{page_num}: {e}')

            # 按阅读顺序排序：先 y（从上到下），再 x（从左到右）
            page_items.sort(key=lambda z: (z['y'], z['x']))

            for pi in page_items:
                xref = pi['xref']
                try:
                    base = doc.extract_image(xref)
                    if not base or not base.get('image'):
                        print(f'[pdf_importer] extract_image({xref}) empty')
                        continue
                    images.append((base['image'], base.get('ext', 'png')))
                except Exception as e:
                    print(f'[pdf_importer] extract_image({xref}) failed: {e}')
                    continue

        print(f'[pdf_importer] total images: {len(images)}')
        return images

    # ==================== 原有实现保持 ====================
    @staticmethod
    def _convert_doc(doc, source_path, image_placeholder, image_opts):
        img_dir = None
        image_dir_override = image_opts.get('image_dir_override')

        if image_dir_override:
            # 优先用 override 目录；MD 里用相对路径 assets/xxx.png
            img_dir = image_dir_override
            image_opts['md_path_prefix'] = 'assets'
        elif source_path:
            try:
                base_name = os.path.splitext(os.path.basename(source_path))[0]
                parent = os.path.dirname(os.path.abspath(source_path))
                img_dir = os.path.join(parent, f"{base_name}_images")
                # 默认场景：MD 里用绝对路径
                image_opts['md_path_prefix'] = ''
            except Exception:
                img_dir = None
                image_opts['md_path_prefix'] = ''

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
                image_placeholder, ordered_counters, image_opts
            )
            output_lines.append('')

        md_text = '\n'.join(output_lines)
        md_text = re.sub(r'\n{3,}', '\n\n', md_text)
        return md_text.strip() + '\n'

    @staticmethod
    def _is_bullet_char(c):
        ch = c['c']
        if ch in PdfImporter.TEXT_BULLET_CHARS:
            return True
        font = (c.get('font') or '').lower()
        if 'symbol' in font or 'wingding' in font:
            code = ord(ch)
            if 0xF000 <= code <= 0xF0FF:
                return True
        return False

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

    @staticmethod
    def _process_page(pd, size_to_level, body_size, threshold,
                      output_lines, img_dir, img_counter, img_dir_created,
                      image_placeholder, ordered_counters, image_opts):
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
                    img_dir_created, image_placeholder, image_opts
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

    @staticmethod
    def _split_by_all_bullets(line, line_bullets, size_to_level, body_size,
                              threshold, base_bullet_x, page_links):
        chars = line['chars']

        bullet_events = []
        for b in line_bullets:
            bullet_events.append((b['cx'], 'vector', b))
        for i, c in enumerate(chars):
            if PdfImporter._is_bullet_char(c):
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
                if ev[0] <= cx + 3:
                    best_gi = gi
                else:
                    break
            if best_gi is None:
                prefix_chars.append(c)
            else:
                groups[best_gi]['chars'].append(c)

        results = []

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

        for g in groups:
            ev = g['event']
            gc = g['chars']
            if not gc:
                continue

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

            checkbox = None
            if kind == 'vector':
                checkbox = PdfImporter._bullet_checkbox_state(obj, ''.join(c['c'] for c in gc))

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

    @staticmethod
    def _handle_image(item, img_dir, counter, img_dir_created, placeholder,
                      image_opts=None):
        """
        图片处理三模式（优先级从高到低）：
          1) data_url_mode=True   → 直接编码成 data URL 嵌入 Markdown
          2) img_dir 有效         → 落盘
          3) 其他                 → 返回 placeholder（[图片]）
        """
        image_opts = image_opts or {}
        data_url_mode = image_opts.get('data_url_mode', False)
        max_image_bytes = image_opts.get('max_image_bytes', 500 * 1024)
        max_total_bytes = image_opts.get('max_total_bytes', 20 * 1024 * 1024)
        total_acc = image_opts.get('total_bytes')
        md_path_prefix = image_opts.get('md_path_prefix', '')

        if data_url_mode:
            try:
                raw = item.get('image') or b''
                if not raw:
                    return placeholder
                if len(raw) > max_image_bytes:
                    return placeholder
                if total_acc is not None:
                    if total_acc[0] + len(raw) > max_total_bytes:
                        return placeholder
                    total_acc[0] += len(raw)
                ext = (item.get('ext') or 'png').lower()
                mime = PdfImporter.MIME_MAP.get(ext, 'image/png')
                b64 = base64.b64encode(raw).decode('ascii')
                return f'![图片](data:{mime};base64,{b64})'
            except Exception:
                return placeholder

        if img_dir:
            try:
                if not img_dir_created[0]:
                    os.makedirs(img_dir, exist_ok=True)
                    img_dir_created[0] = True
                ext = (item.get('ext') or 'png').lower()
                if ext not in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
                    ext = 'png'
                filename = f"image_{counter:03d}.{ext}"
                abs_path = os.path.join(img_dir, filename)
                with open(abs_path, 'wb') as f:
                    f.write(item['image'])

                if md_path_prefix:
                    return f"![]({md_path_prefix}/{filename})"
                return f"![]({abs_path})"
            except Exception:
                pass

        return placeholder

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