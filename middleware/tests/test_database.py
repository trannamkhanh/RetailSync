"""Verify mappings and transaction boundaries against migrated SQL Server."""

import subprocess
import sys
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core import db
from app.domain import models
from app.main import app


MODELS = [
    models.Store, models.PosTerminal, models.StaffUser, models.AuditLog,
    models.Product, models.Inventory, models.SyncBatch, models.PosTransaction,
    models.TransactionItem, models.InventoryMovement, models.GuardrailRule,
]


def test_health_import_needs_no_password():
    code = """
import os
os.environ.pop("MSSQL_SA_PASSWORD", None)
from app.core.config import Settings
assert Settings(_env_file=None).mssql_sa_password is None
from app.main import app
from app.core.db import get_engine
assert get_engine.cache_info().currsize == 0
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_select_one(db_session):
    assert db_session.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.__tablename__)
def test_model_matches_real_table(db_session, model):
    db_session.execute(select(model).limit(1)).all()
    inspector = inspect(db_session.connection())
    actual = {column["name"]: column for column in inspector.get_columns(model.__tablename__)}
    assert set(actual) == set(model.__table__.columns.keys())
    for column in model.__table__.columns:
        stored = actual[column.name]
        assert stored["nullable"] == column.nullable, column.name
        actual_type = stored["type"]
        assert actual_type._type_affinity is column.type._type_affinity, column.name
        for attribute in ("length", "precision", "scale"):
            assert getattr(actual_type, attribute, None) == getattr(column.type, attribute, None), column.name
        assert bool(stored.get("identity")) == bool(column.primary_key and column.autoincrement is True), column.name
    assert inspector.get_pk_constraint(model.__tablename__)["constrained_columns"] == list(model.__table__.primary_key.columns.keys())
    actual_fks = {
        (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
        for fk in inspector.get_foreign_keys(model.__tablename__)
    }
    mapped_fks = {
        (tuple(fk.column_keys), fk.referred_table.name, tuple(element.column.name for element in fk.elements))
        for fk in model.__table__.foreign_key_constraints
    }
    # 002 adds the product_batch FK; that model is deliberately outside Sprint 2.
    actual_fks = {fk for fk in actual_fks if fk[1] != "product_batch"}
    assert actual_fks == mapped_fks


def test_01_fixture_allows_commit(db_session):
    db_session.add(models.Store(store_id="TEST-ISO", name="Isolation", latitude=0, longitude=0, region_id="TEST"))
    db_session.commit()
    assert db_session.get(models.Store, "TEST-ISO") is not None


def test_02_previous_test_row_is_gone(db_session):
    assert db_session.get(models.Store, "TEST-ISO") is None


def test_client_overrides_database(client, db_session):
    original_routes = app.router.routes.copy()
    try:
        @app.get("/fixture-probe")
        def probe(session: Session = Depends(db.get_db)):
            return {"database": session.scalar(text("SELECT DB_NAME()"))}

        assert client.get("/fixture-probe").json() == {
            "database": db_session.scalar(text("SELECT DB_NAME()")),
        }
    finally:
        app.router.routes[:] = original_routes


def test_get_db_rolls_back_and_closes(monkeypatch):
    session = Mock(spec=Session)
    monkeypatch.setattr(db, "SessionLocal", lambda: session)
    dependency = db.get_db()
    assert next(dependency) is session
    with pytest.raises(ValueError):
        dependency.throw(ValueError("route failed"))
    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_get_db_never_commits_implicitly(monkeypatch):
    session = Mock(spec=Session)
    monkeypatch.setattr(db, "SessionLocal", lambda: session)
    dependency = db.get_db()
    assert next(dependency) is session
    with pytest.raises(StopIteration):
        next(dependency)
    session.commit.assert_not_called()
    session.close.assert_called_once()


def test_route_exception_rolls_back_real_database(test_engine, monkeypatch):
    session = Session(bind=test_engine)
    monkeypatch.setattr(db, "SessionLocal", lambda: session)
    test_app = FastAPI()

    @test_app.post("/rollback-probe")
    def fail_route(session: Session = Depends(db.get_db)):
        session.add(models.Store(store_id="TEST-FAIL", name="Rollback", latitude=0, longitude=0, region_id="TEST"))
        session.flush()
        raise RuntimeError("deliberate route failure")

    with TestClient(test_app, raise_server_exceptions=False) as test_client:
        assert test_client.post("/rollback-probe").status_code == 500
    with Session(test_engine) as verification:
        assert verification.get(models.Store, "TEST-FAIL") is None
