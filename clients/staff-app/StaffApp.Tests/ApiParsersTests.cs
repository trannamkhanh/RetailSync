using System.Globalization;
using StaffApp.Models;
using StaffApp.Services;
using Xunit;

namespace StaffApp.Tests;

public class ApiParsersTests
{
    [Fact]
    public void Stf46_1_product_lookup_parses_product_price_stock_and_batches()
    {
        var product = ApiParsers.Product("""
            {"sku":"SKU-0001","barcode":"8930000000011","name":"Fresh milk 1L","category":"Dairy",
             "unit_price":32000.0,"quantity":40,
             "batches":[{"batch_id":"B-1042","expiry_date":"2026-11-05","quantity":12},
                        {"batch_id":"B-1077","expiry_date":"2026-11-20","quantity":28}]}
            """);

        Assert.Equal(("SKU-0001", "Fresh milk 1L", "Dairy", 32000m, 40),
            (product.Sku, product.Name, product.Category, product.UnitPrice, product.Quantity));
        Assert.Equal(new[] { "B-1042", "B-1077" }, product.Batches.Select(batch => batch.BatchId));
        Assert.Equal(new DateOnly(2026, 11, 5), product.Batches[0].ExpiryDate);
    }

    [Fact]
    public void Stf46_2_cross_store_stock_keeps_the_server_order_nearest_first()
    {
        var stock = ApiParsers.CrossStore("""
            {"sku":"SKU-0001","stores":[{"store_id":"STORE-DN3","name":"Son Tra","qty":0,"distance_km":1.8},
                                        {"store_id":"STORE-DN2","name":"Thanh Khe","qty":18,"distance_km":4.42}]}
            """);

        Assert.Equal(new[] { "STORE-DN3", "STORE-DN2" }, stock.Stores.Select(store => store.StoreId));
        Assert.Equal(4.42, stock.Stores[1].DistanceKm, 3);
    }

    [Fact]
    public void Stf46_4_alerts_parse_and_show_their_urgency()
    {
        var alerts = ApiParsers.Alerts("""
            {"items":[
              {"alert_id":3,"batch_id":"B-0998","sku":"SKU-0005","expiry_date":"2026-10-31","remaining_qty":6,
               "days_to_expiry":-1,"alert_type":"EXPIRED"},
              {"alert_id":7,"batch_id":"B-1033","sku":"SKU-0006","expiry_date":"2026-11-02","remaining_qty":14,
               "days_to_expiry":1,"alert_type":"NEAR_EXPIRY"},
              {"alert_id":9,"batch_id":"B-1042","sku":"SKU-0001","expiry_date":"2026-11-05","remaining_qty":12,
               "days_to_expiry":4,"alert_type":"NEAR_EXPIRY"}]}
            """);

        Assert.Equal(new[] { "EXPIRED", "Today or tomorrow", "Soon" }, alerts.Select(alert => alert.Urgency));
        Assert.Equal(new long[] { 3, 7, 9 }, alerts.Select(alert => alert.AlertId));
    }

    [Fact]
    public void Pb47_recommendations_accept_a_decimal_as_a_number_or_a_string()
    {
        var rows = ApiParsers.Recommendations("""
            {"items":[
              {"rec_id":11,"sku":"SKU-0006","action_type":"DISCOUNT","discount_pct":"50.00","proposed_qty":null,"status":"PENDING"},
              {"rec_id":12,"sku":"SKU-0007","action_type":"CLEARANCE","discount_pct":null,"proposed_qty":8,"status":"PENDING"},
              {"rec_id":13,"sku":"SKU-0008","action_type":"REDISTRIBUTION","proposed_qty":10,"status":"PENDING"},
              {"rec_id":14,"sku":"SKU-0009","action_type":"DISCOUNT","discount_pct":12.5,"status":"PENDING"}]}
            """);

        Assert.Equal(new[] { "50%", "8 units", "10 units", "12.5%" }, rows.Select(row => row.Level));
        Assert.All(rows, row => Assert.Equal("PENDING", row.Status));
    }

