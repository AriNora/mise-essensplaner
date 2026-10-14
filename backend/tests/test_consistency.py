"""Konsistenz: Listen, die in Backend, Frontend und Seed getrennt stehen, muessen gleich sein.

Schlaegt ein Test hier fehl, wurde eine Liste an einer Stelle geaendert und an
einer anderen vergessen.
"""
import re
from pathlib import Path

import pytest

from app import schemas
from app.importer import UNITS
from app.seed import RECIPES
from app.shopping import CATEGORY_ORDER
from app.units import CONVERTIBLE, UNIT_CANON, canon_unit

APP_JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "app.js"


def js_list(name):
    """Liest `const NAME = [ "a", "b", ... ];` aus app.js."""
    if not APP_JS.exists():
        pytest.skip("frontend/js/app.js nicht gefunden")
    m = re.search(r"const\s+" + name + r"\s*=\s*\[(.*?)\]\s*;", APP_JS.read_text(encoding="utf-8"), re.S)
    assert m, f"{name} nicht in app.js gefunden"
    return re.findall(r'"([^"]*)"', m.group(1))


def test_warengruppen_frontend_gleich_backend():
    assert js_list("CATEGORIES") == CATEGORY_ORDER


def test_tag_arten_frontend_gleich_backend():
    assert js_list("KIND_ORDER") == list(schemas.TAG_KINDS)


def test_wochentage_frontend_gleich_backend():
    assert js_list("DAYS") == list(schemas.WEEKDAYS)


def test_seed_nutzt_nur_bekannte_warengruppen():
    benutzt = {z[4] for r in RECIPES for z in r["ingredients"]}
    assert benutzt <= set(CATEGORY_ORDER), benutzt - set(CATEGORY_ORDER)


def test_kanonische_einheiten_sind_stabil():
    # Wendet man canon_unit auf eine kanonische Einheit an, aendert sie sich nicht.
    for kanon in set(UNIT_CANON.values()):
        assert canon_unit(kanon) == kanon


def test_umrechenbare_einheiten_sind_kanonisch():
    for einheit in CONVERTIBLE:
        assert canon_unit(einheit) == einheit


def test_import_einheiten_stammen_aus_der_gemeinsamen_tabelle():
    assert set(UNITS.values()) <= set(UNIT_CANON.values())
