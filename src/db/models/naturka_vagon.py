from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_collection import NaturkaCollection
    from src.db.models.station import Station

class NaturkaVagon(Base):
    __tablename__ = "naturka_vagon"
    __table_args__ = (
        CheckConstraint("length_m > 0", name="ck_vagon_length_m"),
        UniqueConstraint("collection_id", "position", name="uq_vagon_position_per_collection"),
        UniqueConstraint("source_vagon_id", name="uq_vagon_one_sorting_copy"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id", ondelete="RESTRICT"), nullable=False, index=True)
    station: Mapped["Station"] = relationship("Station", back_populates="vagons")
    vagon_number: Mapped[int] = mapped_column(Integer, nullable=False)
    vagon_country: Mapped[int] = mapped_column(Integer, nullable=False)
    product_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    
    target_station: Mapped[int] = mapped_column(Integer, nullable=False)
    product_type: Mapped[int] = mapped_column(Integer, nullable=False)
    punkt: Mapped[int] = mapped_column(Integer, nullable=False)

    vagon_condition: Mapped[int] = mapped_column(Integer, nullable=False)
    product_importance: Mapped[int] = mapped_column(Integer, nullable=False)
    ban: Mapped[int] = mapped_column(Integer, nullable=False)
    count_plomba: Mapped[int] = mapped_column(Integer, nullable=False)
    count_container: Mapped[str | None] = mapped_column(String(255), nullable=False)

    through_station: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_data: Mapped[str | None] = mapped_column(String(255))


    collection_id: Mapped[int | None] = mapped_column(ForeignKey("naturka_collection.id", ondelete="CASCADE"), index=True)
    source_vagon_id: Mapped[int | None] = mapped_column(ForeignKey("naturka_vagon.id", ondelete="RESTRICT"), index=True)
    length_m: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    collection: Mapped["NaturkaCollection | None"] = relationship("NaturkaCollection", back_populates="vagons")