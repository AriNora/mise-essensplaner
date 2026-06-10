"""Endpunkte rund um den Wochenplan: planen, Einkaufsliste, Vorbereitungsplan."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/plan", tags=["plan"])


@router.get("", response_model=List[schemas.PlanEntryOut])
def get_plan(db: Session = Depends(get_db)):
    return crud.list_plan(db)


@router.post("", response_model=schemas.PlanEntryOut, status_code=201)
def add_to_plan(data: schemas.PlanEntryCreate, db: Session = Depends(get_db)):
    entry = crud.add_plan_entry(db, data)
    if entry is None:
        raise HTTPException(404, "Rezept nicht gefunden")
    return crud.list_plan(db)[-1]  # frisch hinzugefuegter Eintrag inkl. Rezeptinfos


@router.patch("/{entry_id}", response_model=schemas.PlanEntryOut)
def update_plan_entry(entry_id: int, data: schemas.PlanEntryUpdate, db: Session = Depends(get_db)):
    entry = crud.get_plan_entry(db, entry_id)
    if entry is None:
        raise HTTPException(404, "Planeintrag nicht gefunden")
    crud.update_plan_entry(db, entry, data)
    return next(e for e in crud.list_plan(db) if e["id"] == entry_id)


@router.delete("/{entry_id}", status_code=204)
def remove_plan_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = crud.get_plan_entry(db, entry_id)
    if entry is None:
        raise HTTPException(404, "Planeintrag nicht gefunden")
    crud.delete_plan_entry(db, entry)


@router.delete("", status_code=204)
def clear_plan(db: Session = Depends(get_db)):
    crud.clear_plan(db)


@router.get("/shopping-list", response_model=schemas.ShoppingListResponse)
def shopping_list(db: Session = Depends(get_db)):
    return crud.build_shopping_list(db)


@router.get("/prep-plan", response_model=schemas.PrepPlanResponse)
def prep_plan(db: Session = Depends(get_db)):
    return crud.build_prep_plan(db)
