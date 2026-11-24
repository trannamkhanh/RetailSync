using System.Globalization;
using StaffApp.Models;

namespace StaffApp.Services;

/// <summary>
/// The rows of the Giảm giá tab (PB-50-3). Numbers and dates use fixed formats (en-US thousands
/// separator, dd/MM), as on the other screens, so a vi-VN machine shows the same text.
/// </summary>
public static class DiscountRows
{
    private static readonly CultureInfo Numbers = CultureInfo.GetCultureInfo("en-US");

    public static readonly string[] Columns =
        { "Cửa hàng", "Khoảng cách", "Sản phẩm", "Lô", "HSD", "Giảm", "Giá", "Từ lúc", "Đã bán giá giảm" };

    /// <summary>The nine cells of one line; <paramref name="zone"/> is the time zone of "Từ lúc".</summary>
    public static string[] Cells(DiscountLine line, string ownStoreId, TimeZoneInfo zone) => new[]
    {
        line.StoreId == ownStoreId ? $"{line.StoreName} (tôi)" : line.StoreName,
        line.DistanceKm is { } km ? $"{km.ToString("0.##", Numbers)} km" : string.Empty,
        $"{line.Name} ({line.Sku})",
        line.BatchId ?? "(SKU)",
        line.ExpiryDate?.ToString("dd/MM/yyyy", CultureInfo.InvariantCulture) ?? string.Empty,
        $"{line.DiscountPct.ToString("0.##", Numbers)}%",
        $"{line.DiscountedPrice.ToString("N0", Numbers)} VND",
        TimeZoneInfo.ConvertTime(line.DecidedAt, zone).ToString("dd/MM HH:mm", CultureInfo.InvariantCulture),
        line.SoldAtDiscount ? "Có" : "Chưa",
    };
}
