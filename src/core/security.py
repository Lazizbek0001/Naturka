import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import HTTPException

load_dotenv()  # Load environment variables from .env file
_hasher = PasswordHasher()
ALGORITHM = "HS256"

def secret() -> str:
    result = os.getenv("JWT_SECRET_KEY", "")
    if len(result) < 32:
        raise RuntimeError("Set JWT_SECRET_KEY to a random secret of at least 32 characters")
    return result

def hash_password(password: str) -> str:
    return _hasher.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError):
        return False

def make_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=8)}, secret(), algorithm=ALGORITHM)

def decode_token(token: str) -> int:
    try:
        data = jwt.decode(token, secret(), algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
        return int(data["sub"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc