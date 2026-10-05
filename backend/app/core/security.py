"""Authentication (JWT), password hashing, and role-based authorization boundaries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

import bcrypt
import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthError, ForbiddenError
from app.db.models.user import User
from app.db.session import get_db

ROLES = ("admin", "reviewer", "analyst", "viewer")
# Role hierarchy: higher index can do everything lower ones can.
_RANK = {"viewer": 0, "analyst": 1, "reviewer": 2, "admin": 3}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=s.jwt_expire_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token expired") from e
    except jwt.PyJWTError as e:
        raise AuthError("Invalid token") from e


def _anonymous_admin(db: Session) -> User:
    """Used only when AUTH_ENABLED=false (local demos / tests)."""
    user = db.query(User).filter(User.email == "anonymous@neuroforge.local").first()
    if not user:
        user = User(email="anonymous@neuroforge.local", name="Anonymous (auth disabled)",
                    hashed_password="!", role="admin")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not get_settings().auth_enabled:
        return _anonymous_admin(db)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing bearer token")
    claims = decode_token(authorization.split(" ", 1)[1].strip())
    user = db.get(User, int(claims["sub"]))
    if not user or not user.is_active:
        raise AuthError("User not found or disabled")
    return user


def require_role(minimum: str) -> Callable[[User], User]:
    """Dependency factory: `Depends(require_role("reviewer"))`."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        if _RANK.get(user.role, -1) < _RANK[minimum]:
            raise ForbiddenError(f"Requires role '{minimum}' or higher")
        return user

    return _dep


def safe_filename(name: str) -> str:
    """Strip directories, control chars and anything outside a conservative allowlist."""
    import re
    import unicodedata

    base = name.replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._\- ]", "_", base).strip(" .")
    base = re.sub(r"\.{2,}", ".", base)
    return (base or "upload")[:150]
