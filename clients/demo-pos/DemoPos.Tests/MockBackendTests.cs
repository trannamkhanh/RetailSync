using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Services;
using Xunit;

namespace DemoPos.Tests;

public sealed class MockBackendTests
{
    private static (MockPosBackend Backend, AppConfig Config) Create()
    {
        var config = new AppConfig
        {
            UseMock = true,
            Terminals = new List<TerminalConfig>
            {
                new() { StoreId = "STORE-DN1", StoreName = "Cửa hàng Hải Châu", PosId = "POS-DN1-01" },
            },
            Products = new List<ProductConfig>
            {
                new() { Sku = "SKU-0001", Barcode = "8930000000011", Name = "Fresh milk 1L", UnitPrice = 32000m },
                new() { Sku = "SKU-0002", Barcode = "8930000000028", Name = "Yogurt 100g", UnitPrice = 7000m },
            },
        };
        return (new MockPosBackend(config), config);
    }

    private static string Raw(string eventType, string transactionId, int quantity = 1,
                              string? original = null, string storeId = "STORE-DN1")
    {
        var posEvent = eventType switch
        {
            EventTypes.Sale => PosEvents.Sale(storeId, "POS-DN1-01",
                new[] { new PosEventItem { Sku = "SKU-0001", Quantity = quantity, UnitPrice = 32000m } },
                transactionId),
            EventTypes.Return => PosEvents.Return(storeId, "POS-DN1-01", original!,
                new[] { new PosEventItem { Sku = "SKU-0001", Quantity = quantity, UnitPrice = 32000m } },
                transactionId),
            EventTypes.Cancellation => PosEvents.Cancellation(storeId, "POS-DN1-01", original!, transactionId),
            _ => throw new ArgumentOutOfRangeException(nameof(eventType)),
        };
        return PosEventJson.Serialize(posEvent);
    }

    [Fact]
    public async Task SaleThenDuplicateThenConflict()
    {
        var (backend, _) = Create();
        var first = await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0001", 2));
        Assert.Equal(PosOutcome.OK, first.Outcome);
        Assert.Equal(38, first.CurrentStock["SKU-0001"]);

        var duplicate = await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0001", 2));
        Assert.Equal(PosOutcome.DUPLICATE, duplicate.Outcome);
        Assert.Equal(38, duplicate.CurrentStock["SKU-0001"]);

        var conflict = await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0001", 3));
        Assert.Equal(PosOutcome.REJECTED, conflict.Outcome);
        Assert.Equal("CONFLICT", conflict.Code);
        Assert.Equal(409, conflict.HttpStatus);
    }

    [Fact]
    public async Task InsufficientStockDoesNotChangeStock()
    {
        var (backend, _) = Create();
        var result = await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0002", 999));

        Assert.Equal("INSUFFICIENT_STOCK", result.Code);
        Assert.Equal(40, backend.GetStock("STORE-DN1").First(row => row.Sku == "SKU-0001").Quantity);
    }

    [Fact]
    public async Task ReturnAndReturnLimit()
    {
        var (backend, _) = Create();
        await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0003", 2));

        var firstReturn = await backend.SendAsync(Raw(EventTypes.Return, "TXN-POS-DN1-01-20261106010203-0004", 1,
            "TXN-POS-DN1-01-20261106010203-0003"));
        Assert.Equal(PosOutcome.OK, firstReturn.Outcome);
        Assert.Equal(39, firstReturn.CurrentStock["SKU-0001"]);

        var tooMuch = await backend.SendAsync(Raw(EventTypes.Return, "TXN-POS-DN1-01-20261106010203-0005", 5,
            "TXN-POS-DN1-01-20261106010203-0003"));
        Assert.Equal("RETURN_QTY_EXCEEDED", tooMuch.Code);
        Assert.Equal(39, backend.GetStock("STORE-DN1").First(row => row.Sku == "SKU-0001").Quantity);
    }

    [Fact]
    public async Task CancellationRestoresStockAndCannotRunTwice()
    {
        var (backend, _) = Create();
        await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0006", 2));

        var cancelled = await backend.SendAsync(Raw(EventTypes.Cancellation, "TXN-POS-DN1-01-20261106010203-0007",
            original: "TXN-POS-DN1-01-20261106010203-0006"));
        Assert.Equal(PosOutcome.OK, cancelled.Outcome);
        Assert.Equal(40, cancelled.CurrentStock["SKU-0001"]);

        var again = await backend.SendAsync(Raw(EventTypes.Cancellation, "TXN-POS-DN1-01-20261106010203-0008",
            original: "TXN-POS-DN1-01-20261106010203-0006"));
        Assert.Equal("SALE_ALREADY_CANCELLED", again.Code);
    }

    [Fact]
    public async Task UnregisteredStoreIsRejected()
    {
        var (backend, _) = Create();
        var result = await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0009",
            1, storeId: "STORE-XX"));

        Assert.Equal(PosOutcome.REJECTED, result.Outcome);
        Assert.Equal("UNREGISTERED_STORE_OR_POS", result.Code);
        Assert.Equal(422, result.HttpStatus);
    }

    [Fact]
    public async Task AuditAndStockAreExposedForThePanels()
    {
        var (backend, _) = Create();
        await backend.SendAsync(Raw(EventTypes.Sale, "TXN-POS-DN1-01-20261106010203-0010", 1));

        Assert.Contains(backend.GetStock("STORE-DN1"), row => row.Sku == "SKU-0001" && row.Quantity == 39);
        Assert.Contains(backend.GetAudit(), row => row.Action == "STOCK_CHANGE");
    }
}
