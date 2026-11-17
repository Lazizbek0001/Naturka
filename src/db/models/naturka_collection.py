
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_vagon import NaturkaVagon
    from src.db.models.railway import Railway


class NaturkaCollection(Base):
    __tablename__ = "naturka_collection"

    __table_args__ = (
        CheckConstraint(
            "status IN ('sorting', 'departure', 'sent')",
            name="ck_collection_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    sent_station: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    train_number: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    assigned_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    train_condition: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    length: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    weight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Filled when moving to departure
    tosish: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    tepa: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    yon: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    past: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    animal: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    extra: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    extra2: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    received: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )

    # The current physical railway.
    # NULL after dispatch.
    railway_id: Mapped[int | None] = mapped_column(
        ForeignKey("railway.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Departure railway ID.
    # NULL while sorting.
    target_station: Mapped[int | None] = mapped_column(
        ForeignKey("railway.id", ondelete="RESTRICT"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="sorting",
        server_default="sorting",
    )

    # Explicitly controlled by the user.
    ready: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    railway: Mapped["Railway | None"] = relationship(
        "Railway",
        foreign_keys=[railway_id],
        back_populates="collections",
    )

    vagons: Mapped[list["NaturkaVagon"]] = relationship(
        "NaturkaVagon",
        back_populates="collection",
        order_by="NaturkaVagon.position",
    )
