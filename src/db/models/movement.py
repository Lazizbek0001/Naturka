from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_vagon import NaturkaVagon
    from src.db.models.railway import Railway


class MovementKind(StrEnum):
    ARRIVAL = "arrival"  # outside -> entrance
    TO_SORTING = "to_sorting"  # entrance -> sorting
    SHUNT = "shunt"  # sorting -> back to entrance -> another sorting
    TO_CONNECTING = "to_connecting"  # entrance -> connecting
    TO_DEPARTURE = "to_departure"  # sorting / connecting -> departure


movement_vagon = Table(
    "movement_vagon",
    Base.metadata,
    Column(
        "movement_id",
        ForeignKey("movement.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "vagon_id",
        ForeignKey("naturka_vagon.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Movement(Base):
    """One move of a group of vagons from one railway to another."""

    __tablename__ = "movement"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)

    from_railway_id: Mapped[int | None] = mapped_column(
        ForeignKey("railway.id", ondelete="SET NULL"), nullable=True
    )
    # Entrance railway the vagons are pulled back to during a shunt.
    via_railway_id: Mapped[int | None] = mapped_column(
        ForeignKey("railway.id", ondelete="SET NULL"), nullable=True
    )
    to_railway_id: Mapped[int | None] = mapped_column(
        ForeignKey("railway.id", ondelete="SET NULL"), nullable=True
    )

    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    from_railway: Mapped["Railway | None"] = relationship(
        "Railway", foreign_keys=[from_railway_id]
    )
    via_railway: Mapped["Railway | None"] = relationship(
        "Railway", foreign_keys=[via_railway_id]
    )
    to_railway: Mapped["Railway | None"] = relationship(
        "Railway", foreign_keys=[to_railway_id]
    )
    vagons: Mapped[list["NaturkaVagon"]] = relationship(
        "NaturkaVagon",
        secondary=movement_vagon,
        order_by="NaturkaVagon.order_number",
    )
