
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.db.models.railway import Railway, RailwayType
from src.db.models.naturka_collection import NaturkaCollection
from src.db.models.naturka_vagon import NaturkaVagon

from src.schemas.railway import (
    ReportImport,
    RangeExtract,
    SendDeparture,
)


def fail(message: str, status: int = 400):
    raise HTTPException(
        status_code=status,
        detail=message,
    )


def get_track(
    db: Session,
    railway_id: int,
    expected_type: RailwayType | None = None,
    lock: bool = False,
) -> Railway:
    query = select(Railway).where(
        Railway.id == railway_id
    )

    if lock:
        query = query.with_for_update()

    railway = db.scalar(query)

    if railway is None:
        fail("Railway not found", 404)

    if (
        expected_type is not None
        and railway.type != int(expected_type)
    ):
        fail(
            f"Railway must be type {expected_type.name}"
        )

    return railway


def occupied_length(
    db: Session,
    railway_id: int,
) -> int:
    query = select(
        func.coalesce(
            func.sum(NaturkaCollection.length),
            0,
        )
    ).where(
        NaturkaCollection.railway_id == railway_id
    )

    return int(db.scalar(query) or 0)


def ensure_capacity(
    db: Session,
    railway: Railway,
    additional_length: int,
):
    if railway.length is None:
        fail("A track without length cannot hold collections")

    used = occupied_length(db, railway.id)

    if used + additional_length > railway.length:
        fail(
            f"Insufficient capacity on {railway.code}. "
            f"Capacity: {railway.length} m, "
            f"occupied: {used} m, "
            f"additional: {additional_length} m"
        )


def load_collection(
    db: Session,
    collection_id: int,
    lock: bool = False,
) -> NaturkaCollection:
    query = select(NaturkaCollection).where(
        NaturkaCollection.id == collection_id
    )

    if lock:
        query = query.with_for_update()

    collection = db.scalar(query)

    if collection is None:
        fail("Collection not found", 404)

    db.refresh(collection, ["vagons"])

    collection.vagons.sort(
        key=lambda wagon: wagon.position
    )

    return collection


def select_sorting_railway(
    db: Session,
    length_m: int,
) -> Railway:
    railway_ids = db.scalars(
        select(Railway.id)
        .where(Railway.type == RailwayType.SORTING)
        .order_by(Railway.code, Railway.id)
    ).all()

    for railway_id in railway_ids:
        railway = get_track(
            db,
            railway_id,
            RailwayType.SORTING,
            lock=True,
        )

        free_space = railway.length - occupied_length(
            db, railway.id
        )

        if free_space >= length_m:
            return railway

    fail("No sorting railway has enough free space")


def clone_collection(
    source: NaturkaCollection,
    railway_id: int,
) -> NaturkaCollection:
    return NaturkaCollection(
        sent_station=source.sent_station,
        train_number=source.train_number,
        assigned_id=source.assigned_id,
        train_condition=source.train_condition,

        length=0,
        weight=0,

        tosish=None,
        tepa=None,
        yon=None,
        past=None,
        animal=None,

        extra=None,
        extra2=None,
        received=None,

        railway_id=railway_id,
        target_station=None,

        status="sorting",
        ready=False,
    )


def import_report(
    db: Session,
    data: ReportImport,
) -> NaturkaCollection:
    entrance = get_track(
        db,
        data.entrance_id,
        RailwayType.ENTRANCE,
        lock=True,
    )

    total_length = sum(
        wagon.length_m for wagon in data.vagons
    )

    total_weight = sum(
        wagon.product_weight for wagon in data.vagons
    )

    if (
        data.reported_length is not None
        and data.reported_length != total_length
    ):
        fail(
            "Reported length differs from total wagon length"
        )

    # Validate incoming formation against entrance capacity.
    ensure_capacity(db, entrance, total_length)

    if data.sorting_id is not None:
        sorting = get_track(
            db,
            data.sorting_id,
            RailwayType.SORTING,
            lock=True,
        )

        ensure_capacity(db, sorting, total_length)

    else:
        sorting = select_sorting_railway(
            db, total_length
        )

    collection = NaturkaCollection(
        sent_station=data.header.sent_station,
        train_number=data.header.train_number,
        assigned_id=data.header.assigned_id,
        train_condition=data.header.train_condition,

        length=total_length,
        weight=total_weight,

        tosish=None,
        tepa=None,
        yon=None,
        past=None,
        animal=None,

        extra=None,
        extra2=None,
        received=None,

        railway_id=sorting.id,
        target_station=None,

        status="sorting",
        ready=False,
    )

    db.add(collection)
    db.flush()

    for position, wagon_data in enumerate(
        data.vagons,
        start=1,
    ):
        wagon = NaturkaVagon(
            **wagon_data.model_dump(),
            collection_id=collection.id,
            position=position,
        )

        db.add(wagon)

    db.flush()

    return load_collection(db, collection.id)


