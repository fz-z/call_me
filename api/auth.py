import os
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import get_db, pwd_context
from models import UserRegister, UserLogin, AuthResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()
JWT_SECRET = os.environ.get("JWT_SECRET", "changeme")
JWT_ALGORITHM = "HS256"


def create_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
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
async def register(body: UserRegister):
    db = await get_db()
    try:
        existing = await db.execute("SELECT id FROM users WHERE username = ?", (body.username,))
        if await existing.fetchone():
            raise HTTPException(status_code=400, detail="Username already taken")

        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, body.username, pwd_context.hash(body.password), "user", now),
        )
        await db.commit()

        token = create_token(user_id, body.username, "user")
        return AuthResponse(token=token, user=UserOut(id=user_id, username=body.username, role="user", created_at=now))
    finally:
        await db.close()


@router.post("/login", response_model=AuthResponse)
async def login(body: UserLogin):
    db = await get_db()
    try:
        row = await db.execute("SELECT * FROM users WHERE username = ?", (body.username,))
        user = await row.fetchone()
        if not user or not pwd_context.verify(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        token = create_token(user["id"], user["username"], user["role"])
        return AuthResponse(
            token=token,
            user=UserOut(id=user["id"], username=user["username"], role=user["role"], created_at=user["created_at"]),
        )
    finally:
        await db.close()
