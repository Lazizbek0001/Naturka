import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("INITIAL_SUPERUSER_USERNAME", "test")
os.environ.setdefault("INITIAL_SUPERUSER_PASSWORD", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app import app
from src.db.base import Base
from src.db.session import get_db

REPORT = """(:02 7200 2058 6980 583 7200 1 21 10 09 48 066 05097 6 0000 0 0
 01 29265592 0201 067 72000  52101 9008 0 0 5 2 00/00 00000  000'OXP
 02 29417854 0201 067 72000  52101 9008 0 0 5 2 00/00 00000  000'OXP
 03 29574795 0201 067 72000  52101 9008 0 0 5 2 00/00 00000  000'OXP
 04 28826030 0201 066 72357  12201 9999 0 0 6 2 00/00 00000  000'OXP
 05 63911986 0201 068 72254  32416 9999 0 0 6 0 00/00 00000  000'OXP
 06 51108819 0201 000 72254  42120 9999 9 8 6 1 00/00 00000  000'ПEPECЛ
 07 50037548 0201 000 72309  42103 9999 0 6 0 1 00/00 00000  000'61707-
 08 28010148 0271 068 72000  04302 1026 0 0 0 2 00/00 00000  000'OXPAHA:)
"""


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def yard(client):
    """Railway ids by name: entrance 1, sorting 43 and 47, departure 23, connecting 5."""
    ids = {}
    for name, code, type_ in [
        ("entrance", "1", 1),
        ("s43", "43", 2),
        ("s47", "47", 2),
        ("departure", "23", 3),
        ("connecting", "5", 4),
    ]:
        r = client.post("/railways", json={"code": code, "length": 70, "type": type_})
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    return ids
