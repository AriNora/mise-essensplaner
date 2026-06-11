"""tags_zuweisen.py — vergibt Kategorien/Tags an die bereits vorhandenen Rezepte.

Hintergrund: Die Seed- und die importierten Rezepte stammen aus Quellen, die
Gericht-Typ, Kueche und Eigenschaften kennen. Statt alles von Hand zu taggen,
ordnet dieses Skript jedem bekannten Rezept passende Tags zu.

Vorgehen pro Rezept:
  1. Rezept per exaktem Namen finden (Liste durchgehen).
  2. Vollstaendiges Rezept holen (inkl. Zutaten + bisheriger Tags).
  3. Gewuenschte Tags mit den vorhandenen VEREINEN (nichts geht verloren).
  4. Per PUT zurueckschreiben.

Eigenschaften:
  - idempotent: mehrfaches Ausfuehren aendert nichts mehr (Vereinigung).
  - schonend: vorhandene Tags und alle anderen Felder bleiben erhalten.
  - Rezepte, die (noch) nicht in der DB sind, werden uebersprungen.

Voraussetzung: die App laeuft (z.B. python -m uvicorn app.main:app).
Aufruf:  python tags_zuweisen.py
"""
import sys

import requests

# Windows-Konsole auf UTF-8, damit Umlaute in der Ausgabe sauber erscheinen.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_URL = "http://127.0.0.1:8000"

# name -> {"typ": str|None, "kueche": str|None, "eig": [str, ...]}
TAGS = {
    # --- Seed-Rezepte ---
    "Linsen-Dal mit Spinat":            {"typ": "Curry",        "kueche": "Indisch",     "eig": ["One-Pot", "proteinreich", "budgetfreundlich"]},
    "Kichererbsen-Curry":               {"typ": "Curry",        "kueche": "Indisch",     "eig": ["proteinreich", "budgetfreundlich"]},
    "Pasta Arrabbiata":                 {"typ": "Pasta",        "kueche": "Italienisch", "eig": ["schnell", "budgetfreundlich"]},
    "Gemuese-Stir-Fry mit Tofu":        {"typ": "Hauptgericht", "kueche": "Asiatisch",   "eig": ["schnell", "proteinreich"]},
    "Ofengemuese mit Hummus":           {"typ": "Bowl",         "kueche": "Orientalisch","eig": ["glutenfrei", "budgetfreundlich"]},
    "Haferflocken-Porridge mit Banane": {"typ": "Frühstück",    "kueche": None,          "eig": ["schnell", "budgetfreundlich"]},
    "Tomaten-Linsen-Suppe":             {"typ": "Suppe",        "kueche": None,          "eig": ["One-Pot", "proteinreich", "budgetfreundlich", "glutenfrei"]},
    "Falafel-Bowl":                     {"typ": "Bowl",         "kueche": "Orientalisch","eig": ["proteinreich"]},
    "Erdnuss-Nudeln":                   {"typ": "Pasta",        "kueche": "Asiatisch",   "eig": ["schnell", "budgetfreundlich"]},
    "Pilz-Risotto":                     {"typ": "Hauptgericht", "kueche": "Italienisch", "eig": ["glutenfrei"]},
    "Chili sin Carne":                  {"typ": "Eintopf",      "kueche": "Mexikanisch", "eig": ["One-Pot", "proteinreich", "budgetfreundlich", "glutenfrei", "Meal-Prep"]},
    "Avocado-Toast":                    {"typ": "Frühstück",    "kueche": None,          "eig": ["schnell"]},

    # --- Import-Bundle 1 (veganonboard) ---
    "Rote-Linsen-Dahl mit Kokosmilch":  {"typ": "Curry",        "kueche": "Indisch",     "eig": ["One-Pot", "proteinreich", "budgetfreundlich", "glutenfrei"]},
    "Tofu-Chili mit schwarzen Bohnen":  {"typ": "Eintopf",      "kueche": "Mexikanisch", "eig": ["proteinreich", "One-Pot", "glutenfrei", "Meal-Prep"]},
    "Spinat-Kichererbsen-Curry":        {"typ": "Curry",        "kueche": "Indisch",     "eig": ["proteinreich", "budgetfreundlich", "glutenfrei"]},
    "Klebriger Tempeh (Sticky Tempeh)": {"typ": "Hauptgericht", "kueche": "Asiatisch",   "eig": ["proteinreich", "schnell"]},
    "Cremige Pilz-Pasta":               {"typ": "Pasta",        "kueche": "Italienisch", "eig": ["schnell"]},
    "Veganes Pad Thai":                 {"typ": "Pasta",        "kueche": "Thai",        "eig": ["schnell"]},
    "Veganes Gyros (Tofu)":             {"typ": "Hauptgericht", "kueche": "Griechisch",  "eig": ["proteinreich"]},
    "Teriyaki-Tempeh-Pfanne":           {"typ": "Hauptgericht", "kueche": "Japanisch",   "eig": ["proteinreich", "schnell"]},

    # --- Import-Bundle 2 (pickuplimes) ---
    "Auberginen-Orzo mit rotem Pesto":  {"typ": "Pasta",        "kueche": "Italienisch", "eig": ["schnell"]},
    "Schnelles scharfes Chili":         {"typ": "Eintopf",      "kueche": "Mexikanisch", "eig": ["schnell", "One-Pot", "proteinreich", "glutenfrei"]},
    "Cremige Gnocchi-Suppe":            {"typ": "Suppe",        "kueche": "Italienisch", "eig": ["One-Pot", "schnell"]},
    "Rauchiger Linseneintopf mit Aioli":{"typ": "Eintopf",      "kueche": None,          "eig": ["proteinreich", "budgetfreundlich", "glutenfrei", "Meal-Prep"]},
    "Rote-Linsen-Bolognese":            {"typ": "Pasta",        "kueche": "Italienisch", "eig": ["proteinreich", "budgetfreundlich"]},
    "Dan Dan Nudeln":                   {"typ": "Pasta",        "kueche": "Chinesisch",  "eig": ["schnell", "proteinreich"]},
    "Gochujang-Tempeh-Bowl":            {"typ": "Bowl",         "kueche": "Koreanisch",  "eig": ["proteinreich"]},
    "Linsen-Harvest-Bowl":              {"typ": "Bowl",         "kueche": None,          "eig": ["proteinreich", "Meal-Prep", "glutenfrei", "budgetfreundlich"]},
}


