using System.Net;
using System.Text;
using DemoConsole.Services;
using Xunit;

namespace DemoConsole.Tests;

public class DemoApiClientTests
{
    private static readonly Dictionary<string, string> Tokens = new()
    {
        ["admin"] = "admin-token",
        ["auditor"] = "auditor-token",
        ["hq_operator"] = "hq-token",
        ["staff_dn1"] = "staff1-token",
    };

    private sealed class FakeHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _answer;

        public FakeHandler(Func<HttpRequestMessage, HttpResponseMessage> answer) => _answer = answer;

        public List<(HttpMethod Method, string Url, string? Auth, string? Body)> Requests { get; } = new();

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,
                                                                     CancellationToken cancellationToken)
        {
            var body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
            Requests.Add((request.Method, request.RequestUri!.AbsoluteUri, request.Headers.Authorization?.ToString(), body));
            return _answer(request);
        }
    }

    private static HttpResponseMessage Json(HttpStatusCode status, string body) =>
        new(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };

    private static (DemoApiClient Client, FakeHandler Handler) Create(Func<HttpRequestMessage, HttpResponseMessage> answer)
    {
        var handler = new FakeHandler(answer);
        var client = new DemoApiClient(new HttpClient(handler), "https://s:8443/api/v1/", "https://s:9000/api/v1", Tokens);
        return (client, handler);
    }

    [Fact]
    public async Task Run_sync_posts_as_admin_and_reads_the_status()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.Accepted,
            """{"batches_created":1,"batches_sent":1,"batches_pending":0}"""));

        var result = await client.RunSyncAsync();

        Assert.Equal(202, result.Status);
        Assert.True(result.IsSuccess);
        Assert.Equal((HttpMethod.Post, "https://s:8443/api/v1/sync/run", "Bearer admin-token", (string?)null),
            handler.Requests.Single());
    }

    [Fact]
    public async Task Snapshot_is_sent_as_hq_operator_and_its_refusal_code_is_read()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.UnprocessableEntity,
            """{"outcome":"REJECTED","code":"SNAPSHOT_REJECTED","message":"HQ snapshots are not applied."}"""));

        var result = await client.SendSnapshotAsync(new DateTime(2026, 11, 14, 2, 0, 0, DateTimeKind.Utc));

        Assert.Equal(422, result.Status);
        Assert.Equal("SNAPSHOT_REJECTED", result.Code);
        Assert.Equal("HTTP 422 SNAPSHOT_REJECTED - HQ snapshots are not applied.", result.Summary);
        var request = handler.Requests.Single();
        Assert.Equal("Bearer hq-token", request.Auth);
        Assert.Contains("\"quantity\":999", request.Body);
        Assert.Contains("2026-11-14T02:00:00Z", request.Body);
    }

    [Fact]
    public async Task Hq_mode_is_a_put_without_a_token()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.OK, """{"mode":"OFFLINE"}"""));

        var result = await client.SetHqModeAsync("OFFLINE");

        Assert.Equal(200, result.Status);
        Assert.Equal((HttpMethod.Put, "https://s:9000/api/v1/demo/mode", (string?)null, "{\"mode\":\"OFFLINE\"}"),
            handler.Requests.Single());
    }

    [Fact]
    public async Task Jobs_thresholds_inventory_and_audit_use_the_right_routes_and_tokens()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.OK, "{}"));

        await client.RunJobAsync("near-expiry");
        await client.SetThresholdAsync("Dry goods", 30);
        await client.GetInventoryAsync("STORE-DN1", "staff_dn1");
        await client.GetAuditLogsAsync(30);
        await client.GetHqBatchesAsync();

        Assert.Equal(new[]
        {
            "POST https://s:8443/api/v1/admin/jobs/near-expiry/run Bearer admin-token",
            "PUT https://s:8443/api/v1/admin/near-expiry-thresholds/Dry%20goods Bearer admin-token",
            "GET https://s:8443/api/v1/stores/STORE-DN1/inventory Bearer staff1-token",
            "GET https://s:8443/api/v1/audit-logs?limit=30 Bearer auditor-token",
            "GET https://s:9000/api/v1/demo/batches ",
        }, handler.Requests.Select(r => $"{r.Method} {r.Url} {r.Auth}"));
        Assert.Equal("{\"threshold_days\":30}", handler.Requests[1].Body);
    }

    [Fact]
    public async Task Probes_are_gets_with_no_body()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.MethodNotAllowed,
            """{"outcome":"REJECTED","code":"METHOD_NOT_ALLOWED","message":"Method Not Allowed"}"""));

        var sync = await client.ProbeSyncRunAsync();
        await client.ProbeSnapshotAsync();
        await client.ProbeThresholdsAsync();

        Assert.Equal(FeatureState.Deployed, FeatureAvailability.FromProbe(sync));
        Assert.All(handler.Requests, r => Assert.Equal(HttpMethod.Get, r.Method));
        Assert.All(handler.Requests, r => Assert.Null(r.Body));
    }

    [Fact]
    public async Task A_missing_route_answers_404_and_disables_the_feature()
    {
        var (client, _) = Create(_ => Json(HttpStatusCode.NotFound,
            """{"outcome":"REJECTED","code":"NOT_FOUND","message":"Not Found"}"""));

        var result = await client.ProbeSyncRunAsync();

        Assert.Equal(404, result.Status);
        Assert.Equal(FeatureState.NotDeployed, FeatureAvailability.FromProbe(result));
    }

    [Fact]
    public async Task A_network_failure_is_status_zero_not_an_exception()
    {
        var (client, _) = Create(_ => throw new HttpRequestException("Connection refused"));

        var result = await client.GetHqBatchesAsync();

        Assert.True(result.IsUnreachable);
        Assert.Contains("Connection refused", result.Summary);
    }

    [Fact]
    public async Task A_missing_token_is_reported_without_a_request()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.OK, "{}"));

        var result = await client.GetInventoryAsync("STORE-DN2", "staff_dn2");

        Assert.Equal(0, result.Status);
        Assert.Contains("staff_dn2", result.Message);
        Assert.Empty(handler.Requests);
    }
}
