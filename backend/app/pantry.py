"""Vorrat: Zutaten, die immer vorhanden sind und nie auf der Einkaufsliste landen.

Eintraege haben bewusst keine Menge. Der Abgleich mit den Zutaten eines Rezepts
folgt einer einfachen, erklaerbaren Regel:

    Ein Vorrats-Eintrag deckt eine Zutat ab, wenn er am ENDE des Namens steht.

    Vorrat "Wasser"  -> deckt "Wasser", "kochendes Wasser", "Wasser, lauwarm"
    Vorrat "Pfeffer" -> deckt "Pfeffer", "schwarzer Pfeffer"
    NICHT gedeckt: zusammengesetzte Woerter ("Cayennepfeffer", "Sprudelwasser").
    Die kann man bei Bedarf als eigenen Eintrag aufnehmen.

Zusaetze nach einem Komma oder in Klammern werden vorher abgeschnitten
("Tomaten (Dose)" -> "Tomaten"). Bei "Salz und Pfeffer" muessen ALLE Teile im
Vorrat sein. Die Rezepte selbst bleiben unveraendert - der Vorrat wirkt nur auf
die Einkaufsliste.
"""
import re
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from . import models
from .normalize import ingredient_key

# Wird einmalig eingetragen, wenn die Vorrats-Tabelle neu angelegt wird.
# Danach gehoert die Liste dem Nutzer (aenderbar auf der Seite "Vorrat").
DEFAULT_PANTRY = ["Wasser", "Nudelwasser", "Salz", "Pfeffer"]

_PARENS = re.compile(r"\([^)]*\)")
_ALTERNATIVES = re.compile(r"\s+(?:und|oder)\s+|\s*[/&]\s*", re.IGNORECASE)


def _strip_extras(text: str) -> str:
    """Klammern und alles ab dem ersten Komma entfernen."""
    return _PARENS.sub(" ", text or "").split(",", 1)[0]


def clean_name(name: str) -> str:
    """Anzeigename eines Vorrats-Eintrags (ohne Zusaetze, Leerraum geglaettet)."""
    return " ".join(_strip_extras(name).split())


def pantry_key(name: str) -> str:
    """Vergleichsschluessel: Woerter einzeln normalisiert (siehe normalize.py)."""
    return " ".join(ingredient_key(t) for t in clean_name(name).split())


def find_pantry_match(name: str, items: Iterable) -> Optional[str]:
    """Liefert den Namen des deckenden Vorrats-Eintrags oder None.

    `items`: Objekte mit `.name` und `.key` (PantryItem). Bei "A und B" werden
    alle Teile gebraucht; der Rueckgabewert ist dann z.B. "Salz + Pfeffer".
    """
    by_key = {it.key: it.name for it in items}
    if not by_key:
        return None
    parts = [p for p in _ALTERNATIVES.split(_strip_extras(name)) if p.strip()]
    hits: List[str] = []
    for part in parts:
        tokens = [ingredient_key(t) for t in part.split()]
        hit = next(
            (by_key[" ".join(tokens[-n:])] for n in range(1, len(tokens) + 1)
             if " ".join(tokens[-n:]) in by_key),
            None,
        )
        if hit is None:
            return None
        hits.append(hit)
    return " + ".join(dict.fromkeys(hits)) if hits else None


# --------------------------------------------------------------------------- #
#  Datenbank-Zugriff
# --------------------------------------------------------------------------- #
def list_items(db: Session) -> List[models.PantryItem]:
    return sorted(db.query(models.PantryItem).all(), key=lambda i: i.name.casefold())


def add_item(db: Session, name: str) -> Optional[models.PantryItem]:
    """Legt einen Eintrag an. None, wenn es ihn schon gibt; ValueError, wenn leer."""
    display = clean_name(name)
    key = pantry_key(name)
    if not key:
        raise ValueError("empty")
    if db.query(models.PantryItem).filter(models.PantryItem.key == key).first():
        return None
    item = models.PantryItem(name=display, key=key)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> bool:
    item = db.query(models.PantryItem).filter(models.PantryItem.id == item_id).first()
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


def seed_defaults(db: Session) -> None:
    for name in DEFAULT_PANTRY:
        add_item(db, name)
