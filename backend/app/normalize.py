"""Normalisierung von Zutatennamen.

Gemeinsame Grundlage fuer die Neuanlage (crud.get_or_create_ingredient) und das
Bereinigungsskript (dedupe_ingredients.py): beide erkennen damit dieselben
Schreibweisen als "dieselbe Zutat".
"""
import re


def ingredient_key(name: str) -> str:
    """Vergleichsschluessel: dieselbe Zutat ergibt denselben Schluessel.

    - casefold: Gross-/Kleinschreibung egal, auch bei Umlauten und ss/ß
    - Leerraum entfernt:  'Cayenne Pfeffer'  == 'Cayennepfeffer'
    - Plural-Endung -n:   'Zwiebeln' == 'Zwiebel', 'Tomaten' == 'Tomate'

    Bewusst einfach gehalten (keine Wortstamm-Bibliothek). Unregelmaessige
    Plurale (Nuss/Nuesse) und verschiedene Wortformen mit anderer Bedeutung
    (Knoblauch / Knoblauchzehe) werden NICHT zusammengefasst.
    """
    key = re.sub(r"\s+", "", name or "").casefold()
    if len(key) > 3 and key.endswith("n"):
        key = key[:-1]
    return key
