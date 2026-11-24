"""Схема станции целиком с сервера: настройка (парки, ведомость путей, правило головы поезда) + заготовки."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps.auth import current_user, require_station, superuser_only
from src.api.deps.railway import get_db
from src.db.models import Railway, Station, StationDrawing, StationScheme, User
from src.db.seed import schemes as seed

router = APIRouter(prefix="/schemes", tags=["Station schemes"], dependencies=[Depends(current_user)])


def get_cfg(db: Session, station_id: int) -> StationScheme | None:
    return db.scalar(select(StationScheme).where(StationScheme.station_id == station_id))


def check_config(cfg: dict) -> dict:
    if not isinstance(cfg, dict) or not isinstance(cfg.get("parks", []), list):
        raise HTTPException(400, "Scheme config must have parks")
    for p in cfg.get("parks", []):
        if not isinstance(p, dict) or not p.get("title") or p.get("type") not in (1, 2, 3, 4) or not isinstance(p.get("tracks"), list):
            raise HTTPException(400, "Each park needs title, type 1-4 and tracks")
        for t in p["tracks"]:
            if not isinstance(t, list) or not t or not str(t[0]).strip():
                raise HTTPException(400, f"Park «{p['title']}»: track must be [code, length, type?]")
    cfg.setdefault("singles", [])
    cfg.setdefault("head_rule", {})
    return cfg


def save_cfg(db: Session, station_id: int, cfg: dict) -> StationScheme:
    row = get_cfg(db, station_id)
    text = json.dumps(cfg, ensure_ascii=False)
    if row is None:
        row = StationScheme(station_id=station_id, config=text)
        db.add(row)
    else:
        row.config = text
    db.commit()
    db.refresh(row)
    return row


def view(row: StationScheme | None) -> dict | None:
    return None if row is None else {"station_id": row.station_id, "updated_at": row.updated_at, **json.loads(row.config)}


def make_tracks(db: Session, station: Station, cfg: dict) -> int:
    """Завести в БД пути ведомости, которых ещё нет."""
    have = {r.code for r in db.scalars(select(Railway).where(Railway.station_id == station.id)).all()}
    direct = any(r.type == 4 for r in db.scalars(select(Railway).where(Railway.station_id == station.id)).all())
    made = 0
    for t in seed.plan(cfg):
        if t["code"] in have or (t["type"] == 4 and direct):
            continue
        if t["type"] != 4 and not t["length"]:
            continue
        db.add(Railway(station_id=station.id, code=t["code"], type=t["type"], length=None if t["type"] == 4 else t["length"]))
        direct = direct or t["type"] == 4
        made += 1
    db.commit()
    return made


@router.get("/presets")
def presets(db: Session = Depends(get_db)):
    """Заготовки схем, которые есть на сервере, и к какой станции они уже привязаны."""
    stations = db.scalars(select(Station)).all()
    out = []
    for key, p in seed.PRESETS.items():
        st = next((s for s in stations if seed.match(s) == key), None)
        out.append({"key": key, "code": p["code"], "name": p["name"], "station_id": st.id if st else None})
    return out


@router.post("/presets/{key}")
def apply_preset(key: str, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Создать станцию по заготовке (если её нет), её пути по ведомости, настройку схемы и чертёж."""
    p = seed.PRESETS.get(key)
    if p is None:
        raise HTTPException(404, "Preset not found")
    st = next((s for s in db.scalars(select(Station)).all() if seed.match(s) == key), None)
    if st is None:
        st = Station(code=p["code"], name=p["name"])
        db.add(st)
        db.commit()
        db.refresh(st)
    if get_cfg(db, st.id) is None:
        save_cfg(db, st.id, json.loads(json.dumps(p["config"])))
    attach_drawing(db, st.id, key)
    made = make_tracks(db, st, json.loads(get_cfg(db, st.id).config))
    return {"station_id": st.id, "tracks_created": made}


@router.get("/{station_id}")
def get_scheme(station_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Настройка схемы станции; null — у станции её нет (парки строятся по типам путей)."""
    require_station(user, station_id)
    return view(get_cfg(db, station_id))


class SchemeIn(BaseModel):
    config: dict


@router.put("/{station_id}")
def put_scheme(station_id: int, body: SchemeIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    if db.get(Station, station_id) is None:
        raise HTTPException(404, "Station not found")
    return view(save_cfg(db, station_id, check_config(body.config)))


@router.post("/{station_id}/tracks")
def create_tracks(station_id: int, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Завести пути ведомости схемы, которых нет в БД."""
    st = db.get(Station, station_id)
    row = get_cfg(db, station_id)
    if st is None or row is None:
        raise HTTPException(404, "Scheme not found")
    return {"tracks_created": make_tracks(db, st, json.loads(row.config))}


def attach_drawing(db: Session, station_id: int, key: str) -> bool:
    if db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id)) is not None:
        return False
    p = seed.PRESETS[key]
    db.add(StationDrawing(station_id=station_id, name=p["drawing_name"], source=p["source"],
                          data=json.dumps(seed.drawing_data(key), ensure_ascii=False, separators=(",", ":"))))
    db.commit()
    return True


def seed_existing(db: Session) -> None:
    """При запуске: станциям, для которых есть заготовка, — настройка схемы и чертёж (если своих ещё нет)."""
    for st in db.scalars(select(Station)).all():
        key = seed.match(st)
        if not key:
            continue
        if get_cfg(db, st.id) is None:
            save_cfg(db, st.id, json.loads(json.dumps(seed.PRESETS[key]["config"])))
        attach_drawing(db, st.id, key)
