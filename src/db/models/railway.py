from __future__ import annotations
from enum import IntEnum
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_collection import NaturkaCollection
    from src.db.models.station import Station

class RailwayType(IntEnum):
    ENTRANCE = 1
    SORTING = 2
    DEPARTURE = 3
    DIRECT = 4

class Railway(Base):
    __tablename__ = "railway"
    __table_args__ = (
        CheckConstraint("type IN (1,2,3,4)", name="ck_railway_type"),
        CheckConstraint("(type = 4 AND length IS NULL) OR (type IN (1,2,3) AND length > 0)", name="ck_railway_length"),
        UniqueConstraint("station_id", "code", name="uq_railway_code_per_station"),
        Index("uq_single_direct_railway_per_station", "station_id", unique=True,
              postgresql_where=text("type = 4"), sqlite_where=text("type = 4")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(255), nullable=False)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id", ondelete="RESTRICT"), nullable=False, index=True)
    station: Mapped["Station"] = relationship("Station", back_populates="railways")
    length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[int] = mapped_column(Integer, nullable=False)
    collections: Mapped[list["NaturkaCollection"]] = relationship(
        "NaturkaCollection", foreign_keys="NaturkaCollection.railway_id", back_populates="railway")