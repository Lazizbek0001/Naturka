from __future__ import annotations
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.station import Station

class MessageIdCounter(Base):
    __tablename__ = "message_id_counter"
    __table_args__ = (
        CheckConstraint("last_assigned BETWEEN 0 AND 999", name="ck_message_counter_range"),
    )
    # Exactly one counter per station (no global id=1 row).
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id", ondelete="CASCADE"), primary_key=True)
    last_assigned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    station: Mapped["Station"] = relationship("Station", back_populates="message_counter")