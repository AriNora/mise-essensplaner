# Mise — Essensplaner

Eine schlanke Full-Stack-Webanwendung für die wöchentliche Essensplanung:
Rezepte verwalten, Gerichte für die Woche einplanen, daraus automatisch eine
zusammengefasste **Einkaufsliste** und einen nach Handgriffen gebündelten
**Vorbereitungsplan** (Mise en place) erzeugen — mit frei wählbarer Portionszahl.
Gerichte lassen sich nach Wochentagen (Mo–So) einplanen und mit einem Bild versehen.

---

## 1. Architektur auf einen Blick

```
        Browser (Frontend, Vanilla JS)
                  │  fetch /api/...
                  ▼
   ┌──────────────────────────────────┐
   │  FastAPI  (ein Prozess)            │
   │   • REST-API   /api/...            │
   │   • liefert das Frontend unter /   │
   └──────────────┬───────────────────┘
                  │ SQLAlchemy ORM
                  ▼
            SQLite  (eine Datei: mealplanner.db)
```

**Warum diese Wahl?** Ein einziger Server liefert API *und* Frontend aus:
ein Startbefehl, keine getrennten Dienste, keine CORS-Probleme (alles
same-origin), kein Frontend-Build-Schritt. Genau das Richtige für eine
zuverlässig vorführbare Einzelarbeit — ohne auf eine echte Datenbank,
saubere Schichtentrennung und ein REST-API-Design zu verzichten.

**Technologie**
- Backend: Python, FastAPI, SQLAlchemy 2.0, Pydantic 2
- Datenbank: SQLite (für ~1000 Rezepte mehr als ausreichend; durch das ORM
  ohne Code-Änderung später auf PostgreSQL umstellbar)
- Frontend: HTML/CSS/Vanilla-JavaScript (ES-Module), ohne Build-Werkzeuge

---

## 2. Datenmodell

```
Ingredient (kanonische Zutat)        Recipe (Rezept)
  id                                   id
  name (eindeutig)                     name
  category (Warengruppe)               servings  ← Basis-Portionen
        │                              instructions
        │                                    │
        │        RecipeIngredient            │
        └──────────  recipe_id  ─────────────┘
                     ingredient_id
                     amount, unit, preparation, position

PlanEntry (eingeplantes Gericht)
  recipe_id, servings ← gewünschte Portionen, day (optional)
```

Der zentrale Trick ist die **Normalisierung**: Zutaten leben in einer eigenen
Tabelle. Dadurch ist „Zwiebel" über alle Rezepte hinweg *dieselbe* Zutat — die
Voraussetzung dafür, dass die Einkaufsliste Mengen korrekt zusammenfassen kann.

---

## 3. Die drei Kernfunktionen (in `app/crud.py`)

1. **Portions-Skalierung** — `Faktor = gewünschte / Basis-Portionen`; jede
   Zutatenmenge wird damit hochgerechnet.
2. **Einkaufsliste** (`build_shopping_list`) — sammelt die Zutaten aller
   geplanten Rezepte, rechnet sie auf die gewünschten Portionen hoch, fasst
   gleiche Zutat+Einheit zusammen und gruppiert nach Warengruppe.
3. **Vorbereitungsplan** (`build_prep_plan`) — gruppiert alle vorzubereitenden
   Zutaten nach Verarbeitungsart („würfeln", „schälen") und bündelt gleiche
   Handgriffe, sodass du z.B. alle Zwiebeln auf einmal schneidest.

---

## 4. Einrichten & Starten

Voraussetzung: Python 3.10+.

```bash
cd backend

# 1. Virtuelle Umgebung + Abhängigkeiten
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Datenbank mit Start-Rezepten befüllen (12 vegane Gerichte)
python -m app.seed --reset

# 3. Server starten
uvicorn app.main:app
```

> Hinweis: bewusst ohne `--reload` und ohne `uvicorn[standard]` — so werden keine
> in C kompilierten Zusatzpakete (httptools/uvloop) gebraucht, die unter Windows
> sonst einen C++-Compiler verlangen wuerden. Fuer eine Einzelperson-App ist das
> ohne Bedeutung. Wer beim Entwickeln Auto-Reload moechte, installiert zusaetzlich
> `watchfiles` und startet mit `uvicorn app.main:app --reload`.

Dann im Browser öffnen:
- **App:** http://127.0.0.1:8000
- **API-Doku (automatisch generiert):** http://127.0.0.1:8000/docs

### Seed-Optionen
```bash
python -m app.seed --reset              # 12 kuratierte Rezepte
python -m app.seed --reset --bulk 1000  # auf ~1000 Rezepte auffüllen (Skalierungstest)
```

---

## 5. Projektstruktur

```
mealplanner/
├─ backend/
│  ├─ app/
│  │  ├─ main.py        FastAPI-App: Router einbinden + Frontend ausliefern
│  │  ├─ database.py    SQLite-/SQLAlchemy-Setup
│  │  ├─ models.py      Datenmodell (4 Tabellen)
│  │  ├─ schemas.py     Pydantic-Schemas (Ein-/Ausgabevalidierung)
│  │  ├─ crud.py        CRUD + Kernlogik (Skalierung, Einkaufsliste, Prep)
│  │  ├─ seed.py        Startdaten + Bulk-Generator
│  │  └─ routers/       API-Endpunkte (recipes, ingredients, plan)
│  └─ requirements.txt
└─ frontend/
   ├─ index.html        App-Shell + Navigation
   ├─ css/styles.css    Gestaltung
   └─ js/
      ├─ api.js         gebündelte fetch-Aufrufe
      └─ app.js         Router + alle Ansichten
```

---

## 6. Bewusste Scope-Entscheidungen (gut fürs Kolloquium)

- **Einheiten werden nicht ineinander umgerechnet.** „200 g Tomaten" und
  „1 Dose Tomaten" bleiben getrennte Listenpunkte. Eine Umrechnungslogik wäre
  fachlich kaum eindeutig (Dichten, Packungsgrößen) — daher bewusst
  ausgeklammert und sauber per (Name + Einheit) aggregiert.
- **Ein aktiver Wochenplan**, nicht mehrere Wochen. Hält das Modell schlank;
  ein `Plan`-Elternobjekt ließe sich ohne Bruch ergänzen (`day`-Feld ist schon
  vorgesehen).
- **SQLite statt Server-DB**: angemessen für eine Einzelperson; die ORM-Schicht
  macht einen späteren Wechsel risikoarm.

## 7. Mögliche Erweiterungen

Vorratskammer (vorhandene Zutaten von der Liste abziehen) · Export der
Einkaufsliste · Nährwerte · Anbindung an Bring! (lokal über die inoffizielle API
oder offiziell per Import-Button mit öffentlichem Hosting) · Mehrbenutzer mit Login.
