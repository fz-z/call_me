import asyncio
import os
import uuid

from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import init_db
from auth import router as auth_router, require_admin
from agents import router as agents_router
from permissions import router as permissions_router
from admin import router as admin_router
from call import router as call_router
from sip import router as sip_router
from api_keys import router as api_keys_router
from model_configs import router as model_configs_router
from tts_configs import router as tts_configs_router
from voices import router as voices_router
from worker import router as worker_router

app = FastAPI(title="call_me API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(permissions_router)
app.include_router(admin_router)
app.include_router(call_router)
app.include_router(sip_router)
app.include_router(api_keys_router)
app.include_router(model_configs_router)
app.include_router(tts_configs_router)
app.include_router(voices_router)
app.include_router(worker_router)


@app.on_event("startup")
async def startup():
    await asyncio.to_thread(init_db)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


PHOTOS_DIR = os.environ.get("PHOTOS_DIR", "/data/photos")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB


@app.post("/api/admin/upload")
async def upload_photo(
    file: UploadFile = File(...),
    _: None = Depends(require_admin),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"ok": False, "error": f"不支持的格式: {ext}，仅支持 jpg/png/webp"}
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE:
        return {"ok": False, "error": "文件太大，最大 5MB"}
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(PHOTOS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)
    return {"ok": True, "url": f"/photos/{filename}"}


os.makedirs(PHOTOS_DIR, exist_ok=True)
app.mount("/photos", StaticFiles(directory=PHOTOS_DIR), name="photos")

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    flutter_dir = os.path.join(os.path.dirname(__file__), "flutter_app")
    if os.path.isdir(flutter_dir):
        app.mount("/app", StaticFiles(directory=flutter_dir, html=True), name="flutter_app")
    app.mount("/admin", StaticFiles(directory=static_dir, html=True), name="admin")



