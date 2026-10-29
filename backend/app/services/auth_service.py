from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Unauthorized
from app.core.security import hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn

# Checked when the email doesn't exist so timing doesn't reveal which emails are registered
_DUMMY_HASH = hash_password("not-a-real-password")


def register(db: Session, data: RegisterIn) -> User:
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError("email_taken", "An account with this email already exists. Try signing in instead.", 409)
    user = User(name=data.name, email=email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    return user


def authenticate(db: Session, data: LoginIn) -> User:
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise Unauthorized("That email and password don't match.")
    return user
