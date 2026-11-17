
from pydantic import BaseModel, ConfigDict, Field


class RailwayCreate(BaseModel):
    code: str = Field(min_length=1, max_length=255)
    type: int = Field(ge=1, le=4)
    length: int | None = None


class RailwayView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    type: int
    length: int | None


class WagonImport(BaseModel):
    vagon_number: int
    vagoon_country: int
    product_weight: int
    product_type: int
    target_station: int
    vagon_condition: int
    product_importance: int
    ban: int
    count_plomba: int
    count_container: int
    through_station: int

    extra_data: str | None = None
    length_m: int = Field(gt=0)


class CollectionHeader(BaseModel):
    sent_station: int
    train_number: int
    assigned_id: str
    train_condition: int


class ReportImport(BaseModel):
    entrance_id: int
    sorting_id: int | None = None

    header: CollectionHeader

    vagons: list[WagonImport] = Field(min_length=1)

    reported_length: int | None = Field(
        default=None,
        gt=0,
    )


class RangeExtract(BaseModel):
    source_collection_id: int
    start_position: int = Field(ge=1)
    end_position: int = Field(ge=1)

    destination_sorting_id: int
    destination_collection_id: int | None = None


class SendDeparture(BaseModel):
    collection_id: int
    departure_railway_id: int

    tosish: int
    tepa: int
    yon: int
    past: int
    animal: int

    extra: str | None = None
    extra2: str | None = None
    received: bool


class CollectionReadiness(BaseModel):
    ready: bool


class DispatchCollection(BaseModel):
    collection_id: int


class WagonView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    collection_id: int | None
    vagon_number: int
    position: int
    length_m: int
    product_weight: int
    target_station: int


class CollectionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    sent_station: int
    train_number: int
    assigned_id: str
    train_condition: int

    railway_id: int | None
    target_station: int | None

    length: int
    weight: int

    status: str
    ready: bool
    received: bool | None

    tosish: int | None
    tepa: int | None
    yon: int | None
    past: int | None
    animal: int | None

    extra: str | None
    extra2: str | None

    vagons: list[WagonView]
