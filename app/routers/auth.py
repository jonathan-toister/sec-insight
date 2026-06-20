"""Browser session authentication — POST /auth/login, POST /auth/logout."""
import hmac

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.auth.session import COOKIE_NAME, create_session_token
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(request: LoginRequest, response: Response) -> dict:
    if not settings.login_password:
        raise RuntimeError("LOGIN_PASSWORD is not configured — set it in .env")
    if not hmac.compare_digest(request.password, settings.login_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    token = create_session_token()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="none" if settings.cookie_secure else "lax",
        max_age=settings.jwt_expire_days * 86_400,
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="none" if settings.cookie_secure else "lax",
    )
    return {"ok": True}
