using System.Globalization;
using DemoConsole.Models;
using DemoConsole.Services;
using DemoConsole.UI;
using Xunit;

namespace DemoConsole.Tests;

/// <summary>
/// PB-49 (plan D3, §8.2): the Dashboard pieces that can be tested without a window.
/// The parser is pinned to the contract, the query builder to the half-open interval
/// in UTC, and the quality badge to the five-label vocabulary.
/// </summary>
public sealed class DashboardTests
{
    // The exact shape GET /dashboard/revenue returns (openapi.yaml §Dashboard).
    private const string RevenueBody = """
        {
          "scope": { "store_id": "STORE-HN1", "is_system_wide": false },
          "time_policy": { "max_future_skew_seconds": 300, "max_backfill_days": 30 },
          "data_from": "2026-11-01T00:00:00Z",
          "data_to": "2026-11-08T00:00:00Z",
          "has_data": true,
          "total_revenue": 1234.5,
          "transactions": 17,
          "quality": {
            "on_time": 12, "backfill": 2, "suspect_future": 1, "suspect_old": 1, "unknown": 1
          },
          "buckets": [
            { "from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z",
              "revenue": 100.25, "transactions": 3 },
            { "from": "2026-11-02T00:00:00Z", "to": "2026-11-03T00:00:00Z",
              "revenue": 0, "transactions": 0 }
          ]
        }
        """;

    // --- the parser ---------------------------------------------------------

