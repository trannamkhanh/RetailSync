"""PB-53 real-SQL forecast scope, latest rows, sellable stock and net business-day sales."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core import clock
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, Forecast, PosTerminal, PosTransaction, Product, ProductBatch, StaffUser, Store, TransactionItem
from app.repositories.forecast import utc_start
from tests.pos_test_support import uid

URL="/api/v1/staff/forecasts"
TODAY=date(2026,11,28)


@pytest.fixture
def world(db_session, monkeypatch):
    monkeypatch.setattr(settings,"jwt_secret",SecretStr("test-only-pb53-secret-with-enough-length"))
    monkeypatch.setattr(clock,"today_local",lambda:TODAY)
    monkeypatch.setattr(settings,"business_utc_offset_hours",7)
    suffix=uid(5)
    stores=[f"TEST-{suffix}",f"OTHER{suffix}"]
    skus=[f"TEST-{suffix}-{letter}" for letter in ("Z","A","B","N")]
    for store in stores:
        db_session.add(Store(store_id=store,name=store,latitude=0,longitude=0,region_id="TEST"))
    for sku in skus:
        db_session.add(Product(sku=sku,barcode=sku,name="Forecast "+sku,category="Dairy",unit_price=1000))
    db_session.flush()
    pos="TEST-POS-"+suffix
    db_session.add(PosTerminal(pos_id=pos,store_id=stores[0],status="ACTIVE"))
    db_session.flush()

    def forecast(sku, status="SHORTAGE", demand="12.50", created=None, store=None):
        row=Forecast(store_id=store or stores[0],sku=sku,horizon_days=7,
                     predicted_demand=Decimal(demand),surplus_shortage=Decimal("-2.50"),
                     balance_status=status,model_version="hgb-v1",
                     created_at=created or utc_start(TODAY))
        db_session.add(row);db_session.flush();return row

    def token(role="Staff",store=stores[0]):
        username="TEST-pb53-"+uid()
        db_session.add(StaffUser(username=username,full_name=username,role={"Manager":"STORE_MANAGER","Staff":"STORE_STAFF","POS":"POS_SYSTEM","HQ":"HQ_OPERATOR","Admin":"ADMIN","Auditor":"AUDITOR"}[role],store_id=store))
        db_session.commit()
        return {"Authorization":"Bearer "+create_token(username,role,store_id=store)}

    def transaction(kind,qty,at,status="OK",created=None):
        txn=PosTransaction(txn_id="TEST-"+uid(),store_id=stores[0],pos_id=pos,
                           txn_type=kind,status=status,payload_hash="a"*64,
                           occurred_at=at,created_at=created or utc_start(TODAY))
        db_session.add(txn);db_session.flush()
        db_session.add(TransactionItem(txn_id=txn.txn_id,sku=skus[0],qty=qty,unit_price=1000))
        db_session.flush()
        return txn

    return SimpleNamespace(store=stores[0],other=stores[1],skus=skus,forecast=forecast,token=token,transaction=transaction)


@pytest.mark.parametrize("role",["Staff","Manager"])
def test_pb53_own_store_latest_only_and_numeric_json(client,db_session,world,role):
    old=utc_start(TODAY-timedelta(days=1))
    world.forecast(world.skus[0],demand="1",created=old)
    world.forecast(world.skus[0],demand="15")
    newest=world.forecast(world.skus[0],demand="16.25")
    world.forecast(world.skus[0],demand="999",store=world.other)
    headers=world.token(role)
    audits=db_session.scalar(select(func.count()).select_from(AuditLog))
    response=client.get(URL+"?store_id="+world.other,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()["business_date"]==TODAY.isoformat()
    row,=response.json()["items"]
    assert row["sku"]==world.skus[0]
    assert row["predicted_demand"]==16.25 and isinstance(row["predicted_demand"],float)
    assert row["surplus_shortage"]==-2.5 and isinstance(row["surplus_shortage"],float)
    assert row["category"]=="Dairy"
    assert row["model_version"]=="hgb-v1" and row["horizon_days"]==7
    assert row["created_at"].startswith(newest.created_at.isoformat())
    assert db_session.scalar(select(func.count()).select_from(AuditLog))==audits


def test_pb53_sellable_batches_and_ordering(client,db_session,world):
    for sku,status in zip(world.skus,("SHORTAGE","SURPLUS","BALANCED"),strict=False):
        world.forecast(sku,status)
    for index,(store,days,qty) in enumerate([(world.store,0,4),(world.store,2,6),(world.store,-1,20),(world.other,2,100)]):
        db_session.add(ProductBatch(batch_id="TEST-"+uid(),store_id=store,sku=world.skus[0],
                                    expiry_date=TODAY+timedelta(days=days),quantity=qty))
    response=client.get(URL,headers=world.token())
    assert response.status_code==200,response.text
    items=response.json()["items"]
    assert [r["sku"] for r in items]==world.skus[:3]
    assert [r["sellable_stock"] for r in items]==[10,0,0]
    assert world.skus[3] not in [r["sku"] for r in items]


def test_pb53_net_sales_uses_effective_at_and_full_business_days(client,db_session,world):
    world.forecast(world.skus[0])
    start=utc_start(TODAY-timedelta(days=7));end=utc_start(TODAY)
    world.transaction("SALE",10,start,created=end+timedelta(days=2))
    world.transaction("RETURN",2,start+timedelta(hours=1))
    world.transaction("SALE",3,start+timedelta(days=1),status="CANCELLED")
    world.transaction("CANCELLATION",3,start+timedelta(days=1,hours=1))
    world.transaction("SALE",100,start-timedelta(microseconds=1))
    world.transaction("SALE",100,end)
    # Legacy NULL occurred_at falls back to received time (effective_at).
    world.transaction("SALE",4,None,created=end-timedelta(microseconds=1))
    response=client.get(URL,headers=world.token())
    assert response.status_code==200,response.text
    assert response.json()["items"][0]["sold_last_7_days"]==12


def test_pb53_empty_forecast_list(client,world):
    response=client.get(URL,headers=world.token())
    assert response.status_code==200 and response.json()["items"]==[]


@pytest.mark.parametrize("role",["Staff","Manager"])
def test_pb53_no_store_is_forbidden(client,world,role):
    response=client.get(URL,headers=world.token(role,store=None))
    assert response.status_code==403 and response.json()["code"]=="FORBIDDEN"


@pytest.mark.parametrize("role",["POS","HQ","Admin","Auditor",None])
def test_pb53_authentication_and_other_roles(client,world,role):
    headers={} if role is None else world.token(role)
    response=client.get(URL,headers=headers)
    assert response.status_code==(401 if role is None else 403)
