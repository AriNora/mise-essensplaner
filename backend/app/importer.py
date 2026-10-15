"""Rezept-Import.

Zwei Quellen, ein gemeinsames Ziel: ein Rezept-Entwurf, der im Editor zur
Kontrolle vorausgefuellt wird (es wird NICHTS automatisch gespeichert).

  1. Webseite  -> liest schema.org/Recipe aus dem JSON-LD im Quelltext
                  (derselbe Industriestandard, den auch Bring! nutzt); fehlt
                  das, die Rezeptkarte des Plugins "WP Recipe Maker"
  2. Text      -> zerlegt eingefuegte Zutaten-Zeilen

Der schwierige Teil ist nicht das Beschaffen, sondern das Zerlegen der
Zutaten-Zeilen ("2 EL Olivenoel" -> Menge/Einheit/Zutat). Das uebernimmt
`parse_ingredient_line` mit einer Heuristik; der Rest wird im Editor korrigiert.
"""
import ipaddress
import json
import re
import socket
from typing import Optional
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .units import UNIT_CANON

# Bekannte Einheiten: gemeinsame Tabelle aus units.py. "gr" bleibt draussen, weil es
# in Rezepttexten meist "gross" bedeutet ("1 gr. Zwiebel").
UNITS = {k: v for k, v in UNIT_CANON.items() if k != "gr"}

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
    m = re.match(r"^(\d+)\s*([½¼¾⅓⅔⅛])$", s)             # gemischt mit Unicode-Bruch: 5½
    if m:
        return round(int(m.group(1)) + UNICODE_FRACTIONS[m.group(2)], 2)
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

    # Vorbereitung steht meist nach einem Komma ("1 Zwiebel, fein gewürfelt")
    preparation = None
    # Ein Komma zwischen Ziffern ist ein Dezimalkomma ("1,5 l") und trennt nichts.
    parts = re.split(r"(?<!\d),|,(?!\d)", line, maxsplit=1)
    if len(parts) == 2:
        line = parts[0].strip()
        preparation = parts[1].strip() or None

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


# --------------------------------------------------------------------------- #
#  WP Recipe Maker (Seiten ohne JSON-LD, z. B. Druckansichten)
# --------------------------------------------------------------------------- #
# Viele Food-Blogs nutzen das WordPress-Plugin "WP Recipe Maker". Seine Druck-
# ansicht (/wprm_print/...) enthaelt kein JSON-LD, aber dieselbe Rezeptkarte mit
# festen CSS-Klassen. Daran koennen wir Zutaten und Schritte direkt ablesen.
# Die Seiten sind oft englisch; der Entwurf wird im Editor ohnehin kontrolliert.
WPRM_UNITS = {
    "tablespoon": "EL", "tablespoons": "EL", "tbsp": "EL", "tbsp.": "EL", "tbs": "EL",
    "teaspoon": "TL", "teaspoons": "TL", "tsp": "TL", "tsp.": "TL",
    "piece": "Stück", "pieces": "Stück", "pc": "Stück", "pcs": "Stück",
    "clove": "Zehe", "cloves": "Zehe",
    "cup": "Tasse", "cups": "Tasse",
    "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg",
    "milliliter": "ml", "milliliters": "ml", "liter": "l", "liters": "l", "litre": "l",
    "pinch": "Prise", "pinches": "Prise", "bunch": "Bund", "sprig": "Zweig", "sprigs": "Zweig",
    "slice": "Scheibe", "slices": "Scheibe", "can": "Dose", "cans": "Dose",
}


def _wprm_text(node) -> str:
    if not node:
        return ""
    text = " ".join(node.get_text(" ", strip=True).split())
    text = re.sub(r"\(\s+", "(", text)                 # "( Tipp" -> "(Tipp" (Tags trennen Woerter)
    return re.sub(r"\s+([.,;:!?)])", r"\1", text)


