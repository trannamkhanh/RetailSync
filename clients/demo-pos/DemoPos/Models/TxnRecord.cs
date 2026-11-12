namespace DemoPos.Models;

public sealed class TxnRecord
{
    public DateTime Time { get; init; } = DateTime.Now;

    public required string EventType { get; init; }

    public required string TransactionId { get; init; }

    public required string StoreId { get; init; }

    public required string PosId { get; init; }

    public string? OriginalTransactionId { get; init; }

    public required string ItemsText { get; init; }

    public required string Outcome { get; set; }

    public required string Code { get; set; }

    /// <summary>The exact body sent, used by Send again and Retry.</summary>
    public required string RawBody { get; init; }

    public List<PosEventItem> Items { get; init; } = new();

    public bool IsSale => EventType == EventTypes.Sale;

    public bool CanReturnOrCancel => IsSale && Outcome == nameof(PosOutcome.OK);

    public string TimeText => Time.ToString("HH:mm:ss");

    public string TypeText => EventType;
}

public sealed class ProductRow
{
    public required string Sku { get; init; }

    public required string Name { get; init; }

    public required string Barcode { get; init; }

    public decimal UnitPrice { get; init; }

    public string UnitPriceText => UnitPrice.ToString("N0");

    public string SearchText => $"{Sku} {Name} {Barcode}";
}

public sealed class CartItem
{
    public required string Sku { get; init; }

    public required string Name { get; init; }

    public required decimal UnitPrice { get; init; }

    public int Quantity { get; set; }

    public decimal LineTotal => UnitPrice * Quantity;
}

public sealed class TerminalRow
{
    public required string StoreName { get; init; }

    public required string PosId { get; init; }

    public required string CertificateText { get; init; }

    public required string KeyText { get; init; }

    public required string Fingerprint { get; init; }

    public string LastResult { get; set; } = "—";

    public string LastTime { get; set; } = "—";
}
