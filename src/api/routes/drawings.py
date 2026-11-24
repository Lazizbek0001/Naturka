"""Чертежи станций: получение, импорт (PDF или JSON), сохранение правок, экспорт, удаление."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps.auth import current_user, require_station, superuser_only
from src.api.deps.railway import get_db
from src.db.models import Station, StationDrawing, User
from src.services import drawing_pdf
from src.services.drawing_items import explode
from src.services.track_extend import extend_all, poly_len, track_at

router = APIRouter(prefix="/drawings", tags=["Drawings"], dependencies=[Depends(current_user)])

MAX_PDF = 60 * 1024 * 1024


def get_station(db: Session, station_id: int) -> Station:
    st = db.get(Station, station_id)
    if st is None:
        raise HTTPException(404, "Station not found")
    return st


def check_data(data: dict) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("view"), list) or len(data["view"]) != 4:
        raise HTTPException(400, "Drawing must have view [x, y, w, h]")
    if not isinstance(data.get("layers", data.get("items")), list):
        raise HTTPException(400, "Drawing must have layers or items")
    data = explode(data)  # чертёж — набор отдельных объектов
    tracks = data.get("tracks") or {}
    if not isinstance(tracks, dict):
        raise HTTPException(400, "Drawing tracks must be an object")
    for code, t in tracks.items():
        if not isinstance(t, dict) or not isinstance(t.get("pts"), list) or len(t["pts"]) < 2:
            raise HTTPException(400, f"Track {code}: at least two points required")
    data["tracks"] = tracks
    return data


def meta(d: StationDrawing) -> dict:
    tracks = json.loads(d.data).get("tracks", {})
    return {"id": d.id, "station_id": d.station_id, "name": d.name, "source": d.source,
            "updated_at": d.updated_at, "tracks": len(tracks), "size": len(d.data)}


@router.get("")
def list_drawings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(StationDrawing)).all()
    return [meta(d) for d in rows if user.is_superuser or d.station_id == user.station_id]


@router.get("/{station_id}")
def get_drawing(station_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_station(user, station_id)
    d = db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id))
    if d is None:
        raise HTTPException(404, "Drawing not found")
    return {**meta(d), "data": json.loads(d.data)}


class DrawingIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    data: dict


def save(db: Session, station_id: int, name: str, source: str | None, data: dict) -> StationDrawing:
    d = db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id))
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if d is None:
        d = StationDrawing(station_id=station_id, name=name, source=source, data=text)
        db.add(d)
    else:
        d.name, d.data = name, text
        if source is not None:
            d.source = source
    db.commit()
    db.refresh(d)
    return d


@router.put("/{station_id}")
def put_drawing(station_id: int, body: DrawingIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Создать или заменить чертёж (импорт JSON, сохранение правок путей)."""
    get_station(db, station_id)
    return meta(save(db, station_id, body.name, body.source, check_data(body.data)))


class TracksIn(BaseModel):
    tracks: dict
    name: str | None = Field(default=None, min_length=1, max_length=255)


@router.patch("/{station_id}")
def patch_drawing(station_id: int, body: TracksIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Сохранить привязку путей (и название) существующего чертежа."""
    d = db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id))
    if d is None:
        raise HTTPException(404, "Drawing not found")
    data = json.loads(d.data)
    old = data.get("tracks", {})
    data["tracks"] = body.tracks
    # заново проведённые пути — по всей линии чертежа (от стрелки до стрелки), а не по кусочку
    extend_all(data, {c for c, t in body.tracks.items() if (old.get(c) or {}).get("pts") != t.get("pts")})
    return meta(save(db, station_id, body.name or d.name, None, check_data(data)))


@router.post("/{station_id}/pdf")
async def import_pdf(station_id: int, request: Request, page: int = 1, name: str | None = None, filename: str | None = None,
                     keep_tracks: bool = False, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Создать чертёж из PDF (тело запроса — сам файл). keep_tracks — сохранить уже проведённые пути."""
    st = get_station(db, station_id)
    body = await request.body()
    if not body or not body.startswith(b"%PDF"):
        raise HTTPException(400, "Expected a PDF file")
    if len(body) > MAX_PDF:
        raise HTTPException(413, "PDF is too large")
    try:
        data = drawing_pdf.extract(body, page, prefix=f"s{station_id}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # повреждённый PDF и т. п.
        raise HTTPException(400, f"Cannot read PDF: {exc}") from exc
    if keep_tracks:
        old = db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id))
        if old is not None:
            data["tracks"] = json.loads(old.data).get("tracks", {})
    pages = data.pop("pages", 1)
    d = save(db, station_id, name or f"Схема ст. {st.name}", filename, data)
    return {**meta(d), "pages": pages}


