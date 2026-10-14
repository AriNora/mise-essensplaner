"""Seed-Skript: befuellt die Datenbank mit Startdaten.

Aufruf (aus dem Ordner backend/):
    python -m app.seed              # legt die kuratierten Rezepte an
    python -m app.seed --reset      # DB vorher leeren, dann neu befuellen
    python -m app.seed --reset --bulk 1000   # zusaetzlich auf ~1000 Rezepte
                                             # auffuellen (fuer Performance-Test)

Hintergrund: 1000 Rezepte tippt niemand von Hand. Die kuratierten Rezepte unten
sind echte, vegane Gerichte (sofort nutzbar). Der --bulk-Schalter erzeugt aus
ihnen portionierte Varianten, um zu zeigen, dass Suche/Plan/Liste auch bei der
Zielgroesse von ~1000 Rezepten fluessig laufen.
"""
import argparse

from .database import Base, SessionLocal, engine
from . import crud, models, schemas

# --------------------------------------------------------------------------- #
#  Kuratierte vegane Rezepte
#  Zutat: (Name, Menge, Einheit, Vorbereitung, Kategorie)
# --------------------------------------------------------------------------- #
G = "Obst & Gemüse"
H = "Hülsenfrüchte"
GB = "Getreide & Backwaren"
PT = "Pflanzendrinks & Tofu"
NS = "Nüsse & Samen"
OE = "Öle & Essige"
GW = "Gewürze & Würze"
KV = "Konserven & Vorrat"

