namespace DemoConsole.Models;

public sealed record TransactionRow(string TxnId, string StoreId, string PosId, string TxnType, string Status,
                                    DateTime CreatedAtUtc, string? SyncBatchId);

public sealed record SyncBatchRow(string SyncBatchId, string StoreId, string Status, int Attempts, int TxnCount,
                                  string? LastError, DateTime? NextRetryAtUtc, DateTime? AckedAtUtc,
                                  DateTime CreatedAtUtc);

public sealed record AlertRow(string StoreId, string Sku, string BatchId, DateOnly ExpiryDate, int DaysLeft,
                              int RemainingQty, string AlertType, string Status);

public sealed record ForecastRow(string StoreId, string Sku, int HorizonDays, decimal PredictedDemand,
                                 decimal SurplusShortage, string BalanceStatus, string ModelVersion,
                                 DateTime CreatedAtUtc);
