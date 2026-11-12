namespace DemoConsole.Models;

/// <summary>One HTTP answer: status 0 means no answer (unreachable or timed out).</summary>
public sealed record ApiResult(int Status, string Code, string Message, string Body, double ElapsedMs)
{
    public bool IsSuccess => Status is >= 200 and < 300;

    public bool IsUnreachable => Status == 0;

    /// <summary>One line for the result bar: status, code and message.</summary>
    public string Summary => IsUnreachable
        ? $"no answer: {Message}"
        : $"HTTP {Status}{(Code.Length > 0 ? " " + Code : string.Empty)}{(Message.Length > 0 ? " - " + Message : string.Empty)}";
}

public sealed record BatchInfo(string BatchId, DateOnly ExpiryDate, int Quantity);

public sealed record StockLine(string StoreId, string Sku, int Quantity, IReadOnlyList<BatchInfo> Batches)
{
    public int SellableOn(DateOnly today) => Batches.Where(batch => batch.ExpiryDate >= today).Sum(batch => batch.Quantity);
}

public sealed record AuditRow(long AuditId, string Action, string EntityName, string? EntityKey,
                              string? Details, DateTime CreatedAtUtc);

public sealed record HqBatch(string BatchId, string StoreId, int TxnCount, DateTime ReceivedAtUtc, int DuplicateCount);

public sealed record HqTotal(string StoreId, string Sku, int SoldQty, int ReturnedQty, decimal NetRevenue);

public sealed record HqView(IReadOnlyList<HqBatch> Batches, IReadOnlyList<HqTotal> Totals);

public sealed record SyncRunResult(int BatchesCreated, int BatchesSent, int BatchesPending);

public sealed record JobRunResult(string Job, string Status);
