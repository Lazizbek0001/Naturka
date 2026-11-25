"""«Главная»: сводка по станции (или по всем станциям) для дашборда.
Видят администратор и пользователи с правом «Доступ к Главной» (users.dashboard); пользователь станции — только свою."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps.auth import current_user
from src.api.deps.railway import get_db
from src.db.models import NaturkaCollection, NaturkaVagon, Railway, Station, User

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
ACTIVE = ("entrance", "sorting", "departure")


def allowed(user: User) -> bool:
    return bool(user.is_superuser or getattr(user, "dashboard", False))


# тип вагона по номеру (первая цифра), если в натурке он не указан — как на сайте (wagon-types.js)
BY_DIGIT = {"2": "cov", "3": "spec", "4": "flat", "5": "own", "6": "gon", "7": "tank", "8": "ref", "9": "oth"}
PARK_STATUS = {"entrance", "sorting", "departure"}


def wtype(w: NaturkaVagon) -> str:
    return w.vagon_type or BY_DIGIT.get(str(w.vagon_number)[:1], "oth")


def station_summary(db: Session, station: Station, park: str | None = None, vtype: str | None = None) -> dict:
    rails = db.scalars(select(Railway).where(Railway.station_id == station.id)).all()
    colls = db.scalars(select(NaturkaCollection).where(
        NaturkaCollection.station_id == station.id, NaturkaCollection.hidden.is_(False),
        NaturkaCollection.status.in_(ACTIVE))).all()
    # вагоны на путях: в сортировке и отправлении — все, на приёме — ещё не перенесённые
    ids = [c.id for c in colls]
    wagons = db.scalars(select(NaturkaVagon).where(NaturkaVagon.collection_id.in_(ids))).all() if ids else []
    moved = set(db.scalars(select(NaturkaVagon.source_vagon_id).where(NaturkaVagon.source_vagon_id.in_([w.id for w in wagons]))).all()) if wagons else set()
    status_of = {c.id: c.status for c in colls}
    on_track = [w for w in wagons if not (status_of.get(w.collection_id) == "entrance" and w.id in moved)]
    # фильтры: парк (по состоянию состава) и тип вагона
    if park:
        on_track = [w for w in on_track if status_of.get(w.collection_id) == park]
    if vtype:
        on_track = [w for w in on_track if wtype(w) == vtype]
    shown = {c.id for c in colls if (not park or c.status == park)}
    if vtype:
        shown &= {w.collection_id for w in on_track}

    occ = Counter()
    for c in colls:
        if c.railway_id:
            occ[c.railway_id] += c.length
    parks = {}
    for t in (1, 2, 3):
        rs = [r for r in rails if r.type == t]
        cap = sum(r.length or 0 for r in rs)
        used = sum(min(occ[r.id], r.length or 0) for r in rs)
        busy = sum(1 for r in rs if occ[r.id] > 0)
        parks[t] = {"tracks": len(rs), "busy": busy, "capacity": cap, "occupied": used}
    trains = Counter(c.status for c in colls if c.id in shown)
    ready = sum(1 for c in colls if c.id in shown and c.status == "departure" and c.ready)
    return {
        "id": station.id, "code": station.code, "name": station.name,
        "name_uz": station.name_uz, "name_uzc": station.name_uzc, "name_en": station.name_en,
        "tracks": len(rails), "parks": parks,
        "trains": {"entrance": trains["entrance"], "sorting": trains["sorting"], "departure": trains["departure"], "ready": ready},
        "wagons": len(on_track), "weight": sum(w.product_weight for w in on_track),
        "types": Counter(wtype(w) for w in on_track).most_common(),
        "targets": Counter(w.target_station for w in on_track).most_common(8),
    }


@router.get("")
def dashboard(station_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
              park: str | None = None, vtype: str | None = None,
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Сводка. Период (date_from…date_to, по умолчанию 14 дней) — для натурок; park и vtype — для составов и вагонов на путях."""
    if not allowed(user):
        raise HTTPException(403, "No access to the dashboard")
    if not user.is_superuser:
        station_id = user.station_id
    stations = db.scalars(select(Station).order_by(Station.id)).all()
    if station_id is not None:
        stations = [s for s in stations if s.id == station_id]
        if not stations:
            raise HTTPException(404, "Station not found")
    if park and park not in PARK_STATUS:
        raise HTTPException(400, "park must be entrance, sorting or departure")
    today = datetime.now(timezone.utc).date()
    d_to = date_to or today
    d_from = date_from or (d_to - timedelta(days=13))
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    if (d_to - d_from).days > 3660:
        raise HTTPException(400, "Period is too long (max 10 years)")
    per = [station_summary(db, s, park, vtype) for s in stations]
    sids = [s.id for s in stations]

    # натурки, принятые за период (исходные, не части): по дням (или по месяцам для длинного периода) и последние
    imported = db.scalars(select(NaturkaCollection).where(
        NaturkaCollection.station_id.in_(sids), NaturkaCollection.source_collection_id.is_(None))
        .order_by(NaturkaCollection.date.desc())).all()
    local = lambda c: (c.date if c.date.tzinfo else c.date.replace(tzinfo=timezone.utc)).date()
    in_period = [c for c in imported if d_from <= local(c) <= d_to]
    span = (d_to - d_from).days + 1
    by_month = span > 62
    counts = Counter((local(c).strftime("%Y-%m") if by_month else local(c).isoformat()) for c in in_period)
    if by_month:
        keys, y, m = [], d_from.year, d_from.month
        while (y, m) <= (d_to.year, d_to.month):
            keys.append(f"{y:04d}-{m:02d}"); m += 1
            if m > 12: y, m = y + 1, 1
    else:
        keys = [(d_from + timedelta(days=i)).isoformat() for i in range(span)]
    series = [{"day": k, "count": counts[k]} for k in keys]
    recent = [{"id": c.id, "station_id": c.station_id, "train_number": c.train_number, "date": c.date, "status": c.status,
               "length": c.length, "weight": c.weight, "wagons": len(c.vagons)} for c in in_period[:10]]

    total = {"wagons": sum(p["wagons"] for p in per), "weight": sum(p["weight"] for p in per),
             "trains": {k: sum(p["trains"][k] for p in per) for k in ("entrance", "sorting", "departure", "ready")},
             "parks": {t: {k: sum(p["parks"][t][k] for p in per) for k in ("tracks", "busy", "capacity", "occupied")} for t in (1, 2, 3)},
             "types": Counter(), "targets": Counter(), "sent": len(db.scalars(select(NaturkaCollection.id).where(
                 NaturkaCollection.station_id.in_(sids), NaturkaCollection.status == "sent")).all())}
    for p in per:
        total["types"].update(dict(p["types"]))
        total["targets"].update(dict(p["targets"]))
    total["types"] = total["types"].most_common()
    total["targets"] = total["targets"].most_common(8)
    return {"stations": per, "total": total, "imports": series, "by_month": by_month, "recent": recent,
            "imported_total": len(in_period), "imported_wagons": sum(len(c.vagons) for c in in_period),
            "imported_weight": sum(c.weight for c in in_period), "imported_all": len(imported),
            "period": {"from": d_from.isoformat(), "to": d_to.isoformat()}, "generated": datetime.now(timezone.utc)}
