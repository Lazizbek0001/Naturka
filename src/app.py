from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.db.base import Base
from src.db.session import engine
import src.db.models  # register all models
from src.api.routes.railway import router as railway_router
from src.api.routes.auth import router as auth_router
from src.api.routes.manage import router as manage_router
from src.api.routes.station_refs import router as refs_router
from src.api.routes.drawings import router as drawings_router
from src.api.routes.schemes import router as schemes_router, seed_existing
from src.api.routes.weather import router as weather_router
from src.api.routes.team_platforms import router as team_platforms_router

def add_missing_columns():
    """create_all не добавляет новые колонки в существующие таблицы — добавляем их сами."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} '
                                      f'{col.type.compile(dialect=engine.dialect)}'))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For fresh development DB only. Use Alembic on existing DB.
    Base.metadata.create_all(bind=engine)
    add_missing_columns()
    from src.db.session import SessionLocal
    with SessionLocal() as db:
        seed_existing(db)  # схемы и чертежи станций — в БД
        from src.api.routes.drawings import migrate_all
        migrate_all(db)  # чертёж — набор объектов для редактора
        from src.services.railway_order import backfill_positions
        backfill_positions(db)  # порядок путей станции
    yield

app = FastAPI(title="Naturka Railway API", version="4.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500",
                   "http://127.0.0.1:5173", "http://localhost:5173"],
    # страницы, открытые из локальной сети (10.x, 172.16–31.x, 192.168.x)
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10(\.\d{1,3}){3}|192\.168(\.\d{1,3}){2}"
                       r"|172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2})(:\d+)?$",
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(manage_router)
app.include_router(refs_router)
app.include_router(drawings_router)
app.include_router(schemes_router)
app.include_router(railway_router)
app.include_router(weather_router)
app.include_router(team_platforms_router)

@app.get("/health")
def health():
    return {"status": "ok"}