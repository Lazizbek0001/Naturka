"""Чертёж станции из векторного PDF: геометрия 1:1 (линии, стрелки, сигналы, здания) и подписи контурами глифов.

Общая версия генераторов tools/extract_*.py: без привязки путей — пути потом проводятся в редакторе чертежа.
"""
from collections import defaultdict
import re

import pymupdf


def _css(c):
    if c is None:
        return "none"
    r, g, b = c[:3]
    if r > 0.9 and g < 0.2:
        return "var(--d-main)"      # красные — главные пути
    if b > 0.8 and r < 0.1:
        return "var(--d-elec)"      # синие — электроизоляция
    if r > 0.99 and g > 0.99 and b > 0.99:
        return "var(--d-paper)"
    if r > 0.85 and g > 0.85:
        return "var(--d-build)"
    return "var(--d-ink)"


def _r(v):
    return round(v, 1)


def extract(pdf_bytes: bytes, page_no: int = 1, prefix: str = "d") -> dict:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if not 1 <= page_no <= len(doc):
        raise ValueError(f"В PDF {len(doc)} стр., страницы {page_no} нет")
    page = doc[page_no - 1]
    W, H = page.rect.width, page.rect.height

    groups = defaultdict(list)
    x0, y0, x1, y1 = W, H, 0.0, 0.0
    for d in page.get_drawings():
        rect = d["rect"]
        if rect.width > W * 0.85 and rect.height > H * 0.8 and len(d["items"]) <= 5:
            continue  # рамка листа
        key = (_css(d.get("color")), _css(d.get("fill")), round(d.get("width") or 0, 2))
        parts, last = [], None
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if last is None or abs(last.x - a.x) > 0.05 or abs(last.y - a.y) > 0.05:
                    parts.append(f"M{_r(a.x)} {_r(a.y)}")
                parts.append(f"L{_r(b.x)} {_r(b.y)}")
                last = b
            elif it[0] == "c":
                a, c1, c2, b = it[1:5]
                if last is None or abs(last.x - a.x) > 0.05 or abs(last.y - a.y) > 0.05:
                    parts.append(f"M{_r(a.x)} {_r(a.y)}")
                parts.append(f"C{_r(c1.x)} {_r(c1.y)} {_r(c2.x)} {_r(c2.y)} {_r(b.x)} {_r(b.y)}")
                last = b
            elif it[0] == "re":
                q = it[1]
                parts.append(f"M{_r(q.x0)} {_r(q.y0)}H{_r(q.x1)}V{_r(q.y1)}H{_r(q.x0)}Z")
                last = None
            elif it[0] == "qu":
                q = it[1]
                parts.append(f"M{_r(q.ul.x)} {_r(q.ul.y)}L{_r(q.ur.x)} {_r(q.ur.y)}L{_r(q.lr.x)} {_r(q.lr.y)}L{_r(q.ll.x)} {_r(q.ll.y)}Z")
                last = None
        if not parts:
            continue
        if d.get("closePath"):
            parts.append("Z")
        groups[key].append("".join(parts))
        x0, y0 = min(x0, rect.x0), min(y0, rect.y0)
        x1, y1 = max(x1, rect.x1), max(y1, rect.y1)

    layers = [{"stroke": s, "fill": f, "width": w, "d": "".join(p)} for (s, f, w), p in groups.items()]
    layers.sort(key=lambda l: (l["fill"] != "none", l["stroke"] == "var(--d-main)"))

    # подписи — контурами глифов: так сохраняются и шрифты без юникода (кириллица в старых PDF)
    tdoc = pymupdf.open()
    tdoc.insert_pdf(doc, from_page=page_no - 1, to_page=page_no - 1)
    tp = tdoc[0]
    tp.add_redact_annot(tp.rect)
    tp.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
                        graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                        text=pymupdf.PDF_REDACT_TEXT_NONE)
    svg = tp.get_svg_image(text_as_path=True)
    inner = svg[svg.index(">", svg.index("<svg")) + 1: svg.rindex("</svg>")]
    inner = re.sub(r'fill="#[0-9a-fA-F]{6}"', 'fill="currentColor"', inner)
    inner = inner.replace('id="font_', f'id="{prefix}_font_').replace('href="#font_', f'href="#{prefix}_font_')
    inner = re.sub(r"\s+", " ", inner)
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") == 0:
            bx0, by0, bx1, by1 = b["bbox"]
            x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)

    if x1 <= x0:
        raise ValueError("На странице нет векторной графики (возможно, это скан-картинка)")
    pad = 10
    view = [_r(max(0, x0 - pad)), _r(max(0, y0 - pad)), _r(min(W, x1 + pad) - max(0, x0 - pad)), _r(min(H, y1 + pad) - max(0, y0 - pad))]
    return {"view": view, "layers": layers, "glyphs": inner, "tracks": {}, "pages": len(doc)}
