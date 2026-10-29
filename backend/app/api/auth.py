from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201, dependencies=[Depends(rate_limit(10, 60))])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    user = auth_service.register(db, body)
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit(10, 60))])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, body)
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(_: User = Depends(current_user)):
    # JWTs are stateless; the client discards the token. Endpoint exists so the UI has one call to make.
    return None
