"""REST-Endpunkte fuer Rezepte."""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import UPLOAD_DIR, get_db

router = APIRouter(prefix="/api/recipes", tags=["recipes"])

# Erlaubte Bildformate (Content-Type -> Dateiendung) und Groessenlimit.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


@router.get("", response_model=schemas.RecipeListResponse)
def list_recipes(
    search: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    total, items = crud.list_recipes(db, search=search, limit=limit, offset=offset)
    return {"total": total, "items": items}


@router.post("", response_model=schemas.RecipeOut, status_code=201)
def create_recipe(data: schemas.RecipeCreate, db: Session = Depends(get_db)):
    recipe = crud.create_recipe(db, data)
    return crud.recipe_to_out(recipe)


@router.get("/{recipe_id}", response_model=schemas.RecipeOut)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = crud.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(404, "Rezept nicht gefunden")
    return crud.recipe_to_out(recipe)


@router.put("/{recipe_id}", response_model=schemas.RecipeOut)
def update_recipe(recipe_id: int, data: schemas.RecipeUpdate, db: Session = Depends(get_db)):
    recipe = crud.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(404, "Rezept nicht gefunden")
    recipe = crud.update_recipe(db, recipe, data)
    return crud.recipe_to_out(recipe)


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = crud.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(404, "Rezept nicht gefunden")
    crud.delete_recipe(db, recipe)


@router.post("/{recipe_id}/image", response_model=schemas.RecipeOut)
async def upload_recipe_image(
    recipe_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """Laedt ein Bild zu einem Rezept hoch. Speichert es als Datei im uploads-Ordner
    und merkt sich nur den Dateinamen in der Datenbank."""
    recipe = crud.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(404, "Rezept nicht gefunden")

    ext = ALLOWED_IMAGE_TYPES.get(file.content_type)
    if ext is None:
        raise HTTPException(400, "Nur JPG-, PNG-, WEBP- oder GIF-Bilder sind erlaubt.")

    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "Das Bild ist zu gross (maximal 5 MB).")

    # Eigener, zufaelliger Dateiname (kein Original-Name -> kein Path-Traversal).
    crud.delete_image_file(recipe.image)  # evtl. altes Bild ersetzen
    filename = f"{uuid.uuid4().hex}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / filename).write_bytes(data)

    recipe.image = filename
    db.commit()
    db.refresh(recipe)
    return crud.recipe_to_out(recipe)


@router.delete("/{recipe_id}/image", response_model=schemas.RecipeOut)
def delete_recipe_image(recipe_id: int, db: Session = Depends(get_db)):
    recipe = crud.get_recipe(db, recipe_id)
    if recipe is None:
        raise HTTPException(404, "Rezept nicht gefunden")
    crud.delete_image_file(recipe.image)
    recipe.image = None
    db.commit()
    db.refresh(recipe)
    return crud.recipe_to_out(recipe)
