from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

class Railway(Base):
    __tablename__ = "railway"

    id : Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(255), nullable=False)
    length: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[int] = mapped_column(String(255), nullable=False)



