"""Настройки сайта, общие для всех: автовыход при бездействии. Читает любой вошедший, меняет администратор."""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps.auth import current_user, superuser_only
from src.api.deps.railway import get_db
from src.db.models import SiteDoc, User

router = APIRouter(prefix="/site-settings", tags=["Site settings"], dependencies=[Depends(current_user)])
KEY = "settings"
DEFAULTS = {"idle_logout_minutes": 30}


class SettingsIn(BaseModel):
    idle_logout_minutes: int = Field(ge=0, le=720)  # 0 — не выходить автоматически


def read(db: Session) -> dict:
    row = db.scalar(select(SiteDoc).where(SiteDoc.key == KEY))
    return {**DEFAULTS, **(json.loads(row.data) if row else {})}


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return read(db)


@router.put("")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    data = {**read(db), **body.model_dump()}
    row = db.scalar(select(SiteDoc).where(SiteDoc.key == KEY))
    text = json.dumps(data, ensure_ascii=False)
    if row is None:
        db.add(SiteDoc(key=KEY, data=text))
    else:
        row.data = text
    db.commit()
    return data
