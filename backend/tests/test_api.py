"""Tests auf API-Ebene: HTTP rein, JSON raus (Statuscodes, Fehlertexte, Zusammenspiel).

Aufruf aus dem Ordner backend/:   python -m pytest
"""
import pytest
import requests

from app import bring, importer


def recipe_payload(name="Linsensuppe", **extra):
    body = {
        "name": name,
        "servings": 2,
        "instructions": "Alles kochen.",
        "ingredients": [
            {"name": "Rote Linsen", "amount": 200, "unit": "g", "category": "Hülsenfrüchte"},
            {"name": "Zwiebel", "amount": 1, "unit": "Stück", "preparation": "würfeln"},
        ],
        "tags": [{"kind": "typ", "name": "Suppe"}],
    }
    body.update(extra)
    return body


def create_recipe(client, **kw):
    r = client.post("/api/recipes", json=recipe_payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
#  Rezepte
# --------------------------------------------------------------------------- #
def test_leere_liste(client):
    r = client.get("/api/recipes")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "items": []}


def test_rezept_anlegen_und_lesen(client):
    created = create_recipe(client)
    assert created["name"] == "Linsensuppe"
    assert [i["name"] for i in created["ingredients"]] == ["Rote Linsen", "Zwiebel"]
    assert created["tags"] == [{"kind": "typ", "name": "Suppe"}]

    got = client.get(f"/api/recipes/{created['id']}")
    assert got.status_code == 200
    assert got.json()["instructions"] == "Alles kochen."


def test_rezept_erscheint_in_liste_mit_zutatenzahl(client):
    create_recipe(client)
    data = client.get("/api/recipes").json()
    assert data["total"] == 1
    assert data["items"][0]["ingredient_count"] == 2


def test_rezept_aendern(client):
    rid = create_recipe(client)["id"]
    body = recipe_payload(name="Rote Linsensuppe", servings=4)
    body["ingredients"] = body["ingredients"][:1]
    r = client.put(f"/api/recipes/{rid}", json=body)
    assert r.status_code == 200
    assert r.json()["name"] == "Rote Linsensuppe"
    assert r.json()["servings"] == 4
    assert len(r.json()["ingredients"]) == 1


def test_rezept_loeschen(client):
    rid = create_recipe(client)["id"]
    assert client.delete(f"/api/recipes/{rid}").status_code == 204
    assert client.get(f"/api/recipes/{rid}").status_code == 404
    assert client.get("/api/recipes").json()["total"] == 0


@pytest.mark.parametrize("method", ["get", "delete"])
def test_unbekanntes_rezept_404(client, method):
    r = getattr(client, method)("/api/recipes/9999")
    assert r.status_code == 404
    assert r.json()["detail"] == "Rezept nicht gefunden"


def test_unbekanntes_rezept_aendern_404(client):
    assert client.put("/api/recipes/9999", json=recipe_payload()).status_code == 404


@pytest.mark.parametrize("bad", [
    {"name": ""},                                           # leerer Name
    {"servings": 0},                                        # keine Portionen
    {"tags": [{"kind": "unsinn", "name": "x"}]},            # unbekannte Tag-Art
    {"ingredients": [{"name": ""}]},                        # Zutat ohne Namen
])
def test_ungueltiges_rezept_wird_abgelehnt(client, bad):
    r = client.post("/api/recipes", json=recipe_payload(**bad))
    assert r.status_code == 422


def test_suche_findet_umlaute_ohne_gross_klein(client):
    create_recipe(client, name="Öl-Kartoffeln")
    create_recipe(client, name="Linsensuppe")
    names = [i["name"] for i in client.get("/api/recipes", params={"search": "öl"}).json()["items"]]
    assert names == ["Öl-Kartoffeln"]


def test_filter_nach_tag(client):
    create_recipe(client, name="Suppe A")
    create_recipe(client, name="Curry B", tags=[{"kind": "kueche", "name": "Indisch"}])
    r = client.get("/api/recipes", params={"kueche": "Indisch"}).json()
    assert [i["name"] for i in r["items"]] == ["Curry B"]


def test_paginierung(client):
    for n in range(5):
        create_recipe(client, name=f"Rezept {n}")
    page = client.get("/api/recipes", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert len(page["items"]) == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_ungueltige_paginierung(client, params):
    assert client.get("/api/recipes", params=params).status_code == 422


# --------------------------------------------------------------------------- #
#  Bild-Upload
# --------------------------------------------------------------------------- #
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_bild_hochladen_und_loeschen(client):
    rid = create_recipe(client)["id"]
    r = client.post(f"/api/recipes/{rid}/image", files={"file": ("x.png", PNG, "image/png")})
    assert r.status_code == 200
    assert r.json()["image"]
    assert len(list(client.upload_dir.iterdir())) == 1

    r = client.delete(f"/api/recipes/{rid}/image")
    assert r.status_code == 200
    assert r.json()["image"] is None
    assert list(client.upload_dir.iterdir()) == []


def test_neues_bild_ersetzt_altes(client):
    rid = create_recipe(client)["id"]
    for _ in range(2):
        client.post(f"/api/recipes/{rid}/image", files={"file": ("x.png", PNG, "image/png")})
    assert len(list(client.upload_dir.iterdir())) == 1


def test_bild_falscher_typ_wird_abgelehnt(client):
    rid = create_recipe(client)["id"]
    r = client.post(f"/api/recipes/{rid}/image", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")})
    assert r.status_code == 400
    assert list(client.upload_dir.iterdir()) == []


def test_bild_zu_gross_wird_abgelehnt(client):
    rid = create_recipe(client)["id"]
    big = b"0" * (5 * 1024 * 1024 + 1)
    r = client.post(f"/api/recipes/{rid}/image", files={"file": ("x.png", big, "image/png")})
    assert r.status_code == 400
    assert "zu gross" in r.json()["detail"]


def test_bild_zu_unbekanntem_rezept_404(client):
    r = client.post("/api/recipes/9999/image", files={"file": ("x.png", PNG, "image/png")})
    assert r.status_code == 404


def test_rezept_loeschen_entfernt_bilddatei(client):
    rid = create_recipe(client)["id"]
    client.post(f"/api/recipes/{rid}/image", files={"file": ("x.png", PNG, "image/png")})
    client.delete(f"/api/recipes/{rid}")
    assert list(client.upload_dir.iterdir()) == []


# --------------------------------------------------------------------------- #
#  Zutaten und Tags
# --------------------------------------------------------------------------- #
def test_zutaten_autocomplete(client):
    create_recipe(client)
    r = client.get("/api/ingredients", params={"search": "lins"})
    assert r.status_code == 200
    assert {"name": "Rote Linsen", "category": "Hülsenfrüchte"} in r.json()


def test_tags_mit_anzahl(client):
    create_recipe(client, name="A")
    create_recipe(client, name="B")
    tags = client.get("/api/tags").json()["tags"]
    assert {"kind": "typ", "name": "Suppe", "count": 2} in tags


# --------------------------------------------------------------------------- #
#  Wochenplan
# --------------------------------------------------------------------------- #
def test_plan_hinzufuegen_aendern_entfernen(client):
    rid = create_recipe(client)["id"]
    r = client.post("/api/plan", json={"recipe_id": rid, "servings": 4, "day": "Mo"})
    assert r.status_code == 201
    entry = r.json()
    assert (entry["recipe_name"], entry["servings"], entry["day"]) == ("Linsensuppe", 4, "Mo")

    r = client.patch(f"/api/plan/{entry['id']}", json={"servings": 6, "day": "Di"})
    assert r.status_code == 200
    assert (r.json()["servings"], r.json()["day"]) == (6, "Di")

    assert client.delete(f"/api/plan/{entry['id']}").status_code == 204
    assert client.get("/api/plan").json() == []


def test_plan_antwort_gehoert_zum_neuen_eintrag(client):
    """POST liefert den frisch angelegten Eintrag zurueck - auch wenn die Liste
    nach Wochentag sortiert ist und der neue Eintrag nicht am Ende steht."""
    a = create_recipe(client, name="Rezept A")["id"]
    b = create_recipe(client, name="Rezept B")["id"]
    client.post("/api/plan", json={"recipe_id": a, "servings": 2, "day": "So"})
    r = client.post("/api/plan", json={"recipe_id": b, "servings": 2, "day": "Mo"})
    assert r.json()["recipe_id"] == b


def test_plan_unbekanntes_rezept_404(client):
    r = client.post("/api/plan", json={"recipe_id": 9999, "servings": 2})
    assert r.status_code == 404


@pytest.mark.parametrize("bad", [{"servings": 0}, {"day": "Montag"}])
def test_plan_ungueltige_eingabe(client, bad):
    rid = create_recipe(client)["id"]
    body = {"recipe_id": rid, "servings": 2}
    body.update(bad)
    assert client.post("/api/plan", json=body).status_code == 422


def test_plan_eintrag_unbekannt_404(client):
    assert client.patch("/api/plan/9999", json={"servings": 2}).status_code == 404
    assert client.delete("/api/plan/9999").status_code == 404


def test_plan_leeren(client):
    rid = create_recipe(client)["id"]
    client.post("/api/plan", json={"recipe_id": rid, "servings": 2})
    assert client.delete("/api/plan").status_code == 204
    assert client.get("/api/plan").json() == []


def test_rezept_loeschen_entfernt_planeintrag(client):
    rid = create_recipe(client)["id"]
    client.post("/api/plan", json={"recipe_id": rid, "servings": 2})
    client.delete(f"/api/recipes/{rid}")
    assert client.get("/api/plan").json() == []


def test_einkaufsliste_und_vorbereitungsplan(client):
    rid = create_recipe(client)["id"]
    client.post("/api/plan", json={"recipe_id": rid, "servings": 4})   # doppelte Menge

    shopping = client.get("/api/plan/shopping-list").json()
    items = {i["name"]: i for g in shopping["groups"] for i in g["items"]}
    assert items["Rote Linsen"]["amount"] == 400
    assert items["Zwiebel"]["amount"] == 2

    prep = client.get("/api/plan/prep-plan").json()
    assert [g["preparation"] for g in prep["groups"]] == ["würfeln"]


def test_leerer_plan_gibt_leere_listen(client):
    assert client.get("/api/plan/shopping-list").json()["groups"] == []
    assert client.get("/api/plan/prep-plan").json()["groups"] == []


# --------------------------------------------------------------------------- #
#  Vorrat
# --------------------------------------------------------------------------- #
def test_vorrat_anlegen_doppelt_loeschen(client):
    r = client.post("/api/pantry", json={"name": "Olivenöl"})
    assert r.status_code == 201
    item = r.json()

    assert client.post("/api/pantry", json={"name": "olivenöl"}).status_code == 409
    assert [i["name"] for i in client.get("/api/pantry").json()] == ["Olivenöl"]

    assert client.delete(f"/api/pantry/{item['id']}").status_code == 204
    assert client.delete(f"/api/pantry/{item['id']}").status_code == 404


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_vorrat_ungueltiger_name(client, name):
    assert client.post("/api/pantry", json={"name": name}).status_code == 422


def test_vorrat_nimmt_zutat_von_einkaufsliste(client):
    rid = create_recipe(client)["id"]
    client.post("/api/plan", json={"recipe_id": rid, "servings": 2})
    client.post("/api/pantry", json={"name": "Zwiebel"})
    shopping = client.get("/api/plan/shopping-list").json()
    names = [i["name"] for g in shopping["groups"] for i in g["items"]]
    assert "Zwiebel" not in names
    assert [s["name"] for s in shopping["in_pantry"]] == ["Zwiebel"]


# --------------------------------------------------------------------------- #
#  Import
# --------------------------------------------------------------------------- #
def test_text_import_liefert_entwurf_und_speichert_nichts(client):
    r = client.post("/api/import/text", json={"text": "200 g Linsen\n2 EL Olivenöl", "name": "Test"})
    assert r.status_code == 200
    draft = r.json()
    assert draft["name"] == "Test"
    assert [(i["name"], i["amount"], i["unit"]) for i in draft["ingredients"]] == [
        ("Linsen", 200, "g"), ("Olivenöl", 2, "EL")]
    assert client.get("/api/recipes").json()["total"] == 0


def test_text_import_leer_wird_abgelehnt(client):
    assert client.post("/api/import/text", json={"text": "  \n "}).status_code == 400


def test_url_import_ohne_http_wird_abgelehnt(client):
    r = client.post("/api/import/url", json={"url": "ftp://example.org/x"})
    assert r.status_code == 400


def test_url_import_erfolg(client, monkeypatch):
    draft = {"name": "Dal", "servings": 2, "instructions": None, "source": "https://x.test",
             "ingredients": [{"name": "Linsen", "amount": 200, "unit": "g",
                              "preparation": None, "category": None}]}
    monkeypatch.setattr(importer, "fetch_recipe_from_url", lambda url: draft)
    r = client.post("/api/import/url", json={"url": "https://x.test"})
    assert r.status_code == 200
    assert r.json()["name"] == "Dal"


@pytest.mark.parametrize("error, status", [
    (importer.NoRecipeFound("keine Daten"), 422),
    (requests.ConnectionError("down"), 502),
])
def test_url_import_fehler(client, monkeypatch, error, status):
    def boom(url):
        raise error
    monkeypatch.setattr(importer, "fetch_recipe_from_url", boom)
    assert client.post("/api/import/url", json={"url": "https://x.test"}).status_code == status


# --------------------------------------------------------------------------- #
#  Bring! (Netzwerk wird immer ersetzt - nie ein echter Aufruf)
# --------------------------------------------------------------------------- #
def test_bring_status(client, monkeypatch):
    monkeypatch.setattr(bring, "is_configured", lambda: True)
    assert client.get("/api/bring/status").json() == {"configured": True}


def test_bring_sendet_uebergebene_posten(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(bring, "send_items", lambda items: sent.update(items=items) or {"sent": len(items)})
    body = {"items": [{"name": "Linsen", "amount": 1.5, "unit": "kg"}, {"name": "Salz"}]}
    r = client.post("/api/bring/send", json=body)
    assert r.status_code == 200
    assert sent["items"] == [("Linsen", "1,5 kg"), ("Salz", "")]


def test_bring_ohne_body_sendet_komplette_einkaufsliste(client, monkeypatch):
    rid = create_recipe(client)["id"]
    client.post("/api/plan", json={"recipe_id": rid, "servings": 2})
    sent = {}
    monkeypatch.setattr(bring, "send_items", lambda items: sent.update(items=items) or {"sent": len(items)})
    assert client.post("/api/bring/send").status_code == 200
    assert ("Rote Linsen", "200 g") in sent["items"]


@pytest.mark.parametrize("error", [bring.BringConfigError("fehlt"), bring.BringConnectionError("weg")])
def test_bring_fehler_werden_als_http_fehler_gemeldet(client, monkeypatch, error):
    def boom(items):
        raise error
    monkeypatch.setattr(bring, "send_items", boom)
    r = client.post("/api/bring/send", json={"items": [{"name": "Salz"}]})
    assert r.status_code == error.status
    assert r.json()["detail"] == str(error)
