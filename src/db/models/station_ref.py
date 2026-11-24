from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base


class StationRef(Base):
    """Справочник кодов станций для полей натурки (станция сообщения, отправления, назначения…)."""
    __tablename__ = "station_ref"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_uz: Mapped[str | None] = mapped_column(String(255))
    name_uzc: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    esr: Mapped[str | None] = mapped_column(String(8))      # полный код ЕСР (с контрольной цифрой)
    road: Mapped[str | None] = mapped_column(String(255))   # железная дорога
    source: Mapped[str | None] = mapped_column(String(32))  # откуда запись: "alta.ru" или вручную
