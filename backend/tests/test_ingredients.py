"""Tests fuer die Zutaten-Normalisierung.

Aufruf aus dem Ordner backend/:   python -m pytest
(pytest ist nicht in requirements.txt: pip install pytest)
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, models
from app.database import Base
from app.normalize import ingredient_key


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")  # frische In-Memory-DB je Test
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.mark.parametrize("a, b", [
    ("Zwiebel", "Zwiebeln"),
    ("Tomate", "Tomaten"),
    ("Rote Zwiebel", "rote Zwiebeln"),
    ("Cayenne Pfeffer", "Cayennepfeffer"),
    ("Süßkartoffel", "Süßkartoffeln"),
    ("Knoblauchzehe", "Knoblauchzehen"),
    ("Öl", "öl"),
])
def test_same_ingredient_same_key(a, b):
    assert ingredient_key(a) == ingredient_key(b)


@pytest.mark.parametrize("a, b", [
    ("Knoblauch", "Knoblauchzehe"),      # andere Wortform, eigene Logik in der Einkaufsliste
    ("Tomaten", "Dosentomaten"),         # frisch vs. Konserve bewusst getrennt
    ("Zwiebel", "Rote Zwiebel"),
    ("Reis", "Reisnudeln"),
])
def test_different_ingredient_different_key(a, b):
    assert ingredient_key(a) != ingredient_key(b)


def test_get_or_create_reuses_existing_variant(db):
    first = crud.get_or_create_ingredient(db, "Zwiebel", "Obst & Gemüse")
    second = crud.get_or_create_ingredient(db, "Zwiebeln", "Obst & Gemüse")
    assert second.id == first.id
    assert db.query(models.Ingredient).count() == 1


def test_get_or_create_keeps_distinct_ingredients(db):
    crud.get_or_create_ingredient(db, "Zwiebel", None)
    crud.get_or_create_ingredient(db, "Rote Zwiebeln", None)
    assert db.query(models.Ingredient).count() == 2
