"""Pure PB-37 checks; live transport is exercised by the e2e script, not mocked PASSes."""
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

spec = spec_from_file_location("e2e_check", Path(__file__).resolve().parents[2] / "scripts/e2e/e2e_check.py")
e2e = module_from_spec(spec)
spec.loader.exec_module(e2e)


def test_pb37_stock_and_hq_delta_helpers():
    assert e2e.stock_expectations(40) == [37, 38, 36, 38]
    before = {"totals": [{"store_id": "STORE-DN1", "sku": "SKU-0001",
                          "sold_qty": 7, "returned_qty": 2, "net_revenue": 160000}]}
    after = {"totals": [{"store_id": "STORE-DN1", "sku": "SKU-0001",
                         "sold_qty": 12, "returned_qty": 5, "net_revenue": 224000}]}
    assert e2e.delta(e2e.hq_totals(after, "STORE-DN1", "SKU-0001"),
                     e2e.hq_totals(before, "STORE-DN1", "SKU-0001")) == (5, 3, Decimal(64000))
    assert e2e.hq_totals(before, "STORE-DN2", "SKU-0001") == (0, 0, Decimal(0))
    with pytest.raises(ValueError, match="Duplicate"):
        e2e.hq_totals({"totals": after["totals"] * 2}, "STORE-DN1", "SKU-0001")
