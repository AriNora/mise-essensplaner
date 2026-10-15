"""Tests fuer den Import aus WP-Recipe-Maker-Seiten (z. B. Druckansichten ohne JSON-LD).

Das Beispiel-HTML ist dem beobachteten Aufbau einer solchen Seite nachempfunden
(Klassen `wprm-recipe-...`); die Texte sind erfunden."""
import pytest

from app import importer
from app.importer import _amount_to_float, recipe_from_html, recipe_from_wprm

PRINT_PAGE = """<!DOCTYPE html><html><head><title>Rote Linsen - Beispielblog</title>
<meta name="robots" content="noindex"></head>
<body class="wprm-print wprm-print-recipe"><div class="wprm-print-recipe wprm-print-recipe-1">
<div class="wprm-recipe wprm-recipe-template-chic">
  <h2 class="wprm-recipe-name wprm-block-text-normal">Rote Linsen</h2>
  <span class="wprm-recipe-servings wprm-recipe-details">4</span>
  <div class="wprm-recipe-ingredients-container"><div class="wprm-recipe-ingredient-group"><ul class="wprm-recipe-ingredients">
    <li class="wprm-recipe-ingredient"><span class="wprm-checkbox-container"><input type="checkbox" class="wprm-checkbox" aria-label="1 piece Onion"><label class="wprm-checkbox-label"><span class="sr-only">▢ </span></label></span><span class="wprm-recipe-ingredient-amount">1</span> <span class="wprm-recipe-ingredient-unit">piece</span> <span class="wprm-recipe-ingredient-name">Onion</span> <span class="wprm-recipe-ingredient-notes wprm-recipe-ingredient-notes-faded">(finely chopped)</span></li>
    <li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-amount">250</span> <span class="wprm-recipe-ingredient-unit">grams</span> <span class="wprm-recipe-ingredient-name">Red lentils</span></li>
    <li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-amount">10</span> <span class="wprm-recipe-ingredient-unit">cloves</span> <span class="wprm-recipe-ingredient-name">Garlic</span></li>
    <li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-amount">1½</span> <span class="wprm-recipe-ingredient-unit">tablespoon</span> <span class="wprm-recipe-ingredient-name">Mustard oil</span></li>
    <li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-amount">1/2</span> <span class="wprm-recipe-ingredient-unit">teaspoon</span> <span class="wprm-recipe-ingredient-name">Turmeric</span></li>
    <li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-name">Salt to taste</span></li>
  </ul></div></div>
  <div class="wprm-recipe-instructions-container"><ul class="wprm-recipe-instructions">
    <li id="s0" class="wprm-recipe-instruction"><div class="wprm-recipe-instruction-text"><span style="display: block;">Cook the lentils.</span></div></li>
    <li id="s1" class="wprm-recipe-instruction"><div class="wprm-recipe-instruction-text"><span>Fry the onion.</span> <span>Add the spices.</span></div></li>
    <li id="s2" class="wprm-recipe-instruction"><div class="wprm-recipe-instruction-text"> </div></li>
  </ul></div>
</div></div></body></html>"""


def test_druckseite_wird_gelesen():
    r = recipe_from_wprm(PRINT_PAGE, source="https://blog.example/wprm_print/linsen")
    assert r["name"] == "Rote Linsen"
    assert r["servings"] == 4
    assert r["source"] == "https://blog.example/wprm_print/linsen"
    assert r["instructions"] == "Cook the lentils.\nFry the onion. Add the spices."


def test_zutaten_mit_menge_einheit_und_zubereitung():
    ings = {i["name"]: i for i in recipe_from_wprm(PRINT_PAGE)["ingredients"]}
    assert len(ings) == 6
    assert (ings["Onion"]["amount"], ings["Onion"]["unit"], ings["Onion"]["preparation"]) == (1, "Stück", "finely chopped")
    assert (ings["Red lentils"]["amount"], ings["Red lentils"]["unit"]) == (250, "g")
    assert (ings["Garlic"]["amount"], ings["Garlic"]["unit"]) == (10, "Zehe")
    assert (ings["Mustard oil"]["amount"], ings["Mustard oil"]["unit"]) == (1.5, "EL")
    assert (ings["Turmeric"]["amount"], ings["Turmeric"]["unit"]) == (0.5, "TL")
    assert ings["Salt to taste"]["amount"] is None and ings["Salt to taste"]["unit"] is None


def test_checkbox_beschriftung_landet_nicht_im_namen():
    names = [i["name"] for i in recipe_from_wprm(PRINT_PAGE)["ingredients"]]
    assert all("▢" not in n and "piece" not in n for n in names)


def test_unbekannte_einheit_und_unlesbare_menge_gehen_nicht_verloren():
    html = """<div class="wprm-recipe"><ul>
      <li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-amount">2</span> <span class="wprm-recipe-ingredient-unit">inch</span> <span class="wprm-recipe-ingredient-name">Ginger</span></li>
      <li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-amount">a few</span> <span class="wprm-recipe-ingredient-unit">sprigs</span> <span class="wprm-recipe-ingredient-name">Mint</span></li>
    </ul></div>"""
    ginger, mint = recipe_from_wprm(html)["ingredients"]
    assert (ginger["amount"], ginger["unit"]) == (2, "inch")
    assert mint["amount"] is None and mint["unit"] is None and mint["name"] == "a few sprigs Mint"


def test_nur_die_erste_rezeptkarte_wird_gelesen():
    card = lambda n: f'<div class="wprm-recipe"><h2 class="wprm-recipe-name">R{n}</h2><ul><li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-name">Z{n}</span></li></ul></div>'
    r = recipe_from_wprm(card(1) + card(2))
    assert r["name"] == "R1" and [i["name"] for i in r["ingredients"]] == ["Z1"]


@pytest.mark.parametrize("html", ["<html></html>", "<ul><li>Linsen</li></ul>",
                                  '<div class="wprm-recipe"><ul></ul></div>'])
def test_seite_ohne_karte_gibt_none(html):
    assert recipe_from_wprm(html) is None


def test_json_ld_hat_vorrang():
    html = ('<script type="application/ld+json">{"@type":"Recipe","name":"Aus JSON-LD",'
            '"recipeIngredient":["200 g Linsen"]}</script>' + PRINT_PAGE)
    assert recipe_from_html(html)["name"] == "Aus JSON-LD"


def test_ohne_json_ld_greift_die_karte():
    assert recipe_from_html(PRINT_PAGE)["name"] == "Rote Linsen"


@pytest.mark.parametrize("text, wert", [("5½", 5.5), ("½", 0.5), ("2", 2), ("1/2", 0.5), ("1 1/2", 1.5)])
def test_mengen_mit_unicode_bruch(text, wert):
    assert _amount_to_float(text) == wert


def test_klammern_und_satzzeichen_ohne_stoerende_leerzeichen():
    html = ('<div class="wprm-recipe"><ul><li class="wprm-recipe-ingredient"><span class="wprm-recipe-ingredient-name">X</span></li></ul>'
            '<ul><li class="wprm-recipe-instruction"><div class="wprm-recipe-instruction-text"><span>Kochen.</span>'
            '<span>(<strong>Tipp:</strong>&nbsp;Salz hilft.)</span></div></li></ul></div>')
    assert recipe_from_wprm(html)["instructions"] == "Kochen. (Tipp: Salz hilft.)"


def test_import_ueber_url_nutzt_die_karte(monkeypatch):
    monkeypatch.setattr(importer, "_download", lambda url: PRINT_PAGE)
    assert importer.fetch_recipe_from_url("https://blog.example/wprm_print/linsen")["name"] == "Rote Linsen"
