using System.Diagnostics;
using System.Net.Http.Headers;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using DemoConsole.Models;
using DemoConsole.Security;

namespace DemoConsole.Services;

/// <summary>
/// Every console action and every read that has an API goes through here, with the
/// token of the role the route needs. Calls never throw for HTTP or network errors:
/// they return an <see cref="ApiResult"/> whose status is 0 when nothing answered.
/// </summary>
public sealed class DemoApiClient : IDisposable
{
    public static readonly TimeSpan ReadTimeout = TimeSpan.FromSeconds(5);
    public static readonly TimeSpan ActionTimeout = TimeSpan.FromSeconds(30);
    public static readonly TimeSpan JobTimeout = TimeSpan.FromMinutes(5);

    private readonly HttpClient _http;
    private readonly string _middleware;
    private readonly string _hq;
    private readonly IReadOnlyDictionary<string, string> _tokens;

    public DemoApiClient(string middlewareBaseUrl, string hqBaseUrl, X509Certificate2 authority,
                         IReadOnlyDictionary<string, string> tokens)
        : this(new HttpClient(ServerCertificateValidator.CreateHandler(authority, null)),
               middlewareBaseUrl, hqBaseUrl, tokens)
    {
    }

    internal DemoApiClient(HttpClient http, string middlewareBaseUrl, string hqBaseUrl,
                           IReadOnlyDictionary<string, string> tokens)
    {
        _http = http;
        // Each call has its own timeout through a cancellation token.
        _http.Timeout = Timeout.InfiniteTimeSpan;
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _middleware = middlewareBaseUrl.TrimEnd('/');
        _hq = hqBaseUrl.TrimEnd('/');
        _tokens = tokens;
    }

    // --- Reads --------------------------------------------------------------

    public Task<ApiResult> GetInventoryAsync(string storeId, string tokenName) =>
        SendAsync(HttpMethod.Get, $"{_middleware}/stores/{Uri.EscapeDataString(storeId)}/inventory",
            tokenName, null, ReadTimeout);

    public Task<ApiResult> GetAuditLogsAsync(int limit) =>
        SendAsync(HttpMethod.Get, $"{_middleware}/audit-logs?limit={limit}", "auditor", null, ReadTimeout);

    public Task<ApiResult> GetHqBatchesAsync() =>
        SendAsync(HttpMethod.Get, $"{_hq}/demo/batches", null, null, ReadTimeout);

    // --- Probes for the 404 rule (no side effect) ----------------------------

    /// <summary>GET on the POST-only /sync/run: 405 when deployed, 404 when not.</summary>
    public Task<ApiResult> ProbeSyncRunAsync() =>
        SendAsync(HttpMethod.Get, $"{_middleware}/sync/run", "admin", null, ReadTimeout);

    /// <summary>GET on the POST-only /hq/snapshot: 405 when deployed, 404 when not.</summary>
    public Task<ApiResult> ProbeSnapshotAsync() =>
        SendAsync(HttpMethod.Get, $"{_middleware}/hq/snapshot", "hq_operator", null, ReadTimeout);

    /// <summary>GET /admin/near-expiry-thresholds, which comes with the near-expiry job (#43).</summary>
    public Task<ApiResult> ProbeThresholdsAsync() =>
        SendAsync(HttpMethod.Get, $"{_middleware}/admin/near-expiry-thresholds", "admin", null, ReadTimeout);

    // --- Actions ------------------------------------------------------------

    public Task<ApiResult> RunSyncAsync() =>
        SendAsync(HttpMethod.Post, $"{_middleware}/sync/run", "admin", null, ActionTimeout);

    public Task<ApiResult> SetHqModeAsync(string mode) =>
        SendAsync(HttpMethod.Put, $"{_hq}/demo/mode", null, $"{{\"mode\":\"{mode}\"}}", ActionTimeout);

    public Task<ApiResult> SendSnapshotAsync(DateTime utcNow) =>
        SendAsync(HttpMethod.Post, $"{_middleware}/hq/snapshot", "hq_operator", SnapshotSample(utcNow), ActionTimeout);

    public Task<ApiResult> RunJobAsync(string name) =>
        SendAsync(HttpMethod.Post, $"{_middleware}/admin/jobs/{Uri.EscapeDataString(name)}/run", "admin", null,
            JobTimeout);

    public Task<ApiResult> SetThresholdAsync(string category, int days) =>
        SendAsync(HttpMethod.Put, $"{_middleware}/admin/near-expiry-thresholds/{Uri.EscapeDataString(category)}",
            "admin", $"{{\"threshold_days\":{days}}}", ActionTimeout);

    /// <summary>A small snapshot body: 999 units that must never reach the local stock.</summary>
    public static string SnapshotSample(DateTime utcNow) =>
        "{\"store_id\":\"STORE-DN1\",\"taken_at\":\"" + utcNow.ToString("yyyy-MM-ddTHH:mm:ssZ") +
        "\",\"items\":[{\"sku\":\"SKU-0001\",\"quantity\":999},{\"sku\":\"SKU-0004\",\"quantity\":999}]}";

    private async Task<ApiResult> SendAsync(HttpMethod method, string url, string? tokenName, string? json,
                                            TimeSpan timeout)
    {
        var stopwatch = Stopwatch.StartNew();
        string? token = null;
        if (tokenName is not null && !_tokens.TryGetValue(tokenName, out token))
        {
            return new ApiResult(0, string.Empty, $"no token '{tokenName}' in .tokens/demo_tokens.json", string.Empty, 0);
        }

        using var request = new HttpRequestMessage(method, url);
        if (token is not null)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        if (json is not null)
        {
            request.Content = new StringContent(json, Encoding.UTF8, "application/json");
        }

        using var cancellation = new CancellationTokenSource(timeout);
        try
        {
            using var response = await _http.SendAsync(request, cancellation.Token).ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellation.Token).ConfigureAwait(false);
            var (code, message) = ApiParsers.ErrorOf(body);
            return new ApiResult((int)response.StatusCode, code, message, body, stopwatch.Elapsed.TotalMilliseconds);
        }
        catch (OperationCanceledException)
        {
            return new ApiResult(0, string.Empty, $"no answer within {timeout.TotalSeconds:0} s", string.Empty,
                stopwatch.Elapsed.TotalMilliseconds);
        }
        catch (HttpRequestException error)
        {
            return new ApiResult(0, string.Empty, error.Message, string.Empty, stopwatch.Elapsed.TotalMilliseconds);
        }
    }

    public void Dispose() => _http.Dispose();
}
