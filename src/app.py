from contextlib import asynccontextmanager

from fastapi import FastAPI

import src.db.models  # noqa: F401  (registers all tables on Base.metadata)
from src.api.yard import router as yard_router
from src.core.config import settings
from src.db.base import Base
from src.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)
app.include_router(yard_router)