RECIPES = [
    {
        "name": "Linsen-Dal mit Spinat",
        "servings": 2,
        "instructions": "Zwiebel und Knoblauch anschwitzen, Gewürze kurz mitrösten, Linsen und Wasser zugeben und 20 Min köcheln. Spinat unterheben, mit Salz abschmecken.",
        "ingredients": [
            ("Rote Linsen", 200, "g", None, H),
            ("Zwiebel", 1, "Stueck", "wuerfeln", G),
            ("Knoblauchzehe", 2, "Stueck", "fein hacken", G),
            ("Blattspinat", 150, "g", "waschen", G),
            ("Kokosmilch", 200, "ml", None, KV),
            ("Currypulver", 1, "EL", None, GW),
            ("Ingwer", 2, "cm", "reiben", G),
            ("Salz", None, None, None, GW),
        ],
    },
    {
        "name": "Kichererbsen-Curry",
        "servings": 3,
        "instructions": "Zwiebeln glasig dünsten, Paprika zugeben, Tomaten und Kichererbsen einrühren, mit Gewürzen 15 Min schmoren.",
        "ingredients": [
            ("Kichererbsen", 1, "Dose", "abtropfen", H),
            ("Zwiebel", 2, "Stück", "würfeln", G),
            ("Paprika", 1, "Stück", "in Streifen schneiden", G),
            ("Gehackte Tomaten", 1, "Dose", None, KV),
            ("Kokosmilch", 200, "ml", None, KV),
            ("Knoblauchzehe", 2, "Stück", "fein hacken", G),
            ("Garam Masala", 1, "EL", None, GW),
            ("Olivenoel", 2, "EL", None, OE),
        ],
    },
    {
        "name": "Pasta Arrabbiata",
        "servings": 2,
        "instructions": "Knoblauch in Oel anbraten, Tomaten und Chili zugeben, 10 Min einkochen. Mit der gekochten Pasta mischen.",
        "ingredients": [
            ("Spaghetti", 250, "g", None, GB),
            ("Gehackte Tomaten", 1, "Dose", None, KV),
            ("Knoblauchzehe", 3, "Stueck", "in Scheiben schneiden", G),
            ("Chilischote", 1, "Stueck", "fein hacken", G),
            ("Olivenoel", 3, "EL", None, OE),
            ("Basilikum", 1, "Bund", "zupfen", G),
            ("Salz", None, None, None, GW),
        ],
    },
    {
        "name": "Gemuese-Stir-Fry mit Tofu",
        "servings": 2,
        "instructions": "Tofu knusprig braten, herausnehmen. Gemuese im Wok scharf anbraten, Sauce zugeben, Tofu zurueck in den Wok.",
        "ingredients": [
            ("Tofu natur", 200, "g", "wuerfeln", PT),
            ("Brokkoli", 1, "Stueck", "in Roeschen teilen", G),
            ("Karotte", 2, "Stueck", "in Stifte schneiden", G),
            ("Paprika", 1, "Stueck", "in Streifen schneiden", G),
            ("Sojasauce", 3, "EL", None, GW),
            ("Sesamoel", 1, "EL", None, OE),
            ("Ingwer", 2, "cm", "reiben", G),
            ("Reis", 150, "g", None, GB),
        ],
    },
    {
        "name": "Ofengemuese mit Hummus",
        "servings": 2,
        "instructions": "Gemuese mit Oel und Gewuerzen mischen, bei 200 Grad 30 Min backen. Mit Hummus servieren.",
        "ingredients": [
            ("Suesskartoffel", 2, "Stueck", "wuerfeln", G),
            ("Zucchini", 1, "Stueck", "in Scheiben schneiden", G),
            ("Rote Zwiebel", 1, "Stueck", "in Spalten schneiden", G),
            ("Kichererbsen", 1, "Dose", "abtropfen", H),
            ("Olivenoel", 3, "EL", None, OE),
            ("Paprikapulver", 1, "TL", None, GW),
            ("Hummus", 150, "g", None, KV),
        ],
    },
    {
        "name": "Haferflocken-Porridge mit Banane",
        "servings": 1,
        "instructions": "Haferflocken mit Pflanzendrink aufkochen, 5 Min quellen lassen. Mit Banane und Nuessen toppen.",
        "ingredients": [
            ("Haferflocken", 60, "g", None, GB),
            ("Hafermilch", 250, "ml", None, PT),
            ("Banane", 1, "Stueck", "in Scheiben schneiden", G),
            ("Walnuesse", 20, "g", "grob hacken", NS),
            ("Zimt", 1, "TL", None, GW),
        ],
    },
    {
        "name": "Tomaten-Linsen-Suppe",
        "servings": 3,
        "instructions": "Zwiebel und Karotte anschwitzen, Linsen, Tomaten und Bruehe zugeben, 25 Min koecheln, pueriert oder stueckig servieren.",
        "ingredients": [
            ("Rote Linsen", 150, "g", None, H),
            ("Gehackte Tomaten", 1, "Dose", None, KV),
            ("Zwiebel", 1, "Stueck", "wuerfeln", G),
            ("Karotte", 2, "Stueck", "wuerfeln", G),
            ("Gemuesebruehe", 750, "ml", None, KV),
            ("Kreuzkuemmel", 1, "TL", None, GW),
            ("Olivenoel", 1, "EL", None, OE),
        ],
    },
    {
        "name": "Falafel-Bowl",
        "servings": 2,
        "instructions": "Falafel nach Packung zubereiten. Bowl mit Couscous, frischem Gemuese und Tahini-Dressing anrichten.",
        "ingredients": [
            ("Falafel", 8, "Stueck", None, KV),
            ("Couscous", 150, "g", None, GB),
            ("Gurke", 1, "Stueck", "wuerfeln", G),
            ("Cherrytomaten", 150, "g", "halbieren", G),
            ("Tahini", 2, "EL", None, KV),
            ("Zitrone", 1, "Stueck", "auspressen", G),
            ("Petersilie", 0.5, "Bund", "hacken", G),
        ],
    },
    {
        "name": "Erdnuss-Nudeln",
        "servings": 2,
        "instructions": "Nudeln kochen. Sauce aus Erdnussmus, Sojasauce und Limette ruehren, mit Nudeln und Gemuese mischen.",
        "ingredients": [
            ("Reisnudeln", 200, "g", None, GB),
            ("Erdnussmus", 3, "EL", None, NS),
            ("Sojasauce", 2, "EL", None, GW),
            ("Limette", 1, "Stueck", "auspressen", G),
            ("Karotte", 1, "Stueck", "in Stifte schneiden", G),
            ("Fruehlingszwiebel", 2, "Stueck", "in Ringe schneiden", G),
            ("Erdnuesse", 20, "g", "grob hacken", NS),
        ],
    },
    {
        "name": "Pilz-Risotto",
        "servings": 2,
        "instructions": "Zwiebel anschwitzen, Reis glasig duensten, nach und nach Bruehe zugeben. Gebratene Pilze unterheben.",
        "ingredients": [
            ("Risottoreis", 200, "g", None, GB),
            ("Champignons", 250, "g", "in Scheiben schneiden", G),
            ("Zwiebel", 1, "Stueck", "fein wuerfeln", G),
            ("Gemuesebruehe", 750, "ml", None, KV),
            ("Hefeflocken", 2, "EL", None, GW),
            ("Olivenoel", 2, "EL", None, OE),
        ],
    },
    {
        "name": "Chili sin Carne",
        "servings": 4,
        "instructions": "Zwiebel und Paprika anbraten, Sojagranulat, Bohnen, Mais und Tomaten zugeben, mit Gewuerzen 20 Min schmoren.",
        "ingredients": [
            ("Kidneybohnen", 1, "Dose", "abtropfen", H),
            ("Mais", 1, "Dose", "abtropfen", KV),
            ("Gehackte Tomaten", 1, "Dose", None, KV),
            ("Sojagranulat", 80, "g", None, PT),
            ("Zwiebel", 1, "Stueck", "wuerfeln", G),
            ("Paprika", 1, "Stueck", "wuerfeln", G),
            ("Chilipulver", 1, "TL", None, GW),
            ("Kreuzkuemmel", 1, "TL", None, GW),
        ],
    },
    {
        "name": "Avocado-Toast",
        "servings": 1,
        "instructions": "Brot toasten, Avocado zerdruecken, mit Zitrone, Salz und Chiliflocken wuerzen, auf das Brot streichen.",
        "ingredients": [
            ("Vollkornbrot", 2, "Scheibe", None, GB),
            ("Avocado", 1, "Stueck", "zerdruecken", G),
            ("Zitrone", 0.5, "Stueck", "auspressen", G),
            ("Chiliflocken", 1, "Prise", None, GW),
            ("Salz", None, None, None, GW),
        ],
    },
]


