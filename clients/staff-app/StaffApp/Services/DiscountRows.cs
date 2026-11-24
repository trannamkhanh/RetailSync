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

    /// <summary>
    /// The narrowest text width that shows <paramref name="header"/> in at most two lines, breaking at
    /// one space: the smaller of the widest line over every split, or the whole header when it has
    /// one word. <paramref name="measure"/> gives the width of a text.
    /// </summary>
    public static int TwoLineWidth(string header, Func<string, int> measure)
    {
        var words = header.Split(' ');
        var best = measure(header);
        for (var i = 1; i < words.Length; i++)
        {
            best = Math.Min(best, Math.Max(measure(string.Join(' ', words[..i])), measure(string.Join(' ', words[i..]))));
        }

        return best;
    }

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
