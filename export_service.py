from __future__ import annotations

from typing import Dict, Any, List, Tuple
import os
import re
import json
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
    # 中文两字符缩进粗略按 2*字体大小换算，这里按 2*11pt 兜底
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

    # Word 标题样式映射
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

    # 行内 markdown 处理
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


def render_markdown_to_docx_bytes(
    markdown_text: str,
    template_cfg: Dict[str, Any],
    report_title: str | None = None,
    images: List[bytes] | None = None
) -> bytes:
    """
    images: 预留参数，可传入二进制图片列表，后续扩展插入逻辑
    """
    doc = Document()
    _set_page_layout(doc, template_cfg)

    if report_title:
        _add_text_paragraph(doc, report_title, "title", template_cfg)

    blocks = _parse_markdown_lines(markdown_text)

    for typ, text, lv in blocks:
        if typ == "blank":
            # 空行：加一个空段落（更可控）
            doc.add_paragraph("")
            continue

        if typ == "title":
            _add_text_paragraph(doc, text, "title", template_cfg)
        elif typ == "heading":
            # h2->h1, h3->h2, h4+->h3
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

    # ✅ 预留：未来插入图片（从 plots 或其他来源）
    # if images:
    #     for img_bytes in images:
    #         doc.add_picture(BytesIO(img_bytes))

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_export_filename(prefix: str = "报告", ext: str = "docx") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{_safe_filename(prefix)}_{ts}.{ext}"