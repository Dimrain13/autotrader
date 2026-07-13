"""
Email + password JWT authentication for the internal trading API.

Single-user internal tool: exactly one account, seeded on startup from
ADMIN_EMAIL/ADMIN_PASSWORD in backend/.env (see seed_user()). Login issues
a JWT (30-day expiry) that the frontend stores and sends on every request:

    Authorization: Bearer <jwt>

verify_token() is attached to the whole `/api` router in server.py, so it
protects every route except /api/auth/login (which lives on a separate,
unprotected router - see server.py).
"""
import os
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import Header, HTTPException, status
from database import db

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(email: str) -> str:
    payload = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
        "type": "access"
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


async def seed_user():
    """Idempotently seed the single user account from .env on startup.

    If the account doesn't exist yet, create it. If it exists but the
    password in .env has since changed, update the stored hash - this way
    changing ADMIN_PASSWORD in .env and restarting is enough to rotate it.
    """
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        return
    email = email.strip().lower()
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({
            "email": email,
            "password_hash": hash_password(password),
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    elif not verify_password(password, existing["password_hash"]):
        await db.users.update_one(
            {"email": email},
            {"$set": {"password_hash": hash_password(password)}}
        )


async def check_lockout(identifier: str):
    """Raise 429 if this IP+email combo is currently locked out from too many failed logins."""
    record = await db.login_attempts.find_one({"identifier": identifier})
    if record and record.get("failed_count", 0) >= MAX_FAILED_ATTEMPTS:
        locked_until = record.get("locked_until")
        if locked_until and datetime.fromisoformat(locked_until) > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Try again in {LOCKOUT_MINUTES} minutes."
            )


async def record_failed_attempt(identifier: str):
    record = await db.login_attempts.find_one({"identifier": identifier})
    failed_count = (record.get("failed_count", 0) if record else 0) + 1
    update = {"failed_count": failed_count, "last_attempt": datetime.now(timezone.utc).isoformat()}
    if failed_count >= MAX_FAILED_ATTEMPTS:
        update["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
    await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)


async def clear_failed_attempts(identifier: str):
    await db.login_attempts.delete_one({"identifier": identifier})


def verify_token(authorization: str = Header(None)) -> str:
    """FastAPI dependency: verifies the JWT Bearer token, returns the user's email."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = parts[1]
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed token",
            headers={"WWW-Authenticate": "Bearer"}
        )
