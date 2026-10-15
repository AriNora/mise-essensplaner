"""Endpunkte fuer den Rezept-Import. Beide liefern einen Entwurf (RecipeCreate),
der im Frontend in den Editor geladen wird — gespeichert wird erst nach Kontrolle
ueber den normalen POST /api/recipes."""
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import importer, schemas

router = APIRouter(prefix="/api/import", tags=["import"])


class UrlIn(BaseModel):
    url: str


class TextIn(BaseModel):
    text: str
    name: Optional[str] = None


@router.post("/url", response_model=schemas.RecipeCreate)
def import_from_url(body: UrlIn):
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "Bitte eine vollständige Adresse angeben (mit http:// oder https://).")
    try:
        return importer.fetch_recipe_from_url(url)
    except importer.UrlNotAllowed:
        raise HTTPException(
            400, "Diese Adresse kann nicht abgerufen werden. Erlaubt sind nur öffentliche Webseiten."
        )
    except importer.PageTooLarge:
        raise HTTPException(422, "Die Seite ist zu groß für den Import.")
    except ValueError:
        raise HTTPException(
            422,
            "Auf dieser Seite wurde kein strukturiertes Rezept gefunden. "
            "Tipp: Zutaten kopieren und über 'Text einfügen' importieren.",
        )
    except requests.RequestException:
        raise HTTPException(502, "Die Seite konnte nicht geladen werden. Stimmt die Adresse?")


@router.post("/text", response_model=schemas.RecipeCreate)
def import_from_text(body: TextIn):
    if not body.text.strip():
        raise HTTPException(400, "Bitte zuerst Zutaten einfügen.")
    return importer.recipe_from_text(body.text, body.name)
