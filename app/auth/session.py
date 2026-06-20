from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

_ALGORITHM = "HS256"
COOKIE_NAME = "sec_session"


def create_session_token() -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    return jwt.encode({"exp": expire, "sub": "user"}, settings.jwt_secret, algorithm=_ALGORITHM)


def verify_session_token(token: str) -> bool:
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
        return True
    except jwt.PyJWTError:
        return False
