"""CRUD-Operationen und die fachliche Kernlogik.

Hier stecken die drei "interessanten" Funktionen, die das Projekt ausmachen und
die du im Kolloquium erklaeren kannst:

  - Portions-Skalierung:   Faktor = gewuenschte / Basis-Portionen
  - Einkaufsliste:         Zutaten aller geplanten Rezepte aggregieren (summieren)
  - Vorbereitungsplan:     Zutaten nach Verarbeitungsart gruppieren (Mise en place)
"""
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, schemas
from .database import UPLOAD_DIR


def _round(value: Optional[float]) -> Optional[float]:
    """Auf 2 Nachkommastellen runden; ganze Zahlen bleiben ganz (5.0 -> 5)."""
    if value is None:
        return None
    r = round(value, 2)
    return int(r) if r == int(r) else r


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
    Aufsummieren in der Einkaufsliste."""
    name = name.strip()
    ing = db.query(models.Ingredient).filter(func.lower(models.Ingredient.name) == name.lower()).first()
    if ing is None:
        ing = models.Ingredient(name=name, category=category)
        db.add(ing)
        db.flush()  # vergibt ID, ohne Transaktion abzuschliessen
    elif category and not ing.category:
        ing.category = category  # Kategorie nachtragen, falls vorher leer
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
KIND_ORDER = ["typ", "kueche", "eigenschaft"]


def get_or_create_tag(db: Session, kind: str, name: str) -> Optional[models.Tag]:
    """Findet ein Tag per (kind, name) oder legt es an. Gleiche Idee wie bei den
    Zutaten: jedes Schlagwort existiert genau einmal, Rezepte verweisen darauf."""
    kind = (kind or "").strip().lower()
    name = (name or "").strip()
    if kind not in KIND_ORDER or not name:
        return None
    tag = (
        db.query(models.Tag)
        .filter(models.Tag.kind == kind, func.lower(models.Tag.name) == name.lower())
        .first()
    )
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


# --------------------------------------------------------------------------- #
#  KERNLOGIK 1: Einkaufsliste
# --------------------------------------------------------------------------- #
CATEGORY_ORDER = [
    "Obst & Gemuese",
    "Huelsenfruechte",
    "Getreide & Backwaren",
    "Pflanzendrinks & Tofu",
    "Nuesse & Samen",
    "Oele & Essige",
    "Gewuerze & Wuerze",
    "Konserven & Vorrat",
    "Sonstiges",
]


def build_shopping_list(db: Session) -> dict:
    """Aggregiert alle Zutaten der geplanten Rezepte.

    Vorgehen:
      1. Pro Plan-Eintrag den Skalierungsfaktor bestimmen (gewuenscht / Basis).
      2. Jede Zutat mit dem Faktor hochrechnen.
      3. Nach (Zutatenname, Einheit) zusammenfassen und Mengen summieren.
      4. Nach Warengruppe gruppieren.

    Zutaten ohne Menge (z.B. "Salz, nach Geschmack") werden gelistet, aber nicht
    numerisch summiert.
    """
    entries = db.query(models.PlanEntry).join(models.Recipe).all()

    # key = (name_lower, unit_lower) -> aggregierter Eintrag
    agg: Dict[tuple, dict] = {}
    for entry in entries:
        recipe = entry.recipe
        factor = entry.servings / recipe.servings if recipe.servings else 1.0
        for ri in recipe.ingredients:
            name = ri.ingredient.name
            unit = ri.unit
            key = (name.lower(), (unit or "").lower())
            bucket = agg.setdefault(
                key,
                {"name": name, "unit": unit, "category": ri.ingredient.category, "amount": None},
            )
            if ri.amount is not None:
                scaled = ri.amount * factor
                bucket["amount"] = (bucket["amount"] or 0) + scaled
            if bucket["category"] is None and ri.ingredient.category:
                bucket["category"] = ri.ingredient.category

    # Nach Kategorie gruppieren
    groups: "OrderedDict[str, list]" = OrderedDict()
    for item in agg.values():
        cat = item["category"] or "Sonstiges"
        groups.setdefault(cat, []).append(
            {"name": item["name"], "amount": _round(item["amount"]), "unit": item["unit"], "category": cat}
        )

    # Kategorien in sinnvolle Reihenfolge bringen (Supermarkt-Logik), Rest hinten.
    def cat_sort_key(c: str) -> int:
        return CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else len(CATEGORY_ORDER)

    ordered = []
    for cat in sorted(groups.keys(), key=cat_sort_key):
        items = sorted(groups[cat], key=lambda x: x["name"].lower())
        ordered.append({"category": cat, "items": items})
    return {"groups": ordered}


# --------------------------------------------------------------------------- #
#  KERNLOGIK 2: Vorbereitungsplan (Mise en place)
# --------------------------------------------------------------------------- #
def build_prep_plan(db: Session) -> dict:
    """Gruppiert alle vorzubereitenden Zutaten nach Verarbeitungsart.

    Beispiel-Ergebnis:
      "wuerfeln":  5 Zwiebeln (aus Curry, Suppe), 1 Paprika (aus Curry)
      "schaelen":  4 Kartoffeln (aus Suppe)

    Gleiche Zutat + Einheit innerhalb einer Verarbeitungsart wird summiert, damit
    man z.B. alle Zwiebeln auf einmal wuerfeln kann.
    """
    entries = db.query(models.PlanEntry).join(models.Recipe).all()

    # prep_lower -> { (name_lower, unit_lower): {...} }
    groups: "OrderedDict[str, OrderedDict]" = OrderedDict()
    prep_display: Dict[str, str] = {}

    for entry in entries:
        recipe = entry.recipe
        factor = entry.servings / recipe.servings if recipe.servings else 1.0
        for ri in recipe.ingredients:
            if not ri.preparation:
                continue
            prep_key = ri.preparation.strip().lower()
            prep_display.setdefault(prep_key, ri.preparation.strip())
            bucket = groups.setdefault(prep_key, OrderedDict())

            name = ri.ingredient.name
            ikey = (name.lower(), (ri.unit or "").lower())
            item = bucket.setdefault(
                ikey,
                {"name": name, "amount": None, "unit": ri.unit, "recipes": set()},
            )
            if ri.amount is not None:
                item["amount"] = (item["amount"] or 0) + ri.amount * factor
            item["recipes"].add(recipe.name)

    result = []
    for prep_key, items in groups.items():
        out_items = []
        for it in items.values():
            out_items.append(
                {
                    "name": it["name"],
                    "amount": _round(it["amount"]),
                    "unit": it["unit"],
                    "recipe": ", ".join(sorted(it["recipes"])),
                }
            )
        out_items.sort(key=lambda x: x["name"].lower())
        result.append({"preparation": prep_display[prep_key], "items": out_items})

    result.sort(key=lambda g: g["preparation"].lower())
    return {"groups": result}
