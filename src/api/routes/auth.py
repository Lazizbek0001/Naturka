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