"""Endpunkt fuer Zutaten-Autovervollstaendigung im Rezept-Editor."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db

router = APIRouter(prefix="/api/ingredients", tags=["ingredients"])


@router.get("")
def search_ingredients(search: str = "", db: Session = Depends(get_db)):
    ings = crud.search_ingredients(db, search)
    return [{"name": i.name, "category": i.category} for i in ings]
