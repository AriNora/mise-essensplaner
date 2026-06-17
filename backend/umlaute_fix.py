r"""Einmalige, SICHERE Migration: ASCII-Schreibweise (ue/oe/ae/ss) -> echte Umlaute.

Warum ein Woerterbuch statt Suchen-und-Ersetzen?
  Ein blindes ue->ue / oe->oe / ss->ss wuerde korrekte Woerter zerstoeren:
  "Apfelessig", "Wasser", "Sojasprossen", "lassen", "neue" -> "neue"(!) usw.
  Darum ersetzt dieses Skript nur EXAKT bekannte ganze Woerter (mit Wortgrenzen)
  aus der kuratierten Liste WORD_MAP. Gross-/Kleinschreibung wird uebernommen.

Sicherheit:
  - Standardmaessig nur VORSCHAU (schreibt nichts). Erst mit  --apply  wird gespeichert.
  - Idempotent: nach der Migration sind keine ASCII-Formen mehr da -> nochmaliges
    Ausfuehren aendert nichts.
  - Unique-Konflikt bei Zutatennamen (z.B. es gibt schon "Grünkohl" UND "Gruenkohl")
    wird durch Zusammenfuehren geloest: Rezept-Zuordnungen wandern zur vorhandenen
    Zutat, die doppelte Zeile wird entfernt.
  - Am Ende meldet das Skript ASCII-Verdaechtige, die es NICHT kannte (zum Pruefen).

Aufruf (im Ordner backend, mit derselben venv wie der Server):
  Vorschau:   .\.venv\Scripts\python.exe umlaute_fix.py
  Schreiben:  .\.venv\Scripts\python.exe umlaute_fix.py --apply
"""
import re
import sys

from app.database import SessionLocal
from app import models

