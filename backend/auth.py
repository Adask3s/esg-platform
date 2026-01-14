from datetime import datetime, timedelta
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from jose import JWTError, jwt
import bcrypt

from database.user_repo import get_user_by_username, create_user

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

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
def signup(user: UserCreate):
    try:
        print(f"[SIGNUP DEBUG] Received: {user.username}, {user.email}")
        existing = get_user_by_username(user.username)
        if existing:
            raise HTTPException(status_code=400, detail="Username already registered")
        print("[SIGNUP DEBUG] Hashing password...")
        hashed = get_password_hash(user.password)
        print(f"[SIGNUP DEBUG] Hash created, creating user in DB...")
        user_id = create_user(user.username, user.email, hashed)
        print(f"[SIGNUP DEBUG] User created with ID: {user_id}")
        access_token = create_access_token({"sub": user.username, "user_id": user_id}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        print(f"[SIGNUP ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token({"sub": user["username"], "user_id": user["id"]}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}
