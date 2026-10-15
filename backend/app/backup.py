"""Sicherung: alle Rezepte, Bilder und der Vorrat als eine ZIP-Datei.

Inhalt der ZIP:
    rezepte.json        Rezepte (mit Zutaten und Tags) und Vorrat
    bilder/<datei>      die Rezeptbilder

Beim Einspielen wird NICHTS ueberschrieben oder geloescht: Rezepte, deren Name
schon vorhanden ist, werden uebersprungen; alles andere wird ergaenzt. Der
Wochenplan gehoert nicht zur Sicherung (er ist kurzlebig).
"""
import io
import json
import uuid
import zipfile
from typing import List, Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from . import crud, models, pantry, schemas
from .database import UPLOAD_DIR

FORMAT = "mise-sicherung"
VERSION = 1
JSON_NAME = "rezepte.json"
IMAGE_DIR = "bilder/"

MAX_IMAGE_BYTES = 5 * 1024 * 1024        # wie beim Upload
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024      # entpackte Gesamtgroesse (Schutz vor ZIP-Bomben)


class BackupError(Exception):
    """Die Datei ist keine (gueltige) Sicherung."""


def image_extension(data: bytes) -> Optional[str]:
    """Dateiendung anhand der ersten Bytes - nicht anhand des Namens."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"  # kommt vor, wenn ein Browser/Handy AVIF als "JPEG" hochlaedt
    return None


# --------------------------------------------------------------------------- #
#  Export
# --------------------------------------------------------------------------- #
def build_backup(db: Session) -> bytes:
    recipes = db.query(models.Recipe).order_by(models.Recipe.id).all()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        items = []
        for r in recipes:
            image = None
            path = UPLOAD_DIR / r.image if r.image else None
            if path is not None and path.is_file():
                image = IMAGE_DIR + r.image
                zf.write(path, image, compress_type=zipfile.ZIP_STORED)  # schon komprimiert
            out = crud.recipe_to_out(r)
            items.append({
                "name": out["name"],
                "servings": out["servings"],
                "instructions": out["instructions"],
                "source": out["source"],
                "image": image,
                "ingredients": [
                    {k: i[k] for k in ("name", "amount", "unit", "preparation", "category")}
                    for i in out["ingredients"]
                ],
                "tags": out["tags"],
            })
        document = {
            "format": FORMAT,
            "version": VERSION,
            "recipes": items,
            "pantry": [p.name for p in pantry.list_items(db)],
        }
        zf.writestr(JSON_NAME, json.dumps(document, ensure_ascii=False, indent=1),
                    compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
#  Import
# --------------------------------------------------------------------------- #
def _read_document(zf: zipfile.ZipFile) -> dict:
    infos = {i.filename: i for i in zf.infolist()}
    if sum(i.file_size for i in infos.values()) > MAX_TOTAL_BYTES:
        raise BackupError("Die Sicherung ist zu gross.")
    info = infos.get(JSON_NAME)
    if info is None or info.file_size > MAX_JSON_BYTES:
        raise BackupError("Das ist keine Mise-Sicherung.")
    try:
        document = json.loads(zf.read(info).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise BackupError("Das ist keine Mise-Sicherung.")
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise BackupError("Das ist keine Mise-Sicherung.")
    if document.get("version") != VERSION:
        raise BackupError("Diese Sicherung stammt aus einer nicht unterstuetzten Version.")
    if not isinstance(document.get("recipes"), list):
        raise BackupError("Die Sicherung enthaelt keine Rezepte.")
    return document


def _store_image(zf: zipfile.ZipFile, member: Optional[str]) -> Optional[str]:
    """Liest ein Bild aus der ZIP und speichert es unter neuem, zufaelligem Namen."""
    if not isinstance(member, str) or not member.startswith(IMAGE_DIR):
        return None
    name = member[len(IMAGE_DIR):]
    if not name or "/" in name or "\\" in name or ".." in name:
        return None  # nur flache Dateinamen direkt in bilder/
    try:
        info = zf.getinfo(member)
    except KeyError:
        return None
    if info.file_size > MAX_IMAGE_BYTES:
        return None
    data = zf.read(info)
    ext = image_extension(data)
    if ext is None:
        return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (UPLOAD_DIR / filename).write_bytes(data)
    return filename


def restore_backup(db: Session, raw: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise BackupError("Das ist keine Mise-Sicherung.")
    with zf:
        document = _read_document(zf)
        existing = {
            (name or "").casefold()
            for (name,) in db.query(models.Recipe.name).all()
        }
        added = skipped = images = 0
        invalid: List[str] = []
        for entry in document["recipes"]:
            if not isinstance(entry, dict):
                invalid.append("(unlesbarer Eintrag)")
                continue
            try:
                data = schemas.RecipeCreate(**{k: entry.get(k) for k in
                                               ("name", "servings", "instructions", "source")
                                               if entry.get(k) is not None},
                                            ingredients=entry.get("ingredients") or [],
                                            tags=entry.get("tags") or [])
            except (ValidationError, TypeError):
                invalid.append(str(entry.get("name") or "(ohne Namen)"))
                continue
            key = data.name.strip().casefold()
            if key in existing:
                skipped += 1
                continue
            recipe = crud.create_recipe(db, data)
            existing.add(key)
            added += 1
            filename = _store_image(zf, entry.get("image"))
            if filename:
                recipe.image = filename
                db.commit()
                images += 1

        pantry_added = 0
        for name in document.get("pantry") or []:
            try:
                if isinstance(name, str) and pantry.add_item(db, name) is not None:
                    pantry_added += 1
            except ValueError:
                pass
    return {
        "recipes_added": added,
        "recipes_skipped": skipped,
        "recipes_invalid": invalid,
        "images_added": images,
        "pantry_added": pantry_added,
    }
