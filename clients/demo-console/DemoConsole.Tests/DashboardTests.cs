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

        // The leading '?' is part of the query string: without it the parameters fuse
        // with the path segment and the middleware answers 404.
        Assert.Equal("?from=2026-11-01T00%3A00%3A00Z&to=2026-11-08T00%3A00%3A00Z&bucket=day", query);
        Assert.StartsWith("?", query);
    }

    [Fact]
    public void A_store_scope_still_starts_with_the_question_mark()
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 8, 0, 0, 0, DateTimeKind.Utc);

        Assert.StartsWith("?", DemoApiClient.DashboardWindow(from, to, "STORE-DN1", "day"));
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
    public void Each_period_looks_back_the_documented_number_of_days(string period, int days)
    {
        Assert.Equal(days, DashboardTab.DaysFor(period));
    }

    [Fact]
    public void The_four_choices_are_the_ones_the_plan_lists()
    {
        // "Quý" is a range, not a bucket: it sends bucket=week over 365 days (design
        // 6.5). Sending "quarter" would be rejected by the API with 422.
        Assert.Equal(new[] { "day", "week", "month", "week" },
            DashboardTab.Periods.Select(period => period.Key).ToArray());
        Assert.Equal(new[] { "Ngày", "Tuần", "Tháng", "Quý" },
            DashboardTab.Periods.Select(period => period.Label).ToArray());
        Assert.Equal(new[] { 7, 28, 180, 365 },
            DashboardTab.Periods.Select(period => period.Days).ToArray());
    }

    [Fact]
    public void Every_period_sends_a_bucket_the_api_accepts()
    {
        // The API accepts exactly these four (repositories/dashboard.py _BUCKET_LOCAL).
        var accepted = new[] { "hour", "day", "week", "month" };

        Assert.All(DashboardTab.Periods, period => Assert.Contains(period.Key, accepted));
    }

    [Fact]
    public void The_quarter_choice_looks_back_a_year()
    {
        Assert.Equal(365, DashboardTab.DaysForIndex(3));
        Assert.Equal(7, DashboardTab.DaysForIndex(0));
        // An out-of-range index falls back to the first choice rather than throwing.
        Assert.Equal(7, DashboardTab.DaysForIndex(99));
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

    // --- chart 2: the category pie ------------------------------------------

    private const string CategoryBody = """
        {
          "scope": { "store_id": null, "is_system_wide": true },
          "time_policy": { "max_future_skew_seconds": 300, "max_backfill_days": 30 },
          "total_revenue": 300.0,
          "transactions": 30,
          "quality": { "on_time": 30, "backfill": 0, "suspect_future": 0, "suspect_old": 0, "unknown": 0 },
          "categories": [
            { "category": "Dairy", "revenue": 150.0, "share": 0.5 },
            { "category": "Bakery", "revenue": 100.0, "share": 0.3333 },
            { "category": "Dry goods", "revenue": 50.0, "share": 0.1667 }
          ]
        }
        """;

    [Fact]
    public void Parses_the_category_pie()
    {
        var pie = ApiParsers.DashboardCategoryRevenue(CategoryBody);

        Assert.True(pie.Scope.IsSystemWide);
        Assert.Equal(3, pie.Categories.Count);
        Assert.Equal(150.0m, pie.Categories[0].Revenue);
        Assert.Equal(0.5m, pie.Categories[0].Share);
        Assert.Equal(30, pie.Quality.OnTime);
    }

    [Fact]
    public void A_category_is_drawn_only_when_it_is_positive()
    {
        var body = CategoryBody.Replace(
            """{ "category": "Dry goods", "revenue": 50.0, "share": 0.1667 }""",
            """{ "category": "Dry goods", "revenue": -50.0, "share": -0.1667 }""");

        var pie = ApiParsers.DashboardCategoryRevenue(body);

        Assert.Equal(2, pie.PositiveSlices.Count);
        Assert.Single(pie.NegativeCategories);
        var note = DashboardTab.NoteLine(pie);
        Assert.Contains("Thực phẩm khô", note);
        Assert.Contains("-50 đ", note);
    }

    [Fact]
    public void The_pie_note_is_empty_when_every_category_is_positive()
    {
        Assert.Equal(string.Empty, DashboardTab.NoteLine(ApiParsers.DashboardCategoryRevenue(CategoryBody)));
    }

    [Fact]
    public void The_pie_note_says_so_when_nothing_can_be_drawn()
    {
        var body = CategoryBody.Replace("\"revenue\": 150.0", "\"revenue\": -150.0")
            .Replace("\"revenue\": 100.0", "\"revenue\": -100.0")
            .Replace("\"revenue\": 50.0", "\"revenue\": -50.0");

        var pie = ApiParsers.DashboardCategoryRevenue(body);

        Assert.Empty(pie.PositiveSlices);
        Assert.Contains("để trống", DashboardTab.NoteLine(pie));
    }

    [Fact]
    public void Category_labels_come_from_the_design_mapping()
    {
        Assert.Equal("Sản phẩm từ sữa", DashboardTab.Label("Dairy"));
        Assert.Equal("Bánh nướng", DashboardTab.Label("Bakery"));
        Assert.Equal("Thực phẩm khô", DashboardTab.Label("Dry goods"));
        // An unmapped category keeps its own name rather than being hidden.
        Assert.Equal("Frozen", DashboardTab.Label("Frozen"));
    }

    // --- chart 3: the store comparison --------------------------------------

    private const string StoreBody = """
        {
          "scope": { "store_id": null, "is_system_wide": true },
          "time_policy": { "max_future_skew_seconds": 300, "max_backfill_days": 30 },
          "data_from": "2026-11-01T00:00:00Z",
          "data_to": "2026-11-08T00:00:00Z",
          "has_data": true,
          "total_revenue": 300.0,
          "transactions": 30,
          "quality": { "on_time": 30, "backfill": 0, "suspect_future": 0, "suspect_old": 0, "unknown": 0 },
          "stores": [
            { "store_id": "STORE-DN1", "name": "Hải Châu", "region_id": "DN", "revenue": 200.0, "share": 0.6667 },
            { "store_id": "STORE-DN2", "name": "Thanh Khê", "region_id": "DN", "revenue": 100.0, "share": 0.3333 }
          ]
        }
        """;

    [Fact]
    public void Parses_the_store_comparison()
    {
        var bars = ApiParsers.DashboardStoreRevenue(StoreBody);

        Assert.Equal(2, bars.Stores.Count);
        Assert.Equal("STORE-DN1", bars.Stores[0].StoreId);
        Assert.Equal("Hải Châu", bars.Stores[0].Name);
        Assert.Equal(200.0m, bars.Stores[0].Revenue);
        Assert.Equal(new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc), bars.DataFromUtc);
    }

    [Fact]
    public void The_comparison_window_repeats_the_key_rather_than_joining_with_commas()
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 8, 0, 0, 0, DateTimeKind.Utc);

        var query = DemoApiClient.StoresWindow(from, to, new[] { "STORE-DN1", "STORE-DN2" });

        Assert.StartsWith("?", query);
        Assert.Contains("compare_store_ids=STORE-DN1", query);
        Assert.Contains("compare_store_ids=STORE-DN2", query);
        Assert.DoesNotContain("STORE-DN1,STORE-DN2", query);
    }

    [Fact]
    public void No_store_ids_asks_for_the_whole_comparison_scope()
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 8, 0, 0, 0, DateTimeKind.Utc);

        Assert.DoesNotContain("compare_store_ids", DemoApiClient.StoresWindow(from, to, null));
        Assert.DoesNotContain("compare_store_ids", DemoApiClient.StoresWindow(from, to, Array.Empty<string>()));
    }

    [Fact]
    public void The_category_window_carries_the_view_scope()
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 8, 0, 0, 0, DateTimeKind.Utc);

        Assert.StartsWith("?", DemoApiClient.CategoryWindow(from, to, null));
        Assert.Contains("store_id=STORE-DN1", DemoApiClient.CategoryWindow(from, to, "STORE-DN1"));
    }

    // --- the pie legend swatches --------------------------------------------

    [Fact]
    public void Every_slice_gets_a_colour_from_the_palette()
    {
        // The legend paints its own swatch, so the colours must come from a list the
        // legend can read. If this ever moves back to the library default palette the
        // swatch and the slice would silently disagree.
        Assert.NotEmpty(DashboardTab.SliceColors);
        Assert.Equal(DashboardTab.SliceColors[0], DashboardTab.SliceColor(0));
        Assert.Equal(DashboardTab.SliceColors[2], DashboardTab.SliceColor(2));
    }

    [Fact]
    public void The_palette_cycles_rather_than_running_out()
    {
        var count = DashboardTab.SliceColors.Length;

        Assert.Equal(DashboardTab.SliceColor(0), DashboardTab.SliceColor(count));
        Assert.Equal(DashboardTab.SliceColor(1), DashboardTab.SliceColor(count + 1));
    }

    [Fact]
    public void The_slices_of_one_pie_never_share_a_colour()
    {
        // Three categories is the demo's shape; each must look different.
        var colours = Enumerable.Range(0, 3).Select(DashboardTab.SliceColor).ToList();

        Assert.Equal(3, colours.Distinct().Count());
    }

    [Fact]
    public void The_winforms_swatch_colour_matches_the_skia_slice_colour()
    {
        var skia = DashboardTab.SliceColor(1);
        var winforms = DashboardTab.SliceColorWinForms(1);

        Assert.Equal(skia.Red, winforms.R);
        Assert.Equal(skia.Green, winforms.G);
        Assert.Equal(skia.Blue, winforms.B);
    }

    [Fact]
    public void The_first_slice_keeps_the_console_blue()
    {
        // The line and the bars are this blue, so the first category matching it keeps
        // the tab looking like one dashboard rather than three charts.
        var first = DashboardTab.SliceColor(0);

        Assert.Equal(0, (int)first.Red);
        Assert.Equal(84, (int)first.Green);
        Assert.Equal(166, (int)first.Blue);
    }
}
