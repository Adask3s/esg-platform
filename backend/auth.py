from datetime import datetime, timedelta
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from jose import JWTError, jwt
import bcrypt

from database.user_repo import get_user_by_username, create_user

try:
    from .rate_limiting import client_identifier, enforce_rate_limit
except ImportError:
    from backend.rate_limiting import client_identifier, enforce_rate_limit  # type: ignore

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "JWT_SECRET musi byc ustawiony w .env i miec min. 32 znaki. "
        "Wygeneruj: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

#NA RAZIE WYŁĄCZONY MOZNA WLACZYC JESLI BEDZIE POTRZEBNY
SIGNUP_ENABLED = os.getenv("SIGNUP_ENABLED", "false").lower() == "true"

router = APIRouter(prefix="/auth", tags=["auth"])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_username(username)
    if user is None:
        raise credentials_exception
    return user


class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    password: str


@router.post("/signup")
def signup(user: UserCreate, request: Request):
    enforce_rate_limit(
        request=request,
        scope="auth_signup",
        identity=client_identifier(request),
        limit=int(os.getenv("RATE_LIMIT_SIGNUP_PER_HOUR", "3")),
        window_seconds=3600,
    )
    if not SIGNUP_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Rejestracja wylaczona. Skontaktuj sie z administratorem.",
        )
    try:
        existing = get_user_by_username(user.username)
        if existing:
            raise HTTPException(status_code=400, detail="Username already registered")
        hashed = get_password_hash(user.password)
        user_id = create_user(user.username, user.email, hashed)
        token_payload = {"sub": user.username, "user_id": str(user_id), "role": "user"}
        access_token = create_access_token(token_payload, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    enforce_rate_limit(
        request=request,
        scope="auth_login",
        identity=f"{client_identifier(request)}:{form_data.username}",
        limit=int(os.getenv("RATE_LIMIT_LOGIN_PER_MINUTE", "5")),
        window_seconds=60,
    )
    user = get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_payload = {"sub": user["username"], "user_id": str(user["id"]), "role": user.get("role", "user")}
    access_token = create_access_token(token_payload, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}

class ContactRequest(BaseModel):
    email: str
    problem: str


@router.post("/contact")
def contact(contact: ContactRequest, request: Request):
    enforce_rate_limit(
        request=request,
        scope="auth_contact",
        identity=f"{client_identifier(request)}:{contact.email}",
        limit=int(os.getenv("RATE_LIMIT_CONTACT_PER_10_MINUTES", "3")),
        window_seconds=600,
    )
    """
    Simple contact form endpoint
    In production, this should send an email or save to database
    """
    try:
        # TODO: Send email or save to database
        return {
            "status": "success",
            "message": "Your message has been received. We'll get back to you soon."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
