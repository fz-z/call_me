import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from auth import router as auth_router
from agents import router as agents_router

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


@app.on_event("startup")
async def startup():
    await asyncio.to_thread(init_db)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