# --------------------------------------------------------------------------- #
#  Kuratiertes Woerterbuch: ascii (klein) -> korrekt (klein).
#  Nur eindeutige Faelle. Korrekte ss-/ue-Woerter (Essig, Wasser, ...) fehlen
#  bewusst und bleiben dadurch unangetastet.
# --------------------------------------------------------------------------- #
WORD_MAP = {
    # Verben / Adjektive (Zubereitung)
    "abgespuelt": "abgespült", "abgiessen": "abgießen", "abloeschen": "ablöschen",
    "abspuelen": "abspülen", "angeruehrt": "angerührt", "anroesten": "anrösten",
    "anruehren": "anrühren", "betraeufeln": "beträufeln", "darueber": "darüber",
    "giessen": "gießen", "zugiessen": "zugießen", "angiessen": "angießen",
    "aufgiessen": "aufgießen", "begiessen": "begießen", "uebergiessen": "übergießen",
    "duenne": "dünne", "duennen": "dünnen", "duensten": "dünsten",
    "einkoecheln": "einköcheln", "einruehren": "einrühren", "erhoehen": "erhöhen",
    "fluessigen": "flüssigen", "fluessigkeit": "flüssigkeit", "fuellen": "füllen",
    "fuer": "für", "gemoersert": "gemörsert", "geraeuchertes": "geräuchertes",
    "geroestet": "geröstet", "geroestete": "geröstete", "geroestetem": "geröstetem",
    "geroestetes": "geröstetes", "geschaelt": "geschält", "gewuerfelt": "gewürfelt",
    "grossen": "großen", "gross": "groß", "grosse": "große", "grosser": "großer",
    "grosses": "großes", "groesse": "größe", "groesser": "größer",
    "gruenes": "grünes", "haelfte": "hälfte", "heiss": "heiß", "heisses": "heißes",
    "koecheln": "köcheln", "laengs": "längs", "loeffel": "löffel", "moersern": "mörsern",
    "pfannenruehren": "pfannenrühren", "puerieren": "pürieren", "roesten": "rösten",
    "ruehren": "rühren", "schraeg": "schräg", "staerke": "stärke",
    "suess": "süß", "suesse": "süße", "suesser": "süßer",
    "ueber": "über", "uebrigen": "übrigen",
    "umruehren": "umrühren", "unregelmaessige": "unregelmäßige",
    "unterruehren": "unterrühren", "verruehren": "verrühren",
    "weisse": "weiße", "weissen": "weißen", "weisser": "weißer",
    "wuerfeln": "würfeln", "wuerzen": "würzen", "zerbroeselt": "zerbröselt",
    "zerdrueckt": "zerdrückt", "zerkruemeln": "zerkrümeln", "zerkruemelt": "zerkrümelt",
    "zusammenfaellt": "zusammenfällt",
    "mitroesten": "mitrösten", "pueriert": "püriert", "stueckig": "stückig",
    "zerdruecken": "zerdrücken", "zurueck": "zurück",
    # Substantive (Zutaten / Begriffe)
    "bruehe": "brühe", "bruehwuerfel": "brühwürfel", "chilioel": "chiliöl",
    "erdnuesse": "erdnüsse", "erdnuessen": "erdnüssen",
    "fruehlingszwiebel": "frühlingszwiebel", "fruehlingszwiebeln": "frühlingszwiebeln",
    "gemuese": "gemüse", "gemuesebruehe": "gemüsebrühe",
    "gemuesebruehwuerfel": "gemüsebrühwürfel", "gewuerze": "gewürze",
    "gruenkohl": "grünkohl", "kokosoel": "kokosöl", "kraeuter": "kräuter",
    "kraeutern": "kräutern", "kreuzkuemmel": "kreuzkümmel",
    "kreuzkuemmelsamen": "kreuzkümmelsamen", "olivenoel": "olivenöl",
    "pflanzenoel": "pflanzenöl", "raeuchertofu": "räuchertofu",
    "senfgemuese": "senfgemüse", "sesamoel": "sesamöl", "speisestaerke": "speisestärke",
    "stueck": "stück", "stuecke": "stücke", "stuecken": "stücken",
    "gewuerzen": "gewürzen", "nuessen": "nüssen", "ofengemuese": "ofengemüse",
    "roeschen": "röschen", "schuessel": "schüssel", "suesskartoffel": "süßkartoffel",
    "suesskartoffeln": "süßkartoffeln", "walnuesse": "walnüsse",
    # Kategorie-Woerter
    "huelsenfruechte": "hülsenfrüchte", "nuesse": "nüsse", "oele": "öle",
    "wuerze": "würze",
}

# Bekannt-korrekte ASCII-Woerter -> nur damit der Rest-Report ruhig bleibt.
ALLOW_OK = {
    "essig", "essige", "wasser", "salzwasser", "sprossen", "sojasprossen",
    "lassen", "quellen", "gepresst", "ausgepresst", "dressing", "misopaste",
    "miso", "reisessig", "apfelessig", "balsamicoessig", "presse", "pressen",
    "klasse", "tasse", "masse", "fluss",
    "auspressen", "erdnuss", "erdnussmus", "lieblingsessen", "walnuss",
}

_LETTER = "A-Za-zÄÖÜäöüß"
_keys = sorted(WORD_MAP, key=len, reverse=True)
_PAT = re.compile(
    r"(?<![%s])(%s)(?![%s])" % (_LETTER, "|".join(re.escape(k) for k in _keys), _LETTER),
    re.IGNORECASE,
)
_CAND = re.compile(r"[%s]*(?:ae|oe|ue|ss)[%s]*" % (_LETTER, _LETTER))


def fix_text(text):
    """Gibt (neuer_text, [(quelle, ziel), ...]) zurueck."""
    if not text:
        return text, []
    changes = []

    def repl(m):
        src = m.group(1)
        base = WORD_MAP[src.lower()]
        out = base[0].upper() + base[1:] if src[:1].isupper() else base
        changes.append((src, out))
        return out

    return _PAT.sub(repl, text), changes


def leftovers(text):
    """ASCII-Verdaechtige, die weder im Woerterbuch noch in der OK-Liste stehen."""
    if not text:
        return []
    res = []
    for w in _CAND.findall(text):
        lw = w.lower()
        if lw in WORD_MAP or lw in ALLOW_OK:
            continue
        res.append(w)
    return res


