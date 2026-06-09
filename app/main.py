"""FastAPI entrypoint.

Run locally:  uvicorn app.main:app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import engine
from app.models import Base
from app.routers import ask as ask_router
from app.routers import documents as documents_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="SEC Insight", version="0.1.0", lifespan=lifespan)
app.include_router(ask_router.router)
app.include_router(documents_router.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
