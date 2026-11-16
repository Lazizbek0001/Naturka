from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_vagon import NaturkaVagon


class RailwayType(IntEnum):
    ENTRANCE = 1  # trains arrive here
    SORTING = 2  # between entrance and departure
    DEPARTURE = 3  # trains leave from here
    CONNECTING = 4  # links entrance directly to departure


class Railway(Base):
    __tablename__ = "railway"
    __table_args__ = (UniqueConstraint("type", "code", name="uq_railway_type_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Railway number inside its type, e.g. "43".
    code: Mapped[str] = mapped_column(String(255), nullable=False)
    length: Mapped[int] = mapped_column(Integer, nullable=False)
    # One of RailwayType.
    type: Mapped[int] = mapped_column(Integer, nullable=False)

    vagons: Mapped[list["NaturkaVagon"]] = relationship(
        "NaturkaVagon",
        back_populates="railway",
        order_by="NaturkaVagon.position",
    )
