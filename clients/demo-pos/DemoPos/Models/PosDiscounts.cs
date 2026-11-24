using System.Globalization;
using System.Text.Json;

namespace DemoPos.Models;

public sealed record PosDiscountItem(string Sku, decimal DiscountPct, decimal DiscountedPrice);

public sealed record PosDiscountList(DateOnly BusinessDate, IReadOnlyList<PosDiscountItem> Items);

public sealed class PosDiscountFetchResult
{
    public bool IsSuccess { get; init; }

    public int HttpStatus { get; init; }

    public double ElapsedMs { get; init; }

    public PosDiscountList? Data { get; init; }

    public string? Error { get; init; }
}

/// <summary>
/// DS-04 PosDiscountList contract (PB-50). The Middleware computes discounted_price;
/// the POS parses numbers with InvariantCulture and never computes its own price.
/// </summary>
public static class PosDiscounts
{
    public const int BusinessUtcOffsetHours = 7;

    public static DateOnly CurrentBusinessDate(DateTime? utcNow = null)
    {
        var instant = utcNow ?? DateTime.UtcNow;
        var utc = instant.Kind == DateTimeKind.Local ? instant.ToUniversalTime() : instant;
        return DateOnly.FromDateTime(utc.AddHours(BusinessUtcOffsetHours));
    }

    public static bool TryParse(string? json, out PosDiscountList? list, out string? error)
    {
        list = null;
        error = null;
        if (string.IsNullOrWhiteSpace(json))
        {
            error = "The discount response body was empty.";
            return false;
        }

        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                error = "The discount response must be a JSON object.";
                return false;
            }

            if (!root.TryGetProperty("business_date", out var dateProp)
                || dateProp.ValueKind != JsonValueKind.String
                || !DateOnly.TryParseExact(dateProp.GetString(), "yyyy-MM-dd",
                    CultureInfo.InvariantCulture, DateTimeStyles.None, out var businessDate))
            {
                error = "Missing or invalid 'business_date' (expected YYYY-MM-DD).";
                return false;
            }

            if (!root.TryGetProperty("items", out var itemsProp)
                || itemsProp.ValueKind != JsonValueKind.Array)
            {
                error = "Missing or invalid 'items' array.";
                return false;
            }

            var bySku = new Dictionary<string, PosDiscountItem>(StringComparer.OrdinalIgnoreCase);
            var orderedSkus = new List<string>();
            foreach (var element in itemsProp.EnumerateArray())
            {
                if (element.ValueKind != JsonValueKind.Object)
                {
                    error = "Each discount item must be a JSON object.";
                    return false;
                }

                if (!element.TryGetProperty("sku", out var skuProp)
                    || skuProp.ValueKind != JsonValueKind.String
                    || string.IsNullOrWhiteSpace(skuProp.GetString()))
                {
                    error = "Discount item is missing a valid 'sku'.";
                    return false;
                }

                var sku = skuProp.GetString()!.Trim();
                if (!TryReadDecimal(element, "discount_pct", out var pct) || pct < 0m || pct > 100m)
                {
                    error = $"Invalid 'discount_pct' for SKU '{sku}'.";
                    return false;
                }

                if (!TryReadDecimal(element, "discounted_price", out var discountedPrice) || discountedPrice < 0m)
                {
                    error = $"Invalid 'discounted_price' for SKU '{sku}'.";
                    return false;
                }

                var candidate = new PosDiscountItem(sku, pct, discountedPrice);
                if (!bySku.TryGetValue(sku, out var existing))
                {
                    bySku[sku] = candidate;
                    orderedSkus.Add(sku);
                }
                else if (candidate.DiscountPct > existing.DiscountPct)
                {
                    bySku[sku] = candidate;
                }
            }

            var items = orderedSkus.Select(sku => bySku[sku]).ToList();
            list = new PosDiscountList(businessDate, items);
            return true;
        }
        catch (JsonException ex)
        {
            error = $"Invalid discount JSON: {ex.Message}";
            return false;
        }
    }

    private static bool TryReadDecimal(JsonElement parent, string propertyName, out decimal value)
    {
        value = 0m;
        if (!parent.TryGetProperty(propertyName, out var prop))
        {
            return false;
        }

        const NumberStyles styles = NumberStyles.AllowLeadingSign
                                    | NumberStyles.AllowDecimalPoint
                                    | NumberStyles.AllowLeadingWhite
                                    | NumberStyles.AllowTrailingWhite;

        return prop.ValueKind switch
        {
            JsonValueKind.Number => decimal.TryParse(prop.GetRawText(), styles, CultureInfo.InvariantCulture, out value),
            JsonValueKind.String => decimal.TryParse(prop.GetString(), styles, CultureInfo.InvariantCulture, out value),
            _ => false,
        };
    }
}
