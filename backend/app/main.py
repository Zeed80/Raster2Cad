from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import jobs, models
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(models.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")


@app.on_event("startup")
async def startup() -> None:
    await jobs.pipeline.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await jobs.pipeline.shutdown()


@app.get("/")
async def root() -> dict[str, str | bool]:
    return {
        "name": settings.app_name,
        "status": "ok",
        "live_model_calls": settings.enable_live_model_calls,
    }
