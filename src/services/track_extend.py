"""Путь на чертеже — по всей линии, а не по кусочку.

Путь привязывается к чертежу ломаной (tracks[code].pts). Если её провели не по всей линии (например, от номера
пути до конца), подсветка и составы занимают только часть линии. Здесь ломаная пути заменяется на всю линию
чертежа, по которой он идёт: находим контур (объект-path), на котором лежит ломаная, и берём его целиком.
"""
import math
import re

TOL = 2.5      # насколько точка пути может отстоять от линии чертежа (в единицах чертежа)
STEP = 4.0     # шаг проверки точек вдоль пути


def flatten(d: str) -> list[list[list[float]]]:
    """Контур → список ломаных (по одной на M), кривые — 8 отрезками."""
    tok = re.findall(r"[MLHVCZ]|-?\d*\.?\d+(?:e-?\d+)?", d, re.I)
    polys, cur, i, cmd = [], None, 0, "M"
    cx = cy = 0.0

    def num():
        nonlocal i
        i += 1
        return float(tok[i - 1])
    while i < len(tok):
        if re.fullmatch(r"[MLHVCZ]", tok[i], re.I):
            cmd = tok[i].upper()
            i += 1
        if cmd == "M":
            cx, cy = num(), num()
            cur = [[cx, cy]]
            polys.append(cur)
            cmd = "L"
        elif cmd == "L":
            cx, cy = num(), num(); cur.append([cx, cy])
        elif cmd == "H":
            cx = num(); cur.append([cx, cy])
        elif cmd == "V":
            cy = num(); cur.append([cx, cy])
        elif cmd == "C":
            x1, y1, x2, y2, x, y = (num() for _ in range(6))
            for s in range(1, 9):
                t = s / 8; u = 1 - t
                cur.append([u ** 3 * cx + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x,
                            u ** 3 * cy + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y])
            cx, cy = x, y
        elif cmd == "Z":
            if cur:
                cur.append(list(cur[0]))
        else:
            i += 1
    return [p for p in polys if len(p) >= 2]


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0 if not L2 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def poly_dist(p, poly):
    return min(_seg_dist(p, poly[k - 1], poly[k]) for k in range(1, len(poly)))


def poly_len(poly):
    return sum(math.hypot(poly[k][0] - poly[k - 1][0], poly[k][1] - poly[k - 1][1]) for k in range(1, len(poly)))


def samples(pts):
    out = [pts[0]]
    for k in range(1, len(pts)):
        a, b = pts[k - 1], pts[k]
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / STEP))
        out += [[a[0] + (b[0] - a[0]) * s / n, a[1] + (b[1] - a[1]) * s / n] for s in range(1, n + 1)]
    return out


def _bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def candidates(data: dict):
    """Все ломаные контуров чертежа (без заливки — заливка это здания, знаки)."""
    out = []
    for it in data.get("items", []):
        if it.get("t") == "path" and (it.get("fill") in (None, "none")) and it.get("stroke") not in (None, "none"):
            for poly in flatten(it["d"]):
                out.append((poly, _bbox(poly)))
    for ln in data.get("lines", []):
        out.append((ln["pts"], _bbox(ln["pts"])))
    return out


def _cum(poly):
    c = [0.0]
    for k in range(1, len(poly)):
        c.append(c[-1] + math.hypot(poly[k][0] - poly[k - 1][0], poly[k][1] - poly[k - 1][1]))
    return c


def project(p, poly, cum):
    """Расстояние вдоль ломаной до ближайшей к p точки и само расстояние до неё."""
    best = (float("inf"), 0.0)
    for k in range(1, len(poly)):
        a, b = poly[k - 1], poly[k]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0 if not L2 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        d = math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])
        if d < best[0]:
            best = (d, cum[k - 1] + t * (cum[k] - cum[k - 1]))
    return best[1], best[0]


def cut(poly, cum, s0, s1):
    """Кусок ломаной от s0 до s1 (по длине)."""
    def at(s):
        for k in range(1, len(poly)):
            if cum[k] >= s or k == len(poly) - 1:
                L = cum[k] - cum[k - 1] or 1
                t = max(0, min(1, (s - cum[k - 1]) / L))
                return [poly[k - 1][0] + (poly[k][0] - poly[k - 1][0]) * t, poly[k - 1][1] + (poly[k][1] - poly[k - 1][1]) * t]
    out = [at(s0)] + [list(poly[k]) for k in range(len(poly)) if s0 < cum[k] < s1] + [at(s1)]
    return [[round(x, 1), round(y, 1)] for x, y in out]


