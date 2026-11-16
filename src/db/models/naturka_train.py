from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.naturka_vagon import NaturkaVagon


class NaturkaTrain(Base):
    __tablename__ = "naturka_train"

    id: Mapped[int] = mapped_column(primary_key=True)

    sent_station: Mapped[int] = mapped_column(Integer, nullable=False)
    train_number: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_id: Mapped[str] = mapped_column(String(255), nullable=False)
    train_condition: Mapped[int] = mapped_column(Integer, nullable=False)

    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    length: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    tosish: Mapped[int] = mapped_column(Integer, nullable=False)
    tepa: Mapped[int] = mapped_column(Integer, nullable=False)
    yon: Mapped[int] = mapped_column(Integer, nullable=False)
    past: Mapped[int] = mapped_column(Integer, nullable=False)
    animal: Mapped[int] = mapped_column(Integer, nullable=False)

    extra: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra2: Mapped[str | None] = mapped_column(String(255), nullable=True)

    vagons: Mapped[list["NaturkaVagon"]] = relationship(
        "NaturkaVagon",
        back_populates="train",
        cascade="all, delete-orphan",
    ) 