"""PB-53-2 Vietnamese texts preserve business values and machine-readable codes."""
from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.services.recommendation import near_expiry_proposal, surplus_proposal
from app.services import guardrail_rules, guardrails


def test_pb53_vietnamese_reason_templates_keep_numbers():
    assert near_expiry_proposal("B-1", 2, 10, Decimal(1)).reason == (
        "Lô B-1 hết hạn sau 2 ngày; 7/10 đơn vị có thể không bán kịp.")
    assert surplus_proposal(Decimal(10), Decimal(20), ("STORE-X", Decimal(7))).reason == (
        "STORE-X thiếu 7 đơn vị; cửa hàng này thừa 20.")
    assert surplus_proposal(Decimal(10), Decimal(20), None).reason == (
        "Dự báo cần 10 đơn vị trong 7 ngày; tồn 30.")


@pytest.mark.parametrize(("kind","threshold","discount","price","days","outcome","message"), [
    ("MIN_SHELF_LIFE",2,50,2000,1,"BLOCKED","Còn 1 ngày hạn dùng; tối thiểu là 2 ngày."),
    ("MAX_DISCOUNT",0,50,2000,2,"BLOCKED","Giới hạn giảm giá đưa mức giảm về 0%; không còn giảm giá để áp dụng."),
    ("MAX_DISCOUNT",30,50,2000,2,"ADJUSTED","Giảm 50% vượt mức tối đa 30%."),
    ("MIN_PRICE",1000,50,500,2,"BLOCKED","Giá niêm yết 500 thấp hơn giá tối thiểu 1000."),
    ("MIN_PRICE",1000,1,"1000.01",2,"BLOCKED","Giá tối thiểu đưa mức giảm về 0% sau khi làm tròn xuống; không còn giảm giá để áp dụng."),
    ("MIN_PRICE",1500,50,2000,2,"ADJUSTED","Giảm 50% làm giá bán thấp hơn giá tối thiểu 1500."),
])
def test_pb53_vietnamese_guardrail_messages(kind,threshold,discount,price,days,outcome,message):
    rule=SimpleNamespace(rule_type=kind,threshold=Decimal(str(threshold)))
    rec=SimpleNamespace(action_type="DISCOUNT",discount_pct=Decimal(str(discount)))
    target=guardrails._Target("Dairy",Decimal(str(price)),days)
    result=guardrails._check(rule,rec,target)
    assert (result[0],result[3]) == (outcome,message)
    assert result[1] == Decimal(days if kind=="MIN_SHELF_LIFE" else discount)
    assert rec.action_type == "DISCOUNT"


def test_pb53_rule_load_failure_is_vietnamese(monkeypatch):
    def fail(session):
        raise RuntimeError("test read failure")
    monkeypatch.setattr(guardrail_rules,"active_rules",fail)
    with pytest.raises(guardrails.GuardrailRulesUnavailable,match="Không thể tải các quy tắc kiểm soát"):
        guardrails.load_rules(None)
