from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src.api.deps.railway import get_db
from src.db.models import Railway, RailwayType, NaturkaCollection, NaturkaVagon, Station, MessageIdCounter
from src.schemas.railway import (
    StationCreate, StationView, RailwayCreate, RailwayView, ReportImport, MoveToSorting, RangeExtract,
    SendDeparture, CollectionReadiness, DispatchCollection, CollectionView,
    ReorderWagons, MoveWagonPosition, InsertExistingWagons,
)
from src.services import railway_operations as service
from src.services.railway_order import place_railway
from src.db.models.user import User
from src.api.deps.auth import current_user, superuser_only, require_station

router = APIRouter(prefix="/railways", tags=["Railways"], dependencies=[Depends(current_user)])


def commit_action(db: Session, action):
    try:
        result = action()
        result_id = result.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Database constraint conflict (duplicate wagon assignment or batch)") from exc
    except Exception:
        db.rollback()
        raise
    return service.load_collection(db, result_id)


def check_collection(db: Session, user: User, collection_id: int):
    require_station(user, service.load_collection(db, collection_id).station_id)


def check_track(db: Session, user: User, railway_id: int):
    require_station(user, service.track(db, railway_id).station_id)


@router.post("/stations", response_model=StationView, status_code=201)
def create_station(data: StationCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.is_superuser:
        raise HTTPException(403, "Only superuser may create stations")
    station = Station(**data.model_dump())
    db.add(station)
    try:
        db.flush()
        db.add(MessageIdCounter(station_id=station.id, last_assigned=0))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Station code already exists") from exc
    db.refresh(station)
    return station


@router.get("/stations", response_model=list[StationView])
def list_stations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Station)
    if not user.is_superuser:
        stmt = stmt.where(Station.id == user.station_id)
    return db.scalars(stmt.order_by(Station.code)).all()


