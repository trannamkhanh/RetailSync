using DemoPos.Configuration;
using DemoPos.Services;
using Xunit;

namespace DemoPos.Tests;

public sealed class AutomaticSaleGeneratorTests
{
    [Fact]
    public void SeedReproducesCatalogueSelectionsForTheSelectedTerminal()
    {
        var terminal = new TerminalConfig { StoreId = "STORE-DN1", PosId = "POS-DN1-01" };
        var catalogue = Enumerable.Range(1, 5).Select(i => new ProductConfig { Sku = $"SKU-{i}", UnitPrice = i }).ToList();
        var first = new AutomaticSaleGenerator(123);
        var second = new AutomaticSaleGenerator(123);
        for (var i = 0; i < 20; i++)
        {
            var sale = first.Create(terminal, catalogue);
            var repeat = second.Create(terminal, catalogue);
            Assert.Equal("SALE", sale.EventType);
            Assert.Equal(terminal.PosId, sale.PosId);
            Assert.InRange(sale.Items!.Count, 1, 3);
            Assert.Equal(sale.Items.Select(item => item.Sku), repeat.Items!.Select(item => item.Sku));
        }
    }
}
