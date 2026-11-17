using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Services;
using Xunit;

namespace DemoPos.Tests;

/// <summary>Automatic mode of the demo POS (PB-45-2, POS45-5).</summary>
public sealed class AutomaticSalesTests
{
    private sealed class FakeBackend : IPosBackend
    {
        public List<PosEvent> Sent { get; } = new();

        public bool IsMock => true;

        public Task<PosResult> SendAsync(string rawBody, CancellationToken cancellationToken = default)
        {
            Sent.Add(PosEventJson.Deserialize(rawBody));
            return Task.FromResult(new PosResult
            {
                Outcome = PosOutcome.OK,
                Code = "OK",
                Message = "Event applied.",
                HttpStatus = 200,
            });
        }
    }

    private static List<ProductConfig> Catalogue() => new()
    {
        new() { Sku = "SKU-0001", Barcode = "8930000000011", Name = "Fresh milk 1L", UnitPrice = 32000m },
        new() { Sku = "SKU-0002", Barcode = "8930000000028", Name = "Yogurt 100g", UnitPrice = 7000m },
        new() { Sku = "SKU-0003", Barcode = "8930000000035", Name = "Bread", UnitPrice = 15000m },
    };

    private static string Describe(IReadOnlyList<PosEventItem> items) =>
        string.Join(",", items.Select(item => $"{item.Sku}x{item.Quantity}"));

    [Fact]
    public async Task Pos45_5_AutomaticModeSendsSaleEventsWithoutManualInput()
    {
        var automatic = new AutomaticSales(Catalogue(), seed: 20261117);
        var backend = new FakeBackend();
        var directory = Path.Combine(Path.GetTempPath(), "demopos-auto-" + Guid.NewGuid().ToString("N"));
        try
        {
            // One tick is the form's timer tick: build the event, queue it, send it.
            var queue = new DurableEventQueue(directory, "POS-DN1-01");
            for (var tick = 0; tick < 5; tick++)
            {
                queue.Enqueue(PosEventJson.Serialize(automatic.NextSale("STORE-DN1", "POS-DN1-01")));
                await queue.DrainAsync(entry => backend.SendAsync(entry.Body));
            }

            Assert.Equal(5, backend.Sent.Count);
            Assert.Equal(0, queue.Count);
            Assert.All(backend.Sent, sale =>
            {
                Assert.Equal(EventTypes.Sale, sale.EventType);
                Assert.Equal("STORE-DN1", sale.StoreId);
                Assert.Equal("POS-DN1-01", sale.PosId);
                Assert.True(TransactionIds.IsValid(sale.TransactionId), sale.TransactionId);
                Assert.InRange(sale.Items!.Count, AutomaticSales.FewestItems, AutomaticSales.MostItems);
                Assert.Equal(sale.Items!.Count, sale.Items!.Select(item => item.Sku).Distinct().Count());
                Assert.All(sale.Items!, item => Assert.InRange(item.Quantity, 1,
                                                                AutomaticSales.MostQuantityPerItem));
            });
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void Pb45_2_EverySaleStaysWithinOneToThreeCatalogueItems()
    {
        var catalogue = Catalogue();
        var automatic = new AutomaticSales(catalogue, seed: 7);
        var skus = catalogue.Select(product => product.Sku).ToHashSet();
        var sizes = new HashSet<int>();

        for (var tick = 0; tick < 200; tick++)
        {
            var items = automatic.NextItems();
            sizes.Add(items.Count);
            Assert.InRange(items.Count, AutomaticSales.FewestItems, AutomaticSales.MostItems);
            Assert.Equal(items.Count, items.Select(item => item.Sku).Distinct().Count());
            Assert.All(items, item =>
            {
                Assert.Contains(item.Sku, skus);
                Assert.InRange(item.Quantity, 1, AutomaticSales.MostQuantityPerItem);
            });
        }

        // The demo has to show both a one-item sale and a three-item sale.
        Assert.Contains(AutomaticSales.FewestItems, sizes);
        Assert.Contains(AutomaticSales.MostItems, sizes);
    }

    [Fact]
    public void Pb45_2_TheSeedShownOnScreenRepeatsTheSameSales()
    {
        var first = new AutomaticSales(Catalogue(), seed: 42);
        var again = new AutomaticSales(Catalogue(), seed: 42);
        var other = new AutomaticSales(Catalogue(), seed: 43);

        var firstRun = Enumerable.Range(0, 6).Select(_ => Describe(first.NextItems())).ToList();
        var secondRun = Enumerable.Range(0, 6).Select(_ => Describe(again.NextItems())).ToList();
        var otherRun = Enumerable.Range(0, 6).Select(_ => Describe(other.NextItems())).ToList();

        Assert.Equal(42, first.Seed);
        Assert.Equal(firstRun, secondRun);
        Assert.NotEqual(firstRun, otherRun);
    }

    [Fact]
    public void Pb45_2_ASmallCatalogueNeverRepeatsAnItemInOneSale()
    {
        var catalogue = Catalogue().Take(2).ToList();
        var automatic = new AutomaticSales(catalogue, seed: 3);

        for (var tick = 0; tick < 50; tick++)
        {
            var items = automatic.NextItems();
            Assert.InRange(items.Count, 1, 2);
            Assert.Equal(items.Count, items.Select(item => item.Sku).Distinct().Count());
        }
    }

    [Fact]
    public void Pb45_2_AnEmptyCatalogueCannotStart()
    {
        Assert.Throws<ArgumentException>(
            () => new AutomaticSales(Array.Empty<ProductConfig>(), seed: 1));
    }
}
