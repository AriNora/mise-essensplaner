"""Tests fuer den Vorrat (Abgleich, Verwaltung, Einkaufsliste).

Aufruf aus dem Ordner backend/:   python -m pytest
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, pantry, schemas
from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")  # frische In-Memory-DB je Test
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def items(*names):
    return [SimpleNamespace(name=n, key=pantry.pantry_key(n)) for n in names]


@pytest.mark.parametrize("name", [
    "Wasser", "kochendes Wasser", "kaltes Wasser", "Wasser, lauwarm", "heißes Wasser",
])
def test_wasser_deckt_alle_formen(name):
    assert pantry.find_pantry_match(name, items("Wasser")) == "Wasser"


@pytest.mark.parametrize("name", [
    "Cayennepfeffer", "Sprudelwasser", "Meersalz", "Kokoswasser", "Pfefferminze", "Olivenöl",
])
def test_zusammengesetzte_woerter_werden_nicht_gedeckt(name):
    assert pantry.find_pantry_match(name, items("Wasser", "Salz", "Pfeffer")) is None


def test_zusaetze_in_klammern_und_nach_komma_werden_ignoriert():
    assert pantry.find_pantry_match("Tomaten (Dose)", items("Tomaten")) == "Tomaten"
    assert pantry.find_pantry_match("Salz, grob", items("Salz")) == "Salz"


def test_mehrwort_eintrag_muss_am_ende_stehen():
    vorrat = items("schwarzer Pfeffer")
    assert pantry.find_pantry_match("frisch gemahlener schwarzer Pfeffer", vorrat) == "schwarzer Pfeffer"
    assert pantry.find_pantry_match("Pfeffer", vorrat) is None


def test_und_verlangt_alle_teile():
    assert pantry.find_pantry_match("Salz und Pfeffer", items("Salz", "Pfeffer")) == "Salz + Pfeffer"
    assert pantry.find_pantry_match("Salz und Pfeffer", items("Salz")) is None


def test_plural_und_grossschreibung_egal():
    assert pantry.find_pantry_match("Zwiebeln", items("zwiebel")) == "zwiebel"


def test_leerer_vorrat_deckt_nichts():
    assert pantry.find_pantry_match("Wasser", []) is None


def test_add_item_doppelt_und_leer(db):
    assert pantry.add_item(db, "Salz").name == "Salz"
    assert pantry.add_item(db, "  salz ") is None           # schon vorhanden
    with pytest.raises(ValueError):
        pantry.add_item(db, "(nur Klammer)")


def test_seed_defaults_und_loeschen(db):
    pantry.seed_defaults(db)
    names = [i.name for i in pantry.list_items(db)]
    assert names == sorted(pantry.DEFAULT_PANTRY, key=str.casefold)
    assert pantry.delete_item(db, pantry.list_items(db)[0].id) is True
    assert pantry.delete_item(db, 9999) is False


def _plan_with(db, ingredients):
    recipe = crud.create_recipe(db, schemas.RecipeCreate(
        name="Testgericht", servings=2,
        ingredients=[schemas.RecipeIngredientBase(name=n, amount=a, unit=u) for n, a, u in ingredients],
    ))
    crud.add_plan_entry(db, schemas.PlanEntryCreate(recipe_id=recipe.id, servings=2))


ZUTATEN = [
    ("Zwiebel", 1, "Stück"), ("kochendes Wasser", 180, "ml"), ("Salz", 1, "Prise"),
    ("schwarzer Pfeffer", 1, "TL"), ("Cayennepfeffer", 1, "TL"), ("Salz und Pfeffer", None, None),
]


def test_einkaufsliste_laesst_vorrat_aus_und_meldet_ihn(db):
    pantry.add_item(db, "Wasser"); pantry.add_item(db, "Salz"); pantry.add_item(db, "Pfeffer")
    _plan_with(db, ZUTATEN)
    result = crud.build_shopping_list(db)
    gekauft = {i["name"] for g in result["groups"] for i in g["items"]}
    assert gekauft == {"Zwiebel", "Cayennepfeffer"}
    assert {s["name"]: s["pantry"] for s in result["in_pantry"]} == {
        "kochendes Wasser": "Wasser", "Salz": "Salz",
        "schwarzer Pfeffer": "Pfeffer", "Salz und Pfeffer": "Salz + Pfeffer",
    }


def test_einkaufsliste_ohne_vorrat_zeigt_wasser(db):
    _plan_with(db, ZUTATEN)
    result = crud.build_shopping_list(db)
    gekauft = {i["name"] for g in result["groups"] for i in g["items"]}
    assert {"kochendes Wasser", "Salz", "schwarzer Pfeffer"} <= gekauft
    assert result["in_pantry"] == []
