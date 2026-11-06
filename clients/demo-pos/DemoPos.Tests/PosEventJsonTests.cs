using System.Text.Json;
using DemoPos.Models;
using Xunit;

namespace DemoPos.Tests;

public sealed class PosEventJsonTests
{
    [Fact]
    public void SaleUsesSnakeCaseAndOmitsOriginalTransaction()
    {
        var when = new DateTime(2026, 11, 6, 1, 2, 3, DateTimeKind.Utc);
        var posEvent = PosEvents.Sale("STORE-DN1", "POS-DN1-01",
            new[] { new PosEventItem { Sku = "SKU-0001", Quantity = 2, UnitPrice = 32000m } },
            transactionId: "TXN-POS-DN1-01-20261106010203-0001", utcNow: when);

        var json = PosEventJson.Serialize(posEvent);
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        Assert.Equal("SALE", root.GetProperty("event_type").GetString());
        Assert.Equal("TXN-POS-DN1-01-20261106010203-0001", root.GetProperty("transaction_id").GetString());
        Assert.Equal("STORE-DN1", root.GetProperty("store_id").GetString());
        Assert.Equal("POS-DN1-01", root.GetProperty("pos_id").GetString());
        Assert.Equal("2026-11-06T01:02:03Z", root.GetProperty("timestamp").GetString());
        Assert.False(root.TryGetProperty("original_transaction_id", out _));
        var item = root.GetProperty("items")[0];
        Assert.Equal("SKU-0001", item.GetProperty("sku").GetString());
        Assert.Equal(2, item.GetProperty("quantity").GetInt32());
        Assert.Equal(32000m, item.GetProperty("unit_price").GetDecimal());
    }

    [Fact]
    public void CancellationHasNoItemsAndCarriesOriginalTransaction()
    {
        var posEvent = PosEvents.Cancellation("STORE-DN1", "POS-DN1-01",
            "TXN-POS-DN1-01-20261106010203-0001",
            transactionId: "TXN-POS-DN1-01-20261106010204-0002");

        var json = PosEventJson.Serialize(posEvent);
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        Assert.Equal("CANCELLATION", root.GetProperty("event_type").GetString());
        Assert.Equal("TXN-POS-DN1-01-20261106010203-0001",
            root.GetProperty("original_transaction_id").GetString());
        Assert.False(root.TryGetProperty("items", out _));
    }

    [Fact]
    public void ReturnCarriesOriginalTransactionAndItems()
    {
        var posEvent = PosEvents.Return("STORE-DN1", "POS-DN1-01",
            "TXN-POS-DN1-01-20261106010203-0001",
            new[] { new PosEventItem { Sku = "SKU-0001", Quantity = 1, UnitPrice = 32000m } },
            transactionId: "TXN-POS-DN1-01-20261106010204-0002");

        using var document = JsonDocument.Parse(PosEventJson.Serialize(posEvent));
        var root = document.RootElement;
        Assert.Equal("RETURN", root.GetProperty("event_type").GetString());
        Assert.Equal("TXN-POS-DN1-01-20261106010203-0001",
            root.GetProperty("original_transaction_id").GetString());
        Assert.Equal(1, root.GetProperty("items")[0].GetProperty("quantity").GetInt32());
    }

    [Fact]
    public void TransactionIdHasTheRequiredShapeAndFitsFortyCharacters()
    {
        var id = TransactionIds.New("POS-DN1-01",
            new DateTime(2026, 11, 6, 7, 8, 9, DateTimeKind.Utc), digits: 42);

        Assert.Equal("TXN-POS-DN1-01-20261106070809-0042", id);
        Assert.True(id.Length <= 40);
        Assert.True(TransactionIds.IsValid(id));
    }

    [Fact]
    public void TransactionIdRejectsAnInvalidPosId()
    {
        Assert.Throws<ArgumentException>(() => TransactionIds.New("POS DN1", digits: 1));
        Assert.Throws<ArgumentException>(() => TransactionIds.New(new string('A', 21), digits: 1));
    }

    [Fact]
    public void TimestampAlwaysEndsInZ()
    {
        var local = new DateTime(2026, 11, 6, 7, 8, 9, DateTimeKind.Local);
        var text = PosEventJson.FormatTimestamp(local);
        Assert.EndsWith("Z", text);
        Assert.Matches(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", text);
    }
}
