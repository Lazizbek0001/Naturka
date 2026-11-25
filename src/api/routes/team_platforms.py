"""«Команда разработчиков» и «Существующие веб-платформы» — общие для всех списки (таблица site_doc).

GET /team       — {"members": [...]} или {"members": null}, если состав ещё не сохраняли (сайт показывает состав из кода).
PUT /team       — {"members": [...]}; только администратор. Фото — data URL картинки (сайт сжимает до 320 px).
GET /platforms  — {"platforms": [...]} или {"platforms": null}.
PUT /platforms  — {"platforms": [...]}; только администратор. Логотип — data URL картинки до 120 000 символов.

Читать может любой, без входа: в списках нет ничего закрытого, а карточки полезны и до входа.
Запрос на запись — не больше 5 МБ целиком.
"""
import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps.auth import superuser_only
from src.api.deps.railway import get_db
from src.db.models import SiteDoc, User

router = APIRouter(tags=["Team & platforms"])

MAX_BODY = 5 * 1024 * 1024
MAX_MEMBERS = 60
MAX_PHOTO = 600_000
MAX_PLATFORMS = 40
MAX_ICON = 120_000

ICONS = {"crown", "target", "file", "sparkles", "chart", "shield", "users", "server", "code"}
COLORS = {"blue", "violet", "sky", "pink", "green", "orange", "slate", "amber"}
PHOTO_RE = re.compile(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$")
ICON_RE = re.compile(r"^data:image/(png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/=]+$")
URL_RE = re.compile(r"^https?://\S+$", re.I)
HEX_RE = re.compile(r"^#[0-9a-f]{6}$", re.I)


def _str(v, n: int) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


def _read(db: Session, key: str):
    row = db.scalar(select(SiteDoc).where(SiteDoc.key == key))
    if row is None:
        return None
    try:
        return json.loads(row.data)
    except ValueError:
        return None


def _write(db: Session, key: str, value) -> None:
    row = db.scalar(select(SiteDoc).where(SiteDoc.key == key))
    text = json.dumps(value, ensure_ascii=False)
    if row is None:
        db.add(SiteDoc(key=key, data=text))
    else:
        row.data = text
    db.commit()


async def _body(request: Request) -> dict:
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "Request is too large (max 5 MB)")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Request is too large (max 5 MB)")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid JSON")
    return body


# ---------------------------------------------------------------- команда
def _member(m) -> dict | None:
    if not isinstance(m, dict):
        return None
    mid, name = _str(m.get("id"), 64), _str(m.get("name"), 200)
    if not mid or not name:
        return None
    out = {
        "id": mid,
        "name": name,
        "role": _str(m.get("role"), 120),
        "description": _str(m.get("description"), 600),
        "icon": m.get("icon") if m.get("icon") in ICONS else "code",
        "color": m.get("color") if m.get("color") in COLORS else "blue",
    }
    if m.get("lead") is True:
        out["lead"] = True
    link = _str(m.get("link"), 300)
    if link:
        out["link"] = link
    photo = m.get("photo")
    if isinstance(photo, str) and len(photo) <= MAX_PHOTO and PHOTO_RE.match(photo):
        out["photo"] = photo
    return out


@router.get("/team")
def get_team(db: Session = Depends(get_db)):
    v = _read(db, "team")
    return {"members": v if isinstance(v, list) and v else None}


@router.put("/team")
async def put_team(request: Request, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    body = await _body(request)
    items = body.get("members")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_MEMBERS:
        raise HTTPException(400, f"Members list must have 1 to {MAX_MEMBERS} entries")
    members = [_member(m) for m in items]
    if any(m is None for m in members):
        raise HTTPException(400, "Every member needs an id and a name")
    if len({m["id"] for m in members}) != len(members):
        raise HTTPException(400, "Member ids must be unique")
    lead_seen = False  # руководитель — один
    for m in members:
        if m.get("lead"):
            if lead_seen:
                m.pop("lead")
            lead_seen = True
    _write(db, "team", members)
    return {"members": members}


# ---------------------------------------------------------------- веб-платформы
def _platform(p, i: int) -> dict | None:
    if not isinstance(p, dict):
        return None
    url, name = _str(p.get("url"), 500), _str(p.get("name"), 80)
    if not name or not URL_RE.match(url):
        return None
    icon = p.get("icon")
    color = p.get("color")
    return {
        "id": _str(p.get("id"), 40) or f"p{int(time.time() * 1000):x}{i}",
        "name": name,
        "url": url,
        "description": _str(p.get("description"), 200),
        "color": color if isinstance(color, str) and HEX_RE.match(color) else "#2a78d6",
        "icon": icon if isinstance(icon, str) and len(icon) <= MAX_ICON and ICON_RE.match(icon) else None,
    }


@router.get("/platforms")
def get_platforms(db: Session = Depends(get_db)):
    v = _read(db, "platforms")
    return {"platforms": v if isinstance(v, list) else None}


@router.put("/platforms")
async def put_platforms(request: Request, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    body = await _body(request)
    items = body.get("platforms")
    if not isinstance(items, list):
        raise HTTPException(400, "A platforms list is required")
    if len(items) > MAX_PLATFORMS:
        raise HTTPException(400, f"No more than {MAX_PLATFORMS} platforms")
    platforms = [_platform(p, i) for i, p in enumerate(items)]
    if any(p is None for p in platforms):
        raise HTTPException(400, "Every platform needs a name and an http(s) link")
    _write(db, "platforms", platforms)
    return {"platforms": platforms}
