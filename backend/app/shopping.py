"""Einkaufsliste: Zutaten aller geplanten Rezepte zusammenfassen.

Kernlogik des Projekts. Die Einheiten-Tabellen und das Runden stehen in units.py,
der Vorrat in pantry.py.
"""
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from . import models
from .pantry import find_pantry_match
from .units import CONVERTIBLE, canon_unit, round_amount, round_liters

# --------------------------------------------------------------------------- #
#  KERNLOGIK 1: Einkaufsliste
# --------------------------------------------------------------------------- #
CATEGORY_ORDER = [
    "Obst & Gemüse",
    "Hülsenfrüchte",
    "Getreide & Backwaren",
    "Pflanzendrinks & Tofu",
    "Nüsse & Samen",
    "Öle & Essige",
    "Gewürze & Würze",
    "Konserven & Vorrat",
    "Sonstiges",
]

# Unter dieser Schwelle (g/ml) lieber in Loeffeln anzeigen, sonst in g/ml.
_SPOON_THRESHOLD = 40.0
# Zutaten mit eigener Einheiten-Logik. Schluessel = Zutatenname (casefold, exakt).
#
# Wird in Zehen gefuehrt: 1 TL gehackter Knoblauch = 1 Zehe, 1 EL = 3 Zehen.
# Andere Einheiten (z.B. g) bleiben bei diesen Zutaten als eigene Zeile stehen.
ZEHEN_PROFILE = {
    "knoblauch": {"Zehe": 1.0, "TL": 1.0, "EL": 3.0},
}
# Wird immer in dieser Einheit angezeigt (umgerechnet ueber CONVERTIBLE).
FESTE_ANZEIGE_EINHEIT = {
    "knoblauchpulver": "TL",
}


def _plural_zehe(amount: Optional[float]) -> str:
    return "Zehe" if amount == 1 else "Zehen"


def _spoon_display(total_gml: float) -> Tuple[float, str]:
    """Kleine Mengen als Loeffel: EL wenn glatt durch 15 teilbar, sonst TL."""
    el = total_gml / CONVERTIBLE["EL"]
    if el >= 1 and abs(el - round(el)) < 1e-9:
        return el, "EL"
    return total_gml / CONVERTIBLE["TL"], "TL"


