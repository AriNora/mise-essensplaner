"""Pydantic-Schemas: definieren, wie Daten ueber die API rein- und rausgehen.

Trennung von DB-Modell (models.py) und API-Schema ist bewusst: die API-Form kann
sich unabhaengig vom Datenbankschema entwickeln, und wir validieren Eingaben,
bevor sie die Datenbank erreichen.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- Zutat im Rezept (Verbindungstabelle) ----------
class RecipeIngredientBase(BaseModel):
    name: str = Field(..., min_length=1)        # Zutatenname als Text (wird zu Ingredient)
    amount: Optional[float] = None
    unit: Optional[str] = None
    preparation: Optional[str] = None
    category: Optional[str] = None              # Warengruppe (optional gesetzt)


class RecipeIngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None
    preparation: Optional[str] = None
    category: Optional[str] = None
    position: int = 0


# ---------- Schlagworte (Tags) ----------
class TagIn(BaseModel):
    kind: str = Field(..., min_length=1)   # "typ" | "kueche" | "eigenschaft"
    name: str = Field(..., min_length=1)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kind: str
    name: str


class TagCount(BaseModel):
    """Ein Tag samt Anzahl Rezepte – fuer die Filterleiste (Chips mit Zahl)."""
    kind: str
    name: str
    count: int


class TagListResponse(BaseModel):
    tags: List[TagCount]


# ---------- Rezept ----------
class RecipeBase(BaseModel):
    name: str = Field(..., min_length=1)
    servings: int = Field(2, ge=1)
    instructions: Optional[str] = None
    source: Optional[str] = None


class RecipeCreate(RecipeBase):
    ingredients: List[RecipeIngredientBase] = []
    tags: List[TagIn] = []


class RecipeUpdate(RecipeBase):
    ingredients: List[RecipeIngredientBase] = []
    tags: List[TagIn] = []


class RecipeListItem(BaseModel):
    """Schlanke Form fuer die Listenansicht (ohne Zutaten, performant bei 1000 Rezepten)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    servings: int
    ingredient_count: int = 0
    image: Optional[str] = None


class RecipeOut(RecipeBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    image: Optional[str] = None
    ingredients: List[RecipeIngredientOut] = []
    tags: List[TagOut] = []


class RecipeListResponse(BaseModel):
    total: int
    items: List[RecipeListItem]


# ---------- Plan ----------
class PlanEntryCreate(BaseModel):
    recipe_id: int
    servings: int = Field(..., ge=1)
    day: Optional[str] = None


class PlanEntryUpdate(BaseModel):
    servings: Optional[int] = Field(None, ge=1)
    day: Optional[str] = None


class PlanEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recipe_id: int
    recipe_name: str
    base_servings: int
    servings: int
    day: Optional[str] = None


# ---------- Einkaufsliste ----------
class ShoppingItem(BaseModel):
    name: str
    amount: Optional[float] = None   # None = "nach Geschmack" o.ae. (nicht summierbar)
    unit: Optional[str] = None
    category: Optional[str] = None


class ShoppingGroup(BaseModel):
    category: str
    items: List[ShoppingItem]


class ShoppingListResponse(BaseModel):
    groups: List[ShoppingGroup]


# ---------- Vorbereitungsplan (Mise en place) ----------
class PrepItem(BaseModel):
    name: str
    amount: Optional[float] = None
    unit: Optional[str] = None
    recipe: str                       # aus welchem Rezept stammt die Zutat


class PrepGroup(BaseModel):
    preparation: str                  # z.B. "wuerfeln"
    items: List[PrepItem]


class PrepPlanResponse(BaseModel):
    groups: List[PrepGroup]
