# Mise – Veganer Essensplaner

Mise hilft dir, vegane Rezepte zu sammeln, eine Woche zu planen und daraus
automatisch eine Einkaufsliste zu erstellen. Die App läuft auf deinem eigenen
Computer; deine Daten bleiben bei dir.

Entstanden als Projekt zum Vibe Coden mit Claude und aus persönlichem Wunsch
nach einer solchen Lösung.

## Was kann Mise?

- **Rezepte** mit Zutaten, Mengen und Schritten verwalten, suchen und nach
  Gerichtstyp, Küche und Eigenschaften filtern (eigene Tags möglich)
- **Rezepte importieren** – von einer Webseite (Link) oder aus eingefügtem Text.
  Der Import füllt nur einen Entwurf vor; du prüfst ihn, bevor er gespeichert wird.
  Links funktionieren nur für öffentliche Webseiten (nicht für Adressen im eigenen
  Rechner oder Netzwerk).
- **Wochenplan** – Rezepte den Wochentagen zuordnen
- **Einkaufsliste** – fasst gleiche Zutaten aller geplanten Rezepte zusammen
  und rechnet Einheiten um
- **Vorrat** – Zutaten, die du immer zu Hause hast (z. B. Salz, Wasser). Sie
  bleiben im Rezept stehen, landen aber nie auf der Einkaufsliste. Die Liste
  pflegst du selbst unter „Vorrat“.
- **Vorbereitung** – Zutaten nach Arbeitsschritt gruppiert (z. B. alles
  Gehackte zusammen)
- **Bring!** (optional) – schickt die Einkaufsliste an die Einkaufs-App Bring!
- **Sicherung** – unten auf der Rezeptseite: alle Rezepte, Bilder und den Vorrat
  als eine ZIP-Datei speichern und später wieder einspielen

## Starten

Du brauchst **Python 3.8 oder neuer**. Alles Weitere installiert sich selbst.

Windows (PowerShell), im Projektordner:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1
```

Danach im Browser öffnen: **http://127.0.0.1:8000**

Beenden: im Terminal `Strg + C`. Beim nächsten Mal genügen die Zeilen
`cd backend`, `.\.venv\Scripts\Activate.ps1` und `python -m uvicorn app.main:app --host 127.0.0.1`.

Beim ersten Start legt Mise die Datenbank `backend/mealplanner.db` selbst an.
Sie ist zunächst leer (der Vorrat enthält nur Wasser, Nudelwasser, Salz und
Pfeffer). Die Datenbank gehört dir und ist nicht Teil des Repos.

### Beispielrezepte laden (optional)

Zum Ausprobieren, im Ordner `backend` (virtuelle Umgebung aktiv):

```powershell
python -m app.seed
```

Das legt 12 Beispielrezepte an (ein zweiter Aufruf legt keine Doppelten an). Mit dem Zusatz `--reset` werden vorher **alle Rezepte,
Zutaten und Wochenplan-Einträge gelöscht**, auch deine eigenen.

### Bring! einrichten (optional)

Lege die Datei `backend/bring_account.json` an:

```json
{ "email": "deine@mail.de", "password": "dein-passwort", "list": "" }
```

`list` ist der Name deiner Bring!-Liste; leer = Standardliste. Die Datei bleibt
lokal und ist von Git ausgeschlossen. Bring! bietet keine offizielle Schnittstelle,
Mise nutzt die inoffizielle; sie kann sich künftig ändern.

## Updates einspielen

Neue Version holen, dann Server neu starten (`Strg + C`, dann wieder
`python -m uvicorn app.main:app --host 127.0.0.1`) und die Seite einmal mit `Strg + F5` neu laden.
Deine Datenbank bleibt dabei erhalten.

**Sichern:** Auf der Rezeptseite unter „Sicherung“ auf „Alles sichern“ klicken und die
ZIP-Datei aufbewahren. „Sicherung einspielen …“ ergänzt sie wieder, z. B. auf einem
neuen Rechner; vorhandene Rezepte werden dabei nicht überschrieben. Der Wochenplan
gehört nicht zur Sicherung. Alternativ kannst du `backend/mealplanner.db` und den
Ordner `backend/uploads` kopieren, solange der Server aus ist.

## Für Entwickler

| Bereich   | Technologie                                          |
|-----------|------------------------------------------------------|
| Backend   | FastAPI, SQLAlchemy 2, Pydantic v2                   |
| Datenbank | SQLite (eine Datei, keine Einrichtung nötig)         |
| Frontend  | Vanilla-JavaScript Single-Page-App, vom Backend mit ausgeliefert |

```
backend/
├── app/
│   ├── main.py        # Einstieg, Datenbank-Start
│   ├── models.py      # Tabellen
│   ├── schemas.py     # API-Datenformate
│   ├── crud.py        # Datenbank-Zugriffe (Rezepte, Tags, Plan)
│   ├── shopping.py    # Einkaufsliste (Zusammenfassen, Skalieren, Einheiten)
│   ├── prep.py        # Vorbereitungsplan
│   ├── units.py       # Einheiten-Schreibweisen, Umrechnung, Runden
│   ├── pantry.py      # Vorrat und Abgleich mit der Einkaufsliste
│   ├── normalize.py   # Zutatennamen vereinheitlichen (Zwiebel = Zwiebeln)
│   ├── importer.py    # Rezept-Import (Link/Text)
│   ├── bring.py       # Bring!-Anbindung
│   ├── backup.py      # Sicherung als ZIP (Export und Einspielen)
│   ├── seed.py        # Beispieldaten
│   ├── dedupe_ingredients.py  # Wartungsskript: doppelte Zutaten zusammenführen
│   └── routers/       # API-Endpunkte unter /api
├── tests/
└── requirements.txt
frontend/              # index.html, js/, css/
```

- API-Dokumentation bei laufendem Server: http://127.0.0.1:8000/docs
- Tests (pytest und httpx sind nicht in `requirements.txt`):
  `pip install pytest httpx`, dann im Ordner `backend`: `python -m pytest`
- Doppelte Zutaten prüfen: `python -m app.dedupe_ingredients` (nur Anzeige);
  mit `--apply` ändert es die Datenbank und legt vorher eine Sicherung an.
- Neue Tabellen entstehen automatisch beim Start. Für neue Spalten in bestehenden
  Tabellen gibt es `ensure_schema()` in `main.py`; ein Migrationswerkzeug wie
  Alembic wird bewusst nicht verwendet.

## Hinweis

Rezepte sollen mit Quellenangabe zum jeweiligen Urheber im Feld „Quelle“
versehen werden.
