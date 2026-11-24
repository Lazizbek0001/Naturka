from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    name_uz: str | None = Field(default=None, max_length=255)
    name_uzc: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)

class StationView(StationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int

class RailwayCreate(BaseModel):
    station_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=255)
    type: int = Field(ge=1, le=4)
    length: int | None = None
    position: int | None = Field(default=None, ge=1)  # место в списке путей станции; пусто — в конец

class RailwayView(RailwayCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int

class WagonImport(BaseModel):
    vagon_number: int
    vagon_country: int
    product_weight: int
    product_type: int
    target_station: int
    punkt: int
    vagon_condition: int
    product_importance: int
    ban: int
    count_plomba: int
    count_container: str = Field(min_length=1, max_length=255)
    through_station: int
    extra_data: str | None = None
    length_m: int = Field(gt=0)
    vagon_type: str | None = Field(default=None, max_length=16)

class EntranceHeader(BaseModel):
    message_station: int
    train_number: int
    sent_station: int
    message_id: int = Field(ge=1, le=999)
    target_station: int
    train_condition: int
    length: int = Field(gt=0)
    weight: int = Field(ge=0)
    tosish: int
    tepa: int
    yon: int
    past: int
    animal: int
    extra: str | None = Field(default=None, max_length=255)
    extra2: str | None = Field(default=None, max_length=255)

class ReportImport(BaseModel):
    entrance_id: int
    header: EntranceHeader
    vagons: list[WagonImport] = Field(min_length=1)

class MoveToSorting(BaseModel):
    collection_id: int
    sorting_railway_id: int
    # 1-based inclusive. Omit both to copy every still-unassigned wagon.
    start_position: int | None = Field(default=None, ge=1)
    end_position: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self):
        if (self.start_position is None) != (self.end_position is None):
            raise ValueError("Provide both start_position and end_position")
        if self.start_position is not None and self.start_position > self.end_position:
            raise ValueError("start_position exceeds end_position")
        return self

class RangeExtract(BaseModel):
    source_collection_id: int
    start_position: int = Field(ge=1)
    end_position: int = Field(ge=1)
    destination_sorting_id: int
    destination_collection_id: int | None = None

class SendDeparture(BaseModel):
    collection_id: int
    departure_railway_id: int
    message_station: int
    train_number: int
    sent_station: int
    target_station: int
    train_condition: int
    tosish: int
    tepa: int
    yon: int
    past: int
    animal: int
    extra: str | None = Field(default=None, max_length=255)
    extra2: str | None = Field(default=None, max_length=255)

class CollectionReadiness(BaseModel):
    ready: bool

class DispatchCollection(BaseModel):
    collection_id: int

class WagonView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    station_id: int

    id: int
    collection_id: int | None
    source_vagon_id: int | None
    position: int

    vagon_number: int
    vagon_country: int
    product_weight: int
    length_m: int
    target_station: int
    product_type: int
    punkt: int
    vagon_condition: int
    product_importance: int
    ban: int
    count_plomba: int
    count_container: str
    through_station: int
    extra_data: str | None
    vagon_type: str | None = None


class CollectionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    station_id: int
    id: int
    message_station: int | None
    train_number: int | None
    sent_station: int | None
    message_id: int | None
    target_station: int | None
    train_condition: int | None
    date: datetime
    length: int
    weight: int
    tosish: int | None
    tepa: int | None
    yon: int | None
    past: int | None
    animal: int | None
    extra: str | None
    extra2: str | None
    received: bool
    ready: bool
    hidden: bool
    status: str
    railway_id: int | None
    source_collection_id: int | None
    vagons: list[WagonView]


class ReorderWagons(BaseModel):
    wagon_ids: list[int] = Field(min_length=1)


class MoveWagonPosition(BaseModel):
    wagon_id: int
    new_position: int = Field(ge=1)


class InsertExistingWagons(BaseModel):
    source_collection_id: int
    start_position: int = Field(ge=1)
    end_position: int = Field(ge=1)
    destination_position: int = Field(ge=1)
