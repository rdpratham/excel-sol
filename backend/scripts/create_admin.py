#!/usr/bin/env python3
"""
Create / seed admin users.

Interactive mode (no args):
    python scripts/create_admin.py

Non-interactive mode:
    python scripts/create_admin.py --email user@example.com --name "Full Name" --password "Secret123"
"""

import asyncio
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def create(email: str, full_name: str, password: str) -> None:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User, UserRole
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == email.lower()))
        if existing.scalar_one_or_none():
            print(f"INFO: User '{email}' already exists — skipping.")
            return

        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=full_name,
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"✓ Admin created: {user.email} (id={user.id})")


async def interactive() -> None:
    import getpass
    print("=== MindSpread — Create Admin User ===")
    email = input("Email: ").strip().lower()
    full_name = input("Full name: ").strip()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("ERROR: Passwords do not match.")
        sys.exit(1)
    if len(password) < 8:
        print("ERROR: Password must be at least 8 characters.")
        sys.exit(1)

    await create(email, full_name, password)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    if args.email and args.name and args.password:
        asyncio.run(create(args.email, args.name, args.password))
    else:
        asyncio.run(interactive())


if __name__ == "__main__":
    main()