def extract_range(
    db: Session,
    data: RangeExtract,
) -> NaturkaCollection:
    if data.start_position > data.end_position:
        fail("start_position cannot exceed end_position")

    source = load_collection(
        db,
        data.source_collection_id,
        lock=True,
    )

    if source.status != "sorting":
        fail("Only sorting collections can be modified")

    if source.railway_id is None:
        fail("Source collection has no railway")

    get_track(
        db,
        source.railway_id,
        RailwayType.SORTING,
        lock=True,
    )

    destination_track = get_track(
        db,
        data.destination_sorting_id,
        RailwayType.SORTING,
        lock=True,
    )

    source_vagons = sorted(
        source.vagons,
        key=lambda wagon: wagon.position,
    )

    if data.end_position > len(source_vagons):
        fail("Selected range exceeds collection length")

    selected = source_vagons[
        data.start_position - 1:data.end_position
    ]

    remaining = [
        wagon for wagon in source_vagons
        if wagon not in selected
    ]

    moved_length = sum(
        wagon.length_m for wagon in selected
    )

    if data.destination_collection_id is not None:
        destination = load_collection(
            db,
            data.destination_collection_id,
            lock=True,
        )

        if destination.id == source.id:
            fail("Source and destination must differ")

        if destination.status != "sorting":
            fail("Destination collection is not sorting")

        if destination.railway_id != destination_track.id:
            fail("Destination collection is on another track")

        destination_vagons = sorted(
            destination.vagons,
            key=lambda wagon: wagon.position,
        )

    else:
        destination = clone_collection(
            source,
            destination_track.id,
        )

        db.add(destination)
        db.flush()

        destination_vagons = []

    if source.railway_id != destination_track.id:
        ensure_capacity(
            db,
            destination_track,
            moved_length,
        )

    # Move positions temporarily outside the positive range.
    # This avoids collisions with the unique constraint.
    for wagon in source_vagons + destination_vagons:
        wagon.position = -wagon.id

    db.flush()

    # Transfer the chosen wagons directly.
    # No entrance-track movement is created.
    for wagon in selected:
        wagon.collection_id = destination.id

    db.flush()

    # Rebuild source order.
    for position, wagon in enumerate(
        remaining,
        start=1,
    ):
        wagon.position = position

    # Append selected range to destination.
    combined = destination_vagons + selected

    for position, wagon in enumerate(
        combined,
        start=1,
    ):
        wagon.position = position

    source.length = sum(
        wagon.length_m for wagon in remaining
    )

    source.weight = sum(
        wagon.product_weight for wagon in remaining
    )

    destination.length = sum(
        wagon.length_m for wagon in combined
    )

    destination.weight = sum(
        wagon.product_weight for wagon in combined
    )

    db.flush()

    return load_collection(db, destination.id)


def send_departure(
    db: Session,
    data: SendDeparture,
) -> NaturkaCollection:
    collection = load_collection(
        db,
        data.collection_id,
        lock=True,
    )

    if collection.status != "sorting":
        fail("Collection is not in sorting status")

    if collection.railway_id is None:
        fail("Collection has no sorting railway")

    get_track(
        db,
        collection.railway_id,
        RailwayType.SORTING,
        lock=True,
    )

    if not collection.vagons:
        fail("Cannot move an empty collection")

    departure = get_track(
        db,
        data.departure_railway_id,
        RailwayType.DEPARTURE,
        lock=True,
    )

    ensure_capacity(
        db,
        departure,
        collection.length,
    )

    collection.railway_id = departure.id
    collection.target_station = departure.id

    collection.tosish = data.tosish
    collection.tepa = data.tepa
    collection.yon = data.yon
    collection.past = data.past
    collection.animal = data.animal

    collection.extra = data.extra
    collection.extra2 = data.extra2
    collection.received = data.received

    # Moving to departure does NOT mark it ready.
    collection.status = "departure"
    collection.ready = False

    db.flush()

    return load_collection(db, collection.id)


def set_readiness(
    db: Session,
    collection_id: int,
    ready: bool,
) -> NaturkaCollection:
    collection = load_collection(
        db,
        collection_id,
        lock=True,
    )

    if collection.status != "departure":
        fail(
            "Readiness can only be changed "
            "on a departure railway"
        )

    if collection.railway_id is None:
        fail("Collection has no departure railway")

    get_track(
        db,
        collection.railway_id,
        RailwayType.DEPARTURE,
        lock=True,
    )

    # Explicit user decision.
    collection.ready = ready

    db.flush()

    return load_collection(db, collection.id)


def dispatch_collection(
    db: Session,
    collection_id: int,
) -> NaturkaCollection:
    collection = load_collection(
        db,
        collection_id,
        lock=True,
    )

    if collection.status != "departure":
        fail("Collection is not on a departure railway")

    if not collection.ready:
        fail("Collection has not been marked ready")

    if collection.railway_id is None:
        fail("Collection has no departure railway")

    get_track(
        db,
        collection.railway_id,
        RailwayType.DEPARTURE,
        lock=True,
    )

    # Free occupied railway capacity.
    collection.railway_id = None
    collection.status = "sent"

    # Keep ready and target_station for history.
    # Keep all wagons and collection information.
    db.flush()

    return load_collection(db, collection.id)
