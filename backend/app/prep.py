"""Vorbereitungsplan (Mise en place): Zutaten nach Verarbeitungsart gruppieren."""
from collections import OrderedDict
from typing import Dict

from sqlalchemy.orm import Session

from . import models
from .units import round_amount

# --------------------------------------------------------------------------- #
#  Vorbereitungsarten zusammenfassen (kuratierte Synonym-Tabelle)
# --------------------------------------------------------------------------- #
# Ziel: Schreibvarianten DERSELBEN Handbewegung landen im Vorbereitungsplan in
# einer Gruppe (Kanon-Form = Infinitiv, liest sich wie eine To-do-Liste).
# Bewusste Grenzen:
#   - grob/fein bleiben GETRENNT (eigene Gruppen)
#   - Mengen/Verpackung (z.B. "Dose", "ca. 60 g"), Verwendung ("für den Salat")
#     und Alternativen ("oder Mie-Nudeln") werden NICHT angefasst -> eigene Gruppe
#   - Mehrschritt-Angaben ("entkernt, fein gehackt") bleiben unberührt
#   - ein angehängtes ", optional" reitet mit: "in Scheiben, optional"
#                                              -> "in Scheiben schneiden, optional"
# Prinzip wie beim Umlaut-Wörterbuch: KURATIERT, nicht geraten. Eine unbekannte
# Schreibweise bleibt einfach als eigene Gruppe stehen (es geht nie etwas kaputt);
# neue Varianten ergänzt man hier mit einer Zeile.
# Wichtig: Der Originaltext an der Zutat wird NICHT verändert - nur die
# Gruppierung/Anzeige im Plan nutzt die Kanon-Form.

# Kanon-Form -> Liste der Schreibvarianten (alles klein geschrieben zum Abgleich).
_PREP_CANON_GROUPS = {
    "hacken":                     ["gehackt", "hacken"],
    "fein hacken":                ["fein gehackt", "fein hacken"],
    "grob hacken":                ["grob gehackt", "grob hacken"],
    "würfeln":                    ["gewürfelt", "würfeln"],
    "fein würfeln":               ["fein gewürfelt", "fein würfeln"],
    "in Scheiben schneiden":      ["in scheiben", "in scheiben schneiden"],
    "in dünne Scheiben schneiden":["in dünnen scheiben", "in dünne scheiben schneiden"],
    "in Ringe schneiden":         ["in ringen", "in ringe schneiden"],
    "in Streifen schneiden":      ["in streifen", "in streifen schneiden"],
    "in Stücke schneiden":        ["in stücke", "in stücke schneiden"],
    "in Halbmonde schneiden":     ["in halbmonden", "in halbmonde schneiden"],
    "reiben":                     ["gerieben", "reiben"],
    "auspressen":                 ["ausgepresst", "auspressen"],
    "zerdrücken":                 ["zerdrückt", "zerdrücken"],
    "zerbröseln":                 ["zerbröselt", "zerbröseln"],
    "abspülen":                   ["abgespült", "abspülen"],
    "kochen":                     ["gekocht", "kochen"],
    "mahlen":                     ["gemahlen", "mahlen"],
    "rösten":                     ["geröstet", "rösten"],
    "vierteln":                   ["geviertelt", "vierteln"],
    "längs schneiden":            ["längs geschnitten", "längs schneiden"],
    "schräg schneiden":           ["schräg geschnitten", "schräg schneiden"],
}

# Nachschlage-Tabelle: variante(klein) -> Kanon-Form. Einmal aus den Gruppen
# aufgebaut, damit oben gepflegt und unten schnell nachgeschlagen werden kann.
_PREP_LOOKUP = {
    variant: canon
    for canon, variants in _PREP_CANON_GROUPS.items()
    for variant in variants
}

# Zusätze, die hinter einer bekannten Aktion stehen dürfen und erhalten bleiben.
_PREP_KEEP_SUFFIXES = (", optional",)