def main(apply):
    db = SessionLocal()
    exact = []        # kurze Felder: volle Vorher->Nachher-Zeilen
    word_counts = {}  # Wortpaare aus Freitexten -> Anzahl
    left = set()
    n_fields = 0

    def note_words(changes):
        for src, out in changes:
            word_counts[(src.lower(), out.lower())] = word_counts.get((src.lower(), out.lower()), 0) + 1

    try:
        ings = db.query(models.Ingredient).all()
        by_name = {i.name: i for i in ings}

        for ing in ings:
            new, ch = fix_text(ing.name)
            if ch and new != ing.name:
                exact.append(("Ingredient.name", ing.name, new))
                n_fields += 1
                if apply:
                    tgt = by_name.get(new)
                    if tgt is not None and tgt.id != ing.id:
                        # Zusammenfuehren: Zuordnungen umhaengen, Doppel loeschen
                        db.query(models.RecipeIngredient).filter_by(ingredient_id=ing.id) \
                            .update({"ingredient_id": tgt.id})
                        if not tgt.category and ing.category:
                            tgt.category = ing.category
                        by_name.pop(ing.name, None)
                        db.delete(ing)
                    else:
                        by_name.pop(ing.name, None)
                        ing.name = new
                        by_name[new] = ing

            ncat, cch = fix_text(ing.category)
            if cch and ncat != ing.category:
                exact.append(("Ingredient.category", ing.category, ncat))
                n_fields += 1
                if apply:
                    ing.category = ncat
            for w in leftovers(ing.name) + leftovers(ing.category or ""):
                left.add(w)

        for ri in db.query(models.RecipeIngredient).all():
            for field in ("unit", "preparation"):
                val = getattr(ri, field)
                nv, ch = fix_text(val)
                if ch and nv != val:
                    exact.append((f"RecipeIngredient.{field}", val, nv))
                    n_fields += 1
                    if apply:
                        setattr(ri, field, nv)
                for w in leftovers(val or ""):
                    left.add(w)

        for rc in db.query(models.Recipe).all():
            for field in ("name", "instructions", "source"):
                val = getattr(rc, field)
                nv, ch = fix_text(val)
                if ch and nv != val:
                    n_fields += 1
                    if field == "name":
                        exact.append(("Recipe.name", val, nv))
                    else:
                        note_words(ch)
                    if apply:
                        setattr(rc, field, nv)
                for w in leftovers(val or ""):
                    left.add(w)

        if hasattr(models, "Tag"):
            for tg in db.query(models.Tag).all():
                nv, ch = fix_text(tg.name)
                if ch and nv != tg.name:
                    exact.append(("Tag.name", tg.name, nv))
                    n_fields += 1
                    if apply:
                        tg.name = nv
                for w in leftovers(tg.name):
                    left.add(w)

        if apply:
            db.commit()
    finally:
        db.close()

    head = "ANGEWENDET" if apply else "VORSCHAU (es wurde nichts geschrieben)"
    print(f"=== Umlaut-Migration: {head} ===")
    print(f"Betroffene Felder: {n_fields}\n")

    if exact:
        print("Felder (vorher -> nachher):")
        seen = set()
        for fld, a, b in exact:
            key = (fld, a, b)
            if key in seen:
                continue
            seen.add(key)
            print(f"  [{fld}] {a!r} -> {b!r}")
    if word_counts:
        print("\nWort-Ersetzungen in Freitexten (Anzahl):")
        for (a, b), n in sorted(word_counts.items()):
            print(f"  {a} -> {b}  ({n}x)")
    if left:
        print("\nNicht angefasste ASCII-Verdaechtige (bitte pruefen, ggf. an mich melden):")
        for w in sorted(left, key=str.lower):
            print(f"  {w}")
    if not apply:
        print("\n--> Vorschau ok? Dann schreiben mit:  python umlaute_fix.py --apply")


if __name__ == "__main__":
    main("--apply" in sys.argv)