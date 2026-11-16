from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.db.models.movement import MovementKind
from src.db.models.railway import RailwayType


class RailwayCreate(BaseModel):
    code: str = Field(min_length=1, max_length=255, examples=["43"])
    length: int = Field(ge=0)
    type: RailwayType


class RailwayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    length: int
    type: RailwayType


class VagonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    train_id: int
    order_number: int
    vagon_number: int
    railway_id: int | None
    position: int | None
    extra_data: str | None


class RailwayWithVagons(RailwayOut):
    vagons: list[VagonOut]


class TrainArrive(BaseModel):
    entrance_railway_id: int
    report: str = Field(description="Naturka report text: train line, then vagon lines")


class TrainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    train_number: int
    assigned_id: str
    sent_station: int
    date: datetime
    length: int
    weight: int
    vagons: list[VagonOut]


class MovementCreate(BaseModel):
    to_railway_id: int
    vagon_ids: list[int] | None = Field(
        default=None, description="Vagons to move; they must stand on one railway"
    )
    from_railway_id: int | None = Field(
        default=None, description="Move every vagon standing on this railway"
    )
    via_railway_id: int | None = Field(
        default=None,
        description="Entrance railway used to pull vagons back when shunting "
        "between sorting railways (default: the one they arrived on)",
    )


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: MovementKind
    from_railway_id: int | None
    via_railway_id: int | None
    to_railway_id: int | None
    date: datetime
    vagons: list[VagonOut]
