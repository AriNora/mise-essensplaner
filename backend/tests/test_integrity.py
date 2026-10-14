"""Tests fuer Datenintegritaet: Fremdschluessel, Kaskaden, Indizes, Eingabepruefung.

Aufruf aus dem Ordner backend/:   python -m pytest
"""
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import crud, models, schemas
from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_planned_recipe(db, name):
    recipe = crud.create_recipe(db, schemas.RecipeCreate(
        name=name, servings=2,
        ingredients=[schemas.RecipeIngredientBase(name="Reis", amount=100, unit="g")],
        tags=[schemas.TagIn(kind="typ", name="Hauptgericht")],
    ))
    crud.add_plan_entry(db, schemas.PlanEntryCreate(recipe_id=recipe.id, servings=2))
    return recipe


# --------------------------------------------------------------------------- #
#  Fremdschluessel und Kaskaden
# --------------------------------------------------------------------------- #
def test_fremdschluessel_sind_aktiv(db):
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_loeschen_eines_rezepts_entfernt_plan_zutaten_und_tag_links(db):
    a = make_planned_recipe(db, "A")
    b = make_planned_recipe(db, "B")
    crud.delete_recipe(db, db.get(models.Recipe, b.id))
    assert [e["recipe_name"] for e in crud.list_plan(db)] == ["A"]
    assert db.query(models.PlanEntry).count() == 1            # keine Waise
    assert db.query(models.RecipeIngredient).count() == 1
    assert db.execute(text("select count(*) from recipe_tags")).scalar() == 1
    assert a.id != b.id


def test_wiederverwendete_id_zeigt_keinen_alten_plan_eintrag(db):
    make_planned_recipe(db, "A")
    b = make_planned_recipe(db, "B")
    crud.delete_recipe(db, db.get(models.Recipe, b.id))
    make_planned_recipe(db, "C")      # bekommt ggf. die ID von B
    assert sorted(e["recipe_name"] for e in crud.list_plan(db)) == ["A", "C"]


def test_plan_eintrag_mit_unbekanntem_rezept_wird_von_der_db_abgelehnt(db):
    db.add(models.PlanEntry(recipe_id=9999, servings=2))
    with pytest.raises(IntegrityError):
        db.commit()


def test_zutat_mit_verwendung_kann_nicht_direkt_geloescht_werden(db):
    make_planned_recipe(db, "A")
    ingredient = db.query(models.Ingredient).first()
    db.delete(ingredient)
    with pytest.raises(IntegrityError):
        db.commit()


# --------------------------------------------------------------------------- #
#  Indizes
# --------------------------------------------------------------------------- #
def test_wichtige_fremdschluessel_spalten_haben_indizes(db):
    insp = inspect(db.get_bind())
    def indiziert(table):
        return {c for ix in insp.get_indexes(table) for c in ix["column_names"]}
    assert "recipe_id" in indiziert("recipe_ingredients")
    assert "ingredient_id" in indiziert("recipe_ingredients")
    assert "recipe_id" in indiziert("plan_entries")


# --------------------------------------------------------------------------- #
#  Eingabepruefung
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["typ", "kueche", "eigenschaft", " Typ ", "KUECHE"])
def test_tag_art_gueltig_und_normalisiert(kind):
    assert schemas.TagIn(kind=kind, name="X").kind in schemas.TAG_KINDS


@pytest.mark.parametrize("kind", ["kueche2", "diaet", "Küche"])
def test_tag_art_ungueltig_wird_abgelehnt(kind):
    with pytest.raises(ValidationError):
        schemas.TagIn(kind=kind, name="X")


@pytest.mark.parametrize("day, erwartet", [
    (None, None), ("", ""), ("Mo", "Mo"), (" so ", "So"), ("DI", "Di"),
])
def test_wochentag_gueltig(day, erwartet):
    assert schemas.PlanEntryCreate(recipe_id=1, servings=2, day=day).day == erwartet
    assert schemas.PlanEntryUpdate(day=day).day == erwartet


@pytest.mark.parametrize("day", ["Montag", "Mon", "8", "Xx"])
def test_wochentag_ungueltig_wird_abgelehnt(day):
    with pytest.raises(ValidationError):
        schemas.PlanEntryCreate(recipe_id=1, servings=2, day=day)
    with pytest.raises(ValidationError):
        schemas.PlanEntryUpdate(day=day)
