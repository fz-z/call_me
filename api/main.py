import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from auth import router as auth_router
from agents import router as agents_router
from permissions import router as permissions_router
from admin import router as admin_router
from call import router as call_router
from sip import router as sip_router

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


@app.on_event("startup")
async def startup():
    await asyncio.to_thread(init_db)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
