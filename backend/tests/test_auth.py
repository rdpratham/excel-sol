"""Phase 1 auth tests — login / refresh / logout / me."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.core.security import hash_password


async def _create_user(db: AsyncSession, email: str, password: str, role: UserRole = UserRole.editor) -> User:
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name="Test User",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "alice@example.com", "correctpassword")
    resp = await client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "correctpassword"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "bob@example.com", "correctpassword")
    resp = await client.post("/api/v1/auth/login", json={"email": "bob@example.com", "password": "wrongpassword"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, db_session: AsyncSession):
    user = await _create_user(db_session, "charlie@example.com", "password123")
    user.is_active = False
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login", json={"email": "charlie@example.com", "password": "password123"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_success(client: AsyncClient, db_session: AsyncSession):
    await _create_user(db_session, "dana@example.com", "password123")
    login = await client.post("/api/v1/auth/login", json={"email": "dana@example.com", "password": "password123"})
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "dana@example.com"


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
