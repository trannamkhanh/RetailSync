using System.Net;
using System.Text;
using StaffApp.Services;
using Xunit;

namespace StaffApp.Tests;

public class StaffApiClientTests
{
    private const string Base = "https://10.0.0.5:8443/api/v1/";

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

    private static (StaffApiClient Client, FakeHandler Handler) Create(Func<HttpRequestMessage, HttpResponseMessage> answer)
    {
        var handler = new FakeHandler(answer);
        return (new StaffApiClient(new HttpClient(handler), Base, "staff-token"), handler);
    }

    [Fact]
    public async Task Pb46_calls_follow_ds04_paths_with_the_staff_token()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.OK, "{}"));

        await client.GetProductAsync("8930000000011");
        await client.GetCrossStoreStockAsync("8930000000011", "STORE-DN1");
        await client.GetAlertsAsync();
        await client.GetRecommendationsAsync();
        await client.GetRecommendationAsync(42);

        Assert.Equal(new[]
        {
            "https://10.0.0.5:8443/api/v1/products/barcode/8930000000011",
            "https://10.0.0.5:8443/api/v1/products/barcode/8930000000011/stock?from_store=STORE-DN1",
            "https://10.0.0.5:8443/api/v1/near-expiry-alerts",
            "https://10.0.0.5:8443/api/v1/recommendations",
            "https://10.0.0.5:8443/api/v1/recommendations/42",
        }, handler.Requests.Select(request => request.Url));
        Assert.All(handler.Requests, request =>
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Equal("Bearer staff-token", request.Auth);
        });
    }

    [Theory]
    [InlineData(true, """{"decision":"ACCEPT"}""")]
    [InlineData(false, """{"decision":"REJECT"}""")]
    public async Task Pb47_decision_posts_accept_or_reject(bool accept, string body)
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.OK,
            """{"rec_id":42,"status":"ACCEPTED","decided_at":"2026-11-20T03:15:00Z"}"""));

        var result = await client.DecideAsync(42, accept);

        Assert.True(result.IsSuccess);
        var request = Assert.Single(handler.Requests);
        Assert.Equal((HttpMethod.Post, "https://10.0.0.5:8443/api/v1/recommendations/42/decision", body),
            (request.Method, request.Url, request.Body));
    }

    [Theory]
    [InlineData(HttpStatusCode.Unauthorized, "UNAUTHORIZED")]
    [InlineData(HttpStatusCode.NotFound, "NOT_FOUND")]
    [InlineData(HttpStatusCode.Conflict, "ALREADY_DECIDED")]
    public async Task Pb46_error_answers_keep_status_and_code(HttpStatusCode status, string code)
    {
        var (client, _) = Create(_ => Json(status, $$"""{"outcome":"REJECTED","code":"{{code}}","message":"m"}"""));

        var result = await client.DecideAsync(1, true);

        Assert.Equal(((int)status, code), (result.Status, result.Code));
    }

    [Fact]
    public async Task Pb46_network_error_is_status_0_and_never_throws()
    {
        var (client, _) = Create(_ => throw new HttpRequestException("Could not connect to 10.0.0.5:8443."));

        var result = await client.GetAlertsAsync();

        Assert.True(result.IsUnreachable);
        Assert.Contains("Could not connect", result.Message);
    }

    [Fact]
    public async Task Pb46_barcode_is_escaped_in_the_path()
    {
        var (client, handler) = Create(_ => Json(HttpStatusCode.NotFound, "{}"));

        await client.GetProductAsync("A B");

        Assert.EndsWith("/products/barcode/A%20B", handler.Requests[0].Url);
    }
}
