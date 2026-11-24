"""Чертёж как набор отдельных объектов (как в векторном редакторе).

Слои PDF (один длинный path на цвет) раскладываются на объекты-контуры, подписи — на текстовые объекты,
подписи-глифы (шрифт PDF контурами) — на группы глифов по словам. Каждый объект можно выделить, сдвинуть,
перекрасить, изменить узлы или удалить.

Объект (items[i]):
  {"id", "t": "path", "d", "stroke", "fill", "w", "dash"?}
  {"id", "t": "text", "x", "y", "a", "size", "text", "bold", "color"?}
  {"id", "t": "glyphs", "dx", "dy", "uses", "text", "color"?}   # uses — разметка <use>, шрифт — в data["defs"]
"""
import html
import re

_USE = re.compile(r'<use\b[^>]*?/>')
_MATRIX = re.compile(r'matrix\(([^)]*)\)')
_TEXT = re.compile(r'data-text="([^"]*)"')


def _subpaths(d: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?=M)", d) if p.strip()]


def _glyph_runs(glyphs: str) -> tuple[str, list[dict]]:
    """Разметка глифов → (defs, группы глифов по словам)."""
    m = re.search(r"<defs>(.*?)</defs>", glyphs, re.S)
    defs = m.group(1).strip() if m else ""
    body = glyphs[m.end():] if m else glyphs
    runs: list[dict] = []
    cur, last = None, None
    for el in re.finditer(r'<use\b[^>]*?/>|<path\b[^>]*?/>', body):
        tag = el.group(0)
        if tag.startswith("<path"):  # отдельные штрихи слоя подписей
            runs.append({"uses": tag, "text": ""})
            cur, last = None, None
            continue
        mt = _MATRIX.search(tag)
        nums = [float(v) for v in re.split(r"[ ,]+", mt.group(1).strip())] if mt else [1, 0, 0, 1, 0, 0]
        a, _, _, d, e, f = nums
        ch = _TEXT.search(tag)
        ch = ch.group(1) if ch else ""
        same = (last is not None and abs(last[0] - a) < 1e-6 and abs(last[1] - d) < 1e-6
                and abs(last[3] - f) < max(.3, abs(a) * .1) and 0 <= e - last[2] <= abs(a) * 1.6)
        if cur is None or not same:
            cur = {"uses": "", "text": ""}
            runs.append(cur)
        cur["uses"] += tag
        cur["text"] += ch
        last = (a, d, e, f)
    return defs, runs


def explode(data: dict) -> dict:
    """Перевести чертёж в объекты (если ещё не переведён). Пути, линии, светофоры не трогает."""
    if "items" in data:
        return data
    items, n = [], 0
    for layer in data.get("layers", []):
        for sub in _subpaths(layer.get("d", "")):
            n += 1
            items.append({"id": n, "t": "path", "d": sub, "stroke": layer.get("stroke", "var(--d-ink)"),
                          "fill": layer.get("fill", "none"), "w": layer.get("width") or 0})
    for x, y, a, size, text, bold in data.get("texts", []):
        n += 1
        items.append({"id": n, "t": "text", "x": x, "y": y, "a": a, "size": size, "text": text, "bold": bool(bold)})
    defs = ""
    if data.get("glyphs"):
        defs, runs = _glyph_runs(data["glyphs"])
        for r in runs:
            n += 1
            items.append({"id": n, "t": "glyphs", "dx": 0, "dy": 0, "uses": r["uses"], "text": html.unescape(r["text"])})
    out = {k: v for k, v in data.items() if k not in ("layers", "texts", "glyphs")}
    out["items"] = items
    out["defs"] = defs
    return out
