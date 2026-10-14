"""Fuehrt doppelte Zutaten zusammen (z.B. 'Zwiebel' / 'Zwiebeln').

Aufruf (aus dem Ordner backend/):
    python -m app.dedupe_ingredients            # Dry-Run: nur Bericht, aendert nichts
    python -m app.dedupe_ingredients --apply    # fuehrt zusammen (legt vorher ein Backup an)
    python -m app.dedupe_ingredients --db pfad/zur/mealplanner.db

Pro Gruppe gleicher Zutaten (gleicher ingredient_key, siehe normalize.py) bleibt
die am haeufigsten verwendete Schreibweise erhalten; die Rezept-Zeilen der
anderen werden darauf umgehaengt, dann werden die ueberzaehligen Zutaten
geloescht. Hat die Ziel-Zutat keine Warengruppe, wird die der haeufigsten
anderen Variante uebernommen. Bei abweichenden Warengruppen bleibt die des
Ziels (wird im Bericht gemeldet).

Empfehlung: Server vorher beenden, damit keine Schreibzugriffe parallel laufen.
"""
import argparse
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .normalize import ingredient_key

DEFAULT_DB = Path(__file__).resolve().parent.parent / "mealplanner.db"


def load_groups(conn):
    """Liefert Gruppen (Liste von Zutaten-Dicts, Ziel zuerst) mit >= 2 Eintraegen."""
    rows = conn.execute(
        """
        SELECT i.id, i.name, i.category, COUNT(ri.id) AS uses
        FROM ingredients i
        LEFT JOIN recipe_ingredients ri ON ri.ingredient_id = i.id
        GROUP BY i.id
        """
    ).fetchall()
    buckets = defaultdict(list)
    for id_, name, category, uses in rows:
        buckets[ingredient_key(name)].append(
            {"id": id_, "name": name, "category": category, "uses": uses}
        )
    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        # Ziel: meistgenutzt, dann mit Kategorie, dann aelteste ID.
        members.sort(key=lambda m: (-m["uses"], m["category"] is None, m["id"]))
        groups.append(members)
    groups.sort(key=lambda g: g[0]["name"].casefold())
    return groups


def report(conn, groups):
    print(f"{len(groups)} Gruppen mit Dubletten gefunden:\n")
    for g in groups:
        target, losers = g[0], g[1:]
        print(f"  BEHALTEN  {target['name']!r} ({target['uses']}x, {target['category']})")
        for m in losers:
            note = ""
            if m["category"] and target["category"] and m["category"] != target["category"]:
                note = f"  <- Kategorie-Konflikt, bleibt: {target['category']}"
            print(f"  ENTFERNEN {m['name']!r} ({m['uses']}x, {m['category']}){note}")
        print()
    # Nur melden: andere Wortform mit anderer Bedeutung, wird NICHT zusammengefuehrt.
    hint = conn.execute(
        "SELECT name FROM ingredients WHERE lower(name) LIKE 'knoblauch%' ORDER BY name"
    ).fetchall()
    if len(hint) > 1:
        print("Nur zur Info (wird nicht zusammengefuehrt): " + ", ".join(n for (n,) in hint))


def apply(conn, db_path, groups):
    backup = db_path.with_name(f"{db_path.stem}.bak-{datetime.now():%Y%m%d-%H%M%S}.db")
    shutil.copy2(db_path, backup)  # einfache Dateikopie (Server ist beendet)
    print(f"Backup: {backup}")

    before = {
        "ingredients": conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0],
        "links": conn.execute("SELECT COUNT(*) FROM recipe_ingredients").fetchone()[0],
    }
    removed = relinked = 0
    with conn:  # eine Transaktion: alles oder nichts
        for g in groups:
            target, losers = g[0], g[1:]
            if target["category"] is None:
                cat = next((m["category"] for m in losers if m["category"]), None)
                if cat:
                    conn.execute("UPDATE ingredients SET category=? WHERE id=?", (cat, target["id"]))
            ids = [m["id"] for m in losers]
            marks = ",".join("?" * len(ids))
            relinked += conn.execute(
                f"UPDATE recipe_ingredients SET ingredient_id=? WHERE ingredient_id IN ({marks})",
                [target["id"], *ids],
            ).rowcount
            removed += conn.execute(
                f"DELETE FROM ingredients WHERE id IN ({marks})", ids
            ).rowcount

    after = {
        "ingredients": conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0],
        "links": conn.execute("SELECT COUNT(*) FROM recipe_ingredients").fetchone()[0],
    }
    dangling = conn.execute(
        "SELECT COUNT(*) FROM recipe_ingredients WHERE ingredient_id NOT IN (SELECT id FROM ingredients)"
    ).fetchone()[0]
    print(f"Zutaten: {before['ingredients']} -> {after['ingredients']} (entfernt: {removed})")
    print(f"Rezept-Zeilen umgehaengt: {relinked}; gesamt vorher/nachher: {before['links']}/{after['links']}")
    print(f"Verwaiste Verweise: {dangling}")
    if dangling or before["links"] != after["links"]:
        print("WARNUNG: Pruefung fehlgeschlagen - bitte Backup einspielen.", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Doppelte Zutaten zusammenfuehren")
    parser.add_argument("--apply", action="store_true", help="wirklich zusammenfuehren (sonst Dry-Run)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Pfad zur SQLite-Datei")
    args = parser.parse_args()

    if not args.db.exists():
        sys.exit(f"Datenbank nicht gefunden: {args.db}")
    if args.apply:
        conn = sqlite3.connect(args.db)
    else:
        conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)  # schreibgeschuetzt

    try:
        groups = load_groups(conn)
        if not groups:
            print("Keine Dubletten gefunden.")
            return
        report(conn, groups)
        if args.apply:
            apply(conn, args.db, groups)
        else:
            print("\nDry-Run: es wurde nichts geaendert. Mit --apply zusammenfuehren.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
