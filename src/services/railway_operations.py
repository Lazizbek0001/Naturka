from __future__ import annotations
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from src.db.models import Railway, RailwayType, NaturkaCollection, NaturkaVagon, MessageIdCounter
from src.schemas.railway import ReportImport, MoveToSorting, RangeExtract, SendDeparture, ReorderWagons, MoveWagonPosition, InsertExistingWagons


def fail(message: str, code: int = 400):
    raise HTTPException(status_code=code, detail=message)


def track(db: Session, track_id: int, kind: RailwayType | None = None) -> Railway:
    result = db.get(Railway, track_id)
    if result is None:
        fail("Railway not found", 404)
    if kind is not None and result.type != int(kind):
        fail(f"Railway must be {kind.name}")
    return result


def lock_tracks(db: Session, *track_ids: int | None) -> None:
    """Use a stable lock order in PostgreSQL for every occupancy-changing operation."""
    ids = sorted({i for i in track_ids if i is not None})
    if ids:
        rows = db.scalars(select(Railway).where(Railway.id.in_(ids)).order_by(Railway.id).with_for_update()).all()
        if len(rows) != len(ids):
            fail("Railway not found", 404)


def load_collection(db: Session, collection_id: int) -> NaturkaCollection:
    c = db.scalar(select(NaturkaCollection).where(NaturkaCollection.id == collection_id)
                  .options(selectinload(NaturkaCollection.vagons)).execution_options(populate_existing=True))
    if c is None:
        fail("Collection not found", 404)
    return c


def occupied_length(db: Session, railway_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(NaturkaCollection.length), 0)).where(
        NaturkaCollection.railway_id == railway_id,
        NaturkaCollection.hidden.is_(False),
        NaturkaCollection.status.in_(("entrance", "sorting", "departure")),
    )) or 0)


def ensure_space(db: Session, railway: Railway, additional: int) -> None:
    if railway.length is None:
        fail("Direct railway cannot hold a collection")
    if occupied_length(db, railway.id) + additional > railway.length:
        fail(f"Insufficient space on {railway.code}: need {additional} m", 409)


def allocate_message_id(db: Session, station_id: int) -> int:
    """Allocate a reusable 1..999 message ID within a single station.

    PostgreSQL serializes same-station allocations via the counter row.
    Seed a counter when creating the station (in the same transaction).
    """
    counter = db.scalar(select(MessageIdCounter).where(
        MessageIdCounter.station_id == station_id
    ).with_for_update())
    if counter is None:
        fail("Station message ID counter is missing; create it through station setup", 500)
    active = set(db.scalars(select(NaturkaCollection.message_id).where(
        NaturkaCollection.station_id == station_id,
        NaturkaCollection.message_id.is_not(None),
        NaturkaCollection.hidden.is_(False),
        NaturkaCollection.status.in_(("entrance", "departure")),
    )).all())
    for _ in range(999):
        candidate = (counter.last_assigned % 999) + 1
        counter.last_assigned = candidate
        if candidate not in active:
            db.flush()
            return candidate
    fail("All 999 active message IDs at this station are allocated", 409)


def require_same_station(source_station_id: int, railway: Railway) -> None:
    if source_station_id != railway.station_id:
        fail("Cross-station wagon movement is not supported", 409)


def sorting_batch(db: Session, railway_id: int) -> NaturkaCollection | None:
    batches = db.scalars(select(NaturkaCollection).where(
        NaturkaCollection.railway_id == railway_id,
        NaturkaCollection.status == "sorting",
    ).with_for_update()).all()
    if len(batches) > 1:
        fail("Multiple sorting collections exist; clean up old data", 409)
    return batches[0] if batches else None


def create_sorting_batch(db: Session, railway_id: int, source_id: int) -> NaturkaCollection:
    source = load_collection(db, source_id)
    batch = NaturkaCollection(
        station_id=source.station_id,
        railway_id=railway_id, source_collection_id=source_id,
        length=0, weight=0, received=True, ready=False,
        hidden=False, status="sorting", target_station=None,
    )
    db.add(batch)
    db.flush()
    return batch


WAGON_COPY_FIELDS = (
    "vagon_number", "vagon_country", "product_weight", "product_type", "punkt",
    "target_station", "vagon_condition", "product_importance", "ban",
    "count_plomba", "count_container", "through_station", "extra_data", "length_m", "vagon_type",
)


def recalc(batch: NaturkaCollection, wagons: list[NaturkaVagon]) -> None:
    batch.length = sum(w.length_m for w in wagons)
    batch.weight = sum(w.product_weight for w in wagons)


