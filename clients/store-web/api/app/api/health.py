"""GET /api/health: proves the API answered and names the database it reads."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import Health

router = APIRouter()


@router.get("/health", response_model=Health)
def health(session: Session = Depends(get_db)) -> Health:
    """Return ``ok`` and the database name SQL Server reports."""
    database = session.execute(text("SELECT DB_NAME()")).scalar_one()
    return Health(status="ok", database=str(database))

