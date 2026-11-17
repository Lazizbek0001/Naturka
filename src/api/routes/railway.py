
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps.railway import get_db

from src.db.models.railway import Railway, RailwayType
from src.db.models.naturka_collection import NaturkaCollection

from src.schemas.railway import (
    RailwayCreate,
    RailwayView,
    ReportImport,
    RangeExtract,
    SendDeparture,
    CollectionReadiness,
    DispatchCollection,
    CollectionView,
)

from src.services.railway_operations import (
    import_report,
    extract_range,
    send_departure,
    set_readiness,
    dispatch_collection,
    load_collection,
    occupied_length,
)


router = APIRouter(
    prefix="/railways",
    tags=["Railways"],
)


@router.post(
    "",
    response_model=RailwayView,
    status_code=201,
)
def create_railway(
    payload: RailwayCreate,
    db: Session = Depends(get_db),
):
    if payload.type == RailwayType.DIRECT:
        if payload.length is not None:
            raise HTTPException(
                400,
                "Direct railway cannot have length",
            )

        existing = db.scalar(
            select(Railway.id).where(
                Railway.type == RailwayType.DIRECT
            )
        )

        if existing is not None:
            raise HTTPException(
                409,
                "Only one direct railway is allowed",
            )

    elif payload.length is None or payload.length <= 0:
        raise HTTPException(
            400,
            "Railway length must be positive",
        )

    railway = Railway(**payload.model_dump())
    db.add(railway)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Railway already exists or violates a constraint",
        )

    db.refresh(railway)
    return railway


@router.get(
    "",
    response_model=list[RailwayView],
)
def list_railways(
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(Railway).order_by(
            Railway.type,
            Railway.code,
        )
    ).all()


@router.get("/{railway_id}")
def get_railway(
    railway_id: int,
    db: Session = Depends(get_db),
):
    railway = db.get(Railway, railway_id)

    if railway is None:
        raise HTTPException(404, "Railway not found")

    collections = db.scalars(
        select(NaturkaCollection)
        .where(NaturkaCollection.railway_id == railway_id)
        .order_by(NaturkaCollection.id)
    ).all()

    used = occupied_length(db, railway_id)

    return {
        "id": railway.id,
        "code": railway.code,
        "type": railway.type,
        "length": railway.length,
        "occupied_length": used,
        "available_length": (
            railway.length - used
            if railway.length is not None
            else None
        ),
        "collections": [
            {
                "id": collection.id,
                "train_number": collection.train_number,
                "length": collection.length,
                "weight": collection.weight,
                "status": collection.status,
                "ready": collection.ready,
                "target_station": collection.target_station,
            }
            for collection in collections
        ],
    }


@router.get(
    "/collections/{collection_id}",
    response_model=CollectionView,
)
def get_collection(
    collection_id: int,
    db: Session = Depends(get_db),
):
    return load_collection(db, collection_id)


@router.post(
    "/import-report",
    response_model=CollectionView,
    status_code=201,
)
def receive_report(
    payload: ReportImport,
    db: Session = Depends(get_db),
):
    with db.begin():
        collection = import_report(db, payload)
        collection_id = collection.id

    return load_collection(db, collection_id)


@router.post(
    "/extract-range",
    response_model=CollectionView,
)
def extract_wagons(
    payload: RangeExtract,
    db: Session = Depends(get_db),
):
    with db.begin():
        collection = extract_range(db, payload)
        collection_id = collection.id

    return load_collection(db, collection_id)


@router.post(
    "/send-to-departure",
    response_model=CollectionView,
)
def transfer_to_departure(
    payload: SendDeparture,
    db: Session = Depends(get_db),
):
    with db.begin():
        collection = send_departure(db, payload)
        collection_id = collection.id

    return load_collection(db, collection_id)


@router.patch(
    "/collections/{collection_id}/readiness",
    response_model=CollectionView,
)
def update_readiness(
    collection_id: int,
    payload: CollectionReadiness,
    db: Session = Depends(get_db),
):
    with db.begin():
        collection = set_readiness(
            db,
            collection_id,
            payload.ready,
        )
        result_id = collection.id

    return load_collection(db, result_id)


@router.post(
    "/dispatch",
    response_model=CollectionView,
)
def dispatch_ready_collection(
    payload: DispatchCollection,
    db: Session = Depends(get_db),
):
    with db.begin():
        collection = dispatch_collection(
            db,
            payload.collection_id,
        )
        collection_id = collection.id

    return load_collection(db, collection_id)
