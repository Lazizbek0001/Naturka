from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base


class StationScheme(Base):
    """Настройка схемы станции (JSON в config): парки с ведомостью путей (номер, полезная длина, тип),
    отдельные пути и правило головы поезда по состоянию поезда (head_rule)."""
    __tablename__ = "station_scheme"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("station.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    config: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