def _canon_prep(text: str) -> str:
    """Bringt eine Verarbeitungsangabe auf die Kanon-Form, wenn sie bekannt ist.

    Bekannt    -> Infinitiv-Form (z.B. "gewürfelt" -> "würfeln").
    Mit Zusatz -> Aktion vereinheitlicht, Zusatz bleibt
                  (z.B. "in Scheiben, optional" -> "in Scheiben schneiden, optional").
    Unbekannt  -> unverändert zurück (eigene Gruppe; Mengen/Verwendung/Alternativen
                  und Mehrschritt-Angaben bleiben so erhalten).
    """
    raw = " ".join(text.split())          # Mehrfach-Leerzeichen glätten
    low = raw.lower()

    # 1) Erhaltenswerter Zusatz wie ", optional" abtrennen, Aktion davor prüfen.
    for suffix in _PREP_KEEP_SUFFIXES:
        if low.endswith(suffix):
            base = low[: -len(suffix)].strip()
            canon = _PREP_LOOKUP.get(base)
            if canon is not None:
                return canon + suffix
            return raw                    # Aktion unbekannt -> nichts anfassen

    # 2) Ganze Angabe als bekannte Variante?
    canon = _PREP_LOOKUP.get(low)
    if canon is not None:
        return canon

    # 3) Unbekannt -> Originaltext unverändert (eigene Gruppe).
    return raw


# --------------------------------------------------------------------------- #
#  KERNLOGIK 2: Vorbereitungsplan (Mise en place)
# --------------------------------------------------------------------------- #
def build_prep_plan(db: Session) -> dict:
    """Gruppiert alle vorzubereitenden Zutaten nach Verarbeitungsart.

    Beispiel-Ergebnis:
      "würfeln":  5 Zwiebeln (aus Curry, Suppe), 1 Paprika (aus Curry)
      "schälen":  4 Kartoffeln (aus Suppe)

    Gleiche Zutat + Einheit innerhalb einer Verarbeitungsart wird summiert, damit
    man z.B. alle Zwiebeln auf einmal würfeln kann.
    """
    entries = db.query(models.PlanEntry).join(models.Recipe).all()

    # prep_lower -> { (name_lower, unit_lower): {...} }
    groups: "OrderedDict[str, OrderedDict]" = OrderedDict()
    prep_display: Dict[str, str] = {}

    for entry in entries:
        recipe = entry.recipe
        factor = entry.servings / recipe.servings if recipe.servings else 1.0
        for ri in recipe.ingredients:
            if not ri.preparation:
                continue
            # Schreibvarianten derselben Aktion zusammenfassen (Original bleibt
            # an der Zutat unberuehrt - nur Gruppierung/Anzeige nutzt die Kanon-Form).
            canon_disp = _canon_prep(ri.preparation)
            prep_key = canon_disp.lower()
            prep_display.setdefault(prep_key, canon_disp)
            bucket = groups.setdefault(prep_key, OrderedDict())

            name = ri.ingredient.name
            ikey = (name.lower(), (ri.unit or "").lower())
            item = bucket.setdefault(
                ikey,
                {"name": name, "amount": None, "unit": ri.unit, "recipes": set()},
            )
            if ri.amount is not None:
                item["amount"] = (item["amount"] or 0) + ri.amount * factor
            item["recipes"].add(recipe.name)

    result = []
    for prep_key, items in groups.items():
        out_items = []
        for it in items.values():
            out_items.append(
                {
                    "name": it["name"],
                    "amount": round_amount(it["amount"]),
                    "unit": it["unit"],
                    "recipe": ", ".join(sorted(it["recipes"])),
                }
            )
        out_items.sort(key=lambda x: x["name"].lower())
        result.append({"preparation": prep_display[prep_key], "items": out_items})

    result.sort(key=lambda g: g["preparation"].lower())
    return {"groups": result}
