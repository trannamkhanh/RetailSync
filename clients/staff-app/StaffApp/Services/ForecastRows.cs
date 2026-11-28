using System.Globalization;
using StaffApp.Models;

namespace StaffApp.Services;

/// <summary>Independent chart selections never reorder the table/API list.</summary>
public static class ForecastRows
{
    public static readonly string[] Columns = { "Sản phẩm", "Danh mục", "Dự báo 7 ngày tới",
        "Tồn bán được", "Thừa/Thiếu", "Trạng thái", "Mô hình", "Cập nhật lúc" };

    public static IReadOnlyList<ForecastLine> Top10(IEnumerable<ForecastLine> lines) =>
        lines.OrderByDescending(x => x.PredictedDemand).ThenBy(x => x.Sku, StringComparer.Ordinal).Take(10).ToArray();

    public static IReadOnlyList<ForecastLine> Shortages(IEnumerable<ForecastLine> lines) =>
        lines.Where(x => x.BalanceStatus == "SHORTAGE").OrderBy(x => x.SurplusShortage)
            .ThenBy(x => x.Sku, StringComparer.Ordinal).ToArray();

    public static string[] Cells(ForecastLine x, TimeZoneInfo zone) => new[] {
        $"{x.Name} ({x.Sku})", DisplayNames.Category(x.Category),
        x.PredictedDemand.ToString("#,##0.##", CultureInfo.InvariantCulture),
        x.SellableStock.ToString("N0", CultureInfo.InvariantCulture),
        x.SurplusShortage.ToString("0.##", CultureInfo.InvariantCulture),
        DisplayNames.BalanceStatus(x.BalanceStatus), x.ModelVersion,
        TimeZoneInfo.ConvertTime(x.CreatedAt, zone).ToString("dd/MM HH:mm", CultureInfo.InvariantCulture),
    };
}
