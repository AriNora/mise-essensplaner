"""Rezept-Import.

Zwei Quellen, ein gemeinsames Ziel: ein Rezept-Entwurf, der im Editor zur
Kontrolle vorausgefuellt wird (es wird NICHTS automatisch gespeichert).

  1. Webseite  -> liest schema.org/Recipe aus dem JSON-LD im Quelltext
                  (derselbe Industriestandard, den auch Bring! nutzt)
  2. Text      -> zerlegt eingefuegte Zutaten-Zeilen

Der schwierige Teil ist nicht das Beschaffen, sondern das Zerlegen der
Zutaten-Zeilen ("2 EL Olivenoel" -> Menge/Einheit/Zutat). Das uebernimmt
`parse_ingredient_line` mit einer Heuristik; der Rest wird im Editor korrigiert.
"""
import json
import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

# Bekannte Einheiten (klein, ohne Punkt) -> einheitliche Anzeigeform
UNITS = {
    "g": "g", "gramm": "g", "kg": "kg",
    "ml": "ml", "l": "l", "liter": "l",
    "el": "EL", "esslöffel": "EL", "essloeffel": "EL",
    "tl": "TL", "teelöffel": "TL", "teeloeffel": "TL",
    "stück": "Stück", "stueck": "Stück", "stk": "Stück",
    "prise": "Prise", "prisen": "Prise",
    "bund": "Bund", "dose": "Dose", "dosen": "Dose",
    "zehe": "Zehe", "zehen": "Zehe",
    "scheibe": "Scheibe", "scheiben": "Scheibe",
    "päckchen": "Päckchen", "paeckchen": "Päckchen",
    "tasse": "Tasse", "tassen": "Tasse", "cm": "cm",
}

UNICODE_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}


def _amount_to_float(s: str) -> Optional[float]:
    """Wandelt die erkannte Mengen-Zeichenkette in eine Zahl.
    Unterstuetzt: Bereich (2-3 -> 2), gemischt (1 1/2 -> 1.5), Bruch (1/2),
    Unicode-Brueche (½) und Dezimalzahlen mit Komma oder Punkt."""
    s = s.strip()
    m = re.match(r"^(\d+)\s*[-–]\s*\d+$", s)          # Bereich -> unterer Wert
    if m:
        return float(m.group(1))
    m = re.match(r"^(\d+)\s+(\d+)/(\d+)$", s)          # gemischt 1 1/2
    if m:
        w, a, b = map(int, m.groups())
        return round(w + a / b, 2) if b else float(w)
    m = re.match(r"^(\d+)/(\d+)$", s)                  # Bruch 1/2
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return round(a / b, 2) if b else None
    if s in UNICODE_FRACTIONS:
        return round(UNICODE_FRACTIONS[s], 2)
    try:
        return round(float(s.replace(",", ".")), 2)
    except ValueError:
        return None


def parse_ingredient_line(line: str) -> Optional[dict]:
    """Zerlegt eine Zutaten-Zeile in {name, amount, unit, preparation, category}."""
    line = " ".join((line or "").strip().split())
    line = re.sub(r"^[-•*\u2022\u2013]\s*", "", line)  # Aufzaehlungszeichen weg
    if not line:
        return None

    # Vorbereitung steht meist nach einem Komma ("1 Zwiebel, fein gewuerfelt")
    preparation = None
    if "," in line:
        head, tail = line.split(",", 1)
        line = head.strip()
        preparation = tail.strip() or None

    amount = None
    unit = None
    rest = line

    m = re.match(
        r"^\s*(\d+\s*[-–]\s*\d+|\d+\s+\d+/\d+|\d+/\d+|[½¼¾⅓⅔⅛]|\d+(?:[.,]\d+)?)\s*(.*)$",
        line,
    )
    if m:
        amount = _amount_to_float(m.group(1))
        rest = m.group(2)

    # Falls direkt nach der Menge eine bekannte Einheit folgt
    parts = rest.split(" ", 1)
    if parts and parts[0].lower().strip(".") in UNITS:
        unit = UNITS[parts[0].lower().strip(".")]
        rest = parts[1] if len(parts) > 1 else ""

    name = rest.strip() or line
    if not name:
        return None
    return {"name": name, "amount": amount, "unit": unit,
            "preparation": preparation, "category": None}


# --------------------------------------------------------------------------- #
#  JSON-LD (schema.org/Recipe) aus einer Webseite
# --------------------------------------------------------------------------- #
def _walk_for_recipe(node):
    """Sucht rekursiv den Knoten mit @type == "Recipe" (auch in @graph/Listen)."""
    if isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.lower() == "recipe" for x in types):
            return node
        for v in node.values():
            found = _walk_for_recipe(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_for_recipe(item)
            if found:
                return found
    return None


def _instructions_to_text(instr) -> Optional[str]:
    if not instr:
        return None
    if isinstance(instr, str):
        return instr.strip() or None
    steps = []
    if isinstance(instr, list):
        for s in instr:
            if isinstance(s, str):
                steps.append(s.strip())
            elif isinstance(s, dict):
                txt = s.get("text") or s.get("name")
                if txt:
                    steps.append(str(txt).strip())
    return "\n".join(p for p in steps if p) or None


def _yield_to_servings(y) -> int:
    if isinstance(y, list):
        y = y[0] if y else None
    if y is None:
        return 2
    m = re.search(r"\d+", str(y))
    return int(m.group()) if m else 2


def recipe_from_jsonld(html: str, source: Optional[str] = None) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    recipe = None
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:  # Notfalls das erste JSON-Objekt herausschneiden
                data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            except Exception:
                continue
        recipe = _walk_for_recipe(data)
        if recipe:
            break
    if not recipe:
        return None

    raw_ings = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
    if isinstance(raw_ings, str):
        raw_ings = [raw_ings]
    ingredients = []
    for line in raw_ings:
        parsed = parse_ingredient_line(str(line))
        if parsed:
            ingredients.append(parsed)

    name = recipe.get("name") or "Importiertes Rezept"
    if isinstance(name, list):
        name = name[0] if name else "Importiertes Rezept"

    return {
        "name": str(name).strip() or "Importiertes Rezept",
        "servings": _yield_to_servings(recipe.get("recipeYield")),
        "instructions": _instructions_to_text(recipe.get("recipeInstructions")),
        "source": source,
        "ingredients": ingredients,
    }


def fetch_recipe_from_url(url: str) -> dict:
    """Laedt die Seite und zieht das Rezept aus dem JSON-LD. Wirft ValueError,
    wenn kein strukturiertes Rezept gefunden wird."""
    headers = {"User-Agent": "Mozilla/5.0 (Mise Essensplaner – Rezept-Import)"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    draft = recipe_from_jsonld(resp.text, source=url)
    if draft is None:
        raise ValueError("no-recipe")
    return draft


# --------------------------------------------------------------------------- #
#  Freier Text
# --------------------------------------------------------------------------- #
def recipe_from_text(text: str, name: Optional[str] = None) -> dict:
    """Jede nicht-leere Zeile wird als eine Zutat interpretiert."""
    ingredients = []
    for ln in (text or "").splitlines():
        if not ln.strip():
            continue
        parsed = parse_ingredient_line(ln)
        if parsed and parsed["name"]:
            ingredients.append(parsed)
    return {
        "name": (name or "").strip() or "Eingefügtes Rezept",
        "servings": 2,
        "instructions": None,
        "source": None,
        "ingredients": ingredients,
    }