@router.get("/stations/{station_id}", response_model=StationView)
def get_station(station_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = db.get(Station, station_id)
    if result is None:
        raise HTTPException(404, "Station not found")
    require_station(user, result.id)
    return result


@router.post("", response_model=RailwayView, status_code=201)
def create_railway(data: RailwayCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if data.type == RailwayType.DIRECT:
        if data.length is not None:
            raise HTTPException(400, "Direct railway must have null length")
    elif data.length is None or data.length <= 0:
        raise HTTPException(400, "Railway length must be positive")
    require_station(user, data.station_id)
    if db.get(Station, data.station_id) is None:
        raise HTTPException(404, "Station not found")
    fields = data.model_dump()
    position = fields.pop("position")
    railway = Railway(**fields)
    db.add(railway)
    try:
        db.flush()
        place_railway(db, railway, position)  # на указанное место (остальные сдвигаются) или в конец
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Railway code or direct railway already exists") from exc
    db.refresh(railway)
    return railway


@router.get("", response_model=list[RailwayView])
def list_railways(station_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Railway)
    if station_id is not None:
        require_station(user, station_id)
        stmt = stmt.where(Railway.station_id == station_id)
    elif not user.is_superuser:
        stmt = stmt.where(Railway.station_id == user.station_id)
    return db.scalars(stmt.order_by(Railway.station_id, Railway.position.is_(None), Railway.position,
                                    Railway.type, Railway.code)).all()


@router.get("/originals", response_model=list[CollectionView])
def originals(db: Session = Depends(get_db), user: User = Depends(current_user)):
    ids_query = select(NaturkaCollection.id).where(
        NaturkaCollection.status == "original", NaturkaCollection.hidden.is_(True)
    )
    if not user.is_superuser:
        ids_query = ids_query.where(NaturkaCollection.station_id == user.station_id)
    ids = db.scalars(ids_query.order_by(NaturkaCollection.id.desc())).all()
    return [service.load_collection(db, i) for i in ids]


@router.get("/collections/{collection_id}", response_model=CollectionView)
def get_collection(collection_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    collection = service.load_collection(db, collection_id)
    require_station(user, collection.station_id)
    return collection


@router.get("/{railway_id}")
def get_railway(railway_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    railway = service.track(db, railway_id)
    require_station(user, railway.station_id)
    batches = db.scalars(select(NaturkaCollection).where(
        NaturkaCollection.railway_id == railway_id,
        NaturkaCollection.hidden.is_(False),
    ).order_by(NaturkaCollection.id)).all()
    used = service.occupied_length(db, railway_id)
    return {
        "id": railway.id, "station_id": railway.station_id, "code": railway.code, "type": railway.type,
        "position": railway.position,
        "length": railway.length, "occupied_length": used,
        "available_length": None if railway.length is None else railway.length - used,
        "collections": [{
            "id": b.id, "length": b.length, "weight": b.weight,
            "train_number": b.train_number, "status": b.status, "ready": b.ready,
            "target_station": b.target_station,
            # Active entrance wagons are shown only until they are assigned.
            "unassigned_wagon_ids": (
                [w.id for w in b.vagons if w.id not in set(db.scalars(
                    select(NaturkaVagon.source_vagon_id).where(
                        NaturkaVagon.source_vagon_id.in_([v.id for v in b.vagons])
                    )
                ).all())] if b.status == "entrance" else []
            ),
        } for b in batches],
    }


@router.post("/import-report", response_model=CollectionView, status_code=201)
def import_report(data: ReportImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_track(db, user, data.entrance_id)
    return commit_action(db, lambda: service.import_report(db, data))


@router.post("/move-to-sorting", response_model=CollectionView)
def move_to_sorting(data: MoveToSorting, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_collection(db, user, data.collection_id)
    check_track(db, user, data.sorting_railway_id)
    return commit_action(db, lambda: service.move_to_sorting(db, data))


@router.post("/entrance/extract-range", response_model=CollectionView)
def entrance_extract_range(data: MoveToSorting, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if data.start_position is None:
        raise HTTPException(400, "start_position and end_position are required")
    check_collection(db, user, data.collection_id)
    check_track(db, user, data.sorting_railway_id)
    return commit_action(db, lambda: service.move_to_sorting(db, data))


@router.post("/extract-range", response_model=CollectionView)
def sorting_extract_range(data: RangeExtract, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_collection(db, user, data.source_collection_id)
    check_track(db, user, data.destination_sorting_id)
    return commit_action(db, lambda: service.extract_range(db, data))


@router.post("/send-to-departure", response_model=CollectionView)
def send_departure(data: SendDeparture, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_collection(db, user, data.collection_id)
    check_track(db, user, data.departure_railway_id)
    return commit_action(db, lambda: service.send_departure(db, data))


@router.patch("/collections/{collection_id}/readiness", response_model=CollectionView)
def readiness(collection_id: int, data: CollectionReadiness, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_collection(db, user, collection_id)
    return commit_action(db, lambda: service.set_readiness(db, collection_id, data.ready))


@router.post("/dispatch", response_model=CollectionView)
def dispatch(data: DispatchCollection, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_collection(db, user, data.collection_id)
    return commit_action(db, lambda: service.dispatch(db, data.collection_id))


@router.put("/collections/{collection_id}/wagons/order", response_model=CollectionView)
def reorder_collection_wagons(
    collection_id: int, data: ReorderWagons, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    check_collection(db, user, collection_id)
    return commit_action(db, lambda: service.reorder_wagons(db, collection_id, data))


@router.patch("/collections/{collection_id}/wagons/move", response_model=CollectionView)
def move_wagon_inside_collection(
    collection_id: int, data: MoveWagonPosition, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    check_collection(db, user, collection_id)
    return commit_action(db, lambda: service.move_wagon_position(db, collection_id, data))


@router.post("/collections/{collection_id}/wagons/insert-existing", response_model=CollectionView)
def insert_existing_wagons(
    collection_id: int, data: InsertExistingWagons,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    check_collection(db, user, collection_id)
    check_collection(db, user, data.source_collection_id)
    return commit_action(db, lambda: service.insert_existing_wagons(db, collection_id, data))