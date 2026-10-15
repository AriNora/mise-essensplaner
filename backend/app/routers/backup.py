"""Endpunkte fuer die Sicherung: alles herunterladen, Sicherung einspielen."""
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import backup
from ..database import get_db

router = APIRouter(prefix="/api/backup", tags=["backup"])

# Grosszuegig, weil Bilder enthalten sind; die Pruefung im Detail macht backup.py.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


@router.get("")
def download_backup(db: Session = Depends(get_db)):
    filename = f"mise-sicherung-{date.today().isoformat()}.zip"
    return Response(
        backup.build_backup(db),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
async def restore_backup(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Die Datei ist zu gross.")
    try:
        return backup.restore_backup(db, raw)
    except backup.BackupError as e:
        raise HTTPException(400, str(e))