# ---------------------------------------------------------------- линии, нарисованные на схеме
LINE_STYLES = ("ink", "main", "elec", "dash", "build")


class LineIn(BaseModel):
    pts: list[list[float]] | None = Field(default=None, min_length=2, max_length=500)
    style: str | None = Field(default=None, max_length=16)
    label: str | None = Field(default=None, max_length=64)   # подпись у линии (например, номер пути)
    code: str | None = Field(default=None, max_length=255)   # путь БД, который идёт по этой линии


def _drawing(db: Session, station_id: int) -> tuple[StationDrawing, dict]:
    d = db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id))
    if d is None:
        raise HTTPException(404, "Drawing not found")
    return d, json.loads(d.data)


def _poly_len(pts) -> float:
    return round(sum(((pts[i][0] - pts[i - 1][0]) ** 2 + (pts[i][1] - pts[i - 1][1]) ** 2) ** .5 for i in range(1, len(pts))), 1)


def _apply(line: dict, body: LineIn, data: dict) -> None:
    patch = body.model_dump(exclude_unset=True)
    if "pts" in patch:
        pts = patch["pts"]
        if pts is None or any(len(p) != 2 for p in pts):
            raise HTTPException(400, "Line points must be [x, y]")
        line["pts"] = [[round(x, 1), round(y, 1)] for x, y in pts]
    if "style" in patch:
        if patch["style"] not in LINE_STYLES:
            raise HTTPException(400, f"Line style must be one of {', '.join(LINE_STYLES)}")
        line["style"] = patch["style"]
    if "label" in patch:
        line["label"] = (patch["label"] or "").strip() or None
    tracks = data.setdefault("tracks", {})
    old = line.get("code")
    if "code" in patch:
        line["code"] = (patch["code"] or "").strip() or None
    new = line.get("code")
    if old and old != new and (tracks.get(old) or {}).get("line") == line["id"]:
        del tracks[old]  # путь больше не идёт по этой линии
    if new:
        tracks[new] = {"pts": line["pts"], "len": _poly_len(line["pts"]), "line": line["id"]}


