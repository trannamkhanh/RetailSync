"""GET /api/categories: the filter options of the product page."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.queries import products as product_queries
from app.schemas import Categories

router = APIRouter()


@router.get("/categories", response_model=Categories)
def list_categories(session: Session = Depends(get_db)) -> Categories:
    """Every product category, sorted."""
    return Categories(categories=product_queries.categories(session))
