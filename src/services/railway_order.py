"""Порядок путей внутри станции (Railway.position = 1, 2, 3, …)."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Railway


def _natural(code: str):
    """«2», «10», «IIВП» — числа по значению, остальное по алфавиту."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", code or "")]


def station_railways(db: Session, station_id: int) -> list[Railway]:
    """Пути станции в текущем порядке: с позицией — по ней, без позиции — в конце (тип, номер)."""
    rows = db.scalars(select(Railway).where(Railway.station_id == station_id)).all()
    return sorted(rows, key=lambda r: (r.position is None, r.position or 0, r.type, _natural(r.code)))


def renumber(rows: list[Railway]) -> None:
    for i, r in enumerate(rows, 1):
        r.position = i


def place_railway(db: Session, railway: Railway, position: int | None) -> None:
    """Поставить путь на место position (1 — первым); None — в конец. Остальные пути станции сдвигаются."""
    rows = [r for r in station_railways(db, railway.station_id) if r.id != railway.id]
    idx = len(rows) if position is None else max(0, min(len(rows), position - 1))
    rows.insert(idx, railway)
    renumber(rows)


def set_order(db: Session, station_id: int, ids: list[int]) -> list[Railway]:
    """Новый порядок всех путей станции: ids — все id путей станции в нужном порядке."""
    rows = station_railways(db, station_id)
    by_id = {r.id: r for r in rows}
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ValueError("ids must list every railway of the station exactly once")
    ordered = [by_id[i] for i in ids]
    renumber(ordered)
    return ordered


def backfill_positions(db: Session) -> None:
    """При запуске: путям без позиции — позиции по текущему порядку (у каждой станции свой счёт)."""
    stations = {sid for sid, in db.execute(select(Railway.station_id).where(Railway.position.is_(None))).all()}
    for sid in stations:
        renumber(station_railways(db, sid))
    if stations:
        db.commit()
