"""Datenbank-Operationen: Rezepte, Zutaten, Tags und Wochenplan.

Die fachliche Kernlogik liegt in eigenen Modulen:
  - shopping.py  Einkaufsliste (Portions-Skalierung, Zusammenfassen, Einheiten)
  - prep.py      Vorbereitungsplan (Mise en place)
  - pantry.py    Vorrat
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas
from .database import UPLOAD_DIR
from .normalize import ingredient_key


def image_url(filename: Optional[str]) -> Optional[str]:
    """Dateiname -> oeffentliche URL, unter der das Bild ausgeliefert wird."""
    return f"/uploads/{filename}" if filename else None


def delete_image_file(filename: Optional[str]) -> None:
    """Loescht die Bilddatei auf der Platte (falls vorhanden)."""
    if not filename:
        return
    try:
        (UPLOAD_DIR / filename).unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
#  Zutaten (kanonisch)
# --------------------------------------------------------------------------- #
def get_or_create_ingredient(db: Session, name: str, category: Optional[str]) -> models.Ingredient:
    """Findet eine Zutat per Name oder legt sie an. So bleibt 'Zwiebel' EINE Zutat,
    egal in wie vielen Rezepten sie vorkommt -> Voraussetzung fuer korrektes
    Aufsummieren in der Einkaufsliste.

    Wichtig: SQLites eingebautes lower() kann nur ASCII, macht also aus 'Öl'
    KEIN 'öl'. Ein reiner `func.lower(...)`-Vergleich uebersieht daher bereits
    vorhandene Zutaten mit grossem Umlaut am Anfang (Öl, Äpfel, ...) und wuerde
    sie erneut anlegen -> UNIQUE-Fehler beim Import. Darum:
      1) exakter Namensabgleich (trifft den Normalfall beim Import zuverlaessig),
      2) Fallback: gleiche Zutat in anderer Schreibweise (Gross-/Kleinschreibung,
         Leerzeichen, Plural: 'Zwiebeln' -> vorhandene 'Zwiebel'), verglichen
         ueber ingredient_key() aus normalize.py. So entstehen keine Dubletten,
         die die Einkaufsliste als getrennte Zeilen fuehren wuerde.
    """
    name = name.strip()
    # 1) Exakter Treffer (schnell, dank UNIQUE-Index) - faengt auch Umlaut-Namen.
    ing = db.query(models.Ingredient).filter(models.Ingredient.name == name).first()
    # 2) Fallback: gleiche Zutat in anderer Schreibweise (siehe normalize.py).
    if ing is None:
        key = ingredient_key(name)
        for cand in db.query(models.Ingredient).all():
            if ingredient_key(cand.name) == key:
                ing = cand
                break
    if ing is None:
        ing = models.Ingredient(name=name, category=category)
        db.add(ing)
        db.flush()  # vergibt ID, ohne Transaktion abzuschliessen
    elif category and ing.category != category:
        # Eine ausdruecklich gelieferte Kategorie hat Vorrang und aktualisiert die
        # vorhandene (last-write-wins). Sonst bliebe eine einmal falsch gesetzte
        # Warengruppe fuer immer haengen - z.B. "Tomaten", die zuerst als
        # "Konserven & Vorrat" angelegt wurden. Verschiedene FORMEN (frisch vs.
        # getrocknet/Dose) sollten weiterhin eigene Namen bekommen, damit sie sich
        # nicht gegenseitig ueberschreiben.
        ing.category = category
    return ing


def search_ingredients(db: Session, query: str, limit: int = 10) -> List[models.Ingredient]:
    q = db.query(models.Ingredient)
    if query:
        q = q.filter(models.Ingredient.name.ilike(f"%{query}%"))
    return q.order_by(models.Ingredient.name).limit(limit).all()


# --------------------------------------------------------------------------- #
#  Tags / Schlagworte (kanonisch, n:m zu Rezepten)
# --------------------------------------------------------------------------- #
# Erlaubte Facetten in Anzeige-Reihenfolge. Tags mit anderem `kind` werden beim
# Speichern ignoriert -> haelt die Daten sauber (kontrolliertes Vokabular).
KIND_ORDER = list(schemas.TAG_KINDS)


def get_or_create_tag(db: Session, kind: str, name: str) -> Optional[models.Tag]:
    """Findet ein Tag per (kind, name) oder legt es an. Gleiche Idee wie bei den
    Zutaten: jedes Schlagwort existiert genau einmal, Rezepte verweisen darauf."""
    kind = (kind or "").strip().lower()
    # Kommas wuerden die Filter-Parameter (CSV) zerlegen -> entfernen; Mehrfach-
    # Leerzeichen zusammenfassen; aussen trimmen. Gilt fuer alle Quellen.
    name = " ".join((name or "").replace(",", " ").split())
    if kind not in KIND_ORDER or not name:
        return None
    # Wie bei den Zutaten: SQLites lower() ist ASCII-only, macht aus 'Äthiopisch'
    # KEIN 'äthiopisch'. Ein reiner func.lower(...)-Vergleich uebersieht daher ein
    # bereits vorhandenes Tag mit grossem Umlaut am Anfang (Äthiopisch, Südafrika-
    # nisch, ...) und wuerde es erneut anlegen -> UNIQUE-Fehler beim Import. Darum:
    #   1) exakter Abgleich (kind, name) - faengt auch Umlaut-Namen zuverlaessig,
    #   2) Fallback: Unicode-korrekter, gross-/kleinschreibungsunabhaengiger
    #      Vergleich in Python (casefold) ueber die vorhandenen Tags derselben Facette.
    tag = (
        db.query(models.Tag)
        .filter(models.Tag.kind == kind, models.Tag.name == name)
        .first()
    )
    if tag is None:
        folded = name.casefold()
        for cand in db.query(models.Tag).filter(models.Tag.kind == kind).all():
            if cand.name.casefold() == folded:
                tag = cand
                break
    if tag is None:
        tag = models.Tag(kind=kind, name=name)
        db.add(tag)
        db.flush()  # vergibt ID, ohne Transaktion abzuschliessen
    return tag


def _apply_tags(db: Session, recipe: models.Recipe, items: List[schemas.TagIn]) -> None:
    """Ersetzt die Tag-Liste eines Rezepts vollstaendig (Duplikate werden entfernt)."""
    seen = set()
    tags = []
    for item in items:
        tag = get_or_create_tag(db, item.kind, item.name)
        if tag is None or tag.id in seen:
            continue
        seen.add(tag.id)
        tags.append(tag)
    recipe.tags = tags


def get_tags_with_counts(db: Session) -> List[dict]:
    """Alle benutzten Tags mit Anzahl der Rezepte – Grundlage der Filter-Chips.

    Nur Tags, die an mindestens einem Rezept haengen, werden zurueckgegeben
    (ein Filter ohne Treffer waere nutzlos). Sortiert nach Facette, dann Name.
    """
    rows = (
        db.query(
            models.Tag.kind,
            models.Tag.name,
            func.count(models.recipe_tags.c.recipe_id).label("count"),
        )
        .join(models.recipe_tags, models.Tag.id == models.recipe_tags.c.tag_id)
        .group_by(models.Tag.id)
        .all()
    )

    def sort_key(r):
        kind = r[0]
        kpos = KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)
        return (kpos, r[1].lower())

    rows = sorted(rows, key=sort_key)
    return [{"kind": k, "name": n, "count": c} for k, n, c in rows]


# --------------------------------------------------------------------------- #
#  Rezepte
# --------------------------------------------------------------------------- #
def _apply_ingredients(db: Session, recipe: models.Recipe, items: List[schemas.RecipeIngredientBase]) -> None:
    """Ersetzt die Zutatenliste eines Rezepts vollstaendig (einfach + korrekt)."""
    recipe.ingredients.clear()
    for pos, item in enumerate(items):
        ing = get_or_create_ingredient(db, item.name, item.category)
        recipe.ingredients.append(
            models.RecipeIngredient(
                ingredient=ing,
                amount=item.amount,
                unit=(item.unit or None),
                preparation=(item.preparation or None),
                position=pos,
            )
        )


def create_recipe(db: Session, data: schemas.RecipeCreate) -> models.Recipe:
    recipe = models.Recipe(
        name=data.name.strip(),
        servings=data.servings,
        instructions=data.instructions,
        source=data.source,
    )
    db.add(recipe)  # zuerst in die Session, damit angehaengte Zutaten sauber kaskadieren
    _apply_ingredients(db, recipe, data.ingredients)
    _apply_tags(db, recipe, data.tags)
    db.commit()
    db.refresh(recipe)
    return recipe


def update_recipe(db: Session, recipe: models.Recipe, data: schemas.RecipeUpdate) -> models.Recipe:
    recipe.name = data.name.strip()
    recipe.servings = data.servings
    recipe.instructions = data.instructions
    recipe.source = data.source
    _apply_ingredients(db, recipe, data.ingredients)
    _apply_tags(db, recipe, data.tags)
    db.commit()
    db.refresh(recipe)
    return recipe


def get_recipe(db: Session, recipe_id: int) -> Optional[models.Recipe]:
    return db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()


def delete_recipe(db: Session, recipe: models.Recipe) -> None:
    delete_image_file(recipe.image)  # verwaiste Bilddatei vermeiden
    db.delete(recipe)
    db.commit()


def list_recipes(
    db: Session,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    facets: Optional[Dict[str, List[str]]] = None,
) -> Tuple[int, List[dict]]:
    """Paginierte, schlanke Liste. Bei ~1000 Rezepten liefern wir bewusst nur die
    aktuelle Seite + die Zutatenanzahl, nicht alle Zutaten.

    `facets` filtert nach Tags, z.B. {"typ": ["Suppe", "Curry"], "kueche": ["Indisch"]}.
    Semantik (Standard fuer Facettensuche):
      - innerhalb einer Facette ODER  (Suppe ODER Curry)
      - ueber Facetten hinweg  UND    (… UND Indisch)
    Umgesetzt als je eine EXISTS/IN-Unterabfrage pro Facette, mit AND verknuepft.
    """
    base = db.query(models.Recipe)
    if search:
        base = base.filter(models.Recipe.name.ilike(f"%{search}%"))

    for kind, names in (facets or {}).items():
        clean = [n.strip().lower() for n in names if n and n.strip()]
        if not clean:
            continue
        # func.lower() ist hier dank des Unicode-Overrides in database.py auch fuer
        # grosse Umlaute am Wortanfang korrekt (Äthiopisch, Österreichisch, ...).
        # Ohne diesen Override wuerde SQLites ASCII-lower() solche Tags uebersehen.
        sub = (
            db.query(models.recipe_tags.c.recipe_id)
            .join(models.Tag, models.Tag.id == models.recipe_tags.c.tag_id)
            .filter(models.Tag.kind == kind)
            .filter(func.lower(models.Tag.name).in_(clean))
        )
        base = base.filter(models.Recipe.id.in_(sub))

    total = base.count()
    recipes = base.order_by(models.Recipe.name).offset(offset).limit(limit).all()

    # Zutatenanzahl je Rezept der Seite in EINER Query (vermeidet N+1).
    ids = [r.id for r in recipes]
    counts = {}
    if ids:
        rows = (
            db.query(models.RecipeIngredient.recipe_id, func.count().label("c"))
            .filter(models.RecipeIngredient.recipe_id.in_(ids))
            .group_by(models.RecipeIngredient.recipe_id)
            .all()
        )
        counts = {rid: c for rid, c in rows}

    items = [
        {"id": r.id, "name": r.name, "servings": r.servings,
         "ingredient_count": counts.get(r.id, 0), "image": image_url(r.image)}
        for r in recipes
    ]
    return total, items


def recipe_to_out(recipe: models.Recipe) -> dict:
    """Wandelt ein Rezept in die API-Ausgabeform (mit aufgeloesten Zutatennamen)."""
    return {
        "id": recipe.id,
        "name": recipe.name,
        "servings": recipe.servings,
        "instructions": recipe.instructions,
        "source": recipe.source,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
        "image": image_url(recipe.image),
        "ingredients": [
            {
                "name": ri.ingredient.name,
                "amount": ri.amount,
                "unit": ri.unit,
                "preparation": ri.preparation,
                "category": ri.ingredient.category,
                "position": ri.position,
            }
            for ri in recipe.ingredients
        ],
        "tags": [{"kind": t.kind, "name": t.name} for t in recipe.tags],
    }


# --------------------------------------------------------------------------- #
#  Wochenplan
# --------------------------------------------------------------------------- #
def add_plan_entry(db: Session, data: schemas.PlanEntryCreate) -> Optional[models.PlanEntry]:
    if get_recipe(db, data.recipe_id) is None:
        return None
    entry = models.PlanEntry(recipe_id=data.recipe_id, servings=data.servings, day=data.day)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_plan(db: Session) -> List[dict]:
    entries = (
        db.query(models.PlanEntry)
        .join(models.Recipe)
        .order_by(models.PlanEntry.created_at)
        .all()
    )
    return [
        {
            "id": e.id,
            "recipe_id": e.recipe_id,
            "recipe_name": e.recipe.name,
            "base_servings": e.recipe.servings,
            "servings": e.servings,
            "day": e.day,
        }
        for e in entries
    ]


def update_plan_entry(db: Session, entry: models.PlanEntry, data: schemas.PlanEntryUpdate) -> models.PlanEntry:
    if data.servings is not None:
        entry.servings = data.servings
    if data.day is not None:
        entry.day = data.day or None
    db.commit()
    db.refresh(entry)
    return entry


def get_plan_entry(db: Session, entry_id: int) -> Optional[models.PlanEntry]:
    return db.query(models.PlanEntry).filter(models.PlanEntry.id == entry_id).first()


def delete_plan_entry(db: Session, entry: models.PlanEntry) -> None:
    db.delete(entry)
    db.commit()


def clear_plan(db: Session) -> None:
    db.query(models.PlanEntry).delete()
    db.commit()
