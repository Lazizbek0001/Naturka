from __future__ import annotations
from typing import TYPE_CHECKING
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.user import User
    from src.db.models.railway import Railway
    from src.db.models.naturka_collection import NaturkaCollection
    from src.db.models.naturka_vagon import NaturkaVagon
    from src.db.models.message_id_counter import MessageIdCounter

class Station(Base):
    __tablename__ = "station"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    users: Mapped[list["User"]] = relationship("User", back_populates="station")
    railways: Mapped[list["Railway"]] = relationship("Railway", back_populates="station")
    collections: Mapped[list["NaturkaCollection"]] = relationship("NaturkaCollection", back_populates="station")
    vagons: Mapped[list["NaturkaVagon"]] = relationship("NaturkaVagon", back_populates="station")
    message_counter: Mapped["MessageIdCounter | None"] = relationship("MessageIdCounter", back_populates="station", uselist=False)