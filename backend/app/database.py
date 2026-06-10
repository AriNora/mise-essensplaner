"""Datenbank-Anbindung.

Wir nutzen SQLite als Single-File-Datenbank (mealplanner.db). Vorteil fuer eine
Einzelarbeit: kein separater DB-Server, eine Datei, trivial vorzufuehren und zu
sichern. SQLAlchemy abstrahiert die DB, sodass ein spaeterer Wechsel auf z.B.
PostgreSQL ohne Aenderung der Modelle moeglich waere.
"""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Die DB-Datei liegt im backend-Ordner.
DB_PATH = Path(__file__).resolve().parent.parent / "mealplanner.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Hochgeladene Rezeptbilder liegen als Dateien hier (nicht in der DB).
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"

# check_same_thread=False ist fuer SQLite + FastAPI noetig (mehrere Threads).
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI-Dependency: liefert pro Request eine Session und schliesst sie sicher."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
