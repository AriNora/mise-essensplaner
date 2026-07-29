# Mise – Veganer Essensplaner

Mise ist eine Full-Stack-Webapp zum Planen veganer Rezepte, zum automatischen
Erstellen von Einkaufslisten und zum Verwalten eines eigenen Vorrats.
Entstanden als Spielprojekt zum Vibe Coden mit Claude und aus persönlichem Wunsch nach einer solchen Lösung.

## Funktionen

- **Rezeptverwaltung** mit Zutaten, Mengen und Zubereitungsschritten
- **Tag- und Filtersystem** über drei Facetten (Typ, Küche, Eigenschaft) mit
  ODER-/UND-Verknüpfung und eigenen, nutzererstellbaren Tags
- **Wochenplaner** zum Einplanen von Rezepten
- **Einkaufsliste** mit automatischer Zusammenfassung gleicher Zutaten und
  Einheiten-Umrechnung
- **Vorratsverwaltung** – bereits vorhandene Zutaten werden berücksichtigt
- **Rezept-Import** aus JSON-Bundles

## Tech-Stack

| Bereich   | Technologie                                   |
|-----------|-----------------------------------------------|
| Backend   | FastAPI, SQLAlchemy, Pydantic v2              |
| Datenbank | SQLite                                        |
| Frontend  | Vanilla-JavaScript Single-Page-App            |

## Projektstruktur

```
mise-essensplaner/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI-Einstieg
│   │   ├── models.py        # SQLAlchemy-Modelle
│   │   ├── schemas.py       # Pydantic-Schemas
│   │   ├── crud.py          # Datenbank-Logik
│   │   ├── database.py      # DB-Verbindung
│   │   └── routers/         # API-Endpunkte (recipes, ingredients, plan, tags, imports)
│   ├── import_recipes-v3.py # Import-Skript für Rezept-Bundles
│   ├── recipes-*.json       # Rezept-Bundles (Beispieldaten)
│   └── requirements.txt
└── frontend/
    ├── index.html
    └── js/
        └── app.js
```

## Setup

### Voraussetzungen

- Python 3.8 oder neuer

### Backend starten (Windows / PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app
```

Das Backend läuft anschließend unter **http://127.0.0.1:8000**.
Die API-Dokumentation ist unter **http://127.0.0.1:8000/docs** erreichbar.

> Hinweis: Die Datenbank `mealplanner.db` wird beim ersten Start automatisch
> angelegt und ist bewusst nicht Teil des Repos. Jede:r startet also mit einer
> leeren Datenbank.

### Frontend öffnen

Die Datei `frontend/index.html` im Browser öffnen.

### Rezepte importieren (optional)

Um die leere Datenbank mit Beispielrezepten zu füllen, das Backend starten und
in einem zweiten Terminal ein Bundle importieren:

```powershell
cd backend
.\.venv\Scripts\python.exe import_recipes-v3.py recipes-eisen-01.json
```

Weitere Bundles (`recipes-*.json`) können auf die gleiche Weise importiert
werden. Das Import-Skript ist idempotent – ein erneuter Import legt keine
Dubletten an.

## Rezept-Bundles

Rezepte werden als JSON-Array eingelesen. Jedes Rezept hat folgende Struktur:

```json
{
  "name": "Rezeptname",
  "servings": 4,
  "source": "Creator – Seite – URL",
  "instructions": "1. Schritt eins\n2. Schritt zwei",
  "ingredients": [
    {
      "name": "Zutat",
      "amount": 200,
      "unit": "g",
      "preparation": "gewürfelt",
      "category": "Obst & Gemüse"
    }
  ],
  "tags": [
    { "kind": "typ", "name": "Hauptgericht" },
    { "kind": "kueche", "name": "Italienisch" },
    { "kind": "eigenschaft", "name": "Deftig" }
  ]
}
```

Gültige Kategorien: `Obst & Gemüse`, `Hülsenfrüchte`, `Getreide & Backwaren`,
`Pflanzendrinks & Tofu`, `Nüsse & Samen`, `Öle & Essige`, `Gewürze & Würze`,
`Konserven & Vorrat`, `Sonstiges`.

## Lizenz / Hinweis

Entstanden als Spielprojekt zum Vibe Coden und aus persönlichem Wunsch nach einer solchen Lösung. 
Alle Rezepte sollen mit Quellenangabe zum jeweiligen Urheber im Feld `source` versehen werden.