def import_report(db: Session, request: ReportImport) -> NaturkaCollection:
    lock_tracks(db, request.entrance_id)
    entrance = track(db, request.entrance_id, RailwayType.ENTRANCE)
    # Incoming report length/weight are authoritative. Do NOT calculate/overwrite them.
    ensure_space(db, entrance, request.header.length)
    # Entrance message_id is supplied by user, never allocated here.
    incoming_id = request.header.message_id
    active_id = db.scalar(select(NaturkaCollection.id).where(
        NaturkaCollection.station_id == entrance.station_id,
        NaturkaCollection.message_id == incoming_id,
        NaturkaCollection.hidden.is_(False),
        NaturkaCollection.status.in_(("entrance", "departure")),
    ))
    if active_id is not None:
        fail("This message_id is already active at this station", 409)
    batch = NaturkaCollection(
        **request.header.model_dump(),
        station_id=entrance.station_id,
        railway_id=entrance.id, status="entrance", hidden=False,
        received=True, ready=False,
    )
    db.add(batch)
    db.flush()
    for i, wagon in enumerate(request.vagons, start=1):
        db.add(NaturkaVagon(**wagon.model_dump(), station_id=entrance.station_id, collection_id=batch.id, position=i))
    db.flush()
    return load_collection(db, batch.id)


def move_to_sorting(db: Session, request: MoveToSorting) -> NaturkaCollection:
    original = load_collection(db, request.collection_id)
    if original.status != "entrance" or original.hidden or original.railway_id is None:
        fail("Source must be a visible entrance collection")
    lock_tracks(db, original.railway_id, request.sorting_railway_id)
    track(db, original.railway_id, RailwayType.ENTRANCE)
    target = track(db, request.sorting_railway_id, RailwayType.SORTING)
    require_same_station(original.station_id, target)
    # The row lock below serializes movements from the SAME original.
    db.scalar(select(NaturkaCollection).where(NaturkaCollection.id == original.id).with_for_update())
    original = load_collection(db, original.id)
    wagons = sorted(original.vagons, key=lambda w: w.position)
    if request.start_position is None:
        chosen = wagons
    else:
        chosen = [w for w in wagons if request.start_position <= w.position <= request.end_position]
        if len(chosen) != request.end_position - request.start_position + 1:
            fail("Requested range contains missing positions")
    if not chosen:
        fail("No wagons selected")
    # Global source_vagon_id uniqueness prevents assigning the same original twice.
    selected_ids = [w.id for w in chosen]
    previously_copied = set(db.scalars(select(NaturkaVagon.source_vagon_id).where(
        NaturkaVagon.source_vagon_id.in_(selected_ids)
    )).all())
    chosen = [w for w in chosen if w.id not in previously_copied] if request.start_position is None else chosen
    if request.start_position is not None and any(w.id in previously_copied for w in chosen):
        fail("Selected wagon has already been assigned to sorting", 409)
    if not chosen:
        fail("All wagons from this entrance collection are already assigned", 409)
    additional = sum(w.length_m for w in chosen)
    ensure_space(db, target, additional)
    batch = sorting_batch(db, target.id)
    if batch is None:
        batch = create_sorting_batch(db, target.id, original.id)
    existing = list(db.scalars(select(NaturkaVagon).where(
        NaturkaVagon.collection_id == batch.id).order_by(NaturkaVagon.position)).all())
    for pos, original_wagon in enumerate(chosen, start=len(existing) + 1):
        copied = NaturkaVagon(**{name: getattr(original_wagon, name) for name in WAGON_COPY_FIELDS},
                             station_id=original.station_id,
                             collection_id=batch.id, source_vagon_id=original_wagon.id, position=pos)
        db.add(copied)
    db.flush()
    new_wagons = list(db.scalars(select(NaturkaVagon).where(NaturkaVagon.collection_id == batch.id)).all())
    recalc(batch, new_wagons)
    db.flush()
    copied_ids = set(db.scalars(select(NaturkaVagon.source_vagon_id).where(
        NaturkaVagon.source_vagon_id.in_([w.id for w in wagons])
    )).all())
    if all(w.id in copied_ids for w in wagons):
        original.hidden = True
        original.status = "original"
        original.railway_id = None
    db.flush()
    return load_collection(db, batch.id)


