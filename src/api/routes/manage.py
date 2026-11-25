"""Изменение и удаление справочников, натурок и вагонов.

Подключается раньше роутера railways, чтобы пути вида /railways/wagons/{id}
не перехватывались маршрутом /railways/{railway_id}.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src.api.deps.railway import get_db
from src.api.deps.auth import current_user, superuser_only, require_station
from src.db.models import (
    Railway, RailwayType, NaturkaCollection, NaturkaVagon, Station, MessageIdCounter, User, StationDrawing, StationScheme,
)
from src.schemas.railway import StationView, RailwayView, CollectionView
from src.services import railway_operations as service
from src.services.railway_order import place_railway, renumber, set_order, station_railways

router = APIRouter(prefix="/railways", tags=["Manage"], dependencies=[Depends(current_user)])

ACTIVE = ("entrance", "sorting", "departure")


def commit(db: Session, conflict: str):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, conflict) from exc


def drop_collections(db: Session, ids: list[int]) -> None:
    """Удаляет натурки вместе с вагонами, снимая ссылки на них из копий."""
    if not ids:
        return
    wagon_ids = select(NaturkaVagon.id).where(NaturkaVagon.collection_id.in_(ids))
    db.execute(update(NaturkaVagon).where(NaturkaVagon.source_vagon_id.in_(wagon_ids))
               .values(source_vagon_id=None))
    db.execute(update(NaturkaCollection).where(NaturkaCollection.source_collection_id.in_(ids))
               .values(source_collection_id=None))
    db.execute(delete(NaturkaVagon).where(NaturkaVagon.collection_id.in_(ids)))
    db.execute(delete(NaturkaCollection).where(NaturkaCollection.id.in_(ids)))


# --- Станции ---
class StationUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_uz: str | None = Field(default=None, max_length=255)
    name_uzc: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    inactive: bool | None = None


@router.patch("/stations/{station_id}", response_model=StationView)
def update_station(station_id: int, data: StationUpdate, db: Session = Depends(get_db),
                   _: User = Depends(superuser_only)):
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(404, "Station not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "inactive":
            station.inactive = True if value else None
        elif value is not None or key.startswith("name_"):
            setattr(station, key, value or None)
    commit(db, "Station code already exists")
    db.refresh(station)
    return station


@router.delete("/stations/{station_id}", status_code=204)
def delete_station(station_id: int, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(404, "Station not found")
    users = db.scalars(select(User.username).where(User.station_id == station_id)).all()
    if users:
        raise HTTPException(409, "Station has users: " + ", ".join(users))
    drop_collections(db, list(db.scalars(
        select(NaturkaCollection.id).where(NaturkaCollection.station_id == station_id)).all()))
    db.execute(delete(NaturkaVagon).where(NaturkaVagon.station_id == station_id))
    db.execute(delete(Railway).where(Railway.station_id == station_id))
    db.execute(delete(MessageIdCounter).where(MessageIdCounter.station_id == station_id))
    db.execute(delete(StationDrawing).where(StationDrawing.station_id == station_id))
    db.execute(delete(StationScheme).where(StationScheme.station_id == station_id))
    db.delete(station)
    commit(db, "Station is still referenced")
    return Response(status_code=204)


# --- Пути ---
class RailwayUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=255)
    type: int | None = Field(default=None, ge=1, le=4)
    length: int | None = None
    position: int | None = Field(default=None, ge=1)  # новое место в списке путей станции (1 — первым)


class RailwayReplace(BaseModel):
    """Полная замена пути (PUT): все поля обязательны, кроме длины у сквозного и позиции."""
    code: str = Field(min_length=1, max_length=255)
    type: int = Field(ge=1, le=4)
    length: int | None = None
    position: int | None = Field(default=None, ge=1)


class RailwayOrder(BaseModel):
    station_id: int = Field(gt=0)
    ids: list[int] = Field(min_length=1)  # все пути станции в нужном порядке


@router.put("/order", response_model=list[RailwayView], tags=["Railways"])
def order_railways(body: RailwayOrder, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Задать порядок путей станции: ids — все id путей станции по порядку. Позиции станут 1, 2, 3, …"""
    require_station(user, body.station_id)
    try:
        rows = set_order(db, body.station_id, body.ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return rows


@router.put("/{railway_id}", response_model=RailwayView, tags=["Railways"])
def replace_railway(railway_id: int, data: RailwayReplace, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Изменить путь целиком: номер, тип, длина (и место в списке)."""
    patch = RailwayUpdate(code=data.code, type=data.type, length=data.length)  # длина передаётся всегда (пусто — сквозной)
    if data.position is not None:
        patch.position = data.position
    return update_railway(railway_id, patch, db, user)


@router.patch("/{railway_id}", response_model=RailwayView, tags=["Railways"])
def update_railway(railway_id: int, data: RailwayUpdate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    railway = service.track(db, railway_id)
    require_station(user, railway.station_id)
    fields = data.model_dump(exclude_unset=True)
    new_type = fields.get("type", railway.type)
    new_length = fields["length"] if "length" in fields else railway.length
    if new_type == RailwayType.DIRECT:
        new_length = None
    elif new_length is None or new_length <= 0:
        raise HTTPException(400, "Railway length must be positive")
    used = service.occupied_length(db, railway.id)
    if new_type != railway.type and used:
        raise HTTPException(409, "Cannot change type of a track that holds collections")
    if new_length is not None and new_length < used:
        raise HTTPException(409, f"Track holds {used} m, length cannot be less")
    old_code = railway.code
    if fields.get("code"):
        railway.code = fields["code"]
    railway.type = new_type
    railway.length = new_length
    if fields.get("position") is not None:
        place_railway(db, railway, fields["position"])
    commit(db, "Railway code or direct railway already exists")
    if railway.code != old_code:
        rename_in_scheme(db, railway.station_id, old_code, railway.code)
    db.refresh(railway)
    return railway


def rename_in_scheme(db: Session, station_id: int, old: str, new: str) -> None:
    """Новый номер пути — и в настройке схемы (парки, отдельные пути), и на чертеже (геометрия пути, линии)."""
    import json
    cfg = db.scalar(select(StationScheme).where(StationScheme.station_id == station_id))
    if cfg is not None:
        c = json.loads(cfg.config)
        for park in c.get("parks", []):
            for t in park.get("tracks", []):
                if t and t[0] == old:
                    t[0] = new
        for t in c.get("singles", []):
            if t.get("code") == old:
                t["code"] = new
        cfg.config = json.dumps(c, ensure_ascii=False)
    dwg = db.scalar(select(StationDrawing).where(StationDrawing.station_id == station_id))
    if dwg is not None:
        d = json.loads(dwg.data)
        tracks = d.get("tracks", {})
        if old in tracks and new not in tracks:
            tracks[new] = tracks.pop(old)
        for ln in d.get("lines", []):
            if ln.get("code") == old:
                ln["code"] = new
        dwg.data = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    db.commit()


@router.delete("/{railway_id}", status_code=204, tags=["Railways"])
def delete_railway(railway_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    railway = service.track(db, railway_id)
    require_station(user, railway.station_id)
    active = db.scalar(select(NaturkaCollection.id).where(
        NaturkaCollection.railway_id == railway_id, NaturkaCollection.hidden.is_(False),
        NaturkaCollection.status.in_(ACTIVE)))
    if active is not None:
        raise HTTPException(409, "Track holds collections; move or delete them first")
    db.execute(update(NaturkaCollection).where(NaturkaCollection.railway_id == railway_id)
               .values(railway_id=None))
    station_id = railway.station_id
    db.delete(railway)
    db.flush()
    renumber(station_railways(db, station_id))  # без пропусков в нумерации
    commit(db, "Track is still referenced")
    return Response(status_code=204)


# --- Натурки ---
class CollectionUpdate(BaseModel):
    message_station: int | None = None
    train_number: int | None = None
    sent_station: int | None = None
    message_id: int | None = Field(default=None, ge=1, le=999)
    target_station: int | None = None
    train_condition: int | None = None
    length: int | None = Field(default=None, ge=0)
    weight: int | None = Field(default=None, ge=0)
    tosish: int | None = None
    tepa: int | None = None
    yon: int | None = None
    past: int | None = None
    animal: int | None = None
    extra: str | None = Field(default=None, max_length=255)
    extra2: str | None = Field(default=None, max_length=255)


@router.patch("/collections/{collection_id}", response_model=CollectionView)
def update_collection(collection_id: int, data: CollectionUpdate, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    c = service.load_collection(db, collection_id)
    require_station(user, c.station_id)
    fields = data.model_dump(exclude_unset=True)
    # Длина и вес задаются вручную только у приёма (у остальных они считаются по вагонам).
    if c.status != "entrance":
        fields.pop("length", None)
        fields.pop("weight", None)
    if "length" in fields and c.railway_id is not None and c.status in ACTIVE:
        railway = service.track(db, c.railway_id)
        if railway.length is not None:
            free = railway.length - service.occupied_length(db, railway.id) + c.length
            if fields["length"] > free:
                raise HTTPException(409, f"Insufficient space on {railway.code}: {free} m free")
    for key, value in fields.items():
        setattr(c, key, value)
    commit(db, "This message_id is already active at this station")
    return service.load_collection(db, collection_id)


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = service.load_collection(db, collection_id)
    require_station(user, c.station_id)
    drop_collections(db, [c.id])
    commit(db, "Collection is still referenced")
    return Response(status_code=204)


# --- Вагоны ---
class WagonUpdate(BaseModel):
    vagon_number: int | None = None
    vagon_country: int | None = None
    product_weight: int | None = Field(default=None, ge=0)
    product_type: int | None = None
    target_station: int | None = None
    punkt: int | None = None
    vagon_condition: int | None = None
    product_importance: int | None = None
    ban: int | None = None
    count_plomba: int | None = None
    count_container: str | None = Field(default=None, min_length=1, max_length=255)
    through_station: int | None = None
    extra_data: str | None = Field(default=None, max_length=255)
    length_m: int | None = Field(default=None, gt=0)
    vagon_type: str | None = Field(default=None, max_length=16)  # "" — снова по номеру


def wagon_batch(db: Session, user: User, wagon_id: int) -> tuple[NaturkaVagon, NaturkaCollection]:
    wagon = db.get(NaturkaVagon, wagon_id)
    if wagon is None or wagon.collection_id is None:
        raise HTTPException(404, "Wagon not found")
    batch = service.load_collection(db, wagon.collection_id)
    require_station(user, batch.station_id)
    if batch.status == "departure" and batch.ready:
        raise HTTPException(409, "Unmark the collection as ready before editing its wagons")
    return wagon, batch


def refresh_totals(db: Session, batch: NaturkaCollection) -> None:
    """Длина и вес приёма приходят из натурки; у остальных их считаем по вагонам."""
    if batch.status == "entrance":
        return
    wagons = db.scalars(select(NaturkaVagon).where(NaturkaVagon.collection_id == batch.id)).all()
    service.recalc(batch, list(wagons))


@router.patch("/wagons/{wagon_id}", response_model=CollectionView)
def update_wagon(wagon_id: int, data: WagonUpdate, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    wagon, batch = wagon_batch(db, user, wagon_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items()
              if v is not None or k in ("extra_data", "vagon_type")}
    if "vagon_type" in fields:
        fields["vagon_type"] = fields["vagon_type"] or None
    grow = fields.get("length_m", wagon.length_m) - wagon.length_m
    if grow > 0 and batch.status != "entrance" and batch.railway_id is not None and batch.status in ACTIVE:
        service.ensure_space(db, service.track(db, batch.railway_id), grow)
    for key, value in fields.items():
        setattr(wagon, key, value)
    db.flush()
    refresh_totals(db, batch)
    commit(db, "Wagon update conflicts with existing data")
    return service.load_collection(db, batch.id)


@router.delete("/wagons/{wagon_id}")
def delete_wagon(wagon_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    wagon, batch = wagon_batch(db, user, wagon_id)
    db.execute(update(NaturkaVagon).where(NaturkaVagon.source_vagon_id == wagon.id).values(source_vagon_id=None))
    db.delete(wagon)
    db.flush()
    rest = list(db.scalars(select(NaturkaVagon).where(NaturkaVagon.collection_id == batch.id)
                           .order_by(NaturkaVagon.position)).all())
    if not rest:
        drop_collections(db, [batch.id])
        commit(db, "Collection is still referenced")
        return {"deleted_collection": batch.id}
    service.save_wagon_order(db, rest)
    refresh_totals(db, batch)
    commit(db, "Wagon delete conflicts with existing data")
    return CollectionView.model_validate(service.load_collection(db, batch.id))