def desired_tags(entry):
    """Map-Eintrag -> Liste [{'kind','name'}] in fester Reihenfolge."""
    out = []
    if entry.get("typ"):
        out.append({"kind": "typ", "name": entry["typ"]})
    if entry.get("kueche"):
        out.append({"kind": "kueche", "name": entry["kueche"]})
    for e in entry.get("eig", []):
        out.append({"kind": "eigenschaft", "name": e})
    return out


def fetch_all_recipes():
    """Alle Rezepte (paginiert) als {name_lower: id} holen."""
    by_name = {}
    offset, limit = 0, 200
    while True:
        r = requests.get(f"{BASE_URL}/api/recipes", params={"limit": limit, "offset": offset}, timeout=15)
        r.raise_for_status()
        data = r.json()
        for item in data["items"]:
            by_name[item["name"].strip().lower()] = item["id"]
        offset += limit
        if offset >= data["total"]:
            break
    return by_name


def union_tags(existing, wanted):
    """Vorhandene + gewuenschte Tags vereinen (ohne Duplikate)."""
    seen, merged = set(), []
    for t in list(existing) + list(wanted):
        key = (t["kind"], t["name"])
        if key in seen:
            continue
        seen.add(key)
        merged.append({"kind": t["kind"], "name": t["name"]})
    return merged


def main():
    try:
        by_name = fetch_all_recipes()
    except requests.exceptions.ConnectionError:
        print("Fehler: Keine Verbindung zur App. Laeuft der Server auf "
              f"{BASE_URL}? (python -m uvicorn app.main:app)")
        sys.exit(1)

    tagged = skipped = unchanged = 0
    for name, entry in TAGS.items():
        rid = by_name.get(name.strip().lower())
        if rid is None:
            print(f"  übersprungen (nicht in der DB): {name}")
            skipped += 1
            continue

        full = requests.get(f"{BASE_URL}/api/recipes/{rid}", timeout=15).json()
        wanted = desired_tags(entry)
        merged = union_tags(full.get("tags", []), wanted)

        # Unveraendert, wenn schon alle gewuenschten Tags dran sind.
        before = {(t["kind"], t["name"]) for t in full.get("tags", [])}
        after = {(t["kind"], t["name"]) for t in merged}
        if before >= after:
            print(f"  schon getaggt:  {name}")
            unchanged += 1
            continue

        payload = {
            "name": full["name"],
            "servings": full["servings"],
            "instructions": full.get("instructions"),
            "source": full.get("source"),
            "ingredients": [
                {"name": i["name"], "amount": i.get("amount"), "unit": i.get("unit"),
                 "preparation": i.get("preparation"), "category": i.get("category")}
                for i in full.get("ingredients", [])
            ],
            "tags": merged,
        }
        resp = requests.put(f"{BASE_URL}/api/recipes/{rid}", json=payload, timeout=15)
        resp.raise_for_status()
        labels = ", ".join(t["name"] for t in wanted)
        print(f"  getaggt:        {name}  ->  {labels}")
        tagged += 1

    print(f"\nFertig. {tagged} getaggt, {unchanged} schon aktuell, {skipped} nicht gefunden.")


if __name__ == "__main__":
    main()