def _tangent(poly, cum, s):
    for k in range(1, len(poly)):
        if cum[k] >= s or k == len(poly) - 1:
            return math.atan2(poly[k][1] - poly[k - 1][1], poly[k][0] - poly[k - 1][0])
    return 0.0


def junctions(poly, cum, cands, me):
    """Стрелки на линии: места, где от неё под острым углом отходит другая длинная линия."""
    out = []
    x0, y0, x1, y1 = _bbox(poly)
    for q, (a, b, c, d) in cands:
        if q is me or c < x0 - TOL or a > x1 + TOL or d < y0 - TOL or b > y1 + TOL or poly_len(q) < 40:
            continue
        for end, nxt in ((q[0], q[1]), (q[-1], q[-2])):
            s, dist = project(end, poly, cum)
            if dist > TOL or s < 1 or s > cum[-1] - 1:
                continue
            ang = abs(math.atan2(nxt[1] - end[1], nxt[0] - end[0]) - _tangent(poly, cum, s)) % math.pi
            if min(ang, math.pi - ang) < math.radians(35):
                out.append(s)
    return out


def extend(pts: list, cands, others=()) -> list | None:
    """Ломаная пути → линия чертежа под ней от стрелки до стрелки (или до соседнего пути на той же линии)."""
    sm = samples(pts)
    x0, y0, x1, y1 = _bbox(pts)
    best = None
    for poly, (a, b, c, d) in cands:
        if c < x0 - TOL or a > x1 + TOL or d < y0 - TOL or b > y1 + TOL:
            continue
        on = sum(1 for p in sm if poly_dist(p, poly) <= TOL)
        if on / len(sm) >= 0.9 and (best is None or on > best[0] or (on == best[0] and poly_len(poly) < poly_len(best[1]))):
            best = (on, poly)
    if best is None:
        return None
    poly = best[1]
    cum = _cum(poly)
    proj = [project(p, poly, cum)[0] for p in sm]
    s0, s1 = min(proj), max(proj)
    stops = junctions(poly, cum, cands, poly)
    for o in others:  # соседние пути на той же линии — граница
        op = [project(p, poly, cum) for p in samples(o)]
        if sum(1 for _, dd in op if dd <= TOL) >= 0.9 * len(op):
            stops += [min(s for s, _ in op), max(s for s, _ in op)]
    left = max([s for s in stops if s < s0 - 1], default=0.0)
    right = min([s for s in stops if s > s1 + 1], default=cum[-1])
    if left >= s0 - 1 and right <= s1 + 1:
        return None
    new = cut(poly, cum, min(left, s0), max(right, s1))
    if poly_len(new) <= poly_len(pts) + 1:
        return None
    if math.dist(pts[0], new[-1]) + math.dist(pts[-1], new[0]) < math.dist(pts[0], new[0]) + math.dist(pts[-1], new[-1]):
        new.reverse()
    return new


def extend_all(data: dict, only: set | None = None) -> list[tuple[str, float, float]]:
    """Продлить пути чертежа до целых линий (от стрелки до стрелки). Возвращает [(путь, было, стало)]."""
    cands = candidates(data)
    tracks = data.get("tracks", {})
    orig = {c: t["pts"] for c, t in tracks.items() if len(t.get("pts", [])) >= 2}
    changed = []
    for code, t in tracks.items():
        if only is not None and code not in only:
            continue
        if t.get("line") or code not in orig:
            continue  # путь по нарисованной линии — уже целиком
        new = extend(orig[code], cands, [p for c, p in orig.items() if c != code])
        if new:
            was = poly_len(t["pts"])
            t["pts"], t["len"] = new, round(poly_len(new), 1)
            changed.append((code, round(was), round(t["len"])))
    return changed


def track_at(data: dict, x: float, y: float, code: str) -> list | None:
    """Путь по линии чертежа под точкой (x, y): вся линия от стрелки до стрелки или до соседнего пути."""
    cands = candidates(data)
    best = None
    for poly, (a, b, c, d) in cands:
        if c < x - 8 or a > x + 8 or d < y - 8 or b > y + 8:
            continue
        dist = poly_dist([x, y], poly)
        if dist <= 8 and (best is None or dist < best[0]):
            best = (dist, poly)
    if best is None:
        return None
    poly = best[1]
    cum = _cum(poly)
    s, _ = project([x, y], poly, cum)
    seed = cut(poly, cum, max(0.0, s - 1), min(cum[-1], s + 1))
    others = [t["pts"] for c, t in data.get("tracks", {}).items() if c != code and len(t.get("pts", [])) >= 2]
    return extend(seed, cands, others) or seed
