from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_train import NaturkaTrain
    from src.db.models.railway import Railway


class NaturkaVagon(Base):
    __tablename__ = "naturka_vagon"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Ordinal number of the vagon in the naturka report (01, 02, ...).
    order_number: Mapped[int] = mapped_column(Integer, nullable=False)
    vagon_number: Mapped[int] = mapped_column(Integer, nullable=False)
    vagoon_country: Mapped[int] = mapped_column(Integer, nullable=False)
    product_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    given_station: Mapped[int] = mapped_column(Integer, nullable=False)
    product_type: Mapped[int] = mapped_column(Integer, nullable=False)
    target_station: Mapped[int] = mapped_column(Integer, nullable=False)
    vagon_condition: Mapped[int] = mapped_column(Integer, nullable=False)
    product_importance: Mapped[int] = mapped_column(Integer, nullable=False)
    ban: Mapped[int] = mapped_column(Integer, nullable=False)
    count_plomba: Mapped[int] = mapped_column(Integer, nullable=False)
    count_container: Mapped[int] = mapped_column(Integer, nullable=False)
    through_station: Mapped[int] = mapped_column(Integer, nullable=False)

    extra_data: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    train_id: Mapped[int] = mapped_column(
        ForeignKey("naturka_train.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    train: Mapped["NaturkaTrain"] = relationship(
        "NaturkaTrain",
        back_populates="vagons",
    )

    # Where the vagon stands right now (None = not in the yard).
    railway_id: Mapped[int | None] = mapped_column(
        ForeignKey("railway.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Order of the vagon on its current railway, counted from the entrance side.
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    railway: Mapped["Railway | None"] = relationship(
        "Railway",
        back_populates="vagons",
    )
