
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_collection import NaturkaCollection


class NaturkaVagon(Base):
    __tablename__ = "naturka_vagon"

    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "position",
            name="uq_collection_vagon_position",
        ),
        CheckConstraint(
            "length_m > 0",
            name="ck_vagon_length_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    vagon_number: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    vagoon_country: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    product_weight: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    product_type: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    # Original destination from the report.
    target_station: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    vagon_condition: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    product_importance: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    ban: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    count_plomba: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    count_container: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    through_station: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    extra_data: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "naturka_collection.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    # Physical length in metres.
    length_m: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    # 1-based position within the collection.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    collection: Mapped["NaturkaCollection | None"] = relationship(
        "NaturkaCollection",
        back_populates="vagons",
    )
