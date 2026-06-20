"""FastAPI entrypoint.

Run locally:  uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

from app.config import settings
from app.db import create_redis_pool, engine
from app.models import Base
from app.routers import ask as ask_router
from app.routers import documents as documents_router
from app.routers import auth as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app.state.arq_redis = await create_redis_pool()
    yield
    await app.state.arq_redis.aclose()


app = FastAPI(title="SEC Insight", version="0.1.0", lifespan=lifespan)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router.router)
app.include_router(ask_router.router)
app.include_router(documents_router.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
