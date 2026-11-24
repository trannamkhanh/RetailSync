using DemoPos.Configuration;
using DemoPos.Models;

namespace DemoPos.Services;

/// <summary>
/// Automatic mode for the demo POS (PB-45-2): one tick picks one to three catalogue items at
/// random and builds the same SALE event the Pay button builds, so the form sends it through the
/// same path as a manual sale, durable queue included. The seed is shown on screen, so a demo can
/// be repeated.
/// </summary>
public sealed class AutomaticSales
{
    public const int FewestItems = 1;

    public const int MostItems = 3;

    public const int MostQuantityPerItem = 2;

    private readonly IReadOnlyList<ProductConfig> _catalogue;

    private readonly Random _random;

    public AutomaticSales(IReadOnlyList<ProductConfig> catalogue, int seed)
    {
        if (catalogue is null)
        {
            throw new ArgumentNullException(nameof(catalogue));
        }

        if (catalogue.Count == 0)
        {
            throw new ArgumentException("The catalogue is empty.", nameof(catalogue));
        }

        _catalogue = catalogue;
        _random = new Random(seed);
        Seed = seed;
    }

    /// <summary>The seed of this run, shown next to the toggle.</summary>
    public int Seed { get; }

    /// <summary>One to three different catalogue items, one to two of each.</summary>
    public IReadOnlyList<PosEventItem> NextItems()
    {
        var candidates = Enumerable.Range(0, _catalogue.Count).ToList();
        var count = Math.Min(FewestItems + _random.Next(MostItems - FewestItems + 1), candidates.Count);
        var items = new List<PosEventItem>(count);
        for (var taken = 0; taken < count; taken++)
        {
            var index = _random.Next(candidates.Count);
            var product = _catalogue[candidates[index]];
            candidates.RemoveAt(index);
            items.Add(new PosEventItem
            {
                Sku = product.Sku,
                Quantity = _random.Next(1, MostQuantityPerItem + 1),
                UnitPrice = product.UnitPrice,
            });
        }

        return items;
    }

    /// <summary>The SALE event of one tick: the form adds these items to the cart and pays.</summary>
    public PosEvent NextSale(string storeId, string posId, DateTime? utcNow = null) =>
        PosEvents.Sale(storeId, posId, NextItems(), utcNow: utcNow);
}
