using DemoConsole.Configuration;
using DemoConsole.Services;
using Microsoft.Data.SqlClient;
using Xunit;

namespace DemoConsole.Tests;

public class ReadOnlySqlTests
{
    [Fact]
    public void Every_console_query_is_a_single_select()
    {
        Assert.Equal(4, SqlQueries.All.Count);
        Assert.All(SqlQueries.All, sql => Assert.True(SqlQueries.IsReadOnly(sql), sql));
    }

    [Theory]
    [InlineData("UPDATE dbo.inventory SET quantity = 0")]
    [InlineData("SELECT 1; DELETE FROM dbo.audit_log")]
    [InlineData("SELECT * INTO dbo.copy FROM dbo.inventory")]
    [InlineData("WITH x AS (SELECT 1 AS a) MERGE dbo.t USING x ON 1 = 0 WHEN NOT MATCHED THEN INSERT VALUES (1);")]
    [InlineData("EXEC sp_who")]
    [InlineData("select 1 drop table dbo.inventory")]
    public void Statements_that_write_are_not_read_only(string sql)
    {
        Assert.False(SqlQueries.IsReadOnly(sql));
    }

    [Theory]
    [InlineData("RTS_DB")]
    [InlineData("RTS_DB_TEST")]
    [InlineData("rts_db_test")]
    public void The_sql_reader_refuses_the_development_databases(string database)
    {
        Assert.Throws<ConfigurationException>(() => new ReadOnlySql("127.0.0.1,14333", database, "x"));
    }

    [Fact]
    public void The_connection_targets_the_configured_demo_database()
    {
        var builder = new SqlConnectionStringBuilder(
            ReadOnlySql.BuildConnectionString("127.0.0.1,14333", "RTS_DB_DEMO", "Secret!123"));

        Assert.Equal("127.0.0.1,14333", builder.DataSource);
        Assert.Equal("RTS_DB_DEMO", builder.InitialCatalog);
        Assert.Equal("sa", builder.UserID);
        Assert.Equal(ApplicationIntent.ReadOnly, builder.ApplicationIntent);
    }

    [Fact]
    public void Live_queries_leave_out_the_history()
    {
        Assert.Contains("NOT LIKE 'HIST-%'", SqlQueries.LatestTransactions);
        Assert.Contains("NOT LIKE 'SB-HIST-%'", SqlQueries.SyncBatches);
        Assert.Contains("@limit", SqlQueries.LatestTransactions);
        Assert.Contains("@today", SqlQueries.OpenAlerts);
    }
}