def build_shopping_list(db: Session) -> dict:
    """Aggregiert alle Zutaten der geplanten Rezepte.

    Vorgehen:
      1. Pro Plan-Eintrag den Skalierungsfaktor bestimmen (gewuenscht / Basis).
      2. Jede Zutat mit dem Faktor hochrechnen.
      3. Nach (Zutatenname, Einheit) zusammenfassen und Mengen summieren.
      4. Nach Warengruppe gruppieren.

    Zutaten ohne Menge (z.B. "Salz, nach Geschmack") werden NICHT auf die Liste
    gesetzt - sie kommen aus dem Vorrat und wuerden die Liste nur aufblaehen.
    Zutaten aus dem Vorrat des Nutzers (siehe pantry.py, z.B. Wasser, Salz) werden
    ebenfalls ausgelassen; sie stehen separat unter `in_pantry`.
    """
    entries = db.query(models.PlanEntry).join(models.Recipe).all()
    pantry_items = db.query(models.PantryItem).all()
    in_pantry: Dict[str, str] = {}   # Zutatenname -> deckender Vorrats-Eintrag

    # ------------------------------------------------------------------ #
    # 1) Beitraege pro Zutat sammeln. Pro Name trennen wir:
    #    - umrechenbarer Teil (g/ml/EL/TL/cm) -> in g/ml-Aequivalent summiert
    #    - Knoblauch -> in Zehen (eigene Faktoren); Knoblauchpulver -> Anzeige in TL
    #    - alles andere (Stueck/Prise/... oder ohne Menge) -> eigene Zeile je Einheit
    # ------------------------------------------------------------------ #
    names: "OrderedDict[str, dict]" = OrderedDict()
    for entry in entries:
        recipe = entry.recipe
        factor = entry.servings / recipe.servings if recipe.servings else 1.0
        for ri in recipe.ingredients:
            name = ri.ingredient.name
            nkey = " ".join(name.split()).casefold()
            covered_by = find_pantry_match(name, pantry_items)
            if covered_by is not None:
                in_pantry.setdefault(name, covered_by)
                continue  # immer im Vorrat -> nicht einkaufen
            acc = names.setdefault(nkey, {
                "name": name,
                "category": ri.ingredient.category,
                "conv": 0.0, "conv_units": set(), "conv_has": False,  # umrechenbarer Teil
                "zehe": 0.0, "zehe_has": False,                        # Knoblauch-Profil
                "plain": OrderedDict(),                                # cu -> {amount, unit}
            })
            if acc["category"] is None and ri.ingredient.category:
                acc["category"] = ri.ingredient.category

            cu = canon_unit(ri.unit)
            amount = ri.amount * factor if ri.amount is not None else None

            zehen = ZEHEN_PROFILE.get(nkey)
            if zehen and cu in zehen and amount is not None:
                acc["zehe"] += amount * zehen[cu]
                acc["zehe_has"] = True
            elif not zehen and cu in CONVERTIBLE and amount is not None:
                acc["conv"] += amount * CONVERTIBLE[cu]
                acc["conv_units"].add(cu)
                acc["conv_has"] = True
            else:
                # nicht umrechenbar (Stueck, Prise, ...) oder ohne Menge -> eigene Zeile
                pb = acc["plain"].setdefault(cu, {"amount": None, "unit": ri.unit})
                if amount is not None:
                    pb["amount"] = (pb["amount"] or 0) + amount
                if not pb["unit"] and ri.unit:
                    pb["unit"] = ri.unit

    # ------------------------------------------------------------------ #
    # 2) Aus den Beitraegen je Zutat 1..n Anzeigezeilen bauen.
    #    Anzeige-Einheit: Knoblauch -> Zehen; Knoblauchpulver -> TL; sonst bei
    #    nur EINER umrechenbaren Einheit diese behalten, bei mehreren < 40 g/ml
    #    in Loeffeln, ab 40 in g (falls vorhanden) bzw. ml.
    # ------------------------------------------------------------------ #
    groups: "OrderedDict[str, list]" = OrderedDict()
    for nkey, acc in names.items():
        cat = acc["category"] or "Sonstiges"
        out = groups.setdefault(cat, [])
        name = acc["name"]

        zehen = ZEHEN_PROFILE.get(nkey)
        if zehen and acc["zehe_has"]:
            amount = round_amount(acc["zehe"])
            out.append({"name": name, "amount": amount, "unit": _plural_zehe(amount), "category": cat})
        elif not zehen and acc["conv_has"]:
            total = acc["conv"]                 # in g/ml-Aequivalent
            units = acc["conv_units"]
            fest = FESTE_ANZEIGE_EINHEIT.get(nkey)
            if fest:
                amount, unit = round_amount(total / CONVERTIBLE[fest]), fest
            elif units == {"l"}:
                # reine Liter-Angaben in Litern, ml-genau (3 Nachkommastellen)
                amount, unit = round_liters(total / CONVERTIBLE["l"]), "l"
            elif len(units) == 1:
                u = next(iter(units))
                amount, unit = round_amount(total / CONVERTIBLE[u]), u
            elif total < _SPOON_THRESHOLD:
                a, unit = _spoon_display(total)
                amount = round_amount(a)
            elif "g" in units:
                amount, unit = round_amount(total), "g"   # Masse bleibt in Gramm
            elif total >= CONVERTIBLE["l"]:
                # Volumen ab 1 Liter (z.B. 1 l + 125 ml) zusammengefasst -> Liter
                amount, unit = round_liters(total / CONVERTIBLE["l"]), "l"
            else:
                amount, unit = round_amount(total), "ml"  # ml haben Faktor 1 -> total ist die Menge
            out.append({"name": name, "amount": amount, "unit": unit, "category": cat})

        for pb in acc["plain"].values():
            if pb["amount"] is None:
                # Zutat ohne Mengenangabe ("nach Bedarf", z.B. Salz/Pfeffer/Oel zum
                # Braten) -> nicht auf die Einkaufsliste. Solche Dinge nimmt man aus
                # dem Vorrat; "nach Bedarf" laesst sich ohnehin nicht aufsummieren.
                continue
            out.append({"name": name, "amount": round_amount(pb["amount"]), "unit": pb["unit"], "category": cat})

    # Kategorien in sinnvolle Reihenfolge bringen (Supermarkt-Logik), Rest hinten.
    def cat_sort_key(c: str) -> int:
        return CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else len(CATEGORY_ORDER)

    ordered = []
    for cat in sorted(groups.keys(), key=cat_sort_key):
        items = sorted(groups[cat], key=lambda x: (x["name"].lower(), (x["unit"] or "")))
        if not items:
            continue  # Warengruppe, in der alles mengenlos war -> kein leerer Block
        ordered.append({"category": cat, "items": items})
    skipped = [{"name": n, "pantry": p} for n, p in sorted(in_pantry.items(), key=lambda x: x[0].casefold())]
    return {"groups": ordered, "in_pantry": skipped}
