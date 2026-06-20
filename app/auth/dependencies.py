import hmac
from typing import Optional

from fastapi import Cookie, Header, HTTPException, status

from app.auth.session import COOKIE_NAME, verify_session_token
from app.config import settings


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    sec_session: Optional[str] = Cookie(None, alias=COOKIE_NAME),
) -> None:
    # Header path — for scripts / CLI
    if x_api_key is not None:
        if not settings.api_key:
            raise RuntimeError("API_KEY is not configured — set it in .env")
        if not hmac.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        return

    # Cookie path — for browser FE sessions
    if sec_session is not None:
        if not settings.jwt_secret:
            raise RuntimeError("JWT_SECRET is not configured — set it in .env")
        if verify_session_token(sec_session):
            return
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired — please log in again")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "X-API-Key"},
    )