def recipe_from_wprm(html: str, source: Optional[str] = None) -> Optional[dict]:
    """Liest eine WP-Recipe-Maker-Karte (CSS-Klassen `wprm-recipe-...`).
    None, wenn die Seite keine solche Karte mit Zutaten enthaelt."""
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.wprm-recipe-ingredient")
    if not items:
        return None
    # Nur die erste Rezeptkarte lesen (manche Seiten enthalten mehrere).
    # (Druckansicht und normale Seite haben beide ein Element mit der Klasse "wprm-recipe".)
    card = items[0].find_parent(class_="wprm-recipe") or soup
    items = card.select("li.wprm-recipe-ingredient")

    ingredients = []
    for li in items:
        name = _wprm_text(li.select_one(".wprm-recipe-ingredient-name"))
        if not name:
            continue
        amount_text = _wprm_text(li.select_one(".wprm-recipe-ingredient-amount"))
        unit_text = _wprm_text(li.select_one(".wprm-recipe-ingredient-unit"))
        notes = _wprm_text(li.select_one(".wprm-recipe-ingredient-notes"))
        amount = _amount_to_float(amount_text) if amount_text else None
        if amount_text and amount is None:      # Menge nicht lesbar -> nicht verlieren
            name = f"{amount_text} {unit_text} {name}".replace("  ", " ").strip()
            unit_text = ""
        key = unit_text.lower().strip(".")
        unit = (UNITS.get(key) or WPRM_UNITS.get(key) or unit_text) or None
        if notes.startswith("(") and notes.endswith(")"):
            notes = notes[1:-1].strip()
        ingredients.append({"name": name, "amount": amount, "unit": unit,
                            "preparation": notes or None, "category": None})
    if not ingredients:
        return None

    steps = [_wprm_text(t) for t in card.select("li.wprm-recipe-instruction .wprm-recipe-instruction-text")]
    servings = card.select_one(".wprm-recipe-servings")
    title = _wprm_text(card.select_one(".wprm-recipe-name")) or _wprm_text(soup.find("title"))
    return {
        "name": title or "Importiertes Rezept",
        "servings": _yield_to_servings(_wprm_text(servings)),
        "instructions": "\n".join(t for t in steps if t) or None,
        "source": source,
        "ingredients": ingredients,
    }


def recipe_from_html(html: str, source: Optional[str] = None) -> Optional[dict]:
    """Erst JSON-LD (schema.org/Recipe), sonst die WP-Recipe-Maker-Karte."""
    return recipe_from_jsonld(html, source) or recipe_from_wprm(html, source)


class UrlNotAllowed(Exception):
    """Die Adresse zeigt nicht auf eine oeffentliche Webseite (Schutz vor SSRF)."""


class PageTooLarge(Exception):
    """Die Antwort ist groesser als MAX_PAGE_BYTES."""


MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
ALLOWED_PORTS = {80, 443}


def _check_public_url(url: str) -> None:
    """Wirft UrlNotAllowed, wenn die Adresse nicht auf eine oeffentliche Webseite zeigt.

    Erlaubt sind nur http/https auf den Standard-Ports und nur Rechner mit
    oeffentlicher IP-Adresse. So kann der Import nicht genutzt werden, um Dienste
    im eigenen Rechner oder Netzwerk abzufragen (z. B. http://localhost:8000/...,
    Router-Oberflaechen, Cloud-Metadaten unter 169.254.169.254).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UrlNotAllowed("scheme")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise UrlNotAllowed("port")
    if port not in ALLOWED_PORTS:
        raise UrlNotAllowed("port")
    try:
        infos = socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise requests.ConnectionError("DNS")   # unbekannter Rechnername -> normaler Ladefehler
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UrlNotAllowed("address")


def _download(url: str) -> str:
    """Laedt eine Seite; Weiterleitungen werden einzeln geprueft, die Groesse begrenzt."""
    headers = {"User-Agent": "Mozilla/5.0 (Mise Essensplaner – Rezept-Import)"}
    for _ in range(MAX_REDIRECTS + 1):
        _check_public_url(url)
        with requests.get(url, headers=headers, timeout=10,
                          allow_redirects=False, stream=True) as resp:
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    raise requests.ConnectionError("redirect")
                url = urljoin(url, location)
                continue
            resp.raise_for_status()
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_PAGE_BYTES:
                raise PageTooLarge()
            body = bytearray()
            for chunk in resp.iter_content(64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_PAGE_BYTES:
                    raise PageTooLarge()
            return bytes(body).decode(resp.encoding or resp.apparent_encoding or "utf-8",
                                      errors="replace")
    raise requests.TooManyRedirects()


def fetch_recipe_from_url(url: str) -> dict:
    """Laedt die Seite und zieht das Rezept aus dem JSON-LD. Wirft ValueError,
    wenn kein strukturiertes Rezept gefunden wird, UrlNotAllowed bei nicht
    oeffentlichen Adressen und PageTooLarge bei uebergrossen Seiten."""
    draft = recipe_from_html(_download(url), source=url)
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
