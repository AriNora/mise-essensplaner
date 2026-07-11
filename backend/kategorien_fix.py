r"""Setzt die Warengruppe (category) einzelner Zutaten auf einen kuratierten Wert.

Hintergrund
-----------
Die Kategorie haengt am Zutaten-NAMEN (Ingredient.name ist eindeutig, category
steht einmal pro Name). "Tomaten" ist also EINE Zutat mit EINER Kategorie - egal
in wie vielen Rezepten sie vorkommt. Wurde "Tomaten" irgendwann zuerst als
"Konserven & Vorrat" angelegt, blieb das haengen, weil get_or_create_ingredient
eine schon gesetzte Kategorie nicht mehr ueberschreibt.

Loesung: verschiedene Tomaten-FORMEN sind verschiedene Zutaten (eigener Name ->
eigene, stabile Kategorie). Frische "Tomaten" gehoeren in "Obst & Gemuese", alle
haltbaren Formen (getrocknet, halbgetrocknet, eingelegt, Dose, passiert, Mark)
in "Konserven & Vorrat". Dieses Skript zieht vorhandene Zutaten auf genau diese
Zuordnung nach.

Sicherheit
----------
  - Standardmaessig nur VORSCHAU (schreibt nichts). Erst mit  --apply  wird gespeichert.
  - Umlaut-sicher: Abgleich exakt, dann Unicode-casefold (grosses "Ä" wird erkannt).
  - Idempotent: Ein zweiter Lauf aendert nichts mehr.
  - Am Ende listet das Skript alle Zutaten, deren Name "tomate" enthaelt, aber
    NICHT in der Tabelle unten steht - damit du eigene Schreibweisen pruefen kannst.

Aufruf (im Ordner backend, mit derselben venv wie der Server):
  Vorschau:   .\.venv\Scripts\python.exe kategorien_fix.py
  Schreiben:  .\.venv\Scripts\python.exe kategorien_fix.py --apply
"""
import sys

from app.database import SessionLocal
from app import models

# --------------------------------------------------------------------------- #
#  Kuratierte Zuordnung: Zutatenname -> korrekte Warengruppe.
#  Frisch -> "Obst & Gemuese"; alles Haltbare -> "Konserven & Vorrat".
#  Die Liste ist bewusst erweiterbar: weitere Namen/Formen einfach ergaenzen.
# --------------------------------------------------------------------------- #
FRISCH = "Obst & Gemüse"
VORRAT = "Konserven & Vorrat"

CATEGORY_MAP = {
    # frisch
    "Tomaten": FRISCH,
    "Kirschtomaten": FRISCH,
    "Cherrytomaten": FRISCH,
    "Cocktailtomaten": FRISCH,
    "Datteltomaten": FRISCH,
    "Rispentomaten": FRISCH,
    "Fleischtomaten": FRISCH,
    # haltbar / Vorrat
    "Getrocknete Tomaten": VORRAT,
    "Halbgetrocknete Tomaten": VORRAT,
    "Eingelegte Tomaten": VORRAT,
    "Dosentomaten": VORRAT,
    "Geschälte Tomaten": VORRAT,
    "Passierte Tomaten": VORRAT,
    "Stückige Tomaten": VORRAT,
    "Tomatenpassata": VORRAT,
    "Tomatenmark": VORRAT,
}


def _find(session, name):
    """Zutat per Name finden - exakt, dann Unicode-casefold (umlaut-sicher)."""
    ing = session.query(models.Ingredient).filter(models.Ingredient.name == name).first()
    if ing is not None:
        return ing
    folded = name.casefold()
    for cand in session.query(models.Ingredient).all():
        if cand.name.casefold() == folded:
            return cand
    return None


def main(apply: bool) -> None:
    session = SessionLocal()
    try:
        changes, unchanged, missing = [], 0, []
        for name, cat in CATEGORY_MAP.items():
            ing = _find(session, name)
            if ing is None:
                missing.append(name)
                continue
            if ing.category == cat:
                unchanged += 1
                continue
            changes.append((ing.name, ing.category, cat))
            if apply:
                ing.category = cat

        # Kontrolle: unbekannte "Tomaten"-Schreibweisen aufspueren.
        known = {n.casefold() for n in CATEGORY_MAP}
        stray = [
            (i.name, i.category)
            for i in session.query(models.Ingredient).all()
            if "tomate" in i.name.casefold() and i.name.casefold() not in known
        ]

        print(f"Zutaten in der Zuordnung: {len(CATEGORY_MAP)}")
        print(f"Bereits korrekt:          {unchanged}")
        print(f"Nicht in der DB (ignoriert): {len(missing)}"
              + (f" -> {', '.join(missing)}" if missing else ""))
        print(f"Zu aendern:               {len(changes)}")
        for nm, alt, neu in changes:
            print(f"  - {nm}: {alt!r} -> {neu!r}")
        if stray:
            print("\nHINWEIS - 'Tomaten'-Zutaten ausserhalb der Zuordnung (bitte pruefen):")
            for nm, cat in stray:
                print(f"  ? {nm}: aktuell {cat!r}")

        if apply:
            session.commit()
            print("\nGESPEICHERT.")
        else:
            print("\nVORSCHAU - es wurde nichts geschrieben. Zum Speichern:  "
                  "python kategorien_fix.py --apply")
    finally:
        session.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
