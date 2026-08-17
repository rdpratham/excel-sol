from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expire,
    verify_password,
)
from app.models.audit import AuditLog
from app.models.user import User, UserSession
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger()

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    # Frontend and backend live on different onrender.com subdomains, which
    # browsers treat as cross-site (onrender.com is on the public suffix
    # list) — SameSite=Lax is silently dropped on cross-site XHR/fetch, so
    # the refresh call always failed in production. SameSite=None requires
    # Secure, which is only available (and only needed) in production.
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path="/api/v1/auth",
        secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
    )


async def _audit(db: AsyncSession, user_id, action: str, ip: str, ua: str, meta: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, ip=ip, user_agent=ua, metadata_=meta))


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("User-Agent", "")[:500]

    # Look up user case-insensitively (email column is CITEXT in Postgres)
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user: User | None = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        await _audit(db, None, "login_failed", ip, ua, {"email": body.email})
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Invalid email or password"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "account_disabled", "message": "Account is disabled"},
        )

    # Issue tokens
    access_token = create_access_token(user.id, user.email, user.role.value)
    raw_refresh, refresh_hash = generate_refresh_token()

    session = UserSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        expires_at=refresh_token_expire(),
        ip=ip,
        user_agent=ua,
    )
    db.add(session)

    # Persist last_login_at
    await db.execute(
        update(User).where(User.id == user.id).values(last_login_at=datetime.now(timezone.utc))
    )

    await _audit(db, user.id, "login", ip, ua)
    await db.commit()

    _set_refresh_cookie(response, raw_refresh)
    log.info("user_logged_in", user_id=str(user.id))
    return TokenResponse(access_token=access_token, user=UserResponse.model_validate(user))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_refresh_token", "message": "No refresh token"},
        )

    token_hash = hash_refresh_token(refresh_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == token_hash,
            UserSession.revoked_at == None,  # noqa: E711
            UserSession.expires_at > now,
        )
    )
    session: UserSession | None = result.scalar_one_or_none()

    if session is None:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_refresh_token", "message": "Refresh token is invalid or expired"},
        )

    user_result = await db.execute(select(User).where(User.id == session.user_id, User.is_active == True))
    user: User | None = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "user_not_found", "message": "User not found"})

    # Rotate refresh token
    session.revoked_at = now
    raw_refresh, refresh_hash = generate_refresh_token()
    new_session = UserSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        expires_at=refresh_token_expire(),
        ip=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("User-Agent", "")[:500],
    )
    db.add(new_session)
    await db.commit()

    access_token = create_access_token(user.id, user.email, user.role.value)
    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=access_token, user=UserResponse.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUser,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> None:
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        result = await db.execute(
            select(UserSession).where(UserSession.refresh_token_hash == token_hash, UserSession.user_id == current_user.id)
        )
        session = result.scalar_one_or_none()
        if session:
            session.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    _clear_refresh_cookie(response)
    log.info("user_logged_out", user_id=str(current_user.id))


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)
