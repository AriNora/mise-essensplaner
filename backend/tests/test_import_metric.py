"""Metrische Klammer-Angaben im sichtbaren HTML (Pick Up Limes) beim Import.

Der HTML-Aufbau ist der echten Seite nachgebaut (Stand: Oktober 2026, per Browser geprueft):
Das JSON-LD kennt nur US-Einheiten, das HTML hat hinter der US-Angabe ein Span mit "(850g)".
"""
import json

from app.importer import recipe_from_html


def _box(amount, metric, name):
    m = f'<span class="ingredient-amount-metric-text-1" value="1" type="solid">{metric}</span>' if metric else \
        '<span class="ingredient-amount-metric-text-1" value="1" type="solid"></span>'
    return (f'<li><div class="ingredient-container"><span class="ingredient-amount-text-1">{amount}</span>'
            f'{m}<div class="ingredient"><span class="ingredient-name-text">{name}</span>'
            f'<span>, quartered</span></div></div></li>')


def _page(ld_lines, boxes):
    ld = {"@type": "Recipe", "name": "Potato Pesto Salad", "recipeIngredient": ld_lines,
          "recipeInstructions": "Backen."}
    return ('<html><head><script type="application/ld+json">' + json.dumps(ld) + "</script></head>"
            "<body><ul>" + "".join(boxes) + "</ul></body></html>")


LD = ["29.982 oz baby potatoes", "1&#190; cup cooked butter beans", "1 Tbsp olive oil",
      "&#189; tsp salt", "2 garlic clove", "&#8531; cup extra-virgin olive oil"]
BOXES = [
    _box("30 oz", "(850g)", "baby potatoes"),
    _box("1¾ cups", "(300g)", "cooked butter beans"),
    _box("1 Tbsp", "(15ml)", "olive oil"),
    _box("½ tsp", "", "salt"),
    _box("2", "", "garlic cloves"),
    _box("⅓ cup", "(80ml)", "extra-virgin olive oil"),
]


def _by_name(recipe):
    return {i["name"]: i for i in recipe["ingredients"]}


def test_metrische_klammer_ersetzt_us_angabe():
    r = _by_name(recipe_from_html(_page(LD, BOXES)))
    assert (r["baby potatoes"]["amount"], r["baby potatoes"]["unit"]) == (850, "g")
    assert (r["cooked butter beans"]["amount"], r["cooked butter beans"]["unit"]) == (300, "g")
    assert (r["olive oil"]["amount"], r["olive oil"]["unit"]) == (15, "ml")
    assert (r["extra-virgin olive oil"]["amount"], r["extra-virgin olive oil"]["unit"]) == (80, "ml")


def test_zeilen_ohne_klammer_bleiben_unveraendert():
    r = _by_name(recipe_from_html(_page(LD, BOXES)))
    assert (r["salt"]["amount"], r["salt"]["unit"]) == (0.5, "TL")
    assert (r["garlic clove"]["amount"], r["garlic clove"]["unit"]) == (2, None)


def test_andere_anzahl_im_html_aendert_nichts():
    r = _by_name(recipe_from_html(_page(LD, BOXES[:-1])))
    assert r["cooked butter beans"]["unit"] == "Tasse"       # unveraendert, nur die Standard-Umrechnung
    assert r["baby potatoes"]["unit"] == "g" and r["baby potatoes"]["amount"] == 850   # oz -> g (850 aus 29,982 oz)


def test_namen_passen_nicht_zusammen_aendert_nichts():
    boxes = list(BOXES)
    boxes[1] = _box("1¾ cups", "(300g)", "completely different")
    r = _by_name(recipe_from_html(_page(LD, boxes)))
    assert r["cooked butter beans"]["unit"] == "Tasse"


def test_seite_ohne_metrik_wie_bisher():
    r = _by_name(recipe_from_html(_page(LD, [_box("x", "", "n")] * 6)))
    assert r["cooked butter beans"]["unit"] == "Tasse"


def test_dezimalpunkt_und_kg():
    ld = ["2.2 lb flour"]
    boxes = [_box("2.2 lb", "(1.5kg)", "flour")]
    r = recipe_from_html(_page(ld, boxes))["ingredients"][0]
    assert (r["amount"], r["unit"]) == (1.5, "kg")
