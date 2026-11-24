"""Справочник кодов станций для подсказок в полях натурки."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, union
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src.api.deps.railway import get_db
from src.api.deps.auth import current_user, superuser_only
from src.db.models import NaturkaCollection, NaturkaVagon, StationRef, Station, User
from src.services import alta

router = APIRouter(prefix="/station-refs", tags=["Station directory"], dependencies=[Depends(current_user)])


class RefIn(BaseModel):
    code: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=255)
    name_uz: str | None = Field(default=None, max_length=255)
    name_uzc: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    esr: str | None = Field(default=None, max_length=8)
    road: str | None = Field(default=None, max_length=255)


class RefView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: int
    name: str = ""
    name_uz: str | None = None
    name_uzc: str | None = None
    name_en: str | None = None
    esr: str | None = None
    road: str | None = None
    source: str | None = None
    id: int | None = None
    used: bool = False  # код встречался в натурках, но названия ещё нет


@router.get("", response_model=list[RefView])
def list_refs(db: Session = Depends(get_db)):
    """Справочник + станции с числовым кодом + коды, уже встречавшиеся в натурках."""
    out = {r.code: RefView.model_validate(r) for r in db.scalars(select(StationRef)).all()}
    for st in db.scalars(select(Station)).all():
        if st.code.isdigit() and int(st.code) not in out:
            out[int(st.code)] = RefView(code=int(st.code), name=st.name, name_uz=st.name_uz,
                                        name_uzc=st.name_uzc, name_en=st.name_en)
    cols = [NaturkaCollection.message_station, NaturkaCollection.sent_station, NaturkaCollection.target_station]
    wcols = [NaturkaVagon.target_station, NaturkaVagon.through_station]
    used = union(*[select(c.label("code")).where(c.is_not(None)) for c in cols],
                 *[select(c.label("code")) for c in wcols])
    for code in db.scalars(select(used.subquery().c.code)).all():
        if code and code not in out:
            out[code] = RefView(code=code, name="", used=True)
    return sorted(out.values(), key=lambda r: (r.used, r.code))


def save(db: Session, ref: StationRef) -> StationRef:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Station code already exists in the directory") from exc
    db.refresh(ref)
    return ref


# ---------------------------------------------------------------- alta.ru
def _alta(fn, *args):
    try:
        return fn(*args)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # нет интернета, сайт недоступен
        raise HTTPException(502, f"alta.ru is unavailable: {exc}") from exc


@router.get("/alta/roads")
def alta_roads():
    """Список железных дорог с alta.ru/railway."""
    return _alta(alta.roads)


@router.get("/alta/roads/{road}")
def alta_road(road: str):
    """Станции дороги с alta.ru: код ЕСР, код для натурки (4 цифры), название."""
    return _alta(alta.road_stations, road)


class BulkIn(BaseModel):
    items: list[RefIn] = Field(min_length=1, max_length=20000)
    source: str | None = Field(default=None, max_length=32)
    replace_names: bool = False  # перезаписать названия у станций, которые уже есть в справочнике


@router.post("/bulk")
def bulk_refs(body: BulkIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    """Внести много станций разом (импорт с alta.ru). Новые — добавить, существующие — дополнить."""
    have = {r.code: r for r in db.scalars(select(StationRef)).all()}
    added = updated = 0
    for it in body.items:
        data = it.model_dump()
        ref = have.get(it.code)
        if ref is None:
            ref = StationRef(**data, source=body.source)
            db.add(ref)
            have[it.code] = ref
            added += 1
            continue
        changed = False
        for key, value in data.items():
            if key == "code" or not value:
                continue
            old = getattr(ref, key)
            if old != value and (not old or body.replace_names or key in ("esr", "road")):
                setattr(ref, key, value)
                changed = True
        if changed:
            ref.source = ref.source or body.source
            updated += 1
    db.commit()
    return {"added": added, "updated": updated, "total": len(have)}


@router.post("", response_model=RefView, status_code=201)
def create_ref(data: RefIn, db: Session = Depends(get_db)):
    ref = StationRef(**data.model_dump())
    db.add(ref)
    return save(db, ref)


@router.patch("/{ref_id}", response_model=RefView)
def update_ref(ref_id: int, data: RefIn, db: Session = Depends(get_db)):
    ref = db.get(StationRef, ref_id)
    if ref is None:
        raise HTTPException(404, "Not found")
    for key, value in data.model_dump().items():
        setattr(ref, key, value or None if key.startswith("name_") else value)
    return save(db, ref)


@router.delete("/{ref_id}", status_code=204)
def delete_ref(ref_id: int, db: Session = Depends(get_db)):
    ref = db.get(StationRef, ref_id)
    if ref is None:
        raise HTTPException(404, "Not found")
    db.delete(ref)
    db.commit()
    return Response(status_code=204)
