"""Admin registration endpoints (PB-08-1): stores and POS terminals."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas.registry import (
    PosTerminalCreate,
    PosTerminalRead,
    StoreCreate,
    StoreRead,
)
from app.core.db import get_db
from app.core.security import Principal, require_role
from app.domain.models import PosTerminal, Store
from app.services import registry


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/stores", status_code=status.HTTP_201_CREATED, response_model=StoreRead)
def create_store(payload: StoreCreate, session: Session = Depends(get_db),
                 principal: Principal = Depends(require_role("Admin"))) -> StoreRead:
    store = registry.register_store(session, Store(**payload.model_dump()), principal)
    created = StoreRead.model_validate(store)
    session.commit()
    return created


@router.post("/pos-terminals", status_code=status.HTTP_201_CREATED, response_model=PosTerminalRead)
def create_pos_terminal(payload: PosTerminalCreate, session: Session = Depends(get_db),
                        principal: Principal = Depends(require_role("Admin"))) -> PosTerminalRead:
    terminal = registry.register_pos_terminal(session, PosTerminal(**payload.model_dump()), principal)
    created = PosTerminalRead.model_validate(terminal)
    session.commit()
    return created
