"""Endpunkte fuer den Vorrat (Zutaten, die immer vorhanden sind)."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import pantry, schemas
from ..database import get_db

router = APIRouter(prefix="/api/pantry", tags=["pantry"])


@router.get("", response_model=List[schemas.PantryItemOut])
def list_pantry(db: Session = Depends(get_db)):
    return pantry.list_items(db)


@router.post("", response_model=schemas.PantryItemOut, status_code=201)
def add_pantry_item(data: schemas.PantryItemIn, db: Session = Depends(get_db)):
    try:
        item = pantry.add_item(db, data.name)
    except ValueError:
        raise HTTPException(422, "Bitte einen Zutatennamen angeben.")
    if item is None:
        raise HTTPException(409, "Diese Zutat ist schon im Vorrat.")
    return item


@router.delete("/{item_id}", status_code=204)
def remove_pantry_item(item_id: int, db: Session = Depends(get_db)):
    if not pantry.delete_item(db, item_id):
        raise HTTPException(404, "Eintrag nicht gefunden")
