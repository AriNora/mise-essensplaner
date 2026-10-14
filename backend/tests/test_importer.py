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