    [Fact]
    public void Pb47_levels_and_guardrail_values_ignore_the_machine_culture()
    {
        var previous = CultureInfo.CurrentCulture;
        CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("vi-VN");
        try
        {
            var line = new RecommendationLine(14, "SKU-0009", "DISCOUNT", 12.5m, null, "PENDING");
            var guardrail = new GuardrailLine("MAX_DISCOUNT", "ADJUSTED", 60.25m, 50m, null);

            Assert.Equal("12.5%", line.Level);
            Assert.Equal("MAX_DISCOUNT: adjusted 60.25 -> 50", guardrail.Text);
        }
        finally
        {
            CultureInfo.CurrentCulture = previous;
        }
    }

    [Fact]
    public void Stf47_2_detail_parses_reason_expiry_and_guardrail_results()
    {
        var detail = ApiParsers.Detail("""
            {"rec_id":11,"sku":"SKU-0006","action_type":"DISCOUNT","discount_pct":"50.00","proposed_qty":null,
             "status":"PENDING","batch_id":"B-1033","expiry_date":"2026-11-02",
             "reason":"Batch B-1033 expires in 1 day(s); 10 of 14 units may not sell in time.",
             "guardrail_results":[
               {"rule_type":"MIN_SHELF_LIFE","outcome":"PASSED","original_value":null,"adjusted_value":null,"message":null},
               {"rule_type":"MAX_DISCOUNT","outcome":"ADJUSTED","original_value":"60.00","adjusted_value":"50.00",
                "message":"capped at 50"}]}
            """);

        Assert.Equal("Discount 50% on SKU-0006, batch B-1033", detail.Title);
        Assert.Equal(new DateOnly(2026, 11, 2), detail.ExpiryDate);
        Assert.StartsWith("Batch B-1033 expires", detail.Reason);
        Assert.Equal(new[] { "MIN_SHELF_LIFE: passed", "MAX_DISCOUNT: adjusted 60 -> 50 (capped at 50)" },
            detail.GuardrailResults.Select(line => line.Text));
    }

    [Fact]
    public void Pb47_detail_without_a_batch_has_no_expiry()
    {
        var detail = ApiParsers.Detail("""
            {"rec_id":13,"sku":"SKU-0008","action_type":"REDISTRIBUTION","proposed_qty":10,"status":"PENDING",
             "batch_id":null,"expiry_date":null,"reason":"Shortage of 10 units.","guardrail_results":[]}
            """);

        Assert.Null(detail.ExpiryDate);
        Assert.Equal("Redistribute 10 units of SKU-0008", detail.Title);
        Assert.Empty(detail.GuardrailResults);
    }

    [Fact]
    public void Pb47_decision_answer_parses()
    {
        var decision = ApiParsers.Decision("""{"rec_id":11,"status":"ACCEPTED","decided_at":"2026-11-20T03:15:00Z"}""");

        Assert.Equal((11L, "ACCEPTED"), (decision.RecId, decision.Status));
        Assert.Equal(new DateTimeOffset(2026, 11, 20, 3, 15, 0, TimeSpan.Zero), decision.DecidedAt);
    }

    [Theory]
    [InlineData("""{"items":[{"rec_id":1,"sku":"S","status":"PENDING"}]}""")]
    [InlineData("""{"items":"not a list"}""")]
    [InlineData("""[]""")]
    [InlineData("""not json""")]
    public void Pb47_a_body_outside_ds04_is_a_format_error(string body)
    {
        Assert.Throws<FormatException>(() => ApiParsers.Recommendations(body));
    }

    [Fact]
    public void Pb46_error_body_gives_code_and_message()
    {
        Assert.Equal(("ALREADY_DECIDED", "Decided."),
            ApiParsers.ErrorOf("""{"outcome":"REJECTED","code":"ALREADY_DECIDED","message":"Decided."}"""));
        Assert.Equal((string.Empty, string.Empty), ApiParsers.ErrorOf("<html>bad gateway</html>"));
    }
}
