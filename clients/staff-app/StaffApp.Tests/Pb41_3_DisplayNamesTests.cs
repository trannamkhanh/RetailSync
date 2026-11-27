using StaffApp.Models;
using StaffApp.Services;
using Xunit;

namespace StaffApp.Tests;

/// <summary>PB-41-3: one display mapping for every tab; an unknown code shows as it is.</summary>
public class Pb41_3_DisplayNamesTests
{
    [Theory]
    [InlineData("SURPLUS", "Thừa hàng")]
    [InlineData("SHORTAGE", "Thiếu hàng")]
    [InlineData("BALANCED", "Cân bằng")]
    [InlineData("OVERSTOCK", "OVERSTOCK")]
    public void Pb41_3_balance_status(string code, string text) => Assert.Equal(text, DisplayNames.BalanceStatus(code));

    [Theory]
    [InlineData("EXPIRED", "Đã hết hạn")]
    [InlineData("NEAR_EXPIRY", "Sắp hết hạn")]
    [InlineData("RECALLED", "RECALLED")]
    public void Pb41_3_alert_type(string code, string text) => Assert.Equal(text, DisplayNames.AlertType(code));

    [Theory]
    [InlineData("MIN_SHELF_LIFE", "Hạn dùng tối thiểu")]
    [InlineData("MAX_DISCOUNT", "Giảm giá tối đa")]
    [InlineData("MIN_PRICE", "Giá tối thiểu")]
    [InlineData("MAX_TRANSFER", "MAX_TRANSFER")]
    public void Pb41_3_rule_type(string code, string text) => Assert.Equal(text, DisplayNames.RuleType(code));

    [Theory]
    [InlineData("PASSED", "Đạt")]
    [InlineData("ADJUSTED", "Điều chỉnh")]
    [InlineData("BLOCKED", "Chặn")]
    [InlineData("SKIPPED", "SKIPPED")]
    public void Pb41_3_outcome(string code, string text) => Assert.Equal(text, DisplayNames.Outcome(code));

    [Theory]
    [InlineData("Dairy", "Sữa")]
    [InlineData("Bakery", "Bánh tươi")]
    [InlineData("Dry goods", "Hàng khô")]
    [InlineData("Beverages", "Đồ uống")]
    [InlineData("Snacks", "Bánh kẹo")]
    [InlineData("Frozen", "Đồ đông lạnh")]
    [InlineData("Household", "Household")]
    public void Pb41_3_category(string code, string text) => Assert.Equal(text, DisplayNames.Category(code));

    [Theory]
    [InlineData("DISCOUNT", "Giảm giá")]
    [InlineData("CLEARANCE", "Thanh lý")]
    [InlineData("REDISTRIBUTION", "Điều chuyển")]
    [InlineData("BUNDLE", "BUNDLE")]
    public void Pb41_3_action_type(string code, string text) => Assert.Equal(text, DisplayNames.ActionType(code));

    [Theory]
    [InlineData("ACCEPTED", "đã chấp nhận")]
    [InlineData("REJECTED", "đã từ chối")]
    [InlineData("EXPIRED", "EXPIRED")]
    public void Pb41_3_decision_status(string code, string text) => Assert.Equal(text, DisplayNames.DecisionStatus(code));

    [Fact]
    public void Pb41_3_guardrail_lines_show_the_rule_and_outcome_names()
    {
        Assert.Equal("Hạn dùng tối thiểu: Đạt", new GuardrailLine("MIN_SHELF_LIFE", "PASSED", null, null, null).Text);
        Assert.Equal("Giá tối thiểu: Chặn (below 1000)", new GuardrailLine("MIN_PRICE", "BLOCKED", null, null, "below 1000").Text);
        Assert.Equal("Giảm giá tối đa: Điều chỉnh 60 -> 50 (capped at 50)",
            new GuardrailLine("MAX_DISCOUNT", "ADJUSTED", 60m, 50m, "capped at 50").Text);
        Assert.Equal("NEW_RULE: NEW_OUTCOME", new GuardrailLine("NEW_RULE", "NEW_OUTCOME", null, null, " ").Text);
    }

    [Theory]
    [InlineData("EXPIRED", 2, "Đã hết hạn")]
    [InlineData("NEAR_EXPIRY", -1, "Đã hết hạn")]
    [InlineData("NEAR_EXPIRY", 1, "Hôm nay hoặc mai")]
    [InlineData("NEAR_EXPIRY", 4, "Sắp hết hạn")]
    [InlineData("RECALLED", 4, "RECALLED")]
    public void Pb41_3_alert_urgency_keeps_the_days_level(string type, int days, string text) =>
        Assert.Equal(text, new AlertLine(1, "B-1", "SKU-0001", new DateOnly(2026, 12, 1), 3, days, type).Urgency);
}
