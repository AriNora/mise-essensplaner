"""Gemeinsame Test-Hilfen: eine Test-App mit eigener In-Memory-Datenbank.

Die App wird bewusst NICHT ueber app.main gebaut: main.py legt beim Import
Tabellen in der echten mealplanner.db an. Hier werden nur die Router
eingehaengt; Datenbank und Upload-Ordner sind pro Test frisch und wegwerfbar.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import backup as backup_module, crud
from app.database import Base, get_db
from app.routers import backup as backup_router, bring, imports, ingredients, pantry, plan, recipes, tags


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # StaticPool: alle Verbindungen teilen sich dieselbe In-Memory-DB.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    # Uploads landen im temporaeren Ordner, nie im echten uploads/.
    # (zwei Stellen: das Router-Modul schreibt, crud.py loescht)
    monkeypatch.setattr(recipes, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(crud, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(backup_module, "UPLOAD_DIR", tmp_path)

    app = FastAPI()
    for module in (recipes, ingredients, plan, imports, tags, pantry, bring, backup_router):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        c.upload_dir = tmp_path
        yield c
    engine.dispose()
