using System.Globalization;
using StaffApp.Services;

namespace StaffApp.Models;

/// <summary>One HTTP answer. Status 0 means nothing answered (network error or timeout).</summary>
public sealed record ApiResult(int Status, string Code, string Message, string Body)
{
    public bool IsSuccess => Status is >= 200 and < 300;

    public bool IsUnreachable => Status == 0;
}

/// <summary>GET /products/barcode/{barcode} (DS-04 ProductLookup).</summary>
public sealed record ProductInfo(string Sku, string Barcode, string Name, string Category, decimal UnitPrice,
                                 int Quantity, IReadOnlyList<BatchLine> Batches);

public sealed record BatchLine(string BatchId, DateOnly ExpiryDate, int Quantity);

/// <summary>GET /products/barcode/{barcode}/stock: the other stores, nearest first.</summary>
public sealed record CrossStoreStock(string Sku, IReadOnlyList<NearbyStore> Stores);

public sealed record NearbyStore(string StoreId, string Name, int Qty, double DistanceKm);

/// <summary>GET /near-expiry-alerts (DS-04 NearExpiryAlert).</summary>
public sealed record AlertLine(long AlertId, string BatchId, string Sku, DateOnly ExpiryDate, int RemainingQty,
                               int DaysToExpiry, string AlertType)
{
    /// <summary>The Urgency column of DS-08 screen 2: the alert type's name, with "Hôm nay hoặc mai" for an
    /// alert that expires within a day (a level from the days left, not a code).</summary>
    public string Urgency => IsExpired ? DisplayNames.AlertType("EXPIRED")
        : DaysToExpiry <= 1 ? "Hôm nay hoặc mai" : DisplayNames.AlertType(AlertType);

    public bool IsExpired => AlertType == "EXPIRED" || DaysToExpiry < 0;
}

/// <summary>GET /recommendations (DS-04 RecommendationSummary).</summary>
public record RecommendationLine(long RecId, string Sku, string ActionType, decimal? DiscountPct, int? ProposedQty,
                                 string Status)
{
    /// <summary>The Hành động column; <c>ActionType</c> keeps the API value.</summary>
    public string ActionLabel => DisplayNames.ActionType(ActionType);

    /// <summary>The Level column of DS-08 screen 3: a percentage for DISCOUNT, units otherwise.
    /// Numbers use the invariant culture, so 12.5 never shows as "12,5" on a vi-VN machine.</summary>
    public string Level => ActionType == "DISCOUNT"
        ? DiscountPct is { } pct ? pct.ToString("0.##", CultureInfo.InvariantCulture) + "%" : "-"
        : ProposedQty is { } qty ? $"{qty} đơn vị" : "-";
}

/// <summary>GET /recommendations/{rec_id} (DS-04 RecommendationDetail).</summary>
public sealed record RecommendationDetail(RecommendationLine Summary, string? BatchId, DateOnly? ExpiryDate,
                                          string Reason, IReadOnlyList<GuardrailLine> GuardrailResults)
{
    /// <summary>The detail title of DS-08, for example "Giảm 50% SKU-0001, lô B-1033".</summary>
    public string Title
    {
        get
        {
            var action = Summary.ActionType == "DISCOUNT" ? $"Giảm {Summary.Level} {Summary.Sku}"  // "Giảm 50%"
                : Summary.ActionLabel == Summary.ActionType ? $"{Summary.ActionType} {Summary.Sku}"  // unknown code
                : $"{Summary.ActionLabel} {Summary.Level} {Summary.Sku}";
            return BatchId is null ? action : $"{action}, lô {BatchId}";
        }
    }
}

public sealed record GuardrailLine(string RuleType, string Outcome, decimal? OriginalValue, decimal? AdjustedValue,
                                   string? Message)
{
    /// <summary>"Hạn dùng tối thiểu: Đạt" or "Giảm giá tối đa: Điều chỉnh 60 -> 50 (message)"; the server
    /// message stays as sent.</summary>
    public string Text
    {
        get
        {
            var text = $"{DisplayNames.RuleType(RuleType)}: {DisplayNames.Outcome(Outcome)}";
            if (Outcome == "ADJUSTED")
            {
                text += string.Create(CultureInfo.InvariantCulture, $" {OriginalValue:0.##} -> {AdjustedValue:0.##}");
            }

            return string.IsNullOrWhiteSpace(Message) ? text : $"{text} ({Message})";
        }
    }
}

/// <summary>GET /staff/discounts (DS-04 StaffDiscount, PB-50). <c>DistanceKm</c> is null for the
/// caller's own store; <c>BatchId</c> and <c>ExpiryDate</c> are null for a SKU-level discount.</summary>
public sealed record DiscountLine(string StoreId, string StoreName, double? DistanceKm, string Sku, string Name,
                                  string? BatchId, DateOnly? ExpiryDate, decimal DiscountPct, decimal ListPrice,
                                  decimal DiscountedPrice, DateTimeOffset DecidedAt, bool SoldAtDiscount);

/// <summary>POST /recommendations/{rec_id}/decision, 200 answer.</summary>
public sealed record DecisionResult(long RecId, string Status, DateTimeOffset DecidedAt);
