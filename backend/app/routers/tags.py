"""REST-Endpunkt fuer Schlagworte (Tags).

Liefert alle benutzten Tags samt Anzahl der Rezepte – das Frontend baut daraus
die gruppierte Filterleiste (Chips mit Trefferzahl).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=schemas.TagListResponse)
def list_tags(db: Session = Depends(get_db)):
    return {"tags": crud.get_tags_with_counts(db)}
