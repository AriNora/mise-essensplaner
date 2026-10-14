"""Tests fuer Einkaufsliste (build_shopping_list), Einheiten und Vorbereitungsplan.

Aufruf aus dem Ordner backend/:   python -m pytest
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, schemas
from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")  # frische In-Memory-DB je Test
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def plan(db, ingredients, base=2, portions=2, name="Testgericht"):
    """Legt ein Rezept (Basis-Portionen `base`) an und plant es mit `portions` ein.

    ingredients: Liste aus (name, menge, einheit) oder (name, menge, einheit, kategorie).
    """
    items = []
    for t in ingredients:
        n, a, u = t[:3]
        items.append(schemas.RecipeIngredientBase(
            name=n, amount=a, unit=u, category=t[3] if len(t) > 3 else None))
    recipe = crud.create_recipe(db, schemas.RecipeCreate(name=name, servings=base, ingredients=items))
    crud.add_plan_entry(db, schemas.PlanEntryCreate(recipe_id=recipe.id, servings=portions))


def liste(db):
    """Einkaufsliste als flaches Dict {(name, einheit): menge}."""
    result = crud.build_shopping_list(db)
    return {(i["name"], i["unit"]): i["amount"] for g in result["groups"] for i in g["items"]}


# --------------------------------------------------------------------------- #
#  Einheiten
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("roh, erwartet", [
    ("g", "g"), ("Gramm", "g"), (" GR ", "g"),
    ("el", "EL"), ("Esslöffel", "EL"), ("EL", "EL"),
    ("Teelöffel", "TL"),
    ("Stueck", "Stück"), ("Stk.", "Stück"), ("stück", "Stück"),
    ("Zehen", "Zehe"), ("Liter", "l"), ("Dosen", "Dose"),
    (None, ""), ("", ""),
    ("Fantasieeinheit", "fantasieeinheit"),   # unbekannt: nur casefold, nichts geraten
])
def test_canon_unit(roh, erwartet):
    assert crud._canon_unit(roh) == erwartet


# --------------------------------------------------------------------------- #
#  Zusammenfassen und Skalieren
# --------------------------------------------------------------------------- #
def test_leerer_plan_gibt_leere_liste(db):
    assert crud.build_shopping_list(db) == {"groups": [], "in_pantry": []}


def test_gleiche_zutat_aus_zwei_rezepten_wird_summiert(db):
    plan(db, [("Mehl", 200, "g")], name="A")
    plan(db, [("Mehl", 300, "g")], name="B")
    assert liste(db) == {("Mehl", "g"): 500}


def test_portionen_werden_hochgerechnet(db):
    plan(db, [("Reis", 100, "g")], base=2, portions=6)   # Faktor 3
    assert liste(db) == {("Reis", "g"): 300}


def test_zutat_ohne_menge_kommt_nicht_auf_die_liste(db):
    plan(db, [("Muskat", None, None), ("Reis", 100, "g")])
    assert liste(db) == {("Reis", "g"): 100}


def test_nicht_umrechenbare_einheiten_bleiben_getrennt(db):
    plan(db, [("Tomaten", 2, "Stück"), ("Tomaten", 1, "Dose")])
    assert liste(db) == {("Tomaten", "Stück"): 2, ("Tomaten", "Dose"): 1}


def test_schreibvarianten_der_einheit_fallen_zusammen(db):
    plan(db, [("Zucchini", 1, "Stück")], name="A")
    plan(db, [("Zucchini", 2, "Stueck")], name="B")
    assert sum(liste(db).values()) == 3
    assert len(liste(db)) == 1


# --------------------------------------------------------------------------- #
#  Umrechnung g / ml / EL / TL / l
# --------------------------------------------------------------------------- #
def test_eine_einheit_bleibt_erhalten(db):
    plan(db, [("Olivenöl", 1, "EL")], name="A")
    plan(db, [("Olivenöl", 2, "EL")], name="B")
    assert liste(db) == {("Olivenöl", "EL"): 3}


def test_kleine_mischmengen_werden_in_loeffeln_angezeigt(db):
    plan(db, [("Sojasauce", 1, "EL"), ("Sojasauce", 1, "TL")])   # 20 ml -> 4 TL
    assert liste(db) == {("Sojasauce", "TL"): 4}


def test_grosse_mischmengen_in_gramm(db):
    plan(db, [("Mehl", 100, "g"), ("Mehl", 1, "EL")])             # 115 g
    assert liste(db) == {("Mehl", "g"): 115}


def test_liter_bleiben_liter(db):
    plan(db, [("Gemüsebrühe", 1, "l"), ("Gemüsebrühe", 0.5, "l")])
    assert liste(db) == {("Gemüsebrühe", "l"): 1.5}


def test_liter_und_ml_werden_zu_liter(db):
    plan(db, [("Wasserbasis", 1, "l"), ("Wasserbasis", 125, "ml")])
    assert liste(db) == {("Wasserbasis", "l"): 1.125}


def test_nur_ml_bleiben_ml(db):
    plan(db, [("Pflanzendrink", 200, "ml"), ("Pflanzendrink", 300, "ml")])
    assert liste(db) == {("Pflanzendrink", "ml"): 500}


# --------------------------------------------------------------------------- #
#  Sonderfaelle Knoblauch
# --------------------------------------------------------------------------- #
def test_knoblauch_wird_in_zehen_gefuehrt(db):
    plan(db, [("Knoblauch", 2, "Zehe"), ("Knoblauch", 1, "TL"), ("Knoblauch", 1, "EL")])
    assert liste(db) == {("Knoblauch", "Zehen"): 6}


def test_knoblauch_einzahl_bei_einer_zehe(db):
    plan(db, [("Knoblauch", 1, "Zehe")])
    assert liste(db) == {("Knoblauch", "Zehe"): 1}


def test_knoblauchpulver_wird_in_teeloeffeln_angezeigt(db):
    plan(db, [("Knoblauchpulver", 1, "TL"), ("Knoblauchpulver", 1, "EL")])
    assert liste(db) == {("Knoblauchpulver", "TL"): 4}


# --------------------------------------------------------------------------- #
#  Warengruppen
# --------------------------------------------------------------------------- #
def test_warengruppen_in_supermarkt_reihenfolge_und_sonstiges_am_ende(db):
    plan(db, [
        ("Zimt", 1, "TL", "Gewürze & Würze"),
        ("Mystery", 1, "Stück"),                    # ohne Kategorie
        ("Apfel", 1, "Stück", "Obst & Gemüse"),
    ])
    gruppen = [g["category"] for g in crud.build_shopping_list(db)["groups"]]
    assert gruppen == ["Obst & Gemüse", "Gewürze & Würze", "Sonstiges"]


def test_kategorie_wird_von_spaeterem_rezept_nachgetragen(db):
    plan(db, [("Linsen", 100, "g")], name="A")                      # ohne Kategorie
    plan(db, [("Linsen", 100, "g", "Hülsenfrüchte")], name="B")
    gruppen = crud.build_shopping_list(db)["groups"]
    assert [g["category"] for g in gruppen] == ["Hülsenfrüchte"]
    assert gruppen[0]["items"][0]["amount"] == 200


# --------------------------------------------------------------------------- #
#  Vorbereitungsarten und Vorbereitungsplan
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("roh, erwartet", [
    ("gehackt", "hacken"),
    ("Gewürfelt", "würfeln"),
    ("  fein   gehackt ", "fein hacken"),
    ("in Scheiben, optional", "in Scheiben schneiden, optional"),
    ("fein gehackt", "fein hacken"),       # fein bleibt getrennt von grob
    ("grob gehackt", "grob hacken"),
    ("entkernt, fein gehackt", "entkernt, fein gehackt"),     # Mehrschritt: unberührt
    ("Dose", "Dose"),                                          # unbekannt: unberührt
    ("gehackt, wenn gewünscht", "gehackt, wenn gewünscht"),
    ("unbekannt, optional", "unbekannt, optional"),
])
def test_canon_prep(roh, erwartet):
    assert crud._canon_prep(roh) == erwartet


def test_vorbereitungsplan_fasst_varianten_zusammen(db):
    recipe_a = crud.create_recipe(db, schemas.RecipeCreate(name="A", servings=2, ingredients=[
        schemas.RecipeIngredientBase(name="Zwiebel", amount=1, unit="Stück", preparation="gehackt")]))
    recipe_b = crud.create_recipe(db, schemas.RecipeCreate(name="B", servings=2, ingredients=[
        schemas.RecipeIngredientBase(name="Zwiebel", amount=2, unit="Stück", preparation="hacken")]))
    for r in (recipe_a, recipe_b):
        crud.add_plan_entry(db, schemas.PlanEntryCreate(recipe_id=r.id, servings=2))
    gruppen = crud.build_prep_plan(db)["groups"]
    assert len(gruppen) == 1
    assert gruppen[0]["preparation"] == "hacken"
    assert gruppen[0]["items"][0]["amount"] == 3
    assert gruppen[0]["items"][0]["recipe"] == "A, B"


def test_vorbereitungsplan_ignoriert_zutaten_ohne_vorbereitung(db):
    plan(db, [("Reis", 100, "g")])
    assert crud.build_prep_plan(db) == {"groups": []}
