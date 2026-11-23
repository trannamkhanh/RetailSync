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

// --- Dashboard (PB-49, plan D3) --------------------------------------------

/// <summary>The thresholds the server applied; the console shows them and never recomputes.</summary>
public sealed record DashboardTimePolicy(int MaxFutureSkewSeconds, int MaxBackfillDays);

/// <summary>
/// The five time-quality counts of one interval. They always add up to
/// <see cref="Total"/>, because a transaction carries exactly one label.
/// </summary>
public sealed record DashboardTimeQuality(int OnTime, int Backfill, int SuspectFuture, int SuspectOld, int Unknown)
{
    public int Total => OnTime + Backfill + SuspectFuture + SuspectOld + Unknown;

    /// <summary>
    /// Rows whose moment is not trusted: both suspect groups plus the rows stored
    /// before migration 004. ``BACKFILL`` is trusted, so it is not one of them.
    /// </summary>
    public int NotTrusted => SuspectFuture + SuspectOld + Unknown;

    /// <summary>True when every row is ON_TIME or BACKFILL, so the money is exact.</summary>
    public bool IsClean => NotTrusted == 0;
}

/// <summary>One point of the revenue line: the half-open bucket ``[FromUtc, ToUtc)``.</summary>
public sealed record DashboardBucket(DateTime FromUtc, DateTime ToUtc, decimal Revenue, int Transactions);

/// <summary>The scope the server answered, so the tab can say which one it shows.</summary>
public sealed record DashboardScope(string? StoreId, bool IsSystemWide);

/// <summary>GET /dashboard/revenue.</summary>
public sealed record DashboardRevenue(
    DashboardScope Scope,
    DashboardTimePolicy TimePolicy,
    DateTime? DataFromUtc,
    DateTime? DataToUtc,
    bool HasData,
    decimal TotalRevenue,
    int Transactions,
    DashboardTimeQuality Quality,
    IReadOnlyList<DashboardBucket> Buckets);

/// <summary>One entry of GET /dashboard/stores.</summary>
public sealed record DashboardStore(string StoreId, string Name, string RegionId, bool IsActive);

/// <summary>One slice of the category pie: a category's revenue and its share.</summary>
public sealed record DashboardCategory(string Category, decimal Revenue, decimal Share);

/// <summary>GET /dashboard/revenue-by-category.</summary>
public sealed record DashboardCategoryRevenue(
    DashboardScope Scope,
    DashboardTimePolicy TimePolicy,
    decimal TotalRevenue,
    int Transactions,
    DashboardTimeQuality Quality,
    IReadOnlyList<DashboardCategory> Categories)
{
    /// <summary>
    /// The slices the pie can draw. A negative category cannot be drawn as a share of
    /// a whole, so it is kept out of the pie and reported in a note instead of being
    /// silently dropped (design §6.6).
    /// </summary>
    public IReadOnlyList<DashboardCategory> PositiveSlices =>
        Categories.Where(category => category.Revenue > 0).ToList();

    /// <summary>The categories the pie cannot show, so the note can name them.</summary>
    public IReadOnlyList<DashboardCategory> NegativeCategories =>
        Categories.Where(category => category.Revenue < 0).ToList();
}

/// <summary>One column of the store comparison bar chart.</summary>
public sealed record DashboardStoreRevenue(string StoreId, string Name, string RegionId,
                                           decimal Revenue, decimal Share);

/// <summary>GET /dashboard/revenue-by-store.</summary>
public sealed record DashboardStoreRevenueResponse(
    DashboardScope Scope,
    DashboardTimePolicy TimePolicy,
    DateTime? DataFromUtc,
    DateTime? DataToUtc,
    bool HasData,
    decimal TotalRevenue,
    int Transactions,
    DashboardTimeQuality Quality,
    IReadOnlyList<DashboardStoreRevenue> Stores);
