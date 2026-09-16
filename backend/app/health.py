from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db import get_db


router = APIRouter(tags=["health"])


@router.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok", "service": "business-digital-address"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready", "service": "business-digital-address"}
