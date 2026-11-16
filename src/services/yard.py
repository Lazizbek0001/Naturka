"""Yard movements: arrival, sorting, shunting and departure of vagons."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models.movement import Movement, MovementKind
from src.db.models.naturka_train import NaturkaTrain
from src.db.models.naturka_vagon import NaturkaVagon
from src.db.models.railway import Railway, RailwayType
from src.services.naturka_parser import parse_naturka


class YardError(Exception):
    """A movement that the yard layout does not allow."""


class NotFoundError(YardError):
    pass


# (from type, to type) -> kind of movement. Anything else is not possible.
_ALLOWED: dict[tuple[RailwayType, RailwayType], MovementKind] = {
    (RailwayType.ENTRANCE, RailwayType.SORTING): MovementKind.TO_SORTING,
    (RailwayType.SORTING, RailwayType.SORTING): MovementKind.SHUNT,
    (RailwayType.SORTING, RailwayType.DEPARTURE): MovementKind.TO_DEPARTURE,
    (RailwayType.ENTRANCE, RailwayType.CONNECTING): MovementKind.TO_CONNECTING,
    (RailwayType.CONNECTING, RailwayType.DEPARTURE): MovementKind.TO_DEPARTURE,
}


def get_railway(db: Session, railway_id: int) -> Railway:
    railway = db.get(Railway, railway_id)
    if railway is None:
        raise NotFoundError(f"railway {railway_id} not found")
    return railway


def _place(db: Session, vagons: Sequence[NaturkaVagon], railway: Railway) -> None:
    """Put vagons at the end of the railway, keeping their order."""
    last = db.scalar(
        select(func.max(NaturkaVagon.position)).where(
            NaturkaVagon.railway_id == railway.id
        )
    )
    for offset, vagon in enumerate(vagons, start=1):
        vagon.railway_id = railway.id
        vagon.position = (last or 0) + offset


def arrive_train(db: Session, report: str, entrance_railway_id: int) -> NaturkaTrain:
    """A train from the naturka report arrives on an entrance railway."""
    entrance = get_railway(db, entrance_railway_id)
    if entrance.type != RailwayType.ENTRANCE:
        raise YardError(f"railway {entrance.code} is not an entrance railway")

    train = parse_naturka(report)
    db.add(train)
    db.flush()
    _place(db, train.vagons, entrance)
    db.add(
        Movement(
            kind=MovementKind.ARRIVAL,
            to_railway_id=entrance.id,
            vagons=list(train.vagons),
        )
    )
    db.commit()
    db.refresh(train)
    return train


def _arrival_railway(db: Session, vagon: NaturkaVagon) -> Railway | None:
    """Entrance railway on which the vagon came into the yard."""
    return db.scalar(
        select(Railway)
        .join(Movement, Movement.to_railway_id == Railway.id)
        .where(
            Movement.kind == MovementKind.ARRIVAL,
            Movement.vagons.any(NaturkaVagon.id == vagon.id),
        )
        .order_by(Movement.id.desc())
        .limit(1)
    )


def move_vagons(
    db: Session,
    to_railway_id: int,
    vagon_ids: Sequence[int] | None = None,
    from_railway_id: int | None = None,
    via_railway_id: int | None = None,
) -> Movement:
    """Move vagons to another railway.

    Either ``vagon_ids`` (any vagons standing on one railway) or
    ``from_railway_id`` (every vagon on that railway) selects what moves.
    Sorting -> sorting is a shunt: the vagons are pulled back to an entrance
    railway (``via_railway_id``, by default the one they arrived on) and then
    pushed to the target sorting railway.
    """
    target = get_railway(db, to_railway_id)

    query = select(NaturkaVagon).order_by(NaturkaVagon.position, NaturkaVagon.id)
    if vagon_ids:
        wanted = set(vagon_ids)
        vagons = list(db.scalars(query.where(NaturkaVagon.id.in_(wanted))))
        missing = wanted - {vagon.id for vagon in vagons}
        if missing:
            raise NotFoundError(f"vagons not found: {sorted(missing)}")
    elif from_railway_id is not None:
        get_railway(db, from_railway_id)
        vagons = list(
            db.scalars(query.where(NaturkaVagon.railway_id == from_railway_id))
        )
        if not vagons:
            raise YardError("there are no vagons on the source railway")
    else:
        raise YardError("vagon_ids or from_railway_id is required")

    sources = {vagon.railway_id for vagon in vagons}
    if None in sources:
        raise YardError("some of the vagons are not in the yard")
    if len(sources) > 1:
        raise YardError("vagons must all stand on the same railway")
    source = get_railway(db, sources.pop())
    if from_railway_id is not None and source.id != from_railway_id:
        raise YardError(f"the vagons are not on railway {from_railway_id}")
    if source.id == target.id:
        raise YardError(f"the vagons are already on railway {target.code}")

    kind = _ALLOWED.get((RailwayType(source.type), RailwayType(target.type)))
    if kind is None:
        raise YardError(
            f"cannot move from {RailwayType(source.type).name.lower()} railway "
            f"{source.code} to {RailwayType(target.type).name.lower()} railway "
            f"{target.code}"
        )

    via: Railway | None = None
    if kind is MovementKind.SHUNT:
        via = (
            get_railway(db, via_railway_id)
            if via_railway_id is not None
            else _arrival_railway(db, vagons[0])
        )
        if via is None:
            raise YardError("via_railway_id (an entrance railway) is required")
        if via.type != RailwayType.ENTRANCE:
            raise YardError(f"railway {via.code} is not an entrance railway")
    elif via_railway_id is not None:
        raise YardError(
            "via_railway_id is only used when shunting between sorting railways"
        )

    _place(db, vagons, target)
    movement = Movement(
        kind=kind,
        from_railway_id=source.id,
        via_railway_id=via.id if via else None,
        to_railway_id=target.id,
        vagons=vagons,
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement
