from __future__ import annotations
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base
if TYPE_CHECKING:
    from src.db.models.station import Station

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # право видеть «Главную» (дашборд); администратор видит её всегда
    dashboard: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id", ondelete="RESTRICT"), nullable=True, index=True)
    station: Mapped["Station | None"] = relationship("Station", back_populates="users")