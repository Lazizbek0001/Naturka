from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.db.base import Base
from src.db.session import engine
import src.db.models  # register all models
from src.api.routes.railway import router as railway_router
from src.api.routes.auth import router as auth_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # For fresh development DB only. Use Alembic on existing DB.
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Naturka Railway API", version="4.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500",
                   "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(railway_router)

@app.get("/health")
def health():
    return {"status": "ok"}