def seed_curated(db):
    created = 0
    for r in RECIPES:
        ingredients = [
            schemas.RecipeIngredientBase(
                name=n, amount=a, unit=u, preparation=p, category=c
            )
            for (n, a, u, p, c) in r["ingredients"]
        ]
        crud.create_recipe(
            db,
            schemas.RecipeCreate(
                name=r["name"],
                servings=r["servings"],
                instructions=r.get("instructions"),
                ingredients=ingredients,
            ),
        )
        created += 1
    return created


def seed_bulk(db, target: int):
    """Fuellt mit Varianten der kuratierten Rezepte auf 'target' Rezepte auf.
    Nur fuer Performance-/Skalierungstests gedacht."""
    existing = db.query(models.Recipe).count()
    variants = ["klassisch", "scharf", "mild", "express", "deluxe", "winterlich",
                "sommerlich", "proteinreich", "leicht", "herzhaft"]
    i = 0
    while db.query(models.Recipe).count() < target:
        base = RECIPES[i % len(RECIPES)]
        variant = variants[(i // len(RECIPES)) % len(variants)]
        ingredients = [
            schemas.RecipeIngredientBase(name=n, amount=a, unit=u, preparation=p, category=c)
            for (n, a, u, p, c) in base["ingredients"]
        ]
        crud.create_recipe(
            db,
            schemas.RecipeCreate(
                name=f"{base['name']} ({variant})",
                servings=base["servings"],
                instructions=base.get("instructions"),
                ingredients=ingredients,
            ),
        )
        i += 1
    return db.query(models.Recipe).count() - existing


def main():
    parser = argparse.ArgumentParser(description="Datenbank befuellen")
    parser.add_argument("--reset", action="store_true", help="DB vorher leeren")
    parser.add_argument("--bulk", type=int, default=0, help="auf N Rezepte auffuellen")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.reset:
            db.query(models.PlanEntry).delete()
            db.query(models.RecipeIngredient).delete()
            db.query(models.Recipe).delete()
            db.query(models.Ingredient).delete()
            db.commit()
            print("DB geleert.")

        n = seed_curated(db)
        print(f"{n} kuratierte Rezepte angelegt.")

        if args.bulk:
            extra = seed_bulk(db, args.bulk)
            print(f"{extra} weitere Varianten erzeugt (Ziel: {args.bulk}).")

        print(f"Gesamt jetzt: {db.query(models.Recipe).count()} Rezepte.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
