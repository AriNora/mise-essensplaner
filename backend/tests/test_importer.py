"""Tests fuer das Zerlegen von Zutaten-Zeilen beim Rezept-Import.

Aufruf aus dem Ordner backend/:   python -m pytest
"""
import pytest

from app.importer import parse_ingredient_line


@pytest.mark.parametrize("zeile, menge, einheit, name", [
    ("200 g Mehl", 200, "g", "Mehl"),
    ("2 EL Olivenöl", 2, "EL", "Olivenöl"),
    ("½ TL Salz", 0.5, "TL", "Salz"),
    ("1,5 l Brühe", 1.5, "l", "Brühe"),
    ("1 Stange Sellerie", 1, "Stange", "Sellerie"),
    ("3 Essl. Öl", 3, "EL", "Öl"),
    ("1 Päckchen Hefe", 1, "Päckchen", "Hefe"),
    ("2 Paeckchen Vanillezucker", 2, "Päckchen", "Vanillezucker"),
    ("1 Kopf Blumenkohl", 1, "Kopf", "Blumenkohl"),
])
def test_menge_einheit_und_name(zeile, menge, einheit, name):
    r = parse_ingredient_line(zeile)
    assert (r["amount"], r["unit"], r["name"]) == (menge, einheit, name)


def test_gr_wird_nicht_als_gramm_gelesen():
    # "gr." steht in Rezepten meist fuer "gross"
    r = parse_ingredient_line("1 gr. Zwiebel")
    assert r["unit"] is None
    assert "Zwiebel" in r["name"]


def test_zubereitung_nach_dem_komma():
    r = parse_ingredient_line("1 Zwiebel, fein gehackt")
    assert r["name"] == "Zwiebel" and r["preparation"] == "fein gehackt"


def test_zeile_ohne_menge():
    r = parse_ingredient_line("Salz nach Geschmack")
    assert r["amount"] is None and r["unit"] is None


def test_leere_zeile():
    assert parse_ingredient_line("   ") is None


def test_dezimalkomma_trennt_keine_zubereitung():
    r = parse_ingredient_line("1,5 l Brühe, heiß")
    assert (r["amount"], r["unit"], r["name"], r["preparation"]) == (1.5, "l", "Brühe", "heiß")


# --- Zeilen aus englischen JSON-LD-Seiten (z. B. WP Recipe Maker, Pick Up Limes) ---
@pytest.mark.parametrize("zeile, menge, einheit, name, zubereitung", [
    ("1 piece Cauliflower ((cut and cleaned))", 1, "Stück", "Cauliflower", "cut and cleaned"),
    ("250 grams Red lentil ((rinsed &amp; cleaned))", 250, "g", "Red lentil", "rinsed & cleaned"),
    ("1 Tbsp olive oil", 1, "EL", "olive oil", None),
    ("2 tsp garlic powder", 2, "TL", "garlic powder", None),
    ("1&#190; cup cooked butter beans", 1.75, "Tasse", "cooked butter beans", None),
    ("1 ¾ cup cooked butter beans", 1.75, "Tasse", "cooked butter beans", None),
    ("10 cloves garlic ((cut, peeled))", 10, "Zehe", "garlic", "cut, peeled"),
])
def test_englische_zeilen(zeile, menge, einheit, name, zubereitung):
    r = parse_ingredient_line(zeile)
    assert (r["amount"], r["unit"], r["name"], r["preparation"]) == (menge, einheit, name, zubereitung)


def test_englische_einheit_ohne_menge_wird_nicht_geraten():
    r = parse_ingredient_line("Piece of ginger")
    assert r["unit"] is None and r["name"] == "Piece of ginger"


def test_einfache_klammer_bleibt_im_namen():
    r = parse_ingredient_line("Tomaten (Dose)")
    assert r["name"] == "Tomaten (Dose)" and r["preparation"] is None


def _steps(instr):
    from app.importer import _instructions_to_text
    return _instructions_to_text(instr)


def test_schritte_als_verschachtelte_liste():
    assert _steps([["Heizen.", "Backen &amp; warten."]]) == "Heizen.\nBacken & warten."


def test_schritte_als_howto_objekte_und_abschnitte():
    instr = [
        {"@type": "HowToStep", "text": "Erst."},
        {"@type": "HowToSection", "name": "Teig", "itemListElement": [
            {"@type": "HowToStep", "text": "Dann."}, {"@type": "HowToStep", "name": "Zuletzt."}]},
    ]
    assert _steps(instr) == "Erst.\nDann.\nZuletzt."


@pytest.mark.parametrize("instr", [None, "", [], [[]], [{"@type": "HowToStep"}]])
def test_keine_schritte(instr):
    assert _steps(instr) is None


@pytest.mark.parametrize("zeile, menge", [
    ("29.982 oz baby potatoes", 850),     # Beispiel aus Pick Up Limes: genau 850 g
    ("1 oz Walnüsse", 28),
    ("2 ounces pine nuts", 57),
    ("0.1 oz Safran", 3),
])
def test_unzen_werden_in_gramm_umgerechnet(zeile, menge):
    r = parse_ingredient_line(zeile)
    assert (r["amount"], r["unit"]) == (menge, "g")


def test_unze_ohne_menge_bleibt_im_namen():
    r = parse_ingredient_line("oz Kartoffeln")
    assert r["unit"] is None and "oz" in r["name"]
