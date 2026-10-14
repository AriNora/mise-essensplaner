"""Einheiten und Zahlen: Schreibweisen vereinheitlichen, umrechnen, runden.

Gemeinsame Grundlage fuer Einkaufsliste (shopping.py) und Rezept-Import.
"""
from typing import Optional


def round_amount(value: Optional[float]) -> Optional[float]:
    """Auf 2 Nachkommastellen runden; ganze Zahlen bleiben ganz (5.0 -> 5)."""
    if value is None:
        return None
    r = round(value, 2)
    return int(r) if r == int(r) else r


def round_liters(value: Optional[float]) -> Optional[float]:
    """Wie round_amount, aber auf 3 Nachkommastellen - fuer Liter (ml-genau: 1,125 l)."""
    if value is None:
        return None
    r = round(value, 3)
    return int(r) if r == int(r) else r



# --------------------------------------------------------------------------- #
#  Einheiten-Umrechnung fuer die Einkaufsliste (Schritt 3)
# --------------------------------------------------------------------------- #
# Schreibweisen -> kanonische Einheit (case-insensitiv, auch Vollwoerter).
UNIT_CANON = {
    "g": "g", "gr": "g", "gramm": "g",
    "ml": "ml", "milliliter": "ml",
    "el": "EL", "essl": "EL", "essl.": "EL", "esslöffel": "EL", "essloeffel": "EL",
    "tl": "TL", "teel": "TL", "teel.": "TL", "teelöffel": "TL", "teeloeffel": "TL",
    "cm": "cm",
    "zehe": "Zehe", "zehen": "Zehe",
    # Stueck/Stück und Co.: damit handgetippte oder aeltere Schreibweisen in der
    # Einkaufsliste als EINE Einheit zusammenfallen (sonst gilt Stueck != Stück).
    "stück": "Stück", "stueck": "Stück", "stk": "Stück", "stk.": "Stück", "stck": "Stück",
    "kg": "kg", "kilogramm": "kg",
    "l": "l", "liter": "l",
    "prise": "Prise", "prisen": "Prise",
    "bund": "Bund",
    "stange": "Stange", "stangen": "Stange",
    "scheibe": "Scheibe", "scheiben": "Scheibe",
    "dose": "Dose", "dosen": "Dose",
    "blatt": "Blatt", "blätter": "Blatt", "blaetter": "Blatt",
    "kopf": "Kopf", "köpfe": "Kopf", "koepfe": "Kopf",
    "zweig": "Zweig", "zweige": "Zweig",
    "handvoll": "Handvoll",
    "tasse": "Tasse", "tassen": "Tasse",
    "päckchen": "Päckchen", "paeckchen": "Päckchen",
}
# Umrechenbare Einheiten -> Aequivalent in g/ml. Festgelegte Faktoren:
# 1 EL = 15 g/ml, 1 TL = 5 g/ml = 1 cm.
CONVERTIBLE = {"g": 1.0, "ml": 1.0, "l": 1000.0, "EL": 15.0, "TL": 5.0, "cm": 5.0}


def canon_unit(unit: Optional[str]) -> str:
    """Einheit normalisieren: trimmen, casefold, bekannte Schreibweisen vereinheitlichen."""
    s = " ".join((unit or "").split()).casefold()
    return UNIT_CANON.get(s, s)
