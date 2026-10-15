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
import html as htmllib
import ipaddress
import json
import logging
import re
import socket
from typing import Optional
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .units import UNIT_CANON

# Meldungen erscheinen in der Konsole des Servers (Logger von uvicorn).
log = logging.getLogger("uvicorn.error")

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


# US-Gewichte werden beim Import in Gramm umgerechnet (Mise rechnet metrisch).
IMPERIAL_TO_METRIC = {
    "oz": ("g", 28.349523125), "ounce": ("g", 28.349523125), "ounces": ("g", 28.349523125),
}


def _imperial_to_metric(amount: Optional[float], key: str):
    """(Menge, Einheit) in Gramm, wenn `key` eine US-Gewichtseinheit ist, sonst None.
    Auf ganze Gramm gerundet: 29,982 oz -> 850 g."""
    if amount is None or key not in IMPERIAL_TO_METRIC:
        return None
    unit, factor = IMPERIAL_TO_METRIC[key]
    return float(max(1, round(amount * factor))), unit


def parse_ingredient_line(line: str) -> Optional[dict]:
    """Zerlegt eine Zutaten-Zeile in {name, amount, unit, preparation, category}."""
    line = " ".join(htmllib.unescape(line or "").strip().split())   # &amp; &#190; -> & ¾
    line = re.sub(r"^[-•*\u2022\u2013]\s*", "", line)  # Aufzaehlungszeichen weg
    if not line:
        return None

    # Vorbereitung steht meist nach einem Komma ("1 Zwiebel, fein gewürfelt") ...
    preparation = None
    # ... oder in doppelten Klammern am Ende ("1 Stueck Blumenkohl ((geputzt))", so schreibt
    # WP Recipe Maker seine Hinweise ins JSON-LD).
    m = re.match(r"^(.*?)\s*\(\((.*)\)\)$", line)
    if m and m.group(1):
        line, preparation = m.group(1), (m.group(2).strip() or None)
    # Ein Komma zwischen Ziffern ist ein Dezimalkomma ("1,5 l") und trennt nichts.
    parts = re.split(r"(?<!\d),|,(?!\d)", line, maxsplit=1)
    if len(parts) == 2:
        line = parts[0].strip()
        preparation = preparation or parts[1].strip() or None

    amount = None
    unit = None
    rest = line

    m = re.match(
        r"^\s*(\d+\s*[-–]\s*\d+|\d+\s+\d+/\d+|\d+/\d+|[½¼¾⅓⅔⅛]|\d+\s*[½¼¾⅓⅔⅛]|\d+(?:[.,]\d+)?)\s*(.*)$",
        line,
    )
    if m:
        amount = _amount_to_float(m.group(1))
        rest = m.group(2)

    # Falls direkt nach der Menge eine bekannte Einheit folgt
    parts = rest.split(" ", 1)
    key = parts[0].lower().strip(".") if parts else ""
    metric = _imperial_to_metric(amount, key)
    if metric:
        amount, unit = metric
        rest = parts[1] if len(parts) > 1 else ""
    elif key in UNITS or (amount is not None and key in ENGLISH_UNITS):
        unit = UNITS.get(key) or ENGLISH_UNITS[key]
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


def _collect_steps(node, out: list) -> None:
    """Sammelt Schritte aus Text, Listen (auch verschachtelt) und HowTo-Objekten."""
    if isinstance(node, str):
        text = " ".join(htmllib.unescape(node).split())
        if text:
            out.append(text)
    elif isinstance(node, list):
        for item in node:
            _collect_steps(item, out)
    elif isinstance(node, dict):
        if node.get("itemListElement"):                    # HowToSection: Unterschritte
            _collect_steps(node["itemListElement"], out)
        else:
            _collect_steps(node.get("text") or node.get("name"), out)


def _instructions_to_text(instr) -> Optional[str]:
    steps: list = []
    _collect_steps(instr, steps)
    return "\n".join(steps) or None


def _yield_to_servings(y) -> int:
    if isinstance(y, list):
        y = y[0] if y else None
    if y is None:
        return 2
    m = re.search(r"\d+", str(y))
    return int(m.group()) if m else 2


_METRIC_RE = re.compile(r"^\(\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\s*\)$", re.IGNORECASE)


def _page_metrics(soup) -> list:
    """Metrische Klammer-Angaben aus dem sichtbaren HTML (Pick Up Limes): je Zutat
    `(Menge, Einheit, Namenstext)` oder `(None, None, Namenstext)`, in Seitenreihenfolge.
    Dort steht hinter der US-Angabe z. B. `<span class="ingredient-amount-metric-text-1">(850g)</span>`;
    im JSON-LD derselben Seite fehlt sie."""
    result = []
    for box in soup.select(".ingredient-container"):
        span = box.select_one('[class^="ingredient-amount-metric-text"]')
        name = box.select_one(".ingredient-name-text")
        m = _METRIC_RE.match(span.get_text(strip=True)) if span else None
        amount = _amount_to_float(m.group(1)) if m else None
        unit = m.group(2).lower() if m else None
        result.append((amount, unit, name.get_text(" ", strip=True).lower() if name else ""))
    return result


def _apply_page_metrics(soup, rows: list) -> None:
    """Ersetzt US-Mengen (cup, oz, EL/TL ...) durch die metrische Angabe der Seite.

    Das JSON-LD kennt sie nicht, das HTML schon - beide Listen muessen aber dieselbe Reihenfolge
    haben. Sicherung: nur bei gleicher Anzahl, und jede Zeile muss zum Namen im HTML passen
    (Wortanfang), sonst bleibt alles unveraendert."""
    metrics = _page_metrics(soup)
    if not metrics or len(metrics) != len(rows) or not any(m[0] for m in metrics):
        return
    for (amount, unit, page_name), parsed in zip(metrics, rows):
        if amount is None:
            continue
        if parsed is None or parsed["amount"] is None:
            return
        low = parsed["name"].lower()
        if not any(len(w) >= 3 and w[:4] in low for w in page_name.split()):
            return
    for (amount, unit, _), parsed in zip(metrics, rows):
        if amount is not None:
            parsed["amount"], parsed["unit"] = amount, unit


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
    rows = []                                   # je Zeile: Eintrag oder None (nicht lesbar)
    for line in raw_ings:
        parsed = parse_ingredient_line(str(line))
        rows.append(parsed)
        if parsed:
            ingredients.append(parsed)
    _apply_page_metrics(soup, rows)

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
ENGLISH_UNITS = {
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
        metric = _imperial_to_metric(amount, key)
        if metric:
            amount, unit = metric
        else:
            unit = (UNITS.get(key) or ENGLISH_UNITS.get(key) or unit_text) or None
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


class NoRecipeFound(ValueError):
    """Die Seite wurde geladen, enthaelt aber kein lesbares Rezept. Der Text beschreibt,
    was auf der Seite gefunden wurde (nur zur Fehlersuche)."""


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


# HTTP-Kopfzeilen duerfen nur Latin-1 enthalten: KEIN Gedankenstrich/Umlaut im User-Agent!
USER_AGENT = "Mozilla/5.0 (Mise Essensplaner - Rezept-Import)"


def _download(url: str):
    """Laedt eine Seite; Weiterleitungen werden einzeln geprueft, die Groesse begrenzt.
    Liefert (Text, Abruf-Info) - die Info dient nur der Fehlersuche."""
    headers = {"User-Agent": USER_AGENT}
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
            info = "HTTP %s, %s, Encoding %s, %d Bytes, Server %s" % (
                resp.status_code, resp.headers.get("Content-Type"),
                resp.headers.get("Content-Encoding"), len(body), resp.headers.get("Server"))
            log.info("Import-Abruf %s -> %s", url, info)
            text = bytes(body).decode(resp.encoding or resp.apparent_encoding or "utf-8",
                                      errors="replace")
            return text, info
    raise requests.TooManyRedirects()


def fetch_recipe_from_url(url: str) -> dict:
    """Laedt die Seite und zieht das Rezept aus dem JSON-LD. Wirft ValueError,
    wenn kein strukturiertes Rezept gefunden wird, UrlNotAllowed bei nicht
    oeffentlichen Adressen und PageTooLarge bei uebergrossen Seiten."""
    html, info = _download(url)
    draft = recipe_from_html(html, source=url)
    if draft is None:
        soup = BeautifulSoup(html, "html.parser")
        detail = "%s | JSON-LD-Bloecke: %d, WPRM-Zutaten: %d, Titel: %r, Anfang: %r" % (
            info,
            len(soup.find_all("script", attrs={"type": "application/ld+json"})),
            len(soup.select("li.wprm-recipe-ingredient")),
            soup.title.get_text(strip=True)[:80] if soup.title else None,
            " ".join(html[:200].split()),
        )
        log.warning("Import: kein Rezept in %s gefunden (%s)", url, detail)
        raise NoRecipeFound(detail)
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
