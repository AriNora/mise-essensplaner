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
    Aufsummieren in der Einkaufsliste.

    Wichtig: SQLites eingebautes lower() kann nur ASCII, macht also aus 'Öl'
    KEIN 'öl'. Ein reiner `func.lower(...)`-Vergleich uebersieht daher bereits
    vorhandene Zutaten mit grossem Umlaut am Anfang (Öl, Äpfel, ...) und wuerde
    sie erneut anlegen -> UNIQUE-Fehler beim Import. Darum:
      1) exakter Namensabgleich (trifft den Normalfall beim Import zuverlaessig),
      2) Fallback: Unicode-korrekter, gross-/kleinschreibungsunabhaengiger
         Vergleich in Python (casefold) ueber die vorhandenen Zutaten.
    """
    name = name.strip()
    # 1) Exakter Treffer (schnell, dank UNIQUE-Index) - faengt auch Umlaut-Namen.
    ing = db.query(models.Ingredient).filter(models.Ingredient.name == name).first()
    # 2) Fallback: gross-/kleinschreibungsunabhaengig, aber Unicode-korrekt.
    if ing is None:
        folded = name.casefold()
        for cand in db.query(models.Ingredient).all():
            if cand.name.casefold() == folded:
                ing = cand
                break
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
    "Obst & Gemüse",
    "Hülsenfrüchte",
    "Getreide & Backwaren",
    "Pflanzendrinks & Tofu",
    "Nüsse & Samen",
    "Öle & Essige",
    "Gewürze & Würze",
    "Konserven & Vorrat",
    "Sonstiges",
]


# Zutaten, von denen wir annehmen, dass sie immer im Vorrat sind -> sie landen
# nie auf der Einkaufsliste. Hier ganz normal schreiben (Gross-/Kleinschreibung
# und ss/ß egal) – die Liste wird unten per casefold() vereinheitlicht. Exakte
# Namen -> kaufbares wie "Mineralwasser"/"Kokoswasser" bleibt unberuehrt.
_PANTRY_STAPLES_RAW = [
    "Wasser",
    "Nudelwasser",
    "heißes Wasser",
    "kaltes Wasser",
    "lauwarmes Wasser",
]
PANTRY_STAPLES = {s.casefold() for s in _PANTRY_STAPLES_RAW}


# --------------------------------------------------------------------------- #
#  Einheiten-Umrechnung fuer die Einkaufsliste (Schritt 3)
# --------------------------------------------------------------------------- #
# Schreibweisen -> kanonische Einheit (case-insensitiv, auch Vollwoerter).
_UNIT_CANON = {
    "g": "g", "gr": "g", "gramm": "g",
    "ml": "ml", "milliliter": "ml",
    "el": "EL", "essl": "EL", "essl.": "EL", "esslöffel": "EL", "essloeffel": "EL",
    "tl": "TL", "teel": "TL", "teel.": "TL", "teelöffel": "TL", "teeloeffel": "TL",
    "cm": "cm",
    "zehe": "Zehe", "zehen": "Zehe",
}
# Umrechenbare Einheiten -> Aequivalent in g/ml. Luigis Faktoren:
# 1 EL = 15 g/ml, 1 TL = 5 g/ml = 1 cm.
_CONVERTIBLE = {"g": 1.0, "ml": 1.0, "EL": 15.0, "TL": 5.0, "cm": 5.0}
# Unter dieser Schwelle (g/ml) lieber in Loeffeln anzeigen, sonst in g/ml.
_SPOON_THRESHOLD = 40.0
# Zutaten-Profil Knoblauch: gefuehrt in Zehen. 1 TL gehackter Knoblauch = 1 Zehe,
# 1 EL = 3 Zehen (aus 1 EL = 3 TL). Greift nur beim exakten Namen "Knoblauch".
_GARLIC_TO_ZEHE = {"Zehe": 1.0, "TL": 1.0, "EL": 3.0}


def _canon_unit(unit: Optional[str]) -> str:
    """Einheit normalisieren: trimmen, casefold, bekannte Schreibweisen vereinheitlichen."""
    s = " ".join((unit or "").split()).casefold()
    return _UNIT_CANON.get(s, s)


def _plural_zehe(amount: Optional[float]) -> str:
    return "Zehe" if amount == 1 else "Zehen"


def _spoon_display(total_gml: float) -> Tuple[float, str]:
    """Kleine Mengen als Loeffel: EL wenn glatt durch 15 teilbar, sonst TL."""
    el = total_gml / _CONVERTIBLE["EL"]
    if el >= 1 and abs(el - round(el)) < 1e-9:
        return el, "EL"
    return total_gml / _CONVERTIBLE["TL"], "TL"


def build_shopping_list(db: Session) -> dict:
    """Aggregiert alle Zutaten der geplanten Rezepte.

    Vorgehen:
      1. Pro Plan-Eintrag den Skalierungsfaktor bestimmen (gewuenscht / Basis).
      2. Jede Zutat mit dem Faktor hochrechnen.
      3. Nach (Zutatenname, Einheit) zusammenfassen und Mengen summieren.
      4. Nach Warengruppe gruppieren.

    Zutaten ohne Menge (z.B. "Salz, nach Geschmack") werden gelistet, aber nicht
    numerisch summiert. Vorrats-Selbstverstaendlichkeiten (siehe PANTRY_STAPLES,
    z.B. Wasser) werden komplett ausgelassen.
    """
    entries = db.query(models.PlanEntry).join(models.Recipe).all()

    # ------------------------------------------------------------------ #
    # 1) Beitraege pro Zutat sammeln. Pro Name trennen wir:
    #    - umrechenbarer Teil (g/ml/EL/TL/cm) -> in g/ml-Aequivalent summiert
    #    - Knoblauch -> in Zehen (eigene Faktoren); Knoblauchpulver -> Anzeige in TL
    #    - alles andere (Stueck/Prise/... oder ohne Menge) -> eigene Zeile je Einheit
    # ------------------------------------------------------------------ #
    names: "OrderedDict[str, dict]" = OrderedDict()
    for entry in entries:
        recipe = entry.recipe
        factor = entry.servings / recipe.servings if recipe.servings else 1.0
        for ri in recipe.ingredients:
            name = ri.ingredient.name
            nkey = " ".join(name.split()).casefold()
            if nkey in PANTRY_STAPLES:
                continue  # immer im Vorrat -> nicht einkaufen
            acc = names.setdefault(nkey, {
                "name": name,
                "category": ri.ingredient.category,
                "conv": 0.0, "conv_units": set(), "conv_has": False,  # umrechenbarer Teil
                "zehe": 0.0, "zehe_has": False,                        # Knoblauch-Profil
                "plain": OrderedDict(),                                # cu -> {amount, unit}
            })
            if acc["category"] is None and ri.ingredient.category:
                acc["category"] = ri.ingredient.category

            cu = _canon_unit(ri.unit)
            amount = ri.amount * factor if ri.amount is not None else None

            if nkey == "knoblauch" and cu in _GARLIC_TO_ZEHE and amount is not None:
                acc["zehe"] += amount * _GARLIC_TO_ZEHE[cu]
                acc["zehe_has"] = True
            elif nkey != "knoblauch" and cu in _CONVERTIBLE and amount is not None:
                acc["conv"] += amount * _CONVERTIBLE[cu]
                acc["conv_units"].add(cu)
                acc["conv_has"] = True
            else:
                # nicht umrechenbar (Stueck, Prise, ...) oder ohne Menge -> eigene Zeile
                pb = acc["plain"].setdefault(cu, {"amount": None, "unit": ri.unit})
                if amount is not None:
                    pb["amount"] = (pb["amount"] or 0) + amount
                if not pb["unit"] and ri.unit:
                    pb["unit"] = ri.unit

    # ------------------------------------------------------------------ #
    # 2) Aus den Beitraegen je Zutat 1..n Anzeigezeilen bauen.
    #    Anzeige-Einheit: Knoblauch -> Zehen; Knoblauchpulver -> TL; sonst bei
    #    nur EINER umrechenbaren Einheit diese behalten, bei mehreren < 40 g/ml
    #    in Loeffeln, ab 40 in g (falls vorhanden) bzw. ml.
    # ------------------------------------------------------------------ #
    groups: "OrderedDict[str, list]" = OrderedDict()
    for nkey, acc in names.items():
        cat = acc["category"] or "Sonstiges"
        out = groups.setdefault(cat, [])
        name = acc["name"]

        if nkey == "knoblauch" and acc["zehe_has"]:
            amount = _round(acc["zehe"])
            out.append({"name": name, "amount": amount, "unit": _plural_zehe(amount), "category": cat})
        elif nkey != "knoblauch" and acc["conv_has"]:
            total = acc["conv"]
            units = acc["conv_units"]
            if nkey == "knoblauchpulver":
                amount, unit = _round(total / _CONVERTIBLE["TL"]), "TL"
            elif len(units) == 1:
                u = next(iter(units))
                amount, unit = _round(total / _CONVERTIBLE[u]), u
            elif total < _SPOON_THRESHOLD:
                a, unit = _spoon_display(total)
                amount = _round(a)
            else:
                unit = "g" if "g" in units else "ml"
                amount = _round(total)  # g/ml haben Faktor 1 -> total ist die Menge
            out.append({"name": name, "amount": amount, "unit": unit, "category": cat})

        for pb in acc["plain"].values():
            out.append({"name": name, "amount": _round(pb["amount"]), "unit": pb["unit"], "category": cat})

    # Kategorien in sinnvolle Reihenfolge bringen (Supermarkt-Logik), Rest hinten.
    def cat_sort_key(c: str) -> int:
        return CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else len(CATEGORY_ORDER)

    ordered = []
    for cat in sorted(groups.keys(), key=cat_sort_key):
        items = sorted(groups[cat], key=lambda x: (x["name"].lower(), (x["unit"] or "")))
        ordered.append({"category": cat, "items": items})
    return {"groups": ordered}


# --------------------------------------------------------------------------- #
#  Vorbereitungsarten zusammenfassen (kuratierte Synonym-Tabelle)
# --------------------------------------------------------------------------- #
# Ziel: Schreibvarianten DERSELBEN Handbewegung landen im Vorbereitungsplan in
# einer Gruppe (Kanon-Form = Infinitiv, liest sich wie eine To-do-Liste).
# Bewusste Grenzen (mit Luigi abgestimmt):
#   - grob/fein bleiben GETRENNT (eigene Gruppen)
#   - Mengen/Verpackung (z.B. "Dose", "ca. 60 g"), Verwendung ("für den Salat")
#     und Alternativen ("oder Mie-Nudeln") werden NICHT angefasst -> eigene Gruppe
#   - Mehrschritt-Angaben ("entkernt, fein gehackt") bleiben unberührt
#   - ein angehängtes ", optional" reitet mit: "in Scheiben, optional"
#                                              -> "in Scheiben schneiden, optional"
# Prinzip wie beim Umlaut-Wörterbuch: KURATIERT, nicht geraten. Eine unbekannte
# Schreibweise bleibt einfach als eigene Gruppe stehen (es geht nie etwas kaputt);
# neue Varianten ergänzt man hier mit einer Zeile.
# Wichtig: Der Originaltext an der Zutat wird NICHT verändert - nur die
# Gruppierung/Anzeige im Plan nutzt die Kanon-Form.

# Kanon-Form -> Liste der Schreibvarianten (alles klein geschrieben zum Abgleich).
_PREP_CANON_GROUPS = {
    "hacken":                     ["gehackt", "hacken"],
    "fein hacken":                ["fein gehackt", "fein hacken"],
    "grob hacken":                ["grob gehackt", "grob hacken"],
    "würfeln":                    ["gewürfelt", "würfeln"],
    "fein würfeln":               ["fein gewürfelt", "fein würfeln"],
    "in Scheiben schneiden":      ["in scheiben", "in scheiben schneiden"],
    "in dünne Scheiben schneiden":["in dünnen scheiben", "in dünne scheiben schneiden"],
    "in Ringe schneiden":         ["in ringen", "in ringe schneiden"],
    "in Streifen schneiden":      ["in streifen", "in streifen schneiden"],
    "in Stücke schneiden":        ["in stücke", "in stücke schneiden"],
    "in Halbmonde schneiden":     ["in halbmonden", "in halbmonde schneiden"],
    "reiben":                     ["gerieben", "reiben"],
    "auspressen":                 ["ausgepresst", "auspressen"],
    "zerdrücken":                 ["zerdrückt", "zerdrücken"],
    "zerbröseln":                 ["zerbröselt", "zerbröseln"],
    "abspülen":                   ["abgespült", "abspülen"],
    "kochen":                     ["gekocht", "kochen"],
    "mahlen":                     ["gemahlen", "mahlen"],
    "rösten":                     ["geröstet", "rösten"],
    "vierteln":                   ["geviertelt", "vierteln"],
    "längs schneiden":            ["längs geschnitten", "längs schneiden"],
    "schräg schneiden":           ["schräg geschnitten", "schräg schneiden"],
}

# Nachschlage-Tabelle: variante(klein) -> Kanon-Form. Einmal aus den Gruppen
# aufgebaut, damit oben gepflegt und unten schnell nachgeschlagen werden kann.
_PREP_LOOKUP = {
    variant: canon
    for canon, variants in _PREP_CANON_GROUPS.items()
    for variant in variants
}

# Zusätze, die hinter einer bekannten Aktion stehen dürfen und erhalten bleiben.
_PREP_KEEP_SUFFIXES = (", optional",)


def _canon_prep(text: str) -> str:
    """Bringt eine Verarbeitungsangabe auf die Kanon-Form, wenn sie bekannt ist.

    Bekannt    -> Infinitiv-Form (z.B. "gewürfelt" -> "würfeln").
    Mit Zusatz -> Aktion vereinheitlicht, Zusatz bleibt
                  (z.B. "in Scheiben, optional" -> "in Scheiben schneiden, optional").
    Unbekannt  -> unverändert zurück (eigene Gruppe; Mengen/Verwendung/Alternativen
                  und Mehrschritt-Angaben bleiben so erhalten).
    """
    raw = " ".join(text.split())          # Mehrfach-Leerzeichen glätten
    low = raw.lower()

    # 1) Erhaltenswerter Zusatz wie ", optional" abtrennen, Aktion davor prüfen.
    for suffix in _PREP_KEEP_SUFFIXES:
        if low.endswith(suffix):
            base = low[: -len(suffix)].strip()
            canon = _PREP_LOOKUP.get(base)
            if canon is not None:
                return canon + suffix
            return raw                    # Aktion unbekannt -> nichts anfassen

    # 2) Ganze Angabe als bekannte Variante?
    canon = _PREP_LOOKUP.get(low)
    if canon is not None:
        return canon

    # 3) Unbekannt -> Originaltext unverändert (eigene Gruppe).
    return raw


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
            # Schreibvarianten derselben Aktion zusammenfassen (Original bleibt
            # an der Zutat unberuehrt - nur Gruppierung/Anzeige nutzt die Kanon-Form).
            canon_disp = _canon_prep(ri.preparation)
            prep_key = canon_disp.lower()
            prep_display.setdefault(prep_key, canon_disp)
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