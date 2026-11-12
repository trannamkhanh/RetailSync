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
                RequiredProperty(item, "net_revenue").GetDecimal()))
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
}
