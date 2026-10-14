"""Einstiegspunkt der Anwendung.

Ein einziger FastAPI-Server uebernimmt zwei Aufgaben:
  1. Die REST-API unter /api/...
  2. Das statische Frontend (HTML/CSS/JS) unter /

Vorteil dieser "schlanken Full-Stack"-Variante: ein Prozess, ein Startbefehl,
keine getrennten Server, keine CORS-Probleme (alles same-origin). Genau das
Richtige fuer eine Einzelarbeit, die zuverlaessig vorfuehrbar sein soll.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from sqlalchemy import inspect, text

from .database import UPLOAD_DIR, Base, SessionLocal, engine
from .pantry import seed_defaults as seed_pantry_defaults
from .routers import bring, imports, ingredients, pantry, plan, recipes, tags

# Tabellen anlegen, falls noch nicht vorhanden. Ob der Vorrat neu ist, merken wir
# uns vorher: nur dann werden einmalig die Startwerte eingetragen.
pantry_is_new = "pantry_items" not in inspect(engine).get_table_names()
Base.metadata.create_all(bind=engine)


def ensure_schema():
    """Leichte Migration: ergaenzt fehlende Spalten in einer bestehenden DB.

    `create_all` legt nur komplett fehlende Tabellen an, aber keine neuen Spalten
    in bereits existierenden. Damit eine aeltere mealplanner.db ohne Datenverlust
    weiterlaeuft, ergaenzen wir die Bild-Spalte hier bei Bedarf nach.
    """
    columns = [c["name"] for c in inspect(engine).get_columns("recipes")]
    if "image" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE recipes ADD COLUMN image VARCHAR"))


ensure_schema()

if pantry_is_new:
    with SessionLocal() as _db:
        seed_pantry_defaults(_db)

app = FastAPI(title="Essensplaner", version="1.0")

# API-Router
app.include_router(recipes.router)
app.include_router(ingredients.router)
app.include_router(plan.router)
app.include_router(imports.router)
app.include_router(tags.router)
app.include_router(pantry.router)
app.include_router(bring.router)

# Hochgeladene Rezeptbilder unter /uploads ausliefern.
# WICHTIG: vor dem "/"-Mount, da dieser als Catch-all alles abfaengt.
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

class NoCacheStaticFiles(StaticFiles):
    """Frontend-Dateien mit `Cache-Control: no-cache` ausliefern.

    Der Browser speichert die Dateien weiterhin, fragt aber vor jeder Nutzung
    nach (ETag -> 304, falls unveraendert). Ohne den Header schaetzt er die
    Gueltigkeit selbst und zeigt nach einem Update teils die alte app.js.
    """

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Frontend: statische Dateien aus ../frontend ausliefern (html=True -> index.html
# wird automatisch fuer / geliefert).
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
