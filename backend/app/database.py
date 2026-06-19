"""Datenbank-Anbindung.

Wir nutzen SQLite als Single-File-Datenbank (mealplanner.db). Vorteil fuer eine
Einzelarbeit: kein separater DB-Server, eine Datei, trivial vorzufuehren und zu
sichern. SQLAlchemy abstrahiert die DB, sodass ein spaeterer Wechsel auf z.B.
PostgreSQL ohne Aenderung der Modelle moeglich waere.
"""
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker


def _unicode_lower(value):
    return value.lower() if isinstance(value, str) else value


def _unicode_upper(value):
    return value.upper() if isinstance(value, str) else value


@event.listens_for(Engine, "connect")
def _register_unicode_functions(dbapi_connection, connection_record):
    """SQLites eingebautes lower()/upper() ist ASCII-only: aus 'Ä' wird kein 'ä'.

    Dadurch scheiterte jeder SQL-seitige Vergleich mit gross geschriebenen
    Umlauten am Wortanfang (Äthiopisch, Österreichisch, ...). Statt das an jeder
    Abfrage einzeln zu umgehen, ueberschreiben wir lower()/upper() pro Verbindung
    mit Pythons Unicode-faehigen Varianten. Damit ist JEDER Vergleich
    (func.lower(...), ilike, Zaehlungen) automatisch umlaut-korrekt - auch in
    Code, den wir spaeter erst schreiben. Greift fuer jede SQLite-Verbindung,
    also auch fuer eine frische Nutzer-Datenbank.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return  # andere DBs (z.B. PostgreSQL) sind ohnehin Unicode-korrekt
    try:
        dbapi_connection.create_function("lower", 1, _unicode_lower, deterministic=True)
        dbapi_connection.create_function("upper", 1, _unicode_upper, deterministic=True)
    except TypeError:
        # deterministic gibt es erst ab Python 3.8 / neuerem SQLite -> ohne Flag.
        dbapi_connection.create_function("lower", 1, _unicode_lower)
        dbapi_connection.create_function("upper", 1, _unicode_upper)

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