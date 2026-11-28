using System.Globalization;
using System.Text.Json;
using DemoPos.Configuration;
using DemoPos.Models;

namespace DemoPos.Services;

/// <summary>Fallback backend for a demo without the middleware. Never mixed with LIVE data.</summary>
public sealed class MockPosBackend : IPosBackend
{
    private sealed class MockTransaction
    {
        public required string Type { get; init; }
        public required string StoreId { get; init; }
        public required string PosId { get; init; }
        public string? OriginalId { get; init; }
        public required string Signature { get; init; }
        public List<PosEventItem> Items { get; init; } = new();
        public bool Cancelled { get; set; }
        public Dictionary<string, int> Sold { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, int> Returned { get; } = new(StringComparer.OrdinalIgnoreCase);
    }

    private readonly AppConfig _config;
    private readonly RequestLog? _log;
    private readonly Dictionary<string, Dictionary<string, int>> _stock = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, MockTransaction> _transactions = new(StringComparer.Ordinal);
    private readonly Dictionary<string, PosDiscountList> _discountsByStore = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<AuditEntry> _audit = new();
    private PosDiscountList? _defaultDiscounts;
    private long _nextAuditId = 1;

    public MockPosBackend(AppConfig config, RequestLog? log = null)
    {
        _config = config;
        _log = log;
        foreach (var storeId in config.Terminals.Select(terminal => terminal.StoreId)
                     .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var initial = storeId.ToUpperInvariant() switch
            {
                "STORE-DN1" => 40,
                "STORE-DN2" => 25,
                "STORE-DN3" => 15,
                _ => 30,
            };
            _stock[storeId] = config.Products.ToDictionary(
                product => product.Sku, _ => initial, StringComparer.OrdinalIgnoreCase);
        }
    }

    public bool IsMock => true;

    public Task<PosResult> SendAsync(string rawBody, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        PosResult result;
        try
        {
            var posEvent = PosEventJson.Deserialize(rawBody);
            result = Process(posEvent);
        }
        catch (JsonException error)
        {
            result = new PosResult
            {
                Outcome = PosOutcome.REJECTED,
                Code = "INVALID_EVENT",
                Message = $"JSON sự kiện không hợp lệ: {error.Message}",
                HttpStatus = 422,
            };
        }

        Log(rawBody, result);
        return Task.FromResult(result);
    }

    public IReadOnlyList<StockRow> GetStock(string storeId) =>
        _stock.TryGetValue(storeId, out var stock)
            ? _config.Products
                .Select(product => new StockRow
                {
                    Sku = product.Sku,
                    Name = product.Name,
                    Quantity = stock.TryGetValue(product.Sku, out var quantity) ? quantity : 0,
                })
                .ToList()
            : Array.Empty<StockRow>();

    public IReadOnlyList<AuditRow> GetAudit(int limit = 20) =>
        _audit.Take(limit).Select(entry => AuditRow.From(entry)).ToList();

    public PosDiscountList GetDiscounts(string storeId, DateTime? utcNow = null)
    {
        if (_discountsByStore.TryGetValue(storeId, out var storeDiscounts))
        {
            return storeDiscounts;
        }

        return _defaultDiscounts
               ?? new PosDiscountList(PosDiscounts.CurrentBusinessDate(utcNow), Array.Empty<PosDiscountItem>());
    }

    public void SetDiscounts(PosDiscountList discounts) =>
        _defaultDiscounts = discounts ?? throw new ArgumentNullException(nameof(discounts));

    public void SetDiscounts(string storeId, PosDiscountList discounts)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(storeId);
        _discountsByStore[storeId] = discounts ?? throw new ArgumentNullException(nameof(discounts));
    }

    public void ClearDiscounts()
    {
        _defaultDiscounts = null;
        _discountsByStore.Clear();
    }

    private PosResult Process(PosEvent posEvent)
    {
        var storeKnown = _stock.ContainsKey(posEvent.StoreId);
        var terminalKnown = _config.Terminals.Any(terminal =>
            string.Equals(terminal.PosId, posEvent.PosId, StringComparison.OrdinalIgnoreCase)
            && string.Equals(terminal.StoreId, posEvent.StoreId, StringComparison.OrdinalIgnoreCase));
        if (!storeKnown || !terminalKnown)
        {
            return Reject(posEvent, 422, "UNREGISTERED_STORE_OR_POS",
                $"Cửa hàng '{posEvent.StoreId}' hoặc máy POS '{posEvent.PosId}' chưa được đăng ký hoặc ngừng hoạt động.");
        }

        var signature = Signature(posEvent);
        if (_transactions.TryGetValue(posEvent.TransactionId, out var existing))
        {
            if (existing.Signature == signature)
            {
                AddAudit("DUPLICATE_EVENT", posEvent.TransactionId, null);
                return OkResult(posEvent, "DUPLICATE", "DUPLICATE_IGNORED",
                    "Giao dịch đã được ghi trước đó", StockOf(existing));
            }

            return Reject(posEvent, 409, "CONFLICT",
                "Trùng mã giao dịch nhưng khác nội dung");
        }

        return posEvent.EventType switch
        {
            EventTypes.Sale => Sale(posEvent),
            EventTypes.Return => Return(posEvent),
            EventTypes.Cancellation => Cancellation(posEvent),
            _ => Reject(posEvent, 422, "INVALID_EVENT", $"Loại sự kiện không hợp lệ '{posEvent.EventType}'."),
        };
    }

    private PosResult Sale(PosEvent posEvent)
    {
        var items = posEvent.Items ?? new List<PosEventItem>();
        if (items.Count == 0)
        {
            return Reject(posEvent, 422, "INVALID_EVENT", "Giao dịch bán hàng cần ít nhất một mặt hàng.");
        }

        var storeStock = _stock[posEvent.StoreId];
        var merged = Merge(items);
        foreach (var (sku, quantity) in merged)
        {
            if (!storeStock.TryGetValue(sku, out var available))
            {
                return Reject(posEvent, 422, "INVALID_EVENT", $"Mã sản phẩm '{sku}' không tồn tại.");
            }

            if (available < quantity)
            {
                return Reject(posEvent, 409, "INSUFFICIENT_STOCK",
                    $"Không đủ tồn kho cho mã {sku}.");
            }
        }

        foreach (var (sku, quantity) in merged)
        {
            storeStock[sku] -= quantity;
        }

        var transaction = new MockTransaction
        {
            Type = posEvent.EventType,
            StoreId = posEvent.StoreId,
            PosId = posEvent.PosId,
            Signature = Signature(posEvent),
            Items = items.ToList(),
        };
        foreach (var (sku, quantity) in merged)
        {
            transaction.Sold[sku] = quantity;
        }

        _transactions[posEvent.TransactionId] = transaction;
        AddAudit("STOCK_CHANGE", posEvent.TransactionId,
            $"{posEvent.EventType} {posEvent.PosId}: {StockText(merged, storeStock)}");
        return OkResult(posEvent, "OK", "OK", "Đã áp dụng giao dịch", CurrentStock(merged.Keys, storeStock));
    }

    private PosResult Return(PosEvent posEvent)
    {
        if (posEvent.OriginalTransactionId is null
            || !_transactions.TryGetValue(posEvent.OriginalTransactionId, out var original)
            || original.Type != EventTypes.Sale)
        {
            return Reject(posEvent, 404, "ORIGINAL_SALE_NOT_FOUND",
                "Không tìm thấy giao dịch bán gốc.");
        }

        if (original.Cancelled)
        {
            return Reject(posEvent, 409, "SALE_ALREADY_CANCELLED",
                "Đơn bán gốc đã bị hủy trước đó.");
        }

        var items = posEvent.Items ?? new List<PosEventItem>();
        if (items.Count == 0)
        {
            return Reject(posEvent, 422, "INVALID_EVENT", "Giao dịch trả hàng cần ít nhất một mặt hàng.");
        }

        var merged = Merge(items);
        foreach (var (sku, quantity) in merged)
        {
            var remaining = original.Sold.GetValueOrDefault(sku) - original.Returned.GetValueOrDefault(sku);
            if (quantity > remaining)
            {
                return Reject(posEvent, 409, "RETURN_QTY_EXCEEDED",
                    $"Số lượng trả cho mã '{sku}' vượt quá số lượng đã bán.");
            }
        }

        var storeStock = _stock[posEvent.StoreId];
        foreach (var (sku, quantity) in merged)
        {
            storeStock[sku] = storeStock.GetValueOrDefault(sku) + quantity;
            original.Returned[sku] = original.Returned.GetValueOrDefault(sku) + quantity;
        }

        _transactions[posEvent.TransactionId] = new MockTransaction
        {
            Type = posEvent.EventType,
            StoreId = posEvent.StoreId,
            PosId = posEvent.PosId,
            OriginalId = posEvent.OriginalTransactionId,
            Signature = Signature(posEvent),
            Items = items.ToList(),
        };
        AddAudit("STOCK_CHANGE", posEvent.TransactionId,
            $"{posEvent.EventType} {posEvent.PosId}: {StockText(merged, storeStock)}");
        return OkResult(posEvent, "OK", "OK", "Đã áp dụng giao dịch", CurrentStock(merged.Keys, storeStock));
    }

