from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthError, ConflictError
from app.core.security import create_access_token, get_current_user, hash_password, require_role, verify_password
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.requests import LoginRequest, RegisterRequest
from app.schemas.serializers import user_out
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if not user or not user.is_active or not verify_password(body.password, user.hashed_password):
        audit_service.log_event(db, action="login_failed", summary=f"Failed login for {body.email[:80]}")
        db.commit()
        raise AuthError("Invalid email or password")
    audit_service.log_event(db, action="login", user=user, entity_type="user", entity_id=user.id, summary=f"{user.email} signed in")
    db.commit()
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": user_out(user),
            "expires_in": get_settings().jwt_expire_minutes * 60}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {**user_out(user), "auth_enabled": get_settings().auth_enabled}


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    email = body.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise ConflictError("A user with this email already exists")
    user = User(email=email, name=body.name.strip(), hashed_password=hash_password(body.password), role=body.role)
    db.add(user)
    db.flush()
    audit_service.log_event(db, action="user_created", user=admin, entity_type="user", entity_id=user.id, summary=f"Created {email} as {body.role}")
    db.commit()
    return user_out(user)


@router.get("/users")
def users(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    return [user_out(u) for u in db.query(User).order_by(User.id).all()]
