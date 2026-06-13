"""Anbindung an die Einkaufs-App **Bring!** (inoffiziell).

Bring! bietet keine offizielle oeffentliche API. Diese Anbindung nutzt die von
der Community dokumentierte, inoffizielle REST-Schnittstelle (dieselbe, die z.B.
Home-Assistant-Integrationen verwenden): Login per E-Mail + Passwort, danach die
aggregierte Einkaufsliste in eine Bring!-Liste schreiben.

Bewusst schlank mit `requests` umgesetzt (kein Zusatzpaket), damit jede Zeile
nachvollziehbar ist. Der Login passiert ausschliesslich hier im Backend; die
Zugangsdaten liegen in einer lokalen, nicht versionierten Datei (siehe
load_config) und werden nie an den Browser gegeben.

Hinweis: Da es eine inoffizielle Schnittstelle ist, koennte Bring! sie kuenftig
aendern. Endpunkte/Schluessel sind hier oben gebuendelt und im Zweifel leicht
anzupassen.
"""
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import requests

# --- Inoffizielle Bring!-API (Stand der gepflegten Referenzbibliothek) ------
BASE_URL = "https://api.getbring.com/rest"
# Oeffentlicher API-Schluessel, den die Bring!-Clients verwenden (kein Geheimnis).
API_KEY = "cof4Nc6D8saplXjE3h3HXqHH8m7VU2i1Gs0g85Sp"
BASE_HEADERS = {
    "X-BRING-API-KEY": API_KEY,
    "X-BRING-CLIENT": "android",
    "X-BRING-APPLICATION": "bring",
    "X-BRING-COUNTRY": "DE",
}
TIMEOUT = 15

# Konfigurationsdatei: backend/bring_account.json (liegt NICHT in Git).
CONFIG_PATH = Path(__file__).resolve().parent.parent / "bring_account.json"


# --------------------------------------------------------------------------- #
#  Fehlertypen (mit passendem HTTP-Status fuer den Router)
# --------------------------------------------------------------------------- #
class BringError(Exception):
    status = 400


class BringConfigError(BringError):
    """Zugangsdaten fehlen/sind unvollstaendig."""
    status = 400


class BringAuthError(BringError):
    """Login abgelehnt (E-Mail/Passwort)."""
    status = 400


class BringListError(BringError):
    """Gewuenschte Liste nicht gefunden."""
    status = 400


class BringConnectionError(BringError):
    """Bring! nicht erreichbar / unerwartete Antwort."""
    status = 502


# --------------------------------------------------------------------------- #
#  Konfiguration laden
# --------------------------------------------------------------------------- #
def load_config() -> Optional[dict]:
    """Liest Zugangsdaten aus backend/bring_account.json oder Umgebungsvariablen.

    Datei-Format:
        {"email": "...", "password": "...", "list": ""}
    `list` ist optional (Name der Ziel-Liste); leer = Standardliste.
    Gibt None zurueck, wenn nichts konfiguriert ist.
    """
    email = password = None
    list_name = ""
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            raise BringConfigError(f"bring_account.json konnte nicht gelesen werden: {e}")
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        list_name = (data.get("list") or "").strip()
    # Umgebungsvariablen als Alternative/Override
    email = (os.environ.get("BRING_EMAIL") or email or "").strip()
    password = os.environ.get("BRING_PASSWORD") or password or ""
    list_name = (os.environ.get("BRING_LIST") or list_name or "").strip()

    if not email or not password:
        return None
    return {"email": email, "password": password, "list": list_name}


def is_configured() -> bool:
    try:
        return load_config() is not None
    except BringError:
        return False


