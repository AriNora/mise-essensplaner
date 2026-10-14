"""Datenmodell.

Drei zentrale Tabellen + eine Plan-Tabelle:

  Ingredient          - kanonische Zutat (Name eindeutig), mit Kategorie fuer die
                        nach Warengruppen gruppierte Einkaufsliste.
  Recipe              - Rezept mit Basis-Portionszahl (servings).
  RecipeIngredient    - Verbindungstabelle: welche Zutat steckt in welchem Rezept,
                        mit Menge, Einheit und Vorbereitung ("würfeln", "schälen").
  PlanEntry           - ein eingeplantes Rezept fuer die Woche, mit gewuenschter
                        Portionszahl (kann von der Basis abweichen -> Skalierung).

Diese Normalisierung (eigene Ingredient-Tabelle statt Freitext am Rezept) ist die
Grundlage dafuer, dass die Einkaufsliste Zutaten ueber Rezepte hinweg sauber
zusammenfassen kann (2 Zwiebeln + 3 Zwiebeln = 5 Zwiebeln).
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    # Warengruppe, z.B. "Gemuese", "Huelsenfruechte". Nullable, weil nicht jede
    # Zutat sofort einsortiert werden muss.
    category = Column(String, nullable=True, index=True)

    recipe_links = relationship("RecipeIngredient", back_populates="ingredient")


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)
    servings = Column(Integer, nullable=False, default=2)  # Basis-Portionen
    instructions = Column(Text, nullable=True)             # Zubereitungstext (optional)
    source = Column(String, nullable=True)                 # Quelle/Notiz (optional)
    image = Column(String, nullable=True)                  # Dateiname des Rezeptbilds (optional)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # cascade: loescht man ein Rezept, verschwinden seine Zutaten-Zeilen mit.
    ingredients = relationship(
        "RecipeIngredient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.position",
    )

    # Schlagworte (n:m). Ein Rezept kann mehrere Tags haben, ein Tag mehrere
    # Rezepte. Die Verknuepfung laeuft ueber die Tabelle recipe_tags (unten).
    # secondary als String -> Reihenfolge der Definitionen im Modul egal.
    tags = relationship(
        "Tag",
        secondary="recipe_tags",
        back_populates="recipes",
        order_by="Tag.name",
    )

    # Eingeplante Eintraege verschwinden mit dem Rezept (sonst bleiben Waisen
    # zurueck, die spaeter an einer wiederverwendeten ID haengen koennten).
    plan_entries = relationship(
        "PlanEntry",
        back_populates="recipe",
        cascade="all, delete-orphan",
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False, index=True)

    amount = Column(Float, nullable=True)        # z.B. 2  (nullable: "nach Geschmack")
    unit = Column(String, nullable=True)         # z.B. "g", "Stueck", "EL"
    preparation = Column(String, nullable=True)  # z.B. "würfeln"
    position = Column(Integer, nullable=False, default=0)  # Reihenfolge im Rezept

    recipe = relationship("Recipe", back_populates="ingredients")
    ingredient = relationship("Ingredient", back_populates="recipe_links")


class PlanEntry(Base):
    """Ein Eintrag im aktuellen Wochenplan (ein eingeplantes Rezept)."""
    __tablename__ = "plan_entries"

    id = Column(Integer, primary_key=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    servings = Column(Integer, nullable=False)   # gewuenschte Portionen fuer DIESEN Slot
    day = Column(String, nullable=True)           # optional: "Mo".."So" fuer Wocheneinteilung
    created_at = Column(DateTime, default=datetime.utcnow)

    recipe = relationship("Recipe", back_populates="plan_entries")


class Tag(Base):
    """Ein Schlagwort fuer Rezepte, z.B. ('typ','Suppe') oder ('kueche','Indisch').

    `kind` ordnet das Tag einer Facette zu (Gericht-Typ / Kueche / Eigenschaft),
    sodass das Frontend die Filter gruppiert anzeigen kann. (kind, name) ist
    eindeutig: 'Suppe' als Typ und 'Suppe' als Kueche waeren zwar zwei Eintraege,
    aber innerhalb einer Facette gibt es jeden Namen nur einmal -> saubere
    Normalisierung, genau wie bei den Zutaten.
    """
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False, index=True)   # "typ" | "kueche" | "eigenschaft"
    name = Column(String, nullable=False, index=True)

    __table_args__ = (UniqueConstraint("kind", "name", name="uq_tag_kind_name"),)

    recipes = relationship("Recipe", secondary="recipe_tags", back_populates="tags")


# Reine Verknuepfungstabelle (kein eigenes Modell noetig): welches Rezept traegt
# welches Tag. Loescht man ein Rezept oder Tag, fallen die Verknuepfungen weg.
recipe_tags = Table(
    "recipe_tags",
    Base.metadata,
    Column("recipe_id", Integer, ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class PantryItem(Base):
    """Eine Zutat, die immer im Vorrat ist (ohne Menge) und nie auf die Einkaufsliste kommt.

    `key` ist der Vergleichsschluessel (siehe pantry.pantry_key); er haengt nicht
    an der Tabelle `ingredients`. So kann man auch Zutaten eintragen, die noch in
    keinem Rezept vorkommen, und das Zusammenfuehren von Zutaten laesst den Vorrat
    unberuehrt.
    """
    __tablename__ = "pantry_items"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)                          # Anzeigename
    key = Column(String, nullable=False, unique=True, index=True)  # Vergleichsschluessel
    created_at = Column(DateTime, default=datetime.utcnow)
