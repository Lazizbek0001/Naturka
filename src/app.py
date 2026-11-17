
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.db.base import Base
from src.db.session import engine

import src.db.models

from src.api.routes.railway import router as railway_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For a new development database only.
    # Existing databases require Alembic migrations.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Naturka Railway API",
    description="Railway sorting and dispatch management",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(railway_router)


@app.get("/")
def root():
    return {
        "name": "Naturka Railway API",
        "version": "3.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