# --------------------------------------------------------------------------- #
#  Bring!-API-Aufrufe
# --------------------------------------------------------------------------- #
def _login(email: str, password: str) -> dict:
    """Meldet sich an und liefert Token + User-UUIDs zurueck."""
    try:
        r = requests.post(
            f"{BASE_URL}/v2/bringauth",
            data={"email": email, "password": password},
            headers=BASE_HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise BringConnectionError(f"Bring! nicht erreichbar: {e}")

    if r.status_code in (400, 401):
        raise BringAuthError("Login bei Bring! fehlgeschlagen – bitte E-Mail und Passwort pruefen.")
    if r.status_code != 200:
        raise BringConnectionError(f"Unerwartete Antwort von Bring! beim Login (HTTP {r.status_code}).")

    try:
        d = r.json()
        return {
            "auth": f'{d.get("token_type", "Bearer")} {d["access_token"]}',
            "uuid": d["uuid"],
            "public_uuid": d.get("publicUuid", ""),
        }
    except (ValueError, KeyError) as e:
        raise BringConnectionError(f"Login-Antwort von Bring! nicht verstanden: {e}")


def _auth_headers(session: dict) -> dict:
    return {
        **BASE_HEADERS,
        "Authorization": session["auth"],
        "X-BRING-USER-UUID": session["uuid"],
        "X-BRING-PUBLIC-USER-UUID": session["public_uuid"],
    }


def _load_lists(session: dict) -> List[dict]:
    try:
        r = requests.get(
            f'{BASE_URL}/bringusers/{session["uuid"]}/lists',
            headers=_auth_headers(session),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("lists", [])
    except requests.RequestException as e:
        raise BringConnectionError(f"Bring!-Listen konnten nicht geladen werden: {e}")
    except ValueError as e:
        raise BringConnectionError(f"Listen-Antwort von Bring! nicht verstanden: {e}")


def _pick_list(lists: List[dict], wanted_name: str) -> dict:
    if not lists:
        raise BringListError("In deinem Bring!-Konto wurde keine Liste gefunden.")
    if wanted_name:
        for lst in lists:
            if (lst.get("name") or "").strip().lower() == wanted_name.lower():
                return lst
        names = ", ".join(l.get("name", "?") for l in lists)
        raise BringListError(
            f"Liste '{wanted_name}' nicht gefunden. Verfuegbar: {names}. "
            "Passe das Feld 'list' in bring_account.json an (leer = erste Liste)."
        )
    return lists[0]


def _add_items(session: dict, list_uuid: str, items: List[Tuple[str, str]]) -> None:
    """Schreibt alle Artikel in einem Rutsch (Batch) auf die Liste."""
    changes = [
        {
            "accuracy": "0.0", "altitude": "0.0", "latitude": "0.0", "longitude": "0.0",
            "itemId": name, "spec": spec or "", "operation": "TO_PURCHASE",
        }
        for name, spec in items
    ]
    try:
        r = requests.put(
            f"{BASE_URL}/v2/bringlists/{list_uuid}/items",
            json={"changes": changes, "sender": ""},
            headers=_auth_headers(session),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        raise BringConnectionError(f"Artikel konnten nicht an Bring! gesendet werden: {e}")


# --------------------------------------------------------------------------- #
#  Oeffentliche Funktion fuer den Router
# --------------------------------------------------------------------------- #
def send_items(items: List[Tuple[str, str]]) -> dict:
    """Loggt sich ein und schreibt die Artikel auf die (konfigurierte) Liste.

    `items` ist eine Liste von (Name, Mengenangabe). Gibt {sent, list} zurueck.
    """
    config = load_config()
    if config is None:
        raise BringConfigError(
            "Bring! ist noch nicht eingerichtet. Lege die Datei backend/bring_account.json "
            "mit deiner Bring!-E-Mail und deinem Passwort an (siehe LIES-MICH)."
        )
    if not items:
        return {"sent": 0, "list": None}

    session = _login(config["email"], config["password"])
    lists = _load_lists(session)
    target = _pick_list(lists, config["list"])
    _add_items(session, target["listUuid"], items)
    return {"sent": len(items), "list": target.get("name") or "Bring!-Liste"}
