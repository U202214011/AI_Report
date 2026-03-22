from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional, Set
import os
import re
import json
import base64
from io import BytesIO
from datetime import datetime

from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "export_templates")

# ---- markdown block parse ----
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)$')
_UL_RE = re.compile(r'^\s*[-*]\s+(.*)$')
_OL_RE = re.compile(r'^\s*\d+\.\s+(.*)$')

# ---- inline markdown ----
_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_ITALIC_RE = re.compile(r'\*(.+?)\*')
_UNDERLINE_RE = re.compile(r'__(.+?)__')

# ---- image placeholder ----
_IMAGE_PLACEHOLDER_FULL_RE = re.compile(
    r'^\s*\{\{image:([a-zA-Z0-9_\-\u4e00-\u9fa5]+)\}\}\s*$'
)
_IMAGE_PLACEHOLDER_INLINE_RE = re.compile(
    r'\{\{image:([a-zA-Z0-9_\-\u4e00-\u9fa5]+)\}\}'
)

_BULLET_CHAR = "\u2022"


def _safe_filename(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]+', "_", name or "")
    s = s.strip() or "report"
    return s


def _cm(v: float) -> Cm:
    return Cm(float(v))


def _pt(v: float) -> Pt:
    return Pt(float(v))


def list_export_templates() -> List[Dict[str, Any]]:
    """
    读取 export_templates/*.json 的模板元信息。
    """
    out: List[Dict[str, Any]] = []
    if not os.path.exists(TEMPLATE_DIR):
        return out

    for fn in os.listdir(TEMPLATE_DIR):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(TEMPLATE_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            out.append({
                "id": cfg.get("id") or os.path.splitext(fn)[0],
                "name": cfg.get("name") or os.path.splitext(fn)[0],
                "description": cfg.get("description", ""),
                "file": fn
            })
        except Exception:
            continue
    return sorted(out, key=lambda x: x["id"])


def load_template_config(template_id: str | None) -> Dict[str, Any]:
    """
    template_id -> export_templates/{template_id}.json
    """
    if not template_id:
        template_id = "cn_management_a4"

    path = os.path.join(TEMPLATE_DIR, f"{template_id}.json")
    if not os.path.exists(path):
        # fallback
        path = os.path.join(TEMPLATE_DIR, "cn_management_a4.json")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _set_run_font(run, family: str, size_pt: float, bold: bool = False, italic: bool = False, underline: bool = False):
    run.font.name = family
    # Ensure East Asia (CJK) font is also set so Chinese characters render correctly
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), family)
    rFonts.set(qn("w:hAnsi"), family)
    run.font.size = _pt(size_pt)
    run.bold = bool(bold)
    run.italic = bool(italic)
    run.underline = bool(underline)


_ALIGNMENT_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


def _apply_paragraph_style(paragraph, p_cfg: Dict[str, Any]):
    line_spacing = float(p_cfg.get("line_spacing", 1.5))
    before = float(p_cfg.get("space_before_pt", 4))
    after = float(p_cfg.get("space_after_pt", 6))
    indent_chars = int(p_cfg.get("first_line_indent_chars", 0))

    pf = paragraph.paragraph_format
    pf.line_spacing = line_spacing
    pf.space_before = _pt(before)
    pf.space_after = _pt(after)
    if indent_chars > 0:
        pf.first_line_indent = _pt(indent_chars * 11)

    alignment = p_cfg.get("alignment")
    if alignment and alignment in _ALIGNMENT_MAP:
        pf.alignment = _ALIGNMENT_MAP[alignment]

    keep_with_next = p_cfg.get("keep_with_next")
    if keep_with_next is not None:
        pf.keep_with_next = bool(keep_with_next)

    keep_together = p_cfg.get("keep_together")
    if keep_together is not None:
        pf.keep_together = bool(keep_together)


