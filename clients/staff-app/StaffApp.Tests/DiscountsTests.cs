using StaffApp.Models;
using StaffApp.Services;
using Xunit;

namespace StaffApp.Tests;

/// <summary>PB-50-3: the read-only Giảm giá tab (GET /staff/discounts), parsing and row mapping.</summary>
public class DiscountsTests
{
    private const string Body = """
        {"items":[
          {"store_id":"STORE-DN1","store_name":"Cửa hàng Hải Châu","distance_km":null,"sku":"SKU-0001",
           "name":"Fresh milk 1L","batch_id":"B-STORE-DN1-SKU-0001-1","expiry_date":"2026-11-25",
           "discount_pct":30.0,"list_price":32000.0,"discounted_price":22400.0,
           "decided_at":"2026-11-23T07:29:45Z","sold_at_discount":true},
          {"store_id":"STORE-DN3","store_name":"Cửa hàng Sơn Trà","distance_km":1.72,"sku":"SKU-0002",
           "name":"Yogurt 100g","batch_id":null,"expiry_date":null,
           "discount_pct":"12.50","list_price":"7000.00","discounted_price":"6100.00",
           "decided_at":"2026-11-23T16:59:00Z","sold_at_discount":false}]}
        """;

    private static readonly TimeZoneInfo Vietnam = TimeZoneInfo.CreateCustomTimeZone("UTC+7", TimeSpan.FromHours(7),
        "UTC+7", "UTC+7");

    [Fact]
    public void Pb50_3_discounts_parse_numbers_strings_and_nulls()
    {
        var lines = ApiParsers.Discounts(Body);

        Assert.Equal(2, lines.Count);
        Assert.Equal(("STORE-DN1", null, "B-STORE-DN1-SKU-0001-1", new DateOnly(2026, 11, 25), 30m, 32000m, 22400m, true),
            (lines[0].StoreId, lines[0].DistanceKm, lines[0].BatchId, lines[0].ExpiryDate, lines[0].DiscountPct,
             lines[0].ListPrice, lines[0].DiscountedPrice, lines[0].SoldAtDiscount));
        Assert.Equal(new DateTimeOffset(2026, 11, 23, 7, 29, 45, TimeSpan.Zero), lines[0].DecidedAt);
        Assert.Equal((1.72, null, null, 12.5m, 6100m),
            (lines[1].DistanceKm, lines[1].BatchId, lines[1].ExpiryDate, lines[1].DiscountPct, lines[1].DiscountedPrice));
    }

    [Fact]
    public void Pb50_3_rows_show_the_nine_columns_in_vietnamese()
    {
        var lines = ApiParsers.Discounts(Body);

        Assert.Equal(new[] { "Cửa hàng", "Khoảng cách", "Sản phẩm", "Lô", "HSD", "Giảm", "Giá", "Từ lúc", "Đã bán giá giảm" },
            DiscountRows.Columns);
        Assert.Equal(new[]
            {
                "Cửa hàng Hải Châu (tôi)", "", "Fresh milk 1L (SKU-0001)", "B-STORE-DN1-SKU-0001-1", "25/11/2026",
                "30%", "22,400 VND", "23/11 14:29", "Có",
            },
            DiscountRows.Cells(lines[0], "STORE-DN1", Vietnam));
        Assert.Equal(new[]
            {
                "Cửa hàng Sơn Trà", "1.72 km", "Yogurt 100g (SKU-0002)", "(SKU)", "", "12.5%", "6,100 VND",
                "23/11 23:59", "Chưa",
            },
            DiscountRows.Cells(lines[1], "STORE-DN1", Vietnam));
    }

    [Fact]
    public void Pb50_3_numbers_ignore_the_machine_culture()
    {
        var previous = System.Globalization.CultureInfo.CurrentCulture;
        System.Globalization.CultureInfo.CurrentCulture = new System.Globalization.CultureInfo("vi-VN");
        try
        {
            var cells = DiscountRows.Cells(ApiParsers.Discounts(Body)[1], "STORE-DN1", Vietnam);

            Assert.Equal(("1.72 km", "12.5%", "6,100 VND"), (cells[1], cells[5], cells[6]));
        }
        finally
        {
            System.Globalization.CultureInfo.CurrentCulture = previous;
        }
    }

    [Fact]
    public void Pb50_3_an_empty_list_parses_and_has_its_message()
    {
        Assert.Empty(ApiParsers.Discounts("""{"items":[]}"""));
        Assert.Equal("Không có giảm giá đang áp dụng.", UserMessages.NoDiscounts);
    }

    [Fact]
    public void Pb50_3_a_missing_field_is_a_format_error()
    {
        Assert.Throws<FormatException>(() => ApiParsers.Discounts("""{"items":[{"store_id":"STORE-DN1"}]}"""));
    }

    [Theory]
    [InlineData(401, "Token không hợp lệ hoặc đã hết hạn", false)]
    [InlineData(403, "Vai trò này không dùng được chức năng này", false)]
    [InlineData(503, "Lỗi máy chủ (HTTP 503). Bấm Thử lại.", true)]
    public void Pb50_3_errors_map_like_the_other_screens(int status, string text, bool canRetry)
    {
        var message = UserMessages.For(new ApiResult(status, string.Empty, string.Empty, string.Empty), ApiArea.Discounts);

        Assert.Equal((text, canRetry), (message.Text, message.CanRetry));
    }

    [Fact]
    public void Pb50_3_network_error_offers_retry()
    {
        var message = UserMessages.For(new ApiResult(0, string.Empty, "no answer within 10 s", string.Empty),
            ApiArea.Discounts);

        Assert.True(message.CanRetry);
        Assert.StartsWith("Không kết nối được máy chủ", message.Text);
    }
}
