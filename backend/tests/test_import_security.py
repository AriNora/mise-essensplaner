"""Tests fuer den URL-Import: nur oeffentliche Webseiten, begrenzte Groesse,
geprueftes Weiterleiten. Es findet nie ein echter Netzwerkzugriff statt."""
import ipaddress
import socket

import pytest
import requests

from app import importer

PAGE = """<html><head><script type="application/ld+json">
{"@type": "Recipe", "name": "Dal", "recipeYield": "2", "recipeIngredient": ["200 g Linsen"],
 "recipeInstructions": "Kochen."}</script></head></html>"""

DNS = {
    "rezepte.example": "93.184.216.34",
    "andere.example": "8.8.8.8",
    "intern.example": "192.168.1.10",
    "loopback.example": "127.0.0.1",
    "metadaten.example": "169.254.169.254",
    "v6loop.example": "::1",
    "v6mapped.example": "::ffff:127.0.0.1",
    "carrier.example": "100.64.0.1",
}


class FakeResponse:
    def __init__(self, status=200, body=PAGE, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    @property
    def is_redirect(self):
        return "Location" in self.headers and self.status_code in (301, 302, 303, 307, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        for i in range(0, len(self._body), size):
            yield self._body[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def net(monkeypatch):
    """Ersetzt DNS und HTTP. `net.routes` bildet URL -> FakeResponse ab."""
    class Net:
        routes = {}
        calls = []

    def getaddrinfo(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)        # IP-Adressen "loest" das echte getaddrinfo selbst auf
            return [(0, 0, 0, "", (host, port))]
        except ValueError:
            pass
        if host not in DNS:
            raise socket.gaierror("unbekannt")
        return [(0, 0, 0, "", (DNS[host], port))]

    def get(url, **kwargs):
        assert kwargs.get("allow_redirects") is False   # Weiterleitungen pruefen wir selbst
        Net.calls.append(url)
        return Net.routes[url]

    monkeypatch.setattr(importer.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(importer.requests, "get", get)
    Net.routes = {}
    Net.calls = []
    return Net


def test_oeffentliche_seite_wird_importiert(net):
    net.routes["https://rezepte.example/dal"] = FakeResponse()
    draft = importer.fetch_recipe_from_url("https://rezepte.example/dal")
    assert draft["name"] == "Dal"


@pytest.mark.parametrize("host", [
    "intern.example", "loopback.example", "metadaten.example",
    "v6loop.example", "v6mapped.example", "carrier.example",
])
def test_nicht_oeffentliche_adressen_werden_abgelehnt(net, host):
    with pytest.raises(importer.UrlNotAllowed):
        importer.fetch_recipe_from_url(f"http://{host}/x")
    assert net.calls == []          # es wurde gar nicht erst angefragt


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x", "http://[::1]/x", "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.1/x", "http://0.0.0.0/x",
    "http://rezepte.example:8000/x",       # fremder Port
    "http://rezepte.example:22/x",
    "ftp://rezepte.example/x", "file:///etc/passwd", "http:///x",
])
def test_ungeeignete_adressen_werden_abgelehnt(net, url):
    with pytest.raises(importer.UrlNotAllowed):
        importer.fetch_recipe_from_url(url)
    assert net.calls == []


def test_unbekannter_rechnername_ist_normaler_ladefehler(net):
    with pytest.raises(requests.ConnectionError):
        importer.fetch_recipe_from_url("https://gibt-es-nicht.example/x")


def test_weiterleitung_auf_oeffentliche_seite_wird_gefolgt(net):
    net.routes["https://rezepte.example/alt"] = FakeResponse(301, "", {"Location": "/neu"})
    net.routes["https://rezepte.example/neu"] = FakeResponse()
    assert importer.fetch_recipe_from_url("https://rezepte.example/alt")["name"] == "Dal"


def test_weiterleitung_ins_interne_netz_wird_abgelehnt(net):
    net.routes["https://rezepte.example/x"] = FakeResponse(
        302, "", {"Location": "http://intern.example/admin"})
    with pytest.raises(importer.UrlNotAllowed):
        importer.fetch_recipe_from_url("https://rezepte.example/x")
    assert net.calls == ["https://rezepte.example/x"]    # das interne Ziel wurde nie angefragt


def test_weiterleitung_auf_ip_literal_wird_abgelehnt(net):
    net.routes["https://rezepte.example/x"] = FakeResponse(
        302, "", {"Location": "http://169.254.169.254/latest/"})
    with pytest.raises(importer.UrlNotAllowed):
        importer.fetch_recipe_from_url("https://rezepte.example/x")


def test_zu_viele_weiterleitungen(net):
    net.routes["https://rezepte.example/a"] = FakeResponse(302, "", {"Location": "/a"})
    with pytest.raises(requests.TooManyRedirects):
        importer.fetch_recipe_from_url("https://rezepte.example/a")
    assert len(net.calls) == importer.MAX_REDIRECTS + 1


def test_zu_grosse_seite_laut_header(net):
    net.routes["https://rezepte.example/x"] = FakeResponse(
        headers={"Content-Length": str(importer.MAX_PAGE_BYTES + 1)})
    with pytest.raises(importer.PageTooLarge):
        importer.fetch_recipe_from_url("https://rezepte.example/x")


def test_zu_grosse_seite_ohne_header(net):
    net.routes["https://rezepte.example/x"] = FakeResponse(body="x" * (importer.MAX_PAGE_BYTES + 1))
    with pytest.raises(importer.PageTooLarge):
        importer.fetch_recipe_from_url("https://rezepte.example/x")


def test_http_fehler_bleibt_ladefehler(net):
    net.routes["https://rezepte.example/x"] = FakeResponse(404)
    with pytest.raises(requests.HTTPError):
        importer.fetch_recipe_from_url("https://rezepte.example/x")


def test_seite_ohne_rezept(net):
    net.routes["https://rezepte.example/x"] = FakeResponse(body="<html></html>")
    with pytest.raises(ValueError):
        importer.fetch_recipe_from_url("https://rezepte.example/x")


# --- Zusammenspiel mit der API ---------------------------------------------
def test_api_meldet_interne_adresse_mit_klarem_text(client, net):
    r = client.post("/api/import/url", json={"url": "http://localhost:8000/api/recipes"})
    assert r.status_code == 400
    assert "öffentliche Webseiten" in r.json()["detail"]


def test_api_meldet_zu_grosse_seite(client, net):
    net.routes["https://rezepte.example/x"] = FakeResponse(body="x" * (importer.MAX_PAGE_BYTES + 1))
    r = client.post("/api/import/url", json={"url": "https://rezepte.example/x"})
    assert r.status_code == 422
    assert "zu groß" in r.json()["detail"]
