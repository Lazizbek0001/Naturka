from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.railway import Railway
    from src.db.models.station import Station
    from src.db.models.naturka_vagon import NaturkaVagon

class NaturkaCollection(Base):
    __tablename__ = "naturka_collection"
    __table_args__ = (
        CheckConstraint("status IN ('entrance','original','sorting','departure','sent')", name="ck_collection_status"),
        CheckConstraint("message_id IS NULL OR message_id BETWEEN 1 AND 999", name="ck_message_id_range"),
        Index("uq_active_message_id_per_station", "station_id", "message_id", unique=True,
              postgresql_where=text("message_id IS NOT NULL AND hidden = false AND status IN ('entrance','departure')"),
              sqlite_where=text("message_id IS NOT NULL AND hidden = 0 AND status IN ('entrance','departure')")),
        Index("uq_one_sorting_batch", "railway_id", unique=True,
              postgresql_where=text("status = 'sorting' AND railway_id IS NOT NULL"),
              sqlite_where=text("status = 'sorting' AND railway_id IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id", ondelete="RESTRICT"), nullable=False, index=True)
    station: Mapped["Station"] = relationship("Station", back_populates="collections")
    message_station: Mapped[int | None] = mapped_column(Integer)
    train_number: Mapped[int | None] = mapped_column(Integer)
    sent_station: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(Integer)
    target_station: Mapped[int | None] = mapped_column(Integer)
    train_condition: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tosish: Mapped[int | None] = mapped_column(Integer)
    tepa: Mapped[int | None] = mapped_column(Integer)
    yon: Mapped[int | None] = mapped_column(Integer)
    past: Mapped[int | None] = mapped_column(Integer)
    animal: Mapped[int | None] = mapped_column(Integer)
    extra: Mapped[str | None] = mapped_column(String(255))
    extra2: Mapped[str | None] = mapped_column(String(255))
    received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="entrance", server_default="entrance")
    railway_id: Mapped[int | None] = mapped_column(ForeignKey("railway.id", ondelete="RESTRICT"), index=True)
    source_collection_id: Mapped[int | None] = mapped_column(ForeignKey("naturka_collection.id", ondelete="SET NULL"), index=True)
    railway: Mapped["Railway | None"] = relationship("Railway", foreign_keys=[railway_id], back_populates="collections")
    vagons: Mapped[list["NaturkaVagon"]] = relationship(
        "NaturkaVagon", back_populates="collection", order_by="NaturkaVagon.position")