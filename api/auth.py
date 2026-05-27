import os
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import get_db, pwd_context, _sync_conn
from models import UserRegister, UserLogin, AuthResponse, UserOut, ChangePassword

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()
JWT_SECRET = os.environ.get("JWT_SECRET", "changeme")
JWT_ALGORITHM = "HS256"


def create_token(user_id: str, username: str, role: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + 86400,  # 24 hours
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {"id": payload["sub"], "username": payload["username"], "role": payload["role"]}
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


@router.post("/register", response_model=AuthResponse)
def register(body: UserRegister):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")

    db = _sync_conn()
    try:
        existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")

        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, pwd_context.hash(body.password), "user", now),
        )
        db.commit()

        token = create_token(user_id, username, "user")
        return AuthResponse(token=token, user=UserOut(id=user_id, username=username, role="user", created_at=now))
    finally:
        db.close()


@router.post("/login", response_model=AuthResponse)
def login(body: UserLogin):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    db = _sync_conn()
    try:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = row.fetchone()
        if not user or not pwd_context.verify(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        token = create_token(user["id"], user["username"], user["role"])
        return AuthResponse(
            token=token,
            user=UserOut(id=user["id"], username=user["username"], role=user["role"], created_at=user["created_at"]),
        )
    finally:
        db.close()


@router.put("/change-password", status_code=204)
def change_password(body: ChangePassword, user: dict = Depends(get_current_user)):
    db = _sync_conn()
    try:
        row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not pwd_context.verify(body.old_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="旧密码错误")

        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pwd_context.hash(body.new_password), user["id"]),
        )
        db.commit()
    finally:
        db.close()
    return None
