from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from src.api.deps.railway import get_db
from src.core.security import decode_token
from src.db.models.user import User

bearer = HTTPBearer(auto_error=False)

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, decode_token(credentials.credentials))
    if user is None or not user.is_active:
        raise HTTPException(401, "Account unavailable", headers={"WWW-Authenticate": "Bearer"})
    return user

def superuser_only(user: User = Depends(current_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(403, "Superuser required")
    return user

def require_station(user: User, station_id: int) -> None:
    if not user.is_superuser and user.station_id != station_id:
        raise HTTPException(403, "Access to this station is forbidden")