using System.Globalization;
using System.Text.Json;
using StaffApp.Models;

namespace StaffApp.Services;

/// <summary>
/// Parses the Staff API answers (DS-04). Each parser takes the raw body and throws
/// <see cref="FormatException"/> when a required field is missing or has the wrong type,
/// so a contract change shows as an error instead of a wrong figure. A decimal may come
/// as a JSON number or as a numeric string.
/// </summary>
public static class ApiParsers
{
    /// <summary>The {outcome, code, message} error body; empty strings when absent.</summary>
    public static (string Code, string Message) ErrorOf(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return (string.Empty, string.Empty);
        }

        try
        {
            using var document = JsonDocument.Parse(body);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return (string.Empty, string.Empty);
            }

            return (OptionalString(root, "code") ?? string.Empty, OptionalString(root, "message") ?? string.Empty);
        }
        catch (JsonException)
        {
            return (string.Empty, string.Empty);
        }
    }

    public static ProductInfo Product(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        var batches = new List<BatchLine>();
        if (root.TryGetProperty("batches", out var array) && array.ValueKind == JsonValueKind.Array)
        {
            foreach (var batch in array.EnumerateArray())
            {
                batches.Add(new BatchLine(RequiredString(batch, "batch_id"), RequiredDate(batch, "expiry_date"),
                    RequiredInt(batch, "quantity")));
            }
        }

        return new ProductInfo(RequiredString(root, "sku"), RequiredString(root, "barcode"),
            RequiredString(root, "name"), RequiredString(root, "category"), RequiredDecimal(root, "unit_price"),
            RequiredInt(root, "quantity"), batches);
    }

    public static CrossStoreStock CrossStore(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        var stores = RequiredArray(root, "stores")
            .Select(store => new NearbyStore(RequiredString(store, "store_id"), RequiredString(store, "name"),
                RequiredInt(store, "qty"), (double)RequiredDecimal(store, "distance_km")))
            .ToList();
        return new CrossStoreStock(RequiredString(root, "sku"), stores);
    }

    public static IReadOnlyList<AlertLine> Alerts(string body)
    {
        using var document = Parse(body);
        return RequiredArray(document.RootElement, "items")
            .Select(item => new AlertLine(RequiredLong(item, "alert_id"), RequiredString(item, "batch_id"),
                RequiredString(item, "sku"), RequiredDate(item, "expiry_date"), RequiredInt(item, "remaining_qty"),
                RequiredInt(item, "days_to_expiry"), RequiredString(item, "alert_type")))
            .ToList();
    }

    public static IReadOnlyList<RecommendationLine> Recommendations(string body)
    {
        using var document = Parse(body);
        return RequiredArray(document.RootElement, "items").Select(Summary).ToList();
    }

    public static RecommendationDetail Detail(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        var expiry = OptionalString(root, "expiry_date");
        var results = RequiredArray(root, "guardrail_results")
            .Select(result => new GuardrailLine(RequiredString(result, "rule_type"), RequiredString(result, "outcome"),
                OptionalDecimal(result, "original_value"), OptionalDecimal(result, "adjusted_value"),
                OptionalString(result, "message")))
            .ToList();
        return new RecommendationDetail(Summary(root), OptionalString(root, "batch_id"),
            expiry is null ? null : ParseDate(expiry, "expiry_date"), RequiredString(root, "reason"), results);
    }

    public static DecisionResult Decision(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        return new DecisionResult(RequiredLong(root, "rec_id"), RequiredString(root, "status"),
            RequiredMoment(root, "decided_at"));
    }

    public static IReadOnlyList<DiscountLine> Discounts(string body)
    {
        using var document = Parse(body);
        return RequiredArray(document.RootElement, "items")
            .Select(item =>
            {
                var expiry = OptionalString(item, "expiry_date");
                return new DiscountLine(RequiredString(item, "store_id"), RequiredString(item, "store_name"),
                    OptionalDecimal(item, "distance_km") is { } distance ? (double)distance : null,
                    RequiredString(item, "sku"), RequiredString(item, "name"), OptionalString(item, "batch_id"),
                    expiry is null ? null : ParseDate(expiry, "expiry_date"), RequiredDecimal(item, "discount_pct"),
                    RequiredDecimal(item, "list_price"), RequiredDecimal(item, "discounted_price"),
                    RequiredMoment(item, "decided_at"), RequiredBool(item, "sold_at_discount"));
            })
            .ToList();
    }

    private static RecommendationLine Summary(JsonElement item) =>
        new(RequiredLong(item, "rec_id"), RequiredString(item, "sku"), RequiredString(item, "action_type"),
            OptionalDecimal(item, "discount_pct"), OptionalInt(item, "proposed_qty"), RequiredString(item, "status"));

    // --- Helpers ------------------------------------------------------------

    private static JsonDocument Parse(string body)
    {
        try
        {
            var document = JsonDocument.Parse(body);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                document.Dispose();
                throw new FormatException("The answer is not a JSON object.");
            }

            return document;
        }
        catch (JsonException error)
        {
            throw new FormatException("The answer is not valid JSON.", error);
        }
    }

    private static JsonElement Required(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value)
            && value.ValueKind != JsonValueKind.Null
            ? value
            : throw new FormatException($"Missing field '{name}'.");

    private static IEnumerable<JsonElement> RequiredArray(JsonElement element, string name)
    {
        var value = Required(element, name);
        return value.ValueKind == JsonValueKind.Array
            ? value.EnumerateArray().ToList()
            : throw new FormatException($"Field '{name}' is not an array.");
    }

    private static string RequiredString(JsonElement element, string name)
    {
        var value = Required(element, name);
        return value.ValueKind == JsonValueKind.String
            ? value.GetString()!
            : throw new FormatException($"Field '{name}' is not a string.");
    }

    private static string? OptionalString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int RequiredInt(JsonElement element, string name)
    {
        var value = Required(element, name);
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : throw new FormatException($"Field '{name}' is not an integer.");
    }

    private static int? OptionalInt(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null
            ? RequiredInt(element, name)
            : null;

    private static long RequiredLong(JsonElement element, string name)
    {
        var value = Required(element, name);
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)
            ? number
            : throw new FormatException($"Field '{name}' is not an integer.");
    }

    private static decimal RequiredDecimal(JsonElement element, string name)
    {
        var value = Required(element, name);
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var number))
        {
            return number;
        }

        if (value.ValueKind == JsonValueKind.String && decimal.TryParse(value.GetString(), NumberStyles.Number,
                CultureInfo.InvariantCulture, out var parsed))
        {
            return parsed;
        }

        throw new FormatException($"Field '{name}' is not a number.");
    }

    private static decimal? OptionalDecimal(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null
            ? RequiredDecimal(element, name)
            : null;

    private static bool RequiredBool(JsonElement element, string name) =>
        Required(element, name).ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new FormatException($"Field '{name}' is not a boolean."),
        };

    private static DateTimeOffset RequiredMoment(JsonElement element, string name)
    {
        var text = RequiredString(element, name);
        return DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var moment)
            ? moment
            : throw new FormatException($"{name} is not a date-time: {text}");
    }

    private static DateOnly RequiredDate(JsonElement element, string name) =>
        ParseDate(RequiredString(element, name), name);

    private static DateOnly ParseDate(string text, string name) =>
        DateOnly.TryParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date)
            ? date
            : throw new FormatException($"Field '{name}' is not a yyyy-MM-dd date.");
}