    private PosResult Cancellation(PosEvent posEvent)
    {
        if (posEvent.OriginalTransactionId is null
            || !_transactions.TryGetValue(posEvent.OriginalTransactionId, out var original)
            || original.Type != EventTypes.Sale)
        {
            return Reject(posEvent, 404, "ORIGINAL_SALE_NOT_FOUND",
                "Không tìm thấy giao dịch bán gốc.");
        }

        if (original.Cancelled)
        {
            return Reject(posEvent, 409, "SALE_ALREADY_CANCELLED",
                "Đơn bán gốc đã bị hủy trước đó.");
        }

        if (original.Returned.Values.Any(quantity => quantity > 0))
        {
            return Reject(posEvent, 409, "SALE_HAS_RETURNS",
                "Đơn bán đã có giao dịch trả hàng nên không thể hủy.");
        }

        var storeStock = _stock[posEvent.StoreId];
        foreach (var (sku, quantity) in original.Sold)
        {
            storeStock[sku] = storeStock.GetValueOrDefault(sku) + quantity;
        }

        original.Cancelled = true;
        _transactions[posEvent.TransactionId] = new MockTransaction
        {
            Type = posEvent.EventType,
            StoreId = posEvent.StoreId,
            PosId = posEvent.PosId,
            OriginalId = posEvent.OriginalTransactionId,
            Signature = Signature(posEvent),
            Items = original.Items.ToList(),
        };
        AddAudit("STOCK_CHANGE", posEvent.TransactionId,
            $"{posEvent.EventType} {posEvent.PosId}: {StockText(original.Sold, storeStock)}");
        return OkResult(posEvent, "OK", "OK", "Đã áp dụng giao dịch",
            CurrentStock(original.Sold.Keys, storeStock));
    }

    private PosResult Reject(PosEvent posEvent, int status, string code, string message)
    {
        AddAudit("EVENT_REJECTED", posEvent.TransactionId, $"{code}: {message}");
        return new PosResult
        {
            Outcome = PosOutcome.REJECTED,
            Code = code,
            Message = message,
            HttpStatus = status,
        };
    }

    private PosResult OkResult(PosEvent posEvent, string outcome, string code, string message,
                               IReadOnlyDictionary<string, int> stock) => new()
    {
        Outcome = Enum.Parse<PosOutcome>(outcome, ignoreCase: true),
        Code = code,
        Message = message,
        CurrentStock = stock,
        HttpStatus = 200,
    };

    private static string Signature(PosEvent posEvent)
    {
        var items = posEvent.EventType == EventTypes.Cancellation
            ? string.Empty
            : string.Join(";", (posEvent.Items ?? new List<PosEventItem>())
                .OrderBy(item => item.Sku, StringComparer.Ordinal)
                .ThenBy(item => item.Quantity)
                .ThenBy(item => item.UnitPrice)
                .Select(item => FormattableString.Invariant($"{item.Sku}:{item.Quantity}:{item.UnitPrice:0.00}")));
        return $"{posEvent.EventType}|{posEvent.StoreId}|{posEvent.PosId}|" +
               $"{posEvent.OriginalTransactionId ?? string.Empty}|{items}";
    }

    private static Dictionary<string, int> Merge(IEnumerable<PosEventItem> items)
    {
        var merged = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in items)
        {
            merged[item.Sku] = merged.GetValueOrDefault(item.Sku) + item.Quantity;
        }

        return merged;
    }

    private Dictionary<string, int> CurrentStock(IEnumerable<string> skus, Dictionary<string, int> storeStock) =>
        skus.Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(sku => sku, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(sku => sku, sku => storeStock.GetValueOrDefault(sku),
                StringComparer.OrdinalIgnoreCase);

    private Dictionary<string, int> StockOf(MockTransaction transaction)
    {
        var storeStock = _stock[transaction.StoreId];
        return CurrentStock(transaction.Items.Select(item => item.Sku), storeStock);
    }

    private static string StockText(IReadOnlyDictionary<string, int> quantities,
                                    Dictionary<string, int> storeStock) =>
        string.Join(", ", quantities.OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .Select(pair => $"{pair.Key}={storeStock.GetValueOrDefault(pair.Key)}"));

    private void AddAudit(string action, string? entityKey, string? details)
    {
        _audit.Insert(0, new AuditEntry
        {
            AuditId = _nextAuditId++,
            UserId = null,
            Action = action,
            EntityName = "pos_transaction",
            EntityKey = entityKey,
            Details = details,
            CreatedAt = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
        });
    }

    private void Log(string rawBody, PosResult result)
    {
        if (_log is null)
        {
            return;
        }

        var response = JsonSerializer.Serialize(new
        {
            outcome = result.Outcome.ToString(),
            code = result.Code,
            message = result.Message,
            current_stock = result.CurrentStock,
        }, MonitorJson.Options);
        _log.Add(new RequestLogEntry
        {
            Method = "POST",
            Url = "mock://pos/events",
            Status = result.HttpStatus,
            ElapsedMs = 0.1,
            RequestBody = rawBody,
            ResponseBody = response,
            CertificatePosId = null,
            Role = "MOCK",
            Subject = "mock",
            Kind = RequestKind.Mock,
        });
    }
}
