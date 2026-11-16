from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models.movement import Movement
from src.db.models.naturka_train import NaturkaTrain
from src.db.models.railway import Railway, RailwayType
from src.db.session import get_db
from src.schemas.yard import (
    MovementCreate,
    MovementOut,
    RailwayCreate,
    RailwayOut,
    RailwayWithVagons,
    TrainArrive,
    TrainOut,
)
from src.services import yard
from src.services.naturka_parser import NaturkaParseError

router = APIRouter()


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, yard.NotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, NaturkaParseError):
        return HTTPException(422, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post(
    "/railways",
    response_model=RailwayOut,
    status_code=status.HTTP_201_CREATED,
    tags=["railways"],
)
def create_railway(data: RailwayCreate, db: Session = Depends(get_db)) -> Railway:
    railway = Railway(code=data.code, length=data.length, type=int(data.type))
    db.add(railway)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{data.type.name.lower()} railway {data.code} already exists",
        )
    db.refresh(railway)
    return railway


@router.get("/railways", response_model=list[RailwayOut], tags=["railways"])
def list_railways(
    type: RailwayType | None = None, db: Session = Depends(get_db)
) -> list[Railway]:
    query = select(Railway).order_by(Railway.type, Railway.id)
    if type is not None:
        query = query.where(Railway.type == int(type))
    return list(db.scalars(query))


@router.get(
    "/railways/{railway_id}", response_model=RailwayWithVagons, tags=["railways"]
)
def get_railway(railway_id: int, db: Session = Depends(get_db)) -> Railway:
    """A railway with the vagons standing on it, in order."""
    try:
        return yard.get_railway(db, railway_id)
    except yard.YardError as exc:
        raise _http_error(exc)


@router.post(
    "/trains/arrive",
    response_model=TrainOut,
    status_code=status.HTTP_201_CREATED,
    tags=["trains"],
)
def arrive_train(data: TrainArrive, db: Session = Depends(get_db)) -> NaturkaTrain:
    """Register a train from its naturka report on an entrance railway."""
    try:
        return yard.arrive_train(db, data.report, data.entrance_railway_id)
    except (yard.YardError, NaturkaParseError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/trains/{train_id}", response_model=TrainOut, tags=["trains"])
def get_train(train_id: int, db: Session = Depends(get_db)) -> NaturkaTrain:
    train = db.get(NaturkaTrain, train_id)
    if train is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"train {train_id} not found")
    return train


@router.post(
    "/movements",
    response_model=MovementOut,
    status_code=status.HTTP_201_CREATED,
    tags=["movements"],
)
def move_vagons(data: MovementCreate, db: Session = Depends(get_db)) -> Movement:
    """Move vagons: entrance -> sorting, sorting -> sorting (back through the
    entrance), sorting -> departure, entrance -> connecting -> departure."""
    try:
        return yard.move_vagons(
            db,
            to_railway_id=data.to_railway_id,
            vagon_ids=data.vagon_ids,
            from_railway_id=data.from_railway_id,
            via_railway_id=data.via_railway_id,
        )
    except yard.YardError as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/movements", response_model=list[MovementOut], tags=["movements"])
def list_movements(db: Session = Depends(get_db)) -> list[Movement]:
    return list(db.scalars(select(Movement).order_by(Movement.id)))