def extract_range(db: Session, request: RangeExtract) -> NaturkaCollection:
    if request.start_position > request.end_position:
        fail("Invalid position range")
    source = load_collection(db, request.source_collection_id)
    if source.status != "sorting" or source.railway_id is None:
        fail("Source must be an active sorting collection")
    if source.railway_id == request.destination_sorting_id:
        fail("Choose a different sorting railway")
    lock_tracks(db, source.railway_id, request.destination_sorting_id)
    target = track(db, request.destination_sorting_id, RailwayType.SORTING)
    require_same_station(source.station_id, target)
    source = load_collection(db, source.id)
    wagons = sorted(source.vagons, key=lambda w: w.position)
    if request.end_position > len(wagons):
        fail("Range exceeds wagon count")
    moved = wagons[request.start_position - 1:request.end_position]
    remaining = wagons[:request.start_position - 1] + wagons[request.end_position:]
    ensure_space(db, target, sum(w.length_m for w in moved))
    dest = sorting_batch(db, target.id)
    if dest is None:
        if request.destination_collection_id is not None:
            fail("Requested destination batch does not exist", 409)
        dest = create_sorting_batch(db, target.id, source.source_collection_id or source.id)
    elif request.destination_collection_id not in (None, dest.id):
        fail("Destination track has a different active batch", 409)
    existing = list(db.scalars(select(NaturkaVagon).where(
        NaturkaVagon.collection_id == dest.id).order_by(NaturkaVagon.position)).all())
    for wagon in wagons + existing:
        wagon.position = -wagon.id
    db.flush()
    for wagon in moved:
        wagon.collection_id = dest.id
    db.flush()
    for i, wagon in enumerate(remaining, start=1):
        wagon.position = i
    for i, wagon in enumerate(existing + moved, start=1):
        wagon.position = i
    recalc(dest, existing + moved)
    if remaining:
        recalc(source, remaining)
    else:
        # Persist reassignment before deleting the old parent.
        # Otherwise a loaded source.vagons relationship may null out moved FKs.
        db.flush()
        db.expire(source, ["vagons"])
        db.delete(source)
    db.flush()
    return load_collection(db, dest.id)


def send_departure(db: Session, request: SendDeparture) -> NaturkaCollection:
    batch = load_collection(db, request.collection_id)
    if batch.status != "sorting" or batch.railway_id is None or not batch.vagons:
        fail("Only a nonempty sorting batch can move to departure")
    lock_tracks(db, batch.railway_id, request.departure_railway_id)
    track(db, batch.railway_id, RailwayType.SORTING)
    departure = track(db, request.departure_railway_id, RailwayType.DEPARTURE)
    require_same_station(batch.station_id, departure)
    ensure_space(db, departure, batch.length)
    batch.message_id = allocate_message_id(db, batch.station_id)
    for field in ("message_station", "train_number", "sent_station", "target_station", "train_condition",
                  "tosish", "tepa", "yon", "past", "animal", "extra", "extra2"):
        setattr(batch, field, getattr(request, field))
    batch.railway_id = departure.id
    batch.status = "departure"
    batch.ready = False  # Never automatic
    db.flush()
    return load_collection(db, batch.id)


def set_readiness(db: Session, collection_id: int, ready: bool) -> NaturkaCollection:
    batch = load_collection(db, collection_id)
    if batch.status != "departure" or batch.railway_id is None:
        fail("Only departure collections can be marked ready")
    lock_tracks(db, batch.railway_id)
    batch.ready = ready
    db.flush()
    return load_collection(db, batch.id)


def dispatch(db: Session, collection_id: int) -> NaturkaCollection:
    batch = load_collection(db, collection_id)
    if batch.status != "departure" or not batch.ready or batch.railway_id is None:
        fail("Collection is not ready for dispatch")
    lock_tracks(db, batch.railway_id)
    batch.railway_id = None
    batch.status = "sent"
    db.flush()
    return load_collection(db, batch.id)


# --- Wagon ordering and insertion ---
def editable_batch(db: Session, collection_id: int) -> NaturkaCollection:
    batch = load_collection(db, collection_id)
    if batch.status not in ("sorting", "departure") or batch.railway_id is None:
        fail("Wagons can only be edited on sorting or departure tracks")
    lock_tracks(db, batch.railway_id)
    # Avoid race with readiness and dispatch changes.
    db.scalar(select(NaturkaCollection).where(
        NaturkaCollection.id == collection_id
    ).with_for_update())
    batch = load_collection(db, collection_id)
    if batch.status == "departure" and batch.ready:
        fail("Unmark the collection as ready before editing its wagons", 409)
    return batch


