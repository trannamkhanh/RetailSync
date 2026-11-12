using System.Text.RegularExpressions;
using DemoConsole.Configuration;
using DemoConsole.Models;
using Microsoft.Data.SqlClient;

namespace DemoConsole.Services;

/// <summary>
/// The constant SELECT statements for the data that has no API: sync batches, the
/// latest POS transactions, open near-expiry alerts and the latest forecasts.
/// History rows (HIST-) are left out because they are not live.
/// </summary>
public static class SqlQueries
{
    public const string LatestTransactions = """
        SELECT TOP (@limit) txn_id, store_id, pos_id, txn_type, status, created_at, sync_batch_id
        FROM dbo.pos_transaction
        WHERE txn_id NOT LIKE 'HIST-%'
        ORDER BY created_at DESC, txn_id DESC;
        """;

    public const string SyncBatches = """
        SELECT TOP (@limit) sync_batch_id, store_id, status, attempts, txn_count, last_error,
               next_retry_at, acked_at, created_at
        FROM dbo.sync_batch
        WHERE sync_batch_id NOT LIKE 'SB-HIST-%'
        ORDER BY created_at DESC, sync_batch_id DESC;
        """;

    public const string OpenAlerts = """
        SELECT a.store_id, a.sku, a.batch_id, b.expiry_date,
               DATEDIFF(day, @today, b.expiry_date) AS days_left,
               a.remaining_qty, a.alert_type, a.status
        FROM dbo.near_expiry_alert AS a
        JOIN dbo.product_batch AS b ON b.batch_id = a.batch_id
        WHERE a.status = 'OPEN'
        ORDER BY CASE a.alert_type WHEN 'EXPIRED' THEN 0 ELSE 1 END, days_left, a.store_id, a.sku;
        """;

    public const string LatestForecasts = """
        WITH ranked AS (
            SELECT store_id, sku, horizon_days, predicted_demand, surplus_shortage, balance_status,
                   model_version, created_at,
                   ROW_NUMBER() OVER (PARTITION BY store_id, sku ORDER BY created_at DESC, forecast_id DESC) AS rn
            FROM dbo.forecast
        )
        SELECT store_id, sku, horizon_days, predicted_demand, surplus_shortage, balance_status,
               model_version, created_at
        FROM ranked
        WHERE rn = 1
        ORDER BY store_id, sku;
        """;

    public static readonly IReadOnlyList<string> All = new[]
    {
        LatestTransactions, SyncBatches, OpenAlerts, LatestForecasts,
    };

    private static readonly Regex WriteKeyword = new(
        @"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE|DENY|INTO|BACKUP|RESTORE|DBCC|SHUTDOWN|KILL)\b",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    /// <summary>True for a single SELECT (optionally after a CTE) with no write keyword.</summary>
    public static bool IsReadOnly(string sql)
    {
        var text = sql.Trim();
        var startsAsRead = text.StartsWith("SELECT", StringComparison.OrdinalIgnoreCase)
                           || text.StartsWith("WITH", StringComparison.OrdinalIgnoreCase);
        var body = text.TrimEnd(';');
        return startsAsRead && !body.Contains(';') && !WriteKeyword.IsMatch(text);
    }
}

/// <summary>
/// SELECT-only access to the demo database. It refuses RTS_DB and RTS_DB_TEST, runs
/// only the constant statements of <see cref="SqlQueries"/> with parameters, and wraps
/// each one in a transaction that is always rolled back.
/// </summary>
public sealed class ReadOnlySql
{
    private const int CommandTimeoutSeconds = 5;
    private readonly string _connectionString;

    public ReadOnlySql(string server, string database, string password)
    {
        ConfigLoader.CheckDatabaseName(database);
        Database = database;
        _connectionString = BuildConnectionString(server, database, password);
    }

    public string Database { get; }

    public static string BuildConnectionString(string server, string database, string password)
    {
        ConfigLoader.CheckDatabaseName(database);
        return new SqlConnectionStringBuilder
        {
            DataSource = server,
            InitialCatalog = database,
            UserID = "sa",
            Password = password,
            // Local SQL Server in Docker with its own self-signed certificate.
            Encrypt = true,
            TrustServerCertificate = true,
            ApplicationName = "RetailSync demo console (read-only)",
            ApplicationIntent = ApplicationIntent.ReadOnly,
            ConnectTimeout = 5,
            Pooling = true,
        }.ConnectionString;
    }

    public Task<IReadOnlyList<TransactionRow>> LatestTransactionsAsync(int limit) =>
        QueryAsync(SqlQueries.LatestTransactions, command => command.Parameters.AddWithValue("@limit", limit),
            reader => new TransactionRow(
                reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetString(3),
                reader.GetString(4), reader.GetDateTime(5), reader.IsDBNull(6) ? null : reader.GetString(6)));

    public Task<IReadOnlyList<SyncBatchRow>> SyncBatchesAsync(int limit) =>
        QueryAsync(SqlQueries.SyncBatches, command => command.Parameters.AddWithValue("@limit", limit),
            reader => new SyncBatchRow(
                reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetInt32(3),
                reader.GetInt32(4), reader.IsDBNull(5) ? null : reader.GetString(5),
                reader.IsDBNull(6) ? null : reader.GetDateTime(6), reader.IsDBNull(7) ? null : reader.GetDateTime(7),
                reader.GetDateTime(8)));

    public Task<IReadOnlyList<AlertRow>> OpenAlertsAsync(DateOnly today) =>
        QueryAsync(SqlQueries.OpenAlerts,
            command => command.Parameters.Add("@today", System.Data.SqlDbType.Date).Value = today.ToDateTime(TimeOnly.MinValue),
            reader => new AlertRow(
                reader.GetString(0), reader.GetString(1), reader.GetString(2),
                DateOnly.FromDateTime(reader.GetDateTime(3)), reader.GetInt32(4), reader.GetInt32(5),
                reader.GetString(6), reader.GetString(7)));

    public Task<IReadOnlyList<ForecastRow>> LatestForecastsAsync() =>
        QueryAsync(SqlQueries.LatestForecasts, _ => { },
            reader => new ForecastRow(
                reader.GetString(0), reader.GetString(1), reader.GetInt32(2), reader.GetDecimal(3),
                reader.GetDecimal(4), reader.GetString(5), reader.GetString(6), reader.GetDateTime(7)));

    private async Task<IReadOnlyList<T>> QueryAsync<T>(string sql, Action<SqlCommand> bind,
                                                       Func<SqlDataReader, T> map)
    {
        if (!SqlQueries.IsReadOnly(sql))
        {
            throw new InvalidOperationException("The demo console runs SELECT statements only.");
        }

        await using var connection = new SqlConnection(_connectionString);
        await connection.OpenAsync().ConfigureAwait(false);
        await using var transaction = (SqlTransaction)await connection
            .BeginTransactionAsync(System.Data.IsolationLevel.ReadCommitted).ConfigureAwait(false);
        try
        {
            await using var command = new SqlCommand(sql, connection, transaction)
            {
                CommandTimeout = CommandTimeoutSeconds,
            };
            bind(command);
            var rows = new List<T>();
            await using (var reader = await command.ExecuteReaderAsync().ConfigureAwait(false))
            {
                while (await reader.ReadAsync().ConfigureAwait(false))
                {
                    rows.Add(map(reader));
                }
            }

            return rows;
        }
        finally
        {
            // Nothing is ever written; rolling back makes that hold even by mistake.
            await transaction.RollbackAsync().ConfigureAwait(false);
        }
    }
}