    [Fact]
    public void Parses_every_field_of_the_revenue_contract()
    {
        var revenue = ApiParsers.DashboardRevenue(RevenueBody);

        Assert.Equal("STORE-HN1", revenue.Scope.StoreId);
        Assert.False(revenue.Scope.IsSystemWide);
        Assert.Equal(300, revenue.TimePolicy.MaxFutureSkewSeconds);
        Assert.Equal(30, revenue.TimePolicy.MaxBackfillDays);
        Assert.Equal(new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc), revenue.DataFromUtc);
        Assert.True(revenue.HasData);
        Assert.Equal(1234.5m, revenue.TotalRevenue);
        Assert.Equal(17, revenue.Transactions);
        Assert.Equal(2, revenue.Buckets.Count);
    }

    [Fact]
    public void Money_stays_exact_and_is_never_a_string()
    {
        var revenue = ApiParsers.DashboardRevenue(RevenueBody);

        // 100.25 through a double would not round-trip; decimal keeps the cents.
        Assert.Equal(100.25m, revenue.Buckets[0].Revenue);
        Assert.Equal(0m, revenue.Buckets[1].Revenue);
    }

    [Fact]
    public void A_money_field_sent_as_a_numeric_string_is_accepted()
    {
        var body = RevenueBody.Replace("\"total_revenue\": 1234.5", "\"total_revenue\": \"1234.50\"");

        // DS-04 says money is a JSON number, but audit #7 made every parser in this
        // console accept a numeric string too, so an older server or a recorded body
        // still reads. The figure is the same either way, which is what matters here.
        var revenue = ApiParsers.DashboardRevenue(body);

        Assert.Equal(1234.50m, revenue.TotalRevenue);
    }

    [Fact]
    public void A_money_field_sent_as_text_is_a_format_error()
    {
        var body = RevenueBody.Replace("\"total_revenue\": 1234.5", "\"total_revenue\": \"not a number\"");

        // A string that is not a number still has to fail loudly rather than show a
        // silently wrong figure.
        Assert.Throws<FormatException>(() => ApiParsers.DashboardRevenue(body));
    }

    [Fact]
    public void A_missing_quality_count_is_a_format_error()
    {
        var body = RevenueBody.Replace("\"unknown\": 1", "\"unknown_typo\": 1");

        Assert.Throws<FormatException>(() => ApiParsers.DashboardRevenue(body));
    }

    [Fact]
    public void Timestamps_are_read_as_utc()
    {
        var revenue = ApiParsers.DashboardRevenue(RevenueBody);

        Assert.Equal(DateTimeKind.Utc, revenue.Buckets[0].FromUtc.Kind);
        // The second bucket opens at 02/11 and closes at 03/11: a half-open day.
        Assert.Equal(new DateTime(2026, 11, 2, 0, 0, 0, DateTimeKind.Utc), revenue.Buckets[1].FromUtc);
        Assert.Equal(new DateTime(2026, 11, 3, 0, 0, 0, DateTimeKind.Utc), revenue.Buckets[1].ToUtc);
    }

    [Fact]
    public void Null_span_fields_are_allowed()
    {
        var body = RevenueBody
            .Replace("\"data_from\": \"2026-11-01T00:00:00Z\"", "\"data_from\": null")
            .Replace("\"data_to\": \"2026-11-08T00:00:00Z\"", "\"data_to\": null");

        var revenue = ApiParsers.DashboardRevenue(body);

        Assert.Null(revenue.DataFromUtc);
        Assert.Null(revenue.DataToUtc);
    }

    [Fact]
    public void Parses_the_store_list()
    {
        const string body = """
            {
              "stores": [
                { "store_id": "STORE-DN1", "name": "Hải Châu", "region_id": "DN", "is_active": true },
                { "store_id": "STORE-DN2", "name": "Thanh Khê", "region_id": "DN", "is_active": false }
              ]
            }
            """;

        var stores = ApiParsers.DashboardStores(body);

        Assert.Equal(2, stores.Count);
        Assert.Equal("Hải Châu", stores[0].Name);
        Assert.True(stores[0].IsActive);
        Assert.False(stores[1].IsActive);
    }

    // --- the quality badge --------------------------------------------------

    private static readonly DashboardTimePolicy Policy = new(300, 30);

    [Fact]
    public void A_clean_interval_says_the_money_is_exact()
    {
        var line = DashboardTab.QualityLine(new DashboardTimeQuality(10, 2, 0, 0, 0), Policy);

        Assert.Contains("đủ tin cậy", line);
        Assert.Contains("2 nhận bù", line);
    }

    [Fact]
    public void A_dirty_interval_counts_the_rows_the_money_came_from_but_cannot_trust()
    {
        // BACKFILL is trusted; the other three are not.
        var quality = new DashboardTimeQuality(1, 5, 2, 3, 4);

        var line = DashboardTab.QualityLine(quality, Policy);

        Assert.Equal(9, quality.NotTrusted);
        Assert.False(quality.IsClean);
        Assert.Contains("9/15", line);
        Assert.Contains("2 giờ tương lai", line);
        Assert.Contains("3 quá cũ", line);
        Assert.Contains("4 thiếu mốc", line);
    }

    [Fact]
    public void An_empty_interval_does_not_claim_a_quality()
    {
        var line = DashboardTab.QualityLine(new DashboardTimeQuality(0, 0, 0, 0, 0), Policy);

        Assert.Contains("chưa có giao dịch", line);
        Assert.True(new DashboardTimeQuality(0, 0, 0, 0, 0).IsClean);
    }

    [Fact]
    public void The_five_counts_always_add_up_to_the_total()
    {
        var quality = new DashboardTimeQuality(1, 2, 3, 4, 5);

        Assert.Equal(15, quality.Total);
    }

    // --- the query the tab builds -------------------------------------------

    [Fact]
    public void The_window_is_sent_as_utc_with_a_z()
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 8, 0, 0, 0, DateTimeKind.Utc);

        var query = DemoApiClient.DashboardWindow(from, to, null, "day");

        Assert.Equal("from=2026-11-01T00%3A00%3A00Z&to=2026-11-08T00%3A00%3A00Z&bucket=day", query);
    }

    [Fact]
    public void A_local_kind_is_still_sent_as_its_utc_value()
    {
        // Build the value the tab passes: local midnight converted to UTC.
        var localMidnight = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Unspecified);
        var utc = DateTime.SpecifyKind(localMidnight.Subtract(BusinessClock.Offset), DateTimeKind.Utc);

        Assert.Equal("2026-10-31T17:00:00Z", DemoApiClient.Iso(utc));
    }

    [Fact]
    public void A_store_scope_adds_the_store_id()
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 2, 0, 0, 0, DateTimeKind.Utc);

        var query = DemoApiClient.DashboardWindow(from, to, "STORE-DN1", "week");

        Assert.Contains("store_id=STORE-DN1", query);
        Assert.Contains("bucket=week", query);
    }

    [Fact]
    public void An_empty_store_scope_omits_the_parameter()
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 2, 0, 0, 0, DateTimeKind.Utc);

        Assert.DoesNotContain("store_id", DemoApiClient.DashboardWindow(from, to, "", "day"));
        Assert.DoesNotContain("store_id", DemoApiClient.DashboardWindow(from, to, null, "day"));
    }

    // --- labels and periods -------------------------------------------------

    [Theory]
    [InlineData("day", 7)]
    [InlineData("week", 28)]
    [InlineData("month", 180)]
    [InlineData("quarter", 365)]
    public void Each_period_looks_back_the_documented_number_of_days(string period, int days)
    {
        Assert.Equal(days, DashboardTab.DaysFor(period));
    }

    [Fact]
    public void The_four_periods_are_the_ones_the_plan_lists()
    {
        Assert.Equal(new[] { "day", "week", "month", "quarter" },
            DashboardTab.Periods.Select(period => period.Key).ToArray());
        Assert.Equal(new[] { "Ngày", "Tuần", "Tháng", "Quý" },
            DashboardTab.Periods.Select(period => period.Label).ToArray());
    }

    [Fact]
    public void A_bucket_label_is_shown_in_local_time()
    {
        // 17:00 UTC is local midnight of the next day, so a day bucket labels as 02/11.
        var fromUtc = new DateTime(2026, 11, 1, 17, 0, 0, DateTimeKind.Utc);

        Assert.Equal("02/11", DashboardTab.BucketLabel(fromUtc, "day"));
    }

    [Fact]
    public void Money_is_grouped_without_decimals_for_the_projector()
    {
        Assert.Equal("1,235 đ", DashboardTab.Money(1234.5m));
        Assert.Equal("0 đ", DashboardTab.Money(0m));
        Assert.Equal("-50 đ", DashboardTab.Money(-50m));
    }
}