def _split_inline_markdown(text: str) -> List[Tuple[str, bool, bool, bool]]:
    """
    将文本拆成 (content, bold, italic, underline) 片段
    支持 **bold** 、 *italic* 、 __underline__
    不支持嵌套
    """
    if not text:
        return [("", False, False, False)]

    parts: List[Tuple[str, bool, bool, bool]] = []
    i = 0
    while i < len(text):
        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end != -1:
                parts.append((text[i + 2:end], True, False, False))
                i = end + 2
                continue

        if text.startswith("__", i):
            end = text.find("__", i + 2)
            if end != -1:
                parts.append((text[i + 2:end], False, False, True))
                i = end + 2
                continue

        if text.startswith("*", i):
            end = text.find("*", i + 1)
            if end != -1:
                parts.append((text[i + 1:end], False, True, False))
                i = end + 1
                continue

        next_special = min(
            [p for p in [text.find("**", i), text.find("__", i), text.find("*", i)] if p != -1] or [len(text)]
        )
        parts.append((text[i:next_special], False, False, False))
        i = next_special

    return parts


def _get_para_cfg(style_key: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return paragraph style config for *style_key*.
    Looks in ``paragraph_styles.<style_key>`` first, then falls back to the
    legacy ``paragraph`` block so older templates still work.
    """
    para_styles = cfg.get("paragraph_styles", {})
    if style_key in para_styles:
        return para_styles[style_key]
    # legacy fallback
    return cfg.get("paragraph", {})


def _add_text_paragraph(doc: Document, text: str, style_key: str, cfg: Dict[str, Any]):
    fonts = cfg.get("fonts", {})
    p_cfg = _get_para_cfg(style_key, cfg)
    font_cfg = fonts.get(style_key) or fonts.get("body") or {"family": "宋体", "size_pt": 11, "bold": False}

    # Map style_key to the appropriate Word built-in style
    _WORD_STYLE_MAP = {
        "title": "Title",
        "h1": "Heading 1",
        "h2": "Heading 2",
        "h3": "Heading 3",
        "h4": "Heading 4",
        "h5": "Heading 5",
        "h6": "Heading 6",
    }
    word_style = _WORD_STYLE_MAP.get(style_key)
    if word_style:
        try:
            p = doc.add_paragraph(style=word_style)
        except KeyError:
            # The built-in style may not exist in the blank document template;
            # fall back gracefully to an unstyled paragraph.
            p = doc.add_paragraph()
    else:
        p = doc.add_paragraph()

    _apply_paragraph_style(p, p_cfg)

    for seg, is_bold, is_italic, is_underline in _split_inline_markdown(text):
        if seg == "":
            continue
        run = p.add_run(seg)
        _set_run_font(
            run,
            family=font_cfg.get("family", "宋体"),
            size_pt=float(font_cfg.get("size_pt", 11)),
            bold=is_bold or bool(font_cfg.get("bold", False)),
            italic=is_italic,
            underline=is_underline
        )
    return p


def _parse_markdown_lines(md_text: str) -> List[Tuple[str, str, int]]:
    """
    返回 [(type, text, level)]
    type: title|heading|ul|ol|p|blank
    level: heading level or 0
    """
    lines = (md_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Tuple[str, str, int]] = []

    for raw in lines:
        line = raw.strip()

        if not line:
            blocks.append(("blank", "", 0))
            continue

        hm = _HEADING_RE.match(line)
        if hm:
            lv = len(hm.group(1))
            text = hm.group(2).strip()
            blocks.append(("heading", text, lv))
            continue

        um = _UL_RE.match(raw)
        if um:
            blocks.append(("ul", um.group(1).strip(), 0))
            continue

        om = _OL_RE.match(raw)
        if om:
            blocks.append(("ol", om.group(0).strip(), 0))
            continue

        blocks.append(("p", raw.strip(), 0))

    return blocks


def _set_page_layout(doc: Document, cfg: Dict[str, Any]):
    page = cfg.get("page", {})
    margins = page.get("margin_cm", [2.5, 2.2, 2.5, 2.2])  # top,right,bottom,left
    if len(margins) != 4:
        margins = [2.5, 2.2, 2.5, 2.2]

    sec = doc.sections[0]
    sec.top_margin = _cm(margins[0])
    sec.right_margin = _cm(margins[1])
    sec.bottom_margin = _cm(margins[2])
    sec.left_margin = _cm(margins[3])


def _add_image_block(doc: Document, image_bytes: bytes, cfg: Dict[str, Any]):
    img_cfg = cfg.get("image", {})
    width_cm = float(img_cfg.get("max_width_cm", 16))
    p = doc.add_paragraph()
    run = p.add_run()
    run.add_picture(BytesIO(image_bytes), width=_cm(width_cm))


def _decode_base64_image(b64: str) -> Optional[bytes]:
    if not b64:
        return None
    if "," in b64 and "base64" in b64.split(",")[0]:
        b64 = b64.split(",", 1)[1]
    try:
        return base64.b64decode(b64)
    except Exception:
        return None

# 先在 import 行补充:
# from typing import Dict, Any, List, Tuple, Optional, Set
# 已有，无需额外改 typing

# 在 _decode_base64_image 下方，新增以下辅助函数

_HEADING_LINE_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*$')

_DIMENSION_ALIAS_DEFAULT: Dict[str, List[str]] = {
    "genre": ["genre", "流派", "音乐流派"],
    "artist": ["artist", "艺术家"],
    "country": ["country", "国家"],
    "city": ["city", "城市"],
    "customer": ["customer", "客户"],
    "employee": ["employee", "员工"]
}

_DIMENSION_TITLE_DEFAULT: Dict[str, str] = {
    "genre": "流派",
    "artist": "艺术家",
    "country": "国家",
    "city": "城市",
    "customer": "客户",
    "employee": "员工"
}


def _normalize_text_compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _parse_headings(lines: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(lines):
        m = _HEADING_LINE_RE.match((raw or "").strip())
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        out.append({
            "line_index": i,
            "level": level,
            "text": text,
            "norm": _normalize_text_compact(text)
        })
    return out


def _build_dimension_maps(
    selected_dimensions: Optional[List[Dict[str, Any]]]
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    返回:
    - dim_key -> 标题中文
    - dim_key -> aliases
    """
    if not selected_dimensions:
        return dict(_DIMENSION_TITLE_DEFAULT), dict(_DIMENSION_ALIAS_DEFAULT)

    title_map: Dict[str, str] = {}
    alias_map: Dict[str, List[str]] = {}

    for item in selected_dimensions:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip().lower()
        t = str(item.get("title") or "").strip()
        aliases = item.get("aliases") or []

        if not k:
            continue
        if not t:
            t = _DIMENSION_TITLE_DEFAULT.get(k, k)

        alias_list = [k, t] + [str(a).strip() for a in aliases if str(a).strip()]
        # 合并默认别名
        alias_list += _DIMENSION_ALIAS_DEFAULT.get(k, [])
        # 去重
        seen = set()
        cleaned = []
        for a in alias_list:
            aa = a.lower()
            if aa in seen:
                continue
            seen.add(aa)
            cleaned.append(a)

        title_map[k] = t
        alias_map[k] = cleaned

    return title_map, alias_map


def _find_main_sections(headings: List[Dict[str, Any]], total_lines: int) -> Dict[str, Dict[str, Any]]:
    """
    识别一级标题分段:
    overview/findings/cause/advice
    """
    seq: List[Tuple[str, int, str]] = []
    for h in headings:
        if h["level"] != 1:
            continue
        n = h["norm"]
        if n == "概览":
            seq.append(("overview", h["line_index"], h["text"]))
        elif n == "维度关键发现":
            seq.append(("findings", h["line_index"], h["text"]))
        elif n == "原因分析":
            seq.append(("cause", h["line_index"], h["text"]))
        elif n == "建议":
            seq.append(("advice", h["line_index"], h["text"]))

    result: Dict[str, Dict[str, Any]] = {}
    for i, (name, start, title) in enumerate(seq):
        end = total_lines - 1
        if i + 1 < len(seq):
            end = seq[i + 1][1] - 1
        result[name] = {"start": start, "end": end, "title": title}
    return result


def _find_dimension_sections_in_findings(
    headings: List[Dict[str, Any]],
    findings_start: int,
    findings_end: int,
    dim_title_map: Dict[str, str]
) -> Dict[str, Dict[str, Any]]:
    """
    在 # 维度关键发现 范围内，只识别 level=2 的维度标题
    """
    title_to_dim = {_normalize_text_compact(v): k for k, v in dim_title_map.items()}
    found: List[Tuple[str, int, str]] = []

    for h in headings:
        if h["level"] != 2:
            continue
        if not (findings_start <= h["line_index"] <= findings_end):
            continue
        dim = title_to_dim.get(h["norm"])
        if not dim:
            continue
        found.append((dim, h["line_index"], h["text"]))

    result: Dict[str, Dict[str, Any]] = {}
    for i, (dim, start, title) in enumerate(found):
        end = findings_end
        if i + 1 < len(found):
            end = found[i + 1][1] - 1
        result[dim] = {"start": start, "end": end, "title": title}
    return result


def _chart_rank_for_insert(key: str) -> int:
    """
    你的需求：总量柱状图与折线图优先
    排序: bar -> line -> pie -> other
    """
    k = (key or "").lower()
    if ("bar" in k) or ("柱状" in k):
        return 1
    if ("line" in k) or ("趋势" in k) or ("折线" in k):
        return 2
    if ("pie" in k) or ("饼" in k):
        return 3
    return 9


def _is_overview_chart_key(key: str) -> bool:
    k = (key or "").lower()
    return any(x in k for x in ["total", "总量", "overview", "summary", "概览", "总体"])


def _infer_dim_from_key(key: str, dim_alias_map: Dict[str, List[str]]) -> Optional[str]:
    k = (key or "").lower()
    for dim, aliases in dim_alias_map.items():
        for a in aliases:
            if str(a).lower() in k:
                return dim
    return None


def inject_placeholders_by_sections(
    markdown_text: str,
    images: Dict[str, str] | None,
    selected_dimensions: Optional[List[Dict[str, Any]]] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    按 markdown 标题层级注入占位符（稳定版）：
    - 总量柱状图/折线图 -> # 概览
    - 维度图 -> # 维度关键发现 下对应 ## 维度标题
    - 未匹配 -> 附录

    selected_dimensions:
    [
      {"key":"artist","title":"艺术家","aliases":["artist","艺术家"]},
      ...
    ]
    """
    debug: Dict[str, Any] = {
        "main_sections": {},
        "dimension_sections": {},
        "inserted": [],
        "existing_placeholders": [],
        "unmatched_to_appendix": [],
        "input_image_keys": [],
        "final_image_keys": [],
        "selected_dimensions": selected_dimensions or []
    }

    if not markdown_text:
        return markdown_text or "", debug
    if not images:
        return markdown_text, debug

    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    keys = [k for k, v in (images or {}).items() if v]
    debug["input_image_keys"] = list(keys)

    # 已存在占位符去重
    existing: Set[str] = set()
    for ln in lines:
        found = re.findall(r"\{\{image:([a-zA-Z0-9_\-\u4e00-\u9fa5]+)\}\}", ln or "")
        existing.update(found)
    debug["existing_placeholders"] = sorted(existing)

    keys = [k for k in keys if k not in existing]
    debug["final_image_keys"] = list(keys)
    if not keys:
        return "\n".join(lines), debug

    # 维度映射（动态）
    dim_title_map, dim_alias_map = _build_dimension_maps(selected_dimensions)

    # 解析标题结构
    headings = _parse_headings(lines)
    main_sections = _find_main_sections(headings, len(lines))
    debug["main_sections"] = main_sections

    dim_sections: Dict[str, Dict[str, Any]] = {}
    findings_sec = main_sections.get("findings")
    if findings_sec:
        dim_sections = _find_dimension_sections_in_findings(
            headings=headings,
            findings_start=findings_sec["start"],
            findings_end=findings_sec["end"],
            dim_title_map=dim_title_map
        )
    debug["dimension_sections"] = dim_sections

    # 分类图片
    overview_keys: List[str] = []
    dim_groups: Dict[str, List[str]] = {}
    remain_keys: List[str] = []

    for k in keys:
        if _is_overview_chart_key(k):
            overview_keys.append(k)
            continue
        dim = _infer_dim_from_key(k, dim_alias_map)
        if dim:
            dim_groups.setdefault(dim, []).append(k)
        else:
            remain_keys.append(k)

    overview_keys = sorted(overview_keys, key=lambda x: (_chart_rank_for_insert(x), x))
    for d in list(dim_groups.keys()):
        dim_groups[d] = sorted(dim_groups[d], key=lambda x: (_chart_rank_for_insert(x), x))

    # 构建插入计划 (insert_after_line_index, key, placeholder, section)
    inserts: List[Tuple[int, str, str, str]] = []
    placed: Set[str] = set()

    # 1) 概览插图
    if overview_keys and "overview" in main_sections:
        anchor = main_sections["overview"]["start"]
        for k in overview_keys:
            inserts.append((anchor, k, f"{{{{image:{k}}}}}", "overview"))
            placed.add(k)
    else:
        # 找不到概览则暂放 remain
        for k in overview_keys:
            remain_keys.append(k)

    # 2) 维度插图（必须能匹配到对应 ## 维度标题）
    for dim, ks in dim_groups.items():
        sec = dim_sections.get(dim)
        if not sec:
            remain_keys.extend(ks)
            continue
        anchor = sec["start"]
        for k in ks:
            inserts.append((anchor, k, f"{{{{image:{k}}}}}", f"dimension:{dim}"))
            placed.add(k)

    # 3) 执行插入（按 anchor 升序 + offset）
    offset = 0
    for idx, key, ph, section in sorted(inserts, key=lambda it: it[0]):
        pos = idx + 1 + offset
        lines.insert(pos, "")
        lines.insert(pos + 1, ph)
        lines.insert(pos + 2, "")
        debug["inserted"].append({
            "key": key,
            "section": section,
            "insert_after_line": idx + 1,
            "actual_placeholder_line": pos + 2
        })
        offset += 3

    # 4) 兜底附录
    true_remain = [k for k in keys if k not in placed]
    if true_remain:
        lines.append("")
        lines.append("# 附录：图表")
        appendix_header_line = len(lines)
        for k in sorted(true_remain, key=lambda x: (_chart_rank_for_insert(x), x)):
            lines.append("")
            lines.append(f"{{{{image:{k}}}}}")
            lines.append("")
            debug["inserted"].append({
                "key": k,
                "section": "appendix",
                "insert_after_line": appendix_header_line,
                "actual_placeholder_line": len(lines) - 1
            })
            debug["unmatched_to_appendix"].append(k)

    return "\n".join(lines), debug

# ---------------------------
# markdown -> docx
# ---------------------------

def render_markdown_to_docx_bytes(
    markdown_text: str,
    template_cfg: Dict[str, Any],
    report_title: str | None = None,
    images: Dict[str, str] | None = None
) -> bytes:
    """
    images: {key: base64} 的图像映射
    """
    doc = Document()
    _set_page_layout(doc, template_cfg)

    if report_title:
        _add_text_paragraph(doc, report_title, "title", template_cfg)

    blocks = _parse_markdown_lines(markdown_text)

    for typ, text, lv in blocks:
        if typ == "blank":
            doc.add_paragraph("")
            continue

        if typ == "p":
            # 1) 整行占位符
            full = _IMAGE_PLACEHOLDER_FULL_RE.match(text)
            if full and images:
                key = full.group(1)
                img_b64 = images.get(key)
                img_bytes = _decode_base64_image(img_b64) if img_b64 else None
                if img_bytes:
                    _add_image_block(doc, img_bytes, template_cfg)
                    continue

            # 2) 段内占位符
            if images and _IMAGE_PLACEHOLDER_INLINE_RE.search(text or ""):
                last = 0
                for mm in _IMAGE_PLACEHOLDER_INLINE_RE.finditer(text):
                    start, end = mm.span()
                    key = mm.group(1)

                    before = text[last:start].strip()
                    if before:
                        _add_text_paragraph(doc, before, "body", template_cfg)

                    img_b64 = images.get(key)
                    img_bytes = _decode_base64_image(img_b64) if img_b64 else None
                    if img_bytes:
                        _add_image_block(doc, img_bytes, template_cfg)
                    else:
                        _add_text_paragraph(doc, f"{{{{image:{key}}}}}", "body", template_cfg)

                    last = end

                tail = text[last:].strip()
                if tail:
                    _add_text_paragraph(doc, tail, "body", template_cfg)
                continue

        if typ == "title":
            _add_text_paragraph(doc, text, "title", template_cfg)
        elif typ == "heading":
            if lv == 1:
                key = "h1"
            elif lv == 2:
                key = "h2"
            elif lv == 3:
                key = "h3"
            elif lv == 4:
                key = "h4"
            elif lv == 5:
                key = "h5"
            else:
                key = "h6"
            _add_text_paragraph(doc, text, key, template_cfg)
        elif typ == "ul":
            _add_text_paragraph(doc, f"{_BULLET_CHAR} {text}", "list", template_cfg)
        elif typ == "ol":
            _add_text_paragraph(doc, text, "list", template_cfg)
        else:
            _add_text_paragraph(doc, text, "body", template_cfg)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_export_filename(prefix: str = "报告", ext: str = "docx") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{_safe_filename(prefix)}_{ts}.{ext}"