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
    run._element.rPr.rFonts.set(qn("w:eastAsia"), family)
    run.font.size = _pt(size_pt)
    run.bold = bool(bold)
    run.italic = bool(italic)
    run.underline = bool(underline)


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


def _add_text_paragraph(doc: Document, text: str, style_key: str, cfg: Dict[str, Any]):
    fonts = cfg.get("fonts", {})
    p_cfg = cfg.get("paragraph", {})
    font_cfg = fonts.get(style_key) or fonts.get("body") or {"family": "宋体", "size_pt": 11, "bold": False}

    if style_key == "title":
        p = doc.add_paragraph(style="Title")
    elif style_key == "h1":
        p = doc.add_paragraph(style="Heading 1")
    elif style_key == "h2":
        p = doc.add_paragraph(style="Heading 2")
    elif style_key == "h3":
        p = doc.add_paragraph(style="Heading 3")
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
            if lv == 1:
                blocks.append(("title", text, 1))
            else:
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


# ---------------------------
# 导出前：按章节语义注入占位符
# ---------------------------

def _collect_dimension_anchors(lines: List[str]) -> Dict[str, int]:
    anchors: Dict[str, int] = {}
    patterns = {
        "genre": [r"\bgenre\b", r"流派"],
        "artist": [r"\bartist\b", r"艺术家"],
        "country": [r"\bcountry\b", r"国家"],
        "city": [r"\bcity\b", r"城市"],
        "customer": [r"\bcustomer\b", r"客户"],
        "employee": [r"\bemployee\b", r"员工"],
    }
    for i, raw in enumerate(lines):
        t = (raw or "").strip().lower()
        if not t:
            continue
        for dim, pats in patterns.items():
            if dim in anchors:
                continue
            for p in pats:
                if re.search(p, t, flags=re.IGNORECASE):
                    anchors[dim] = i
                    break
    return anchors


def inject_placeholders_by_sections(
    markdown_text: str,
    images: Dict[str, str] | None
) -> Tuple[str, Dict[str, Any]]:
    """
    返回: (注入后的markdown, debug信息)
    """
    debug: Dict[str, Any] = {
        "anchors": {},
        "inserted": [],
        "existing_placeholders": [],
        "unmatched_to_appendix": [],
        "input_image_keys": [],
        "final_image_keys": []
    }

    if not markdown_text:
        return markdown_text or "", debug
    if not images:
        return markdown_text, debug

    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    keys = [k for k, v in (images or {}).items() if v]
    debug["input_image_keys"] = list(keys)

    existing: Set[str] = set()
    for ln in lines:
        found = re.findall(r"\{\{image:([a-zA-Z0-9_\-\u4e00-\u9fa5]+)\}\}", ln or "")
        for x in found:
            existing.add(x)
    debug["existing_placeholders"] = sorted(existing)

    keys = [k for k in keys if k not in existing]
    debug["final_image_keys"] = list(keys)
    if not keys:
        return "\n".join(lines), debug

    def key_dim(k: str) -> Optional[str]:
        kk = (k or "").lower()
        if "genre" in kk or "流派" in kk:
            return "genre"
        if "artist" in kk or "艺术家" in kk:
            return "artist"
        if "country" in kk or "国家" in kk:
            return "country"
        if "city" in kk or "城市" in kk:
            return "city"
        if "customer" in kk or "客户" in kk:
            return "customer"
        if "employee" in kk or "员工" in kk:
            return "employee"
        return None

    def is_total(k: str) -> bool:
        kk = (k or "").lower()
        return ("总量" in kk) or ("total" in kk)

    def sort_chart_keys(ks: List[str]) -> List[str]:
        def score(x: str):
            xx = x.lower()
            if "趋势" in xx or "line" in xx:
                return 1
            if "柱状图" in xx or "bar" in xx:
                return 2
            if "饼图" in xx or "pie" in xx:
                return 3
            return 9
        return sorted(ks, key=lambda s: (score(s), s))

    overview_idx = 0
    overview_title = "文档开头"
    for i, ln in enumerate(lines):
        tt = (ln or "").strip()
        if any(x in tt for x in ["一、概览", "概览", "核心指标", "数据事实", "概述"]):
            overview_idx = i
            overview_title = tt[:50]
            break

    dim_anchors = _collect_dimension_anchors(lines)

    debug["anchors"] = {
        "overview": {"line": overview_idx + 1, "title": overview_title},
        "dimensions": {
            d: {"line": idx + 1, "title": (lines[idx].strip() if 0 <= idx < len(lines) else "")}
            for d, idx in dim_anchors.items()
        }
    }

    inserts: List[Tuple[int, str, str, str]] = []
    placed: Set[str] = set()

    for k in sort_chart_keys([x for x in keys if is_total(x)]):
        inserts.append((overview_idx, k, f"{{{{image:{k}}}}}", "overview"))
        placed.add(k)

    for dim in ["genre", "artist", "country", "city", "customer", "employee"]:
        anchor = dim_anchors.get(dim, -1)
        dkeys = sort_chart_keys([x for x in keys if key_dim(x) == dim and x not in placed])
        if anchor >= 0:
            for k in dkeys:
                inserts.append((anchor, k, f"{{{{image:{k}}}}}", f"dimension:{dim}"))
                placed.add(k)

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

    remain = [k for k in keys if k not in placed]
    if remain:
        lines.append("")
        lines.append("## 附录：图表")
        appendix_header_line = len(lines)
        for k in sort_chart_keys(remain):
            lines.append(f"{{{{image:{k}}}}}")
            debug["inserted"].append({
                "key": k,
                "section": "appendix",
                "insert_after_line": appendix_header_line,
                "actual_placeholder_line": len(lines)
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
            if lv <= 2:
                key = "h1"
            elif lv == 3:
                key = "h2"
            else:
                key = "h3"
            _add_text_paragraph(doc, text, key, template_cfg)
        elif typ == "ul":
            _add_text_paragraph(doc, f"• {text}", "body", template_cfg)
        elif typ == "ol":
            _add_text_paragraph(doc, text, "body", template_cfg)
        else:
            _add_text_paragraph(doc, text, "body", template_cfg)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_export_filename(prefix: str = "报告", ext: str = "docx") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{_safe_filename(prefix)}_{ts}.{ext}"