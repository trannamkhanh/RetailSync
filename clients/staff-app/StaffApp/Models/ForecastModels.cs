namespace StaffApp.Models;

public sealed record ForecastLine(string Sku, string Name, string Category, int HorizonDays,
    decimal PredictedDemand, int SellableStock, decimal SurplusShortage, string BalanceStatus,
    string ModelVersion, DateTimeOffset CreatedAt, int SoldLast7Days);

public sealed record ForecastList(DateOnly BusinessDate, IReadOnlyList<ForecastLine> Items);
