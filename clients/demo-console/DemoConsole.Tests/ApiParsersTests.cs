using DemoConsole.Services;
using Xunit;

namespace DemoConsole.Tests;

public class ApiParsersTests
{
    [Fact]
    public void Inventory_answer_gives_lines_with_batches()
    {
        const string body = """
            {"store_id":"STORE-DN1","items":[
              {"sku":"SKU-0001","quantity":40,"batches":[
                {"batch_id":"B-STORE-DN1-SKU-0001-1","expiry_date":"2026-11-14","quantity":16},
                {"batch_id":"B-STORE-DN1-SKU-0001-2","expiry_date":"2026-12-02","quantity":24}]},
              {"sku":"SKU-0007","quantity":0}]}
            """;

        var lines = ApiParsers.Inventory(body);

        Assert.Equal(2, lines.Count);
        Assert.Equal("STORE-DN1", lines[0].StoreId);
        Assert.Equal(40, lines[0].Quantity);
        Assert.Equal(new DateOnly(2026, 11, 14), lines[0].Batches[0].ExpiryDate);
        Assert.Equal(24, lines[0].Batches[1].Quantity);
        Assert.Empty(lines[1].Batches);
    }

    [Fact]
    public void Sellable_stock_leaves_out_expired_batches()
    {
        var line = ApiParsers.Inventory("""
            {"store_id":"STORE-DN1","items":[{"sku":"SKU-0005","quantity":40,"batches":[
              {"batch_id":"old","expiry_date":"2026-11-11","quantity":16},
              {"batch_id":"today","expiry_date":"2026-11-12","quantity":4},
              {"batch_id":"new","expiry_date":"2026-11-22","quantity":20}]}]}
            """)[0];

        Assert.Equal(24, line.SellableOn(new DateOnly(2026, 11, 12)));
    }

    [Fact]
    public void Audit_answer_gives_rows_in_utc()
    {
        const string body = """
            {"items":[{"audit_id":14,"user_id":7,"action":"SNAPSHOT_REJECTED","entity_name":"hq_snapshot",
              "entity_key":null,"details":"Rejected an HQ snapshot.","created_at":"2026-11-12T07:47:16.756860Z"},
              {"audit_id":13,"user_id":null,"action":"STOCK_CHANGE","entity_name":"pos_transaction",
              "entity_key":"TXN-1","details":null,"created_at":"2026-11-12T07:46:44Z"}]}
            """;

        var rows = ApiParsers.AuditLogs(body);

        Assert.Equal(2, rows.Count);
        Assert.Equal(14, rows[0].AuditId);
        Assert.Null(rows[0].EntityKey);
        Assert.Equal("TXN-1", rows[1].EntityKey);
        Assert.Null(rows[1].Details);
        Assert.Equal(new DateTime(2026, 11, 12, 7, 46, 44, DateTimeKind.Utc), rows[1].CreatedAtUtc);
        Assert.Equal(DateTimeKind.Utc, rows[0].CreatedAtUtc.Kind);
    }

    [Fact]
    public void Hq_demo_answer_gives_batches_and_totals()
    {
        const string body = """
            {"batches":[{"batch_id":"SB-STORE-DN1-1","store_id":"STORE-DN1","txn_count":3,
              "received_at":"2026-11-12T08:00:00.123456Z","duplicate_count":1}],
             "totals":[{"sku":"SKU-0001","store_id":"STORE-DN1","sold_qty":5,"returned_qty":1,"net_revenue":128000.0}]}
            """;

        var view = ApiParsers.DemoBatches(body);

        Assert.Single(view.Batches);
        Assert.Equal(3, view.Batches[0].TxnCount);
        Assert.Equal(1, view.Batches[0].DuplicateCount);
        Assert.Equal(128000m, view.Totals[0].NetRevenue);
        Assert.Equal("STORE-DN1", view.Totals[0].StoreId);
    }

    [Fact]
    public void Empty_hq_demo_answer_is_valid()
    {
        var view = ApiParsers.DemoBatches("""{"batches":[],"totals":[]}""");

        Assert.Empty(view.Batches);
        Assert.Empty(view.Totals);
    }

    [Fact]
    public void Sync_run_answer_gives_the_three_counts()
    {
        var run = ApiParsers.SyncRun("""{"batches_created":2,"batches_sent":3,"batches_pending":1}""");

        Assert.Equal(2, run.BatchesCreated);
        Assert.Equal(3, run.BatchesSent);
        Assert.Equal(1, run.BatchesPending);
    }

    [Fact]
    public void Job_run_and_mode_answers()
    {
        var job = ApiParsers.JobRun("""{"job":"near-expiry","status":"COMPLETED"}""");

        Assert.Equal("near-expiry", job.Job);
        Assert.Equal("COMPLETED", job.Status);
        Assert.Equal("OFFLINE", ApiParsers.DemoMode("""{"mode":"OFFLINE"}"""));
    }

    [Theory]
    [InlineData("""{"outcome":"REJECTED","code":"SNAPSHOT_REJECTED","message":"HQ snapshots are not applied."}""", "SNAPSHOT_REJECTED", "HQ snapshots are not applied.")]
    [InlineData("""{"status":"NACK","batch_id":"b","code":"HQ_OFFLINE","message":"HQ is offline."}""", "HQ_OFFLINE", "HQ is offline.")]
    [InlineData("""{"mode":"ONLINE"}""", "", "")]
    [InlineData("<html>Bad gateway</html>", "", "")]
    [InlineData("", "", "")]
    public void Error_code_and_message_are_read_when_present(string body, string code, string message)
    {
        Assert.Equal((code, message), ApiParsers.ErrorOf(body));
    }

    [Theory]
    [InlineData("""{"items":[{"sku":"SKU-0001","quantity":1}]}""")]
    [InlineData("""{"store_id":"STORE-DN1","items":[{"sku":"SKU-0001"}]}""")]
    [InlineData("""{"store_id":"STORE-DN1","items":[{"sku":"SKU-0001","quantity":"many"}]}""")]
    [InlineData("""[]""")]
    [InlineData("not json")]
    public void A_changed_inventory_contract_is_a_format_error(string body)
    {
        Assert.Throws<FormatException>(() => ApiParsers.Inventory(body));
    }

    [Fact]
    public void A_sync_run_answer_without_counts_is_a_format_error()
    {
        Assert.Throws<FormatException>(() => ApiParsers.SyncRun("""{"batches_created":1}"""));
    }
}
