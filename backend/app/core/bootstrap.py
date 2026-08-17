import structlog
from sqlalchemy import select

from app.config import settings
from app.core.security import hash_password
from app.database import AsyncSessionLocal
from app.models.user import User, UserRole

log = structlog.get_logger()


async def bootstrap_admin_user() -> None:
    """Create the first admin user from env vars if it doesn't already exist.

    Exists for hosts with no shell access (e.g. Render's free tier), where
    there's otherwise no way to seed the very first account. Safe to leave
    the env vars set across restarts — it only acts when no user with that
    email exists yet, it never overwrites anything.
    """
    if not settings.BOOTSTRAP_ADMIN_EMAIL or not settings.BOOTSTRAP_ADMIN_PASSWORD:
        return

    email = settings.BOOTSTRAP_ADMIN_EMAIL.strip().lower()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            return

        db.add(User(
            email=email,
            password_hash=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
            full_name="Admin",
            role=UserRole.admin,
            is_active=True,
        ))
        await db.commit()
        log.info("bootstrap_admin_created", email=email)
