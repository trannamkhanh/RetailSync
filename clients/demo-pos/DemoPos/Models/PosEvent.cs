using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace DemoPos.Models;

public static class EventTypes
{
    public const string Sale = "SALE";
    public const string Return = "RETURN";
    public const string Cancellation = "CANCELLATION";
}

/// <summary>DS-04 PosEvent. Timestamp is a string so it always ends in Z.</summary>
public sealed class PosEvent
{
    [JsonPropertyName("event_type")]
    public string EventType { get; set; } = EventTypes.Sale;

    [JsonPropertyName("transaction_id")]
    public string TransactionId { get; set; } = string.Empty;

    [JsonPropertyName("original_transaction_id")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? OriginalTransactionId { get; set; }

    [JsonPropertyName("store_id")]
    public string StoreId { get; set; } = string.Empty;

    [JsonPropertyName("pos_id")]
    public string PosId { get; set; } = string.Empty;

    [JsonPropertyName("timestamp")]
    public string Timestamp { get; set; } = string.Empty;

    [JsonPropertyName("items")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<PosEventItem>? Items { get; set; }
}

public sealed class PosEventItem
{
    [JsonPropertyName("sku")]
    public string Sku { get; set; } = string.Empty;

    [JsonPropertyName("quantity")]
    public int Quantity { get; set; }

    [JsonPropertyName("unit_price")]
    public decimal UnitPrice { get; set; }
}

public static class PosEventJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };

    public static string Serialize(PosEvent value) => JsonSerializer.Serialize(value, Options);

    public static PosEvent Deserialize(string json) =>
        JsonSerializer.Deserialize<PosEvent>(json, Options)
        ?? throw new JsonException("The event body is empty.");

    public static string FormatTimestamp(DateTime utc)
    {
        var value = utc.Kind == DateTimeKind.Utc ? utc : utc.ToUniversalTime();
        return value.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", System.Globalization.CultureInfo.InvariantCulture);
    }
}

public static class TransactionIds
{
    private static readonly Regex Allowed = new("^[A-Za-z0-9_-]+$", RegexOptions.Compiled);
    private static readonly Regex Shape = new("^TXN-[A-Za-z0-9_-]+-[0-9]{14}-[0-9]{4}$", RegexOptions.Compiled);

    /// <summary>TXN-&lt;pos_id&gt;-&lt;yyyyMMddHHmmss&gt;-&lt;4 digits&gt;, at most 40 characters.</summary>
    public static string New(string posId, DateTime? utcNow = null, int? digits = null)
    {
        if (string.IsNullOrWhiteSpace(posId) || posId.Length > 20 || !Allowed.IsMatch(posId))
        {
            throw new ArgumentException($"Invalid POS id: '{posId}'.", nameof(posId));
        }

        var now = utcNow ?? DateTime.UtcNow;
        var suffix = digits ?? RandomNumberGenerator.GetInt32(0, 10_000);
        if (suffix is < 0 or > 9_999)
        {
            throw new ArgumentOutOfRangeException(nameof(digits), "The suffix must fit in four digits.");
        }

        var id = $"TXN-{posId}-{now:yyyyMMddHHmmss}-{suffix:D4}";
        if (id.Length > 40 || !Shape.IsMatch(id))
        {
            throw new InvalidOperationException($"Generated an invalid transaction id: {id}");
        }

        return id;
    }

    public static bool IsValid(string? value) =>
        !string.IsNullOrWhiteSpace(value) && value.Length <= 40 && Shape.IsMatch(value);
}

public static class PosEvents
{
    public static PosEvent Sale(string storeId, string posId, IEnumerable<PosEventItem> items,
                                string? transactionId = null, DateTime? utcNow = null)
    {
        var now = utcNow ?? DateTime.UtcNow;
        return new PosEvent
        {
            EventType = EventTypes.Sale,
            TransactionId = transactionId ?? TransactionIds.New(posId, now),
            StoreId = storeId,
            PosId = posId,
            Timestamp = PosEventJson.FormatTimestamp(now),
            Items = items.ToList(),
        };
    }

    public static PosEvent Return(string storeId, string posId, string originalTransactionId,
                                  IEnumerable<PosEventItem> items, string? transactionId = null,
                                  DateTime? utcNow = null)
    {
        var now = utcNow ?? DateTime.UtcNow;
        return new PosEvent
        {
            EventType = EventTypes.Return,
            TransactionId = transactionId ?? TransactionIds.New(posId, now),
            OriginalTransactionId = originalTransactionId,
            StoreId = storeId,
            PosId = posId,
            Timestamp = PosEventJson.FormatTimestamp(now),
            Items = items.ToList(),
        };
    }

    public static PosEvent Cancellation(string storeId, string posId, string originalTransactionId,
                                        string? transactionId = null, DateTime? utcNow = null)
    {
        var now = utcNow ?? DateTime.UtcNow;
        return new PosEvent
        {
            EventType = EventTypes.Cancellation,
            TransactionId = transactionId ?? TransactionIds.New(posId, now),
            OriginalTransactionId = originalTransactionId,
            StoreId = storeId,
            PosId = posId,
            Timestamp = PosEventJson.FormatTimestamp(now),
            Items = null,
        };
    }
}
