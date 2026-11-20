using System.Globalization;

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
    /// <summary>The Urgency column of DS-08 screen 2.</summary>
    public string Urgency => AlertType == "EXPIRED" || DaysToExpiry < 0
        ? "EXPIRED"
        : DaysToExpiry <= 1 ? "Today or tomorrow" : "Soon";
}

/// <summary>GET /recommendations (DS-04 RecommendationSummary).</summary>
public record RecommendationLine(long RecId, string Sku, string ActionType, decimal? DiscountPct, int? ProposedQty,
                                 string Status)
{
    /// <summary>The Level column of DS-08 screen 3: a percentage for DISCOUNT, units otherwise.
    /// Numbers use the invariant culture, so 12.5 never shows as "12,5" on a vi-VN machine.</summary>
    public string Level => ActionType == "DISCOUNT"
        ? DiscountPct is { } pct ? pct.ToString("0.##", CultureInfo.InvariantCulture) + "%" : "-"
        : ProposedQty is { } qty ? (qty == 1 ? "1 unit" : $"{qty} units") : "-";
}

/// <summary>GET /recommendations/{rec_id} (DS-04 RecommendationDetail).</summary>
public sealed record RecommendationDetail(RecommendationLine Summary, string? BatchId, DateOnly? ExpiryDate,
                                          string Reason, IReadOnlyList<GuardrailLine> GuardrailResults)
{
    /// <summary>The detail title of DS-08, for example "Discount 50% on SKU-0001, batch B-1033".</summary>
    public string Title
    {
        get
        {
            var action = Summary.ActionType switch
            {
                "DISCOUNT" => $"Discount {Summary.Level} on {Summary.Sku}",
                "CLEARANCE" => $"Clearance of {Summary.Level} of {Summary.Sku}",
                "REDISTRIBUTION" => $"Redistribute {Summary.Level} of {Summary.Sku}",
                _ => $"{Summary.ActionType} {Summary.Sku}",
            };
            return BatchId is null ? action : $"{action}, batch {BatchId}";
        }
    }
}

public sealed record GuardrailLine(string RuleType, string Outcome, decimal? OriginalValue, decimal? AdjustedValue,
                                   string? Message)
{
    /// <summary>"MIN_SHELF_LIFE: passed" or "MAX_DISCOUNT: adjusted 60 -> 50 (message)".</summary>
    public string Text
    {
        get
        {
            var text = Outcome == "ADJUSTED"
                ? string.Create(CultureInfo.InvariantCulture,
                    $"{RuleType}: adjusted {OriginalValue:0.##} -> {AdjustedValue:0.##}")
                : $"{RuleType}: {Outcome.ToLowerInvariant()}";
            return string.IsNullOrWhiteSpace(Message) ? text : $"{text} ({Message})";
        }
    }
}

/// <summary>POST /recommendations/{rec_id}/decision, 200 answer.</summary>
public sealed record DecisionResult(long RecId, string Status, DateTimeOffset DecidedAt);
