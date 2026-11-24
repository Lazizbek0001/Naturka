from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src.api.deps.railway import get_db
from src.api.deps.auth import current_user, superuser_only
from src.core.security import make_token, hash_password, verify_password
from src.db.models import User, Station

router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginData(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=10, max_length=256)
    station_id: int | None = None
    is_superuser: bool = False
    is_active: bool = True

class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    station_id: int | None
    is_superuser: bool
    is_active: bool

@router.post("/login")
def login(payload: LoginData, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    return {"access_token": make_token(user.id), "token_type": "bearer", "user": UserView.model_validate(user)}

@router.get("/me", response_model=UserView)
def me(user: User = Depends(current_user)):
    return user

@router.get("/users", response_model=list[UserView])
def users(db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    return db.scalars(select(User).order_by(User.id)).all()

@router.post("/users", response_model=UserView, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(superuser_only)):
    if not payload.is_superuser and payload.station_id is None:
        raise HTTPException(400, "A normal user must be assigned to a station")
    if payload.station_id is not None and db.get(Station, payload.station_id) is None:
        raise HTTPException(404, "Station not found")
    user = User(username=payload.username, password_hash=hash_password(payload.password),
                station_id=payload.station_id, is_superuser=payload.is_superuser, is_active=payload.is_active)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Username already exists") from exc
    db.refresh(user)
    return user

class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=100)
    password: str | None = Field(default=None, min_length=10, max_length=256)
    station_id: int | None = None
    is_superuser: bool | None = None
    is_active: bool | None = None

@router.patch("/users/{user_id}", response_model=UserView)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), me_: User = Depends(superuser_only)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    fields = payload.model_dump(exclude_unset=True)
    if user.id == me_.id and (fields.get("is_superuser") is False or fields.get("is_active") is False):
        raise HTTPException(400, "You cannot remove your own superuser rights or deactivate yourself")
    if "station_id" in fields and fields["station_id"] is not None and db.get(Station, fields["station_id"]) is None:
        raise HTTPException(404, "Station not found")
    if fields.get("username"):
        user.username = fields["username"]
    if fields.get("password"):
        user.password_hash = hash_password(fields["password"])
    if "station_id" in fields:
        user.station_id = fields["station_id"]
    for key in ("is_superuser", "is_active"):
        if fields.get(key) is not None:
            setattr(user, key, fields[key])
    if not user.is_superuser and user.station_id is None:
        raise HTTPException(400, "A normal user must be assigned to a station")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Username already exists") from exc
    db.refresh(user)
    return user

@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), me_: User = Depends(superuser_only)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == me_.id:
        raise HTTPException(400, "You cannot delete yourself")
    db.delete(user)
    db.commit()
