using System.Globalization;
using System.Text.Json;
using DemoConsole.Models;

namespace DemoConsole.Services;

/// <summary>
/// Parses the API answers the console reads. Each parser takes the raw body and
/// throws <see cref="FormatException"/> when a required field is missing, so a
/// contract change shows up as an error line instead of a wrong number.
/// </summary>
public static class ApiParsers
{
    /// <summary>The {outcome, code, message} error body, or the HQ NACK body; empty when absent.</summary>
    public static (string Code, string Message) ErrorOf(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return (string.Empty, string.Empty);
        }

        try
        {
            using var document = JsonDocument.Parse(body);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                return (string.Empty, string.Empty);
            }

            var root = document.RootElement;
            return (OptionalString(root, "code") ?? string.Empty, OptionalString(root, "message") ?? string.Empty);
        }
        catch (JsonException)
        {
            return (string.Empty, string.Empty);
        }
    }

    /// <summary>GET /stores/{id}/inventory.</summary>
    public static IReadOnlyList<StockLine> Inventory(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        var storeId = RequiredString(root, "store_id");
        var lines = new List<StockLine>();
        foreach (var item in RequiredArray(root, "items"))
        {
            var batches = new List<BatchInfo>();
            if (item.TryGetProperty("batches", out var batchArray) && batchArray.ValueKind == JsonValueKind.Array)
            {
                foreach (var batch in batchArray.EnumerateArray())
                {
                    batches.Add(new BatchInfo(
                        RequiredString(batch, "batch_id"),
                        DateOnly.ParseExact(RequiredString(batch, "expiry_date"), "yyyy-MM-dd", CultureInfo.InvariantCulture),
                        RequiredInt(batch, "quantity")));
                }
            }

            lines.Add(new StockLine(storeId, RequiredString(item, "sku"), RequiredInt(item, "quantity"), batches));
        }

        return lines;
    }

    /// <summary>GET /audit-logs.</summary>
    public static IReadOnlyList<AuditRow> AuditLogs(string body)
    {
        using var document = Parse(body);
        return RequiredArray(document.RootElement, "items")
            .Select(item => new AuditRow(
                RequiredLong(item, "audit_id"),
                RequiredString(item, "action"),
                RequiredString(item, "entity_name"),
                OptionalString(item, "entity_key"),
                OptionalString(item, "details"),
                RequiredUtc(item, "created_at")))
            .ToList();
    }

    /// <summary>GET /demo/batches on the HQ demo service.</summary>
    public static HqView DemoBatches(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        var batches = RequiredArray(root, "batches")
            .Select(item => new HqBatch(
                RequiredString(item, "batch_id"),
                RequiredString(item, "store_id"),
                RequiredInt(item, "txn_count"),
                RequiredUtc(item, "received_at"),
                RequiredInt(item, "duplicate_count")))
            .ToList();
        var totals = RequiredArray(root, "totals")
            .Select(item => new HqTotal(
                OptionalString(item, "store_id") ?? string.Empty,
                RequiredString(item, "sku"),
                RequiredInt(item, "sold_qty"),
                RequiredInt(item, "returned_qty"),
                RequiredDecimal(item, "net_revenue")))
            .ToList();
        return new HqView(batches, totals);
    }

    /// <summary>POST /sync/run (202).</summary>
    public static SyncRunResult SyncRun(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        return new SyncRunResult(RequiredInt(root, "batches_created"), RequiredInt(root, "batches_sent"),
            RequiredInt(root, "batches_pending"));
    }

    /// <summary>POST /admin/jobs/{name}/run (200).</summary>
    public static JobRunResult JobRun(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        return new JobRunResult(RequiredString(root, "job"), RequiredString(root, "status"));
    }

    /// <summary>PUT /demo/mode (200).</summary>
    public static string DemoMode(string body)
    {
        using var document = Parse(body);
        return RequiredString(document.RootElement, "mode");
    }

    /// <summary>GET /dashboard/revenue.</summary>
    public static DashboardRevenue DashboardRevenue(string body)
    {
        using var document = Parse(body);
        var root = document.RootElement;
        var scope = RequiredProperty(root, "scope");
        var policy = RequiredProperty(root, "time_policy");
        var quality = RequiredProperty(root, "quality");

        var buckets = RequiredArray(root, "buckets")
            .Select(item => new DashboardBucket(
                RequiredUtc(item, "from"),
                RequiredUtc(item, "to"),
                RequiredDecimal(item, "revenue"),
                RequiredInt(item, "transactions")))
            .ToList();

        return new DashboardRevenue(
            new DashboardScope(OptionalString(scope, "store_id"), RequiredBool(scope, "is_system_wide")),
            new DashboardTimePolicy(RequiredInt(policy, "max_future_skew_seconds"),
                RequiredInt(policy, "max_backfill_days")),
            OptionalUtc(root, "data_from"),
            OptionalUtc(root, "data_to"),
            RequiredBool(root, "has_data"),
            RequiredDecimal(root, "total_revenue"),
            RequiredInt(root, "transactions"),
            new DashboardTimeQuality(
                RequiredInt(quality, "on_time"),
                RequiredInt(quality, "backfill"),
                RequiredInt(quality, "suspect_future"),
                RequiredInt(quality, "suspect_old"),
                RequiredInt(quality, "unknown")),
            buckets);
    }

    /// <summary>GET /dashboard/stores.</summary>
    public static IReadOnlyList<DashboardStore> DashboardStores(string body)
    {
        using var document = Parse(body);
        return RequiredArray(document.RootElement, "stores")
            .Select(item => new DashboardStore(
                RequiredString(item, "store_id"),
                RequiredString(item, "name"),
                RequiredString(item, "region_id"),
                RequiredBool(item, "is_active")))
            .ToList();
    }

    private static JsonDocument Parse(string body)
    {
        try
        {
            var document = JsonDocument.Parse(body);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                document.Dispose();
                throw new FormatException("Expected a JSON object.");
            }

            return document;
        }
        catch (JsonException error)
        {
            throw new FormatException($"Not JSON: {error.Message}", error);
        }
    }

    private static JsonElement RequiredProperty(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            throw new FormatException($"Missing field '{name}'.");
        }

        return value;
    }

    private static IEnumerable<JsonElement> RequiredArray(JsonElement element, string name)
    {
        var value = RequiredProperty(element, name);
        if (value.ValueKind != JsonValueKind.Array)
        {
            throw new FormatException($"Field '{name}' is not a list.");
        }

        return value.EnumerateArray().ToList();
    }

    private static string RequiredString(JsonElement element, string name)
    {
        var value = RequiredProperty(element, name);
        return value.ValueKind == JsonValueKind.String
            ? value.GetString()!
            : throw new FormatException($"Field '{name}' is not text.");
    }

    private static string? OptionalString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int RequiredInt(JsonElement element, string name)
    {
        var value = RequiredProperty(element, name);
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : throw new FormatException($"Field '{name}' is not a whole number.");
    }

    private static long RequiredLong(JsonElement element, string name)
    {
        var value = RequiredProperty(element, name);
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)
            ? number
            : throw new FormatException($"Field '{name}' is not a whole number.");
    }

    /// <summary>
    /// A decimal field, as a JSON number or as a numeric string (audit #7).
    /// <c>GetDecimal()</c> throws <see cref="InvalidOperationException"/> for a
    /// string, which escaped every caller as a crash instead of an error line, so
    /// both forms are read here with the invariant culture and anything else is a
    /// <see cref="FormatException"/> that names the field.
    /// </summary>
    private static decimal RequiredDecimal(JsonElement element, string name)
    {
        var value = RequiredProperty(element, name);
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var number))
        {
            return number;
        }

        if (value.ValueKind == JsonValueKind.String && decimal.TryParse(value.GetString(),
                NumberStyles.Number, CultureInfo.InvariantCulture, out var parsed))
        {
            return parsed;
        }

        throw new FormatException($"Field '{name}' is not a number.");
    }

    private static DateTime RequiredUtc(JsonElement element, string name)
    {
        var text = RequiredString(element, name);
        if (!DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var value))
        {
            throw new FormatException($"Field '{name}' is not a date and time: '{text}'.");
        }

        return value.UtcDateTime;
    }

    private static DateTime? OptionalUtc(JsonElement element, string name) =>
        OptionalString(element, name) is null ? null : RequiredUtc(element, name);

    private static bool RequiredBool(JsonElement element, string name)
    {
        var value = RequiredProperty(element, name);
        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new FormatException($"Field '{name}' is not true or false."),
        };
    }
}