def save_wagon_order(db: Session, ordered: list[NaturkaVagon]) -> None:
    """Two-phase update avoids (collection_id, position) UNIQUE collisions."""
    for wagon in ordered:
        wagon.position = -wagon.id
    db.flush()
    for position, wagon in enumerate(ordered, 1):
        wagon.position = position
    db.flush()


def reorder_wagons(db: Session, collection_id: int, request: ReorderWagons) -> NaturkaCollection:
    batch = editable_batch(db, collection_id)
    existing = sorted(batch.vagons, key=lambda w: w.position)
    actual_ids = [w.id for w in existing]
    if len(request.wagon_ids) != len(actual_ids) or set(request.wagon_ids) != set(actual_ids):
        fail("wagon_ids must contain each wagon in this collection exactly once")
    by_id = {w.id: w for w in existing}
    save_wagon_order(db, [by_id[i] for i in request.wagon_ids])
    return load_collection(db, collection_id)


def move_wagon_position(db: Session, collection_id: int, request: MoveWagonPosition) -> NaturkaCollection:
    batch = editable_batch(db, collection_id)
    ordered = sorted(batch.vagons, key=lambda w: w.position)
    if not 1 <= request.new_position <= len(ordered):
        fail("new_position out of range")
    wagon = next((w for w in ordered if w.id == request.wagon_id), None)
    if wagon is None:
        fail("Wagon does not belong to this collection", 404)
    ordered.remove(wagon)
    ordered.insert(request.new_position - 1, wagon)
    save_wagon_order(db, ordered)
    return load_collection(db, collection_id)


def insert_existing_wagons(db: Session, destination_collection_id: int, request: InsertExistingWagons) -> NaturkaCollection:
    """Move an existing contiguous wagon range into a specified position.

    Sorting -> sorting and non-ready departure <-> sorting/departure are allowed.
    No new wagon rows are created. A whole-source departure batch cannot vanish
    silently: empty departure batches are rejected, but empty sorting batches are deleted.
    """
    if request.source_collection_id == destination_collection_id:
        fail("Use /wagons/move or /wagons/order for the same collection")
    if request.start_position > request.end_position:
        fail("Invalid wagon range")
    src = load_collection(db, request.source_collection_id)
    dst = load_collection(db, destination_collection_id)
    if src.station_id != dst.station_id:
        fail("Cross-station transfer forbidden", 403)
    if src.railway_id is None or dst.railway_id is None:
        fail("Both collections must occupy a railway")
    lock_tracks(db, src.railway_id, dst.railway_id)
    # Lock collection rows in deterministic order as well.
    db.scalars(select(NaturkaCollection).where(NaturkaCollection.id.in_(sorted((src.id, dst.id))))
               .order_by(NaturkaCollection.id).with_for_update()).all()
    src = load_collection(db, src.id)
    dst = load_collection(db, dst.id)
    for c in (src, dst):
        if c.status not in ("sorting", "departure") or (c.status == "departure" and c.ready):
            fail("Only sorting and not-ready departure collections can be edited", 409)
        t = track(db, c.railway_id)
        require_same_station(c.station_id, t)
    source_order = sorted(src.vagons, key=lambda w: w.position)
    dest_order = sorted(dst.vagons, key=lambda w: w.position)
    if request.end_position > len(source_order):
        fail("Selected range exceeds source wagon count")
    if not 1 <= request.destination_position <= len(dest_order) + 1:
        fail("Invalid destination position")
    moving = source_order[request.start_position - 1:request.end_position]
    keep = source_order[:request.start_position - 1] + source_order[request.end_position:]
    if not keep and src.status == "departure":
        fail("Cannot empty a departure collection; change its status through the departure workflow", 409)
    moved_len = sum(w.length_m for w in moving)
    if src.railway_id != dst.railway_id:
        ensure_space(db, track(db, dst.railway_id), moved_len)
    # A sorting track has one collection; destination selection must not create two.
    new_dest = dest_order[:request.destination_position - 1] + moving + dest_order[request.destination_position - 1:]
    for w in source_order + dest_order:
        w.position = -w.id
    db.flush()
    for w in moving:
        w.collection_id = dst.id
    db.flush()
    for position, wagon in enumerate(keep, 1):
        wagon.position = position
    for position, wagon in enumerate(new_dest, 1):
        wagon.position = position
    recalc(dst, new_dest)
    if keep:
        recalc(src, keep)
    else:
        db.flush()
        db.expire(src, ["vagons"])
        db.delete(src)
    db.flush()
    return load_collection(db, dst.id)