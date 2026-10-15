"""Tests fuer Sicherung und Wiederherstellung (ZIP mit rezepte.json und Bildern)."""
import io
import json
import zipfile

import pytest

from app import backup

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def make_recipe(client, name="Linsensuppe", with_image=False):
    r = client.post("/api/recipes", json={
        "name": name, "servings": 3, "instructions": "Kochen.", "source": "https://x.test",
        "ingredients": [
            {"name": "Rote Linsen", "amount": 200, "unit": "g", "category": "Hülsenfrüchte"},
            {"name": "Zwiebel", "amount": 1, "unit": "Stück", "preparation": "würfeln",
             "category": "Obst & Gemüse"},
        ],
        "tags": [{"kind": "typ", "name": "Suppe"}, {"kind": "kueche", "name": "Indisch"}],
    })
    assert r.status_code == 201
    rid = r.json()["id"]
    if with_image:
        client.post(f"/api/recipes/{rid}/image", files={"file": ("x.png", PNG, "image/png")})
    return rid


def download(client):
    r = client.get("/api/backup")
    assert r.status_code == 200
    return r.content


def restore(client, raw):
    return client.post("/api/backup/restore", files={"file": ("s.zip", raw, "application/zip")})


def zip_with(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def document(recipes, **extra):
    d = {"format": backup.FORMAT, "version": backup.VERSION, "recipes": recipes, "pantry": []}
    d.update(extra)
    return json.dumps(d)


# --------------------------------------------------------------------------- #
#  Export
# --------------------------------------------------------------------------- #
def test_download_ist_zip_mit_dateiname(client):
    r = client.get("/api/backup")
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith('attachment; filename="mise-sicherung-')
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["rezepte.json"]


def test_download_enthaelt_rezepte_bilder_und_vorrat(client):
    make_recipe(client, with_image=True)
    client.post("/api/pantry", json={"name": "Olivenöl"})
    zf = zipfile.ZipFile(io.BytesIO(download(client)))
    doc = json.loads(zf.read("rezepte.json"))
    assert doc["format"] == "mise-sicherung" and doc["version"] == 1
    recipe = doc["recipes"][0]
    assert recipe["name"] == "Linsensuppe"
    assert [i["name"] for i in recipe["ingredients"]] == ["Rote Linsen", "Zwiebel"]
    assert recipe["image"].startswith("bilder/") and recipe["image"] in zf.namelist()
    assert doc["pantry"] == ["Olivenöl"]


def test_download_ueberspringt_fehlende_bilddatei(client):
    rid = make_recipe(client, with_image=True)
    for f in client.upload_dir.iterdir():
        f.unlink()
    doc = json.loads(zipfile.ZipFile(io.BytesIO(download(client))).read("rezepte.json"))
    assert doc["recipes"][0]["image"] is None
    assert client.get(f"/api/recipes/{rid}").status_code == 200


# --------------------------------------------------------------------------- #
#  Kreislauf: sichern -> alles loeschen -> einspielen
# --------------------------------------------------------------------------- #
def test_kreislauf_stellt_alles_wieder_her(client):
    rid = make_recipe(client, with_image=True)
    client.post("/api/pantry", json={"name": "Olivenöl"})
    raw = download(client)

    client.delete(f"/api/recipes/{rid}")
    for item in client.get("/api/pantry").json():
        client.delete(f"/api/pantry/{item['id']}")
    assert client.get("/api/recipes").json()["total"] == 0

    result = restore(client, raw)
    assert result.status_code == 200
    assert result.json() == {"recipes_added": 1, "recipes_skipped": 0, "recipes_invalid": [],
                             "images_added": 1, "pantry_added": 1}

    item = client.get("/api/recipes").json()["items"][0]
    got = client.get(f"/api/recipes/{item['id']}").json()
    assert (got["name"], got["servings"], got["instructions"], got["source"]) == (
        "Linsensuppe", 3, "Kochen.", "https://x.test")
    assert [(i["name"], i["amount"], i["unit"], i["preparation"], i["category"])
            for i in got["ingredients"]] == [
        ("Rote Linsen", 200, "g", None, "Hülsenfrüchte"),
        ("Zwiebel", 1, "Stück", "würfeln", "Obst & Gemüse")]
    assert sorted((t["kind"], t["name"]) for t in got["tags"]) == [("kueche", "Indisch"), ("typ", "Suppe")]
    assert got["image"]
    assert len(list(client.upload_dir.iterdir())) == 1
    assert [p["name"] for p in client.get("/api/pantry").json()] == ["Olivenöl"]


def test_zweimal_einspielen_legt_nichts_doppelt_an(client):
    make_recipe(client)
    raw = download(client)
    result = restore(client, raw).json()
    assert (result["recipes_added"], result["recipes_skipped"]) == (0, 1)
    assert client.get("/api/recipes").json()["total"] == 1


def test_vorhandener_name_zaehlt_ohne_gross_klein_und_umlaut_unterschied(client):
    make_recipe(client, name="Öl-Kartoffeln")
    raw = zip_with({"rezepte.json": document([{"name": "öl-kartoffeln", "servings": 2}])})
    assert restore(client, raw).json()["recipes_skipped"] == 1
    assert client.get("/api/recipes").json()["total"] == 1


def test_einspielen_ueberschreibt_nichts(client):
    rid = make_recipe(client)
    raw = zip_with({"rezepte.json": document([{"name": "Linsensuppe", "servings": 9,
                                               "instructions": "ANDERS"}])})
    restore(client, raw)
    got = client.get(f"/api/recipes/{rid}").json()
    assert (got["servings"], got["instructions"]) == (3, "Kochen.")


# --------------------------------------------------------------------------- #
#  Fehlerfaelle
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", [
    b"das ist keine zip-datei",
    zip_with({"etwas.txt": "x"}),                                    # kein rezepte.json
    zip_with({"rezepte.json": "kein json"}),
    zip_with({"rezepte.json": json.dumps({"format": "anderes", "version": 1, "recipes": []})}),
    zip_with({"rezepte.json": json.dumps([1, 2, 3])}),
])
def test_keine_sicherung_wird_abgelehnt(client, raw):
    r = restore(client, raw)
    assert r.status_code == 400
    assert r.json()["detail"] == "Das ist keine Mise-Sicherung."


def test_unbekannte_version_wird_abgelehnt(client):
    raw = zip_with({"rezepte.json": document([], version=99)})
    r = restore(client, raw)
    assert r.status_code == 400
    assert "Version" in r.json()["detail"]


def test_ungueltige_rezepte_werden_gemeldet_der_rest_trotzdem_eingespielt(client):
    raw = zip_with({"rezepte.json": document([
        {"name": "", "servings": 2},                                  # leerer Name
        {"name": "Kaputt", "servings": 0},                            # keine Portionen
        {"name": "Tags", "tags": [{"kind": "unsinn", "name": "x"}]},  # unbekannte Tag-Art
        "kein objekt",
        {"name": "Gut", "servings": 2},
    ])})
    r = restore(client, raw).json()
    assert r["recipes_added"] == 1
    assert r["recipes_invalid"] == ["(ohne Namen)", "Kaputt", "Tags", "(unlesbarer Eintrag)"]
    assert [i["name"] for i in client.get("/api/recipes").json()["items"]] == ["Gut"]


# --------------------------------------------------------------------------- #
#  Bilder aus fremden ZIP-Dateien
# --------------------------------------------------------------------------- #
def one_recipe_zip(image_member, files):
    rec = {"name": "Mit Bild", "servings": 2, "image": image_member}
    return zip_with({"rezepte.json": document([rec]), **files})


def test_bild_wird_unter_neuem_namen_gespeichert(client):
    raw = one_recipe_zip("bilder/original.png", {"bilder/original.png": PNG})
    assert restore(client, raw).json()["images_added"] == 1
    names = [f.name for f in client.upload_dir.iterdir()]
    assert len(names) == 1 and names[0] != "original.png" and names[0].endswith(".png")


@pytest.mark.parametrize("member, data", [
    ("bilder/a.png", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),   # kein Bild-Format
    ("bilder/a.png", b"GIF"),                                          # zu kurz / falsche Kennung
    ("bilder/a.png", PNG + b"0" * (5 * 1024 * 1024)),                  # zu gross
    ("../a.png", PNG),                                                 # ausserhalb von bilder/
    ("bilder/../../a.png", PNG),                                       # Pfad-Tricks
    ("bilder/unter/a.png", PNG),                                       # Unterordner
    ("bilder/fehlt.png", None),                                        # Datei nicht in der ZIP
])
def test_unzulaessige_bilder_werden_ignoriert_rezept_bleibt(client, member, data):
    files = {} if data is None else {member: data}
    r = restore(client, one_recipe_zip(member, files)).json()
    assert (r["recipes_added"], r["images_added"]) == (1, 0)
    assert list(client.upload_dir.iterdir()) == []


@pytest.mark.parametrize("data, ext", [
    (PNG, ".png"), (b"\xff\xd8\xff\xe0" + b"0" * 8, ".jpg"), (b"GIF89a" + b"0" * 8, ".gif"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", ".webp"), (b"\x00\x00\x00\x1cftypavif", ".avif"), (b"nope", None), (b"", None),
])
def test_bildformat_wird_an_den_ersten_bytes_erkannt(data, ext):
    assert backup.image_extension(data) == ext
