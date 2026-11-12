using DemoPos.Configuration;
using DemoPos.Models;

namespace DemoPos.Services;

public sealed class AutomaticSaleGenerator(int seed)
{
    private readonly Random _random = new(seed);

    public PosEvent Create(TerminalConfig terminal, IReadOnlyList<ProductConfig> products)
    {
        if (products.Count == 0) throw new ArgumentException("Catalogue is empty", nameof(products));
        var count = _random.Next(1, Math.Min(3, products.Count) + 1);
        var items = products.OrderBy(_ => _random.Next()).Take(count)
            .Select(product => new PosEventItem { Sku = product.Sku, Quantity = 1, UnitPrice = product.UnitPrice });
        return PosEvents.Sale(terminal.StoreId, terminal.PosId, items);
    }
}
