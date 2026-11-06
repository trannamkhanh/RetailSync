using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace DemoPos.Models;

public sealed class StoreInventory
{
    [JsonPropertyName("store_id")]
    public string StoreId { get; set; } = string.Empty;

    [JsonPropertyName("items")]
    public List<StockLine> Items { get; set; } = new();
}

public sealed class StockLine
{
    [JsonPropertyName("sku")]
    public string Sku { get; set; } = string.Empty;

    [JsonPropertyName("quantity")]
    public int Quantity { get; set; }
}

public sealed class AuditLogList
{
    [JsonPropertyName("items")]
    public List<AuditEntry> Items { get; set; } = new();
}

public sealed class AuditEntry
{
    [JsonPropertyName("audit_id")]
    public long AuditId { get; set; }

    [JsonPropertyName("user_id")]
    public int? UserId { get; set; }

    [JsonPropertyName("action")]
    public string Action { get; set; } = string.Empty;

    [JsonPropertyName("entity_name")]
    public string EntityName { get; set; } = string.Empty;

    [JsonPropertyName("entity_key")]
    public string? EntityKey { get; set; }

    [JsonPropertyName("details")]
    public string? Details { get; set; }

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = string.Empty;
}

public sealed class HealthResponse
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = string.Empty;
}

public sealed class ApiCallResult<T>
{
    public bool IsSuccess { get; init; }

    public int Status { get; init; }

    public double ElapsedMs { get; init; }

    public T? Data { get; init; }

    public string? Error { get; init; }

    public string RawBody { get; init; } = string.Empty;
}

public sealed class StockRow
{
    public required string Sku { get; init; }

    public required string Name { get; init; }

    public int Quantity { get; init; }
}

public sealed class AuditRow
{
    public required string TimeText { get; init; }

    public required string Action { get; init; }

    public required string EntityKey { get; init; }

    public required string Details { get; init; }

    public static AuditRow From(AuditEntry entry, TimeZoneInfo? zone = null)
    {
        var text = entry.CreatedAt;
        if (DateTimeOffset.TryParse(entry.CreatedAt, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var parsed))
        {
            var local = TimeZoneInfo.ConvertTime(parsed, zone ?? TimeZoneInfo.Local);
            text = local.ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        }

        return new AuditRow
        {
            TimeText = text,
            Action = entry.Action,
            EntityKey = entry.EntityKey ?? "—",
            Details = entry.Details ?? string.Empty,
        };
    }
}

public static class MonitorJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        AllowTrailingCommas = true,
    };
}