@router.post("/{station_id}/lines", status_code=201)
def add_line(station_id: int, body: LineIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Нарисовать линию на схеме. Если указан путь (code) — путь проводится по этой линии."""
    if not body.pts:
        raise HTTPException(400, "Line needs at least two points")
    d, data = _drawing(db, station_id)
    lines = data.setdefault("lines", [])
    line = {"id": max((ln["id"] for ln in lines), default=0) + 1, "style": "ink"}
    _apply(line, body, data)
    lines.append(line)
    save(db, station_id, d.name, None, check_data(data))
    return {"line": line, "tracks": data["tracks"]}


@router.patch("/{station_id}/lines/{line_id}")
def edit_line(station_id: int, line_id: int, body: LineIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    d, data = _drawing(db, station_id)
    line = next((ln for ln in data.get("lines", []) if ln["id"] == line_id), None)
    if line is None:
        raise HTTPException(404, "Line not found")
    _apply(line, body, data)
    save(db, station_id, d.name, None, check_data(data))
    return {"line": line, "tracks": data["tracks"]}


@router.delete("/{station_id}/lines/{line_id}")
def delete_line(station_id: int, line_id: int, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    d, data = _drawing(db, station_id)
    lines = data.get("lines", [])
    line = next((ln for ln in lines if ln["id"] == line_id), None)
    if line is None:
        raise HTTPException(404, "Line not found")
    lines.remove(line)
    tracks = data.setdefault("tracks", {})
    if line.get("code") and (tracks.get(line["code"]) or {}).get("line") == line_id:
        del tracks[line["code"]]
    save(db, station_id, d.name, None, check_data(data))
    return {"tracks": tracks}


# ---------------------------------------------------------------- светофоры на схеме
SIGNAL_KINDS = {  # вид → огни, которые он может показывать
    "entry": ("red", "yellow", "green", "yy", "white"),   # входной
    "exit": ("red", "yellow", "green", "white"),          # выходной
    "route": ("red", "yellow", "green"),                  # маршрутный
    "pass": ("red", "yellow", "green"),                   # проходной
    "shunt": ("blue", "white"),                           # маневровый
    "elec": ("on", "off"),                                # электроизоляция контактной сети: напряжение есть / снято
}


class SignalIn(BaseModel):
    x: float | None = None
    y: float | None = None
    kind: str | None = Field(default=None, max_length=16)
    name: str | None = Field(default=None, max_length=32)       # литера: Н, Ч, НМ1, М12…
    dir: str | None = Field(default=None, pattern="^(left|right)$")    # куда смотрит (для какого направления)
    side: str | None = Field(default=None, pattern="^(top|bottom)$")   # с какой стороны пути мачта
    aspect: str | None = Field(default=None, max_length=16)     # горящий огонь
    form: str | None = Field(default=None, pattern="^(mast|inline|dwarf)$")  # inline — ⊢○○○ как на чертеже, dwarf — карликовый ⊂○○⊃
    a: float | None = Field(default=None, ge=-360, le=360)      # наклон (для inline), градусы
    r: float | None = Field(default=None, ge=0.3, le=10)        # радиус огня (для inline)
    n: int | None = Field(default=None, ge=1, le=8)             # число огней (для inline)


def _apply_signal(sig: dict, body: SignalIn) -> None:
    patch = body.model_dump(exclude_unset=True)
    for k in ("x", "y"):
        if k in patch:
            if patch[k] is None:
                raise HTTPException(400, "Signal needs x and y")
            sig[k] = round(patch[k], 1)
    if "kind" in patch:
        if patch["kind"] not in SIGNAL_KINDS:
            raise HTTPException(400, f"Signal kind must be one of {', '.join(SIGNAL_KINDS)}")
        sig["kind"] = patch["kind"]
    if "name" in patch:
        sig["name"] = (patch["name"] or "").strip() or None
    for k in ("dir", "side", "form"):
        if patch.get(k):
            sig[k] = patch[k]
    for k in ("a", "r", "n"):
        if k in patch:
            if patch[k] is None:
                sig.pop(k, None)
            else:
                sig[k] = round(patch[k], 2) if k != "n" else patch[k]
    allowed = SIGNAL_KINDS[sig["kind"]]
    if "aspect" in patch:
        if patch["aspect"] not in allowed:
            raise HTTPException(400, f"This signal shows only: {', '.join(allowed)}")
        sig["aspect"] = patch["aspect"]
    if sig.get("aspect") not in allowed:
        sig["aspect"] = allowed[0]  # по умолчанию — запрещающий


def _signal(data: dict, signal_id: int) -> dict:
    sig = next((s for s in data.get("signals", []) if s["id"] == signal_id), None)
    if sig is None:
        raise HTTPException(404, "Signal not found")
    return sig


@router.post("/{station_id}/signals", status_code=201)
def add_signal(station_id: int, body: SignalIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Поставить светофор на схему."""
    if body.x is None or body.y is None:
        raise HTTPException(400, "Signal needs x and y")
    d, data = _drawing(db, station_id)
    signals = data.setdefault("signals", [])
    sig = {"id": max((s["id"] for s in signals), default=0) + 1, "kind": "exit", "dir": "right", "side": "top"}
    _apply_signal(sig, body)
    signals.append(sig)
    save(db, station_id, d.name, None, check_data(data))
    return sig


@router.patch("/{station_id}/signals/{signal_id}")
def edit_signal(station_id: int, signal_id: int, body: SignalIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Изменить светофор. Дежурный станции может только переключать огонь (aspect), остальное — администратор."""
    require_station(user, station_id)
    if not user.is_superuser and set(body.model_dump(exclude_unset=True)) - {"aspect"}:
        raise HTTPException(403, "Only an administrator can move or edit signals")
    d, data = _drawing(db, station_id)
    sig = _signal(data, signal_id)
    _apply_signal(sig, body)
    save(db, station_id, d.name, None, check_data(data))
    return sig


@router.delete("/{station_id}/signals/{signal_id}", status_code=204)
def delete_signal(station_id: int, signal_id: int, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    d, data = _drawing(db, station_id)
    data["signals"].remove(_signal(data, signal_id))
    save(db, station_id, d.name, None, check_data(data))
    return Response(status_code=204)


# ---------------------------------------------------------------- правка объектов чертежа (как в векторном редакторе)
ITEM_KEYS = {"t", "d", "stroke", "fill", "w", "dash", "x", "y", "a", "size", "text", "bold", "color", "dx", "dy", "uses", "opacity",
             "bind"}  # bind: {"rid": id пути в БД, "f": "code" | "len"} — надпись берёт значение из БД
COLLS = ("items", "lines", "signals")


class OpsIn(BaseModel):
    ops: list[dict] = Field(min_length=1, max_length=5000)


def _clean_item(obj: dict) -> dict:
    item = {k: v for k, v in obj.items() if k in ITEM_KEYS}
    if item.get("t") not in ("path", "text", "glyphs"):
        raise HTTPException(400, "Item type must be path, text or glyphs")
    if item["t"] == "path" and not str(item.get("d", "")).startswith("M"):
        raise HTTPException(400, "Path item needs d")
    if item["t"] == "text" and (item.get("x") is None or item.get("y") is None):
        raise HTTPException(400, "Text item needs x and y")
    return item


@router.post("/{station_id}/ops")
def apply_ops(station_id: int, body: OpsIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Пакет правок чертежа: add / update / delete / order для объектов (items), линий и светофоров.
    Пакет применяется целиком или не применяется вовсе."""
    d, data = _drawing(db, station_id)
    data = explode(data)
    for c in COLLS:
        data.setdefault(c, [])
    added = []
    for op in body.ops:
        kind, coll = op.get("op"), op.get("coll", "items")
        if coll not in COLLS:
            raise HTTPException(400, f"Unknown collection {coll}")
        arr = data[coll]
        if kind == "track":  # путь на чертеже: по линии под точкой (at), готовой ломаной (value) или убрать (value=null)
            code = str(op.get("code") or "").strip()
            if not code:
                raise HTTPException(400, "Track code required")
            tracks = data.setdefault("tracks", {})
            if op.get("at"):
                x, y = op["at"]
                pts = track_at(data, float(x), float(y), code)
                if not pts:
                    raise HTTPException(400, "No drawing line under this point")
                tracks[code] = {"pts": pts, "len": round(poly_len(pts), 1)}
            elif op.get("value"):
                v = op["value"]
                if not isinstance(v, dict) or len(v.get("pts") or []) < 2:
                    raise HTTPException(400, "Track needs at least two points")
                tracks[code] = v
            else:
                tracks.pop(code, None)
            continue
        if kind == "add":
            obj = dict(op.get("obj") or {})
            oid = obj.get("id")
            if not isinstance(oid, int) or any(o["id"] == oid for o in arr):
                oid = max((o["id"] for o in arr), default=0) + 1
            if coll == "items":
                new = {"id": oid, **_clean_item(obj)}
            elif coll == "lines":
                new = {"id": oid, "style": obj.get("style") or "ink"}
                _apply(new, LineIn(**{k: obj[k] for k in ("pts", "style", "label", "code") if k in obj}), data)
            else:
                new = {"id": oid, "kind": obj.get("kind") or "exit", "dir": obj.get("dir") or "right", "side": obj.get("side") or "top"}
                _apply_signal(new, SignalIn(**{k: obj[k] for k in ("x", "y", "kind", "name", "dir", "side", "aspect", "form", "a", "r", "n") if k in obj}))
            idx = op.get("index")
            arr.insert(idx if isinstance(idx, int) and 0 <= idx <= len(arr) else len(arr), new)
            added.append(oid)
            continue
        obj = next((o for o in arr if o["id"] == op.get("id")), None)
        if obj is None:
            raise HTTPException(404, f"{coll} #{op.get('id')} not found")
        if kind == "update":
            patch = op.get("set") or {}
            if coll == "items":
                obj.update(_clean_item({**obj, **patch}))
                for k in [k for k, v in patch.items() if v is None]:
                    obj.pop(k, None)
            elif coll == "lines":
                _apply(obj, LineIn(**{k: v for k, v in patch.items() if k in ("pts", "style", "label", "code")}), data)
            else:
                _apply_signal(obj, SignalIn(**{k: v for k, v in patch.items() if k in ("x", "y", "kind", "name", "dir", "side", "aspect", "form", "a", "r", "n")}))
        elif kind == "delete":
            arr.remove(obj)
            if coll == "lines" and obj.get("code") and (data["tracks"].get(obj["code"]) or {}).get("line") == obj["id"]:
                del data["tracks"][obj["code"]]
        elif kind == "order":  # z-порядок: новое место в списке
            arr.remove(obj)
            idx = op.get("index")
            arr.insert(max(0, min(len(arr), idx if isinstance(idx, int) else len(arr))), obj)
        else:
            raise HTTPException(400, f"Unknown op {kind}")
    save(db, station_id, d.name, None, check_data(data))
    return {"added": added, "tracks": data.get("tracks", {})}


def migrate_all(db: Session) -> None:
    """При запуске: старые чертежи (слои целиком) — в набор отдельных объектов."""
    for d in db.scalars(select(StationDrawing)).all():
        data = json.loads(d.data)
        if "items" not in data:
            d.data = json.dumps(explode(data), ensure_ascii=False, separators=(",", ":"))
    db.commit()


@router.delete("/{station_id}", status_code=204)
def delete_drawing(station_id: int, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    d = db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id))
    if d is None:
        raise HTTPException(404, "Drawing not found")
    db.delete(d)
    db.commit()
    return Response(status_code=204)
