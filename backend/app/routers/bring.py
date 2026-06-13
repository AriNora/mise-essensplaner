"""Endpunkte fuer die Bring!-Anbindung: Status abfragen und Liste senden."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import bring, crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/bring", tags=["bring"])


def _spec(amount, unit) -> str:
    """Mengenangabe als kurze Notiz fuer Bring!, z.B. '500 g' oder '1,5 l'.

    Ohne Menge (z.B. 'Salz nach Geschmack') bleibt die Notiz leer – dann steht
    in Bring! nur der Artikelname.
    """
    if amount is None:
        return ""
    if float(amount).is_integer():
        num = str(int(amount))
    else:
        num = f"{amount:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{num} {unit}".strip() if unit else num


@router.get("/status")
def status():
    """Sagt dem Frontend, ob Zugangsdaten hinterlegt sind."""
    return {"configured": bring.is_configured()}


@router.post("/send")
def send(payload: Optional[schemas.BringSendRequest] = None, db: Session = Depends(get_db)):
    """Schickt Posten an Bring!.

    Werden im Body `items` mitgegeben (die im Browser nicht abgehakten Posten),
    senden wir genau diese. Ohne `items` faellt der Endpunkt auf die komplette,
    aggregierte Einkaufsliste zurueck.
    """
    if payload is not None and payload.items is not None:
        items = [(it.name, _spec(it.amount, it.unit)) for it in payload.items]
    else:
        data = crud.build_shopping_list(db)
        items = [
            (item["name"], _spec(item["amount"], item.get("unit")))
            for group in data["groups"]
            for item in group["items"]
        ]
    try:
        result = bring.send_items(items)
    except bring.BringError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return result
