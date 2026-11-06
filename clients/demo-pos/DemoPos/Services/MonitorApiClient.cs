using System.Diagnostics;
using System.Net.Http.Headers;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using DemoPos.Models;
using DemoPos.Security;

namespace DemoPos.Services;

/// <summary>Read-only monitor calls on port 8443; no client certificate is sent here.</summary>
public sealed class MonitorApiClient : IDisposable
{
    private static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(5);

    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private readonly RequestLog _log;

    public MonitorApiClient(string monitorBaseUrl, X509Certificate2 authority, RequestLog log)
    {
        _http = new HttpClient(ServerCertificateValidator.CreateHandler(authority, null))
        {
            Timeout = RequestTimeout,
        };
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _baseUrl = monitorBaseUrl.TrimEnd('/');
        _log = log;
    }

    public Task<ApiCallResult<StoreInventory>> GetStockAsync(string storeId, string token,
                                                             CancellationToken cancellationToken = default) =>
        GetAsync<StoreInventory>(
            $"{_baseUrl}/stores/{Uri.EscapeDataString(storeId)}/inventory", token,
            RequestKind.Monitor, cancellationToken);

    public Task<ApiCallResult<AuditLogList>> GetAuditAsync(string token,
                                                           CancellationToken cancellationToken = default) =>
        GetAsync<AuditLogList>($"{_baseUrl}/audit-logs?limit=20", token,
            RequestKind.Monitor, cancellationToken);

    public Task<ApiCallResult<HealthResponse>> GetHealthAsync(
        CancellationToken cancellationToken = default) =>
        GetAsync<HealthResponse>($"{_baseUrl}/health", null, RequestKind.Probe, cancellationToken);

    private async Task<ApiCallResult<T>> GetAsync<T>(string url, string? token, RequestKind kind,
                                                      CancellationToken cancellationToken)
    {
        var identity = token is null ? JwtIdentity.Unknown : JwtInspector.Describe(token);
        var stopwatch = Stopwatch.StartNew();
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        if (token is not null)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        try
        {
            using var response = await _http
                .SendAsync(request, HttpCompletionOption.ResponseContentRead, cancellationToken)
                .ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            stopwatch.Stop();
            _log.Add(Entry("GET", url, (int)response.StatusCode, stopwatch.Elapsed.TotalMilliseconds,
                string.Empty, body, identity, kind));

            if (!response.IsSuccessStatusCode)
            {
                return Failure<T>((int)response.StatusCode, stopwatch.Elapsed.TotalMilliseconds,
                    $"HTTP {(int)response.StatusCode}: {Trim(body)}", body);
            }

            try
            {
                var data = JsonSerializer.Deserialize<T>(body, MonitorJson.Options);
                if (data is null)
                {
                    return Failure<T>((int)response.StatusCode, stopwatch.Elapsed.TotalMilliseconds,
                        "The response body was empty.", body);
                }

                return new ApiCallResult<T>
                {
                    IsSuccess = true,
                    Status = (int)response.StatusCode,
                    ElapsedMs = Math.Round(stopwatch.Elapsed.TotalMilliseconds, 1),
                    Data = data,
                    RawBody = body,
                };
            }
            catch (JsonException error)
            {
                return Failure<T>((int)response.StatusCode, stopwatch.Elapsed.TotalMilliseconds,
                    $"The response was not the expected JSON: {error.Message}", body);
            }
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            stopwatch.Stop();
            _log.Add(Entry("GET", url, 0, stopwatch.Elapsed.TotalMilliseconds, string.Empty,
                "Request timed out after 5 seconds.", identity, kind));
            return Failure<T>(0, stopwatch.Elapsed.TotalMilliseconds,
                "No answer within 5 seconds.", string.Empty);
        }
        catch (HttpRequestException error)
        {
            stopwatch.Stop();
            _log.Add(Entry("GET", url, 0, stopwatch.Elapsed.TotalMilliseconds, string.Empty,
                error.Message, identity, kind));
            return Failure<T>(0, stopwatch.Elapsed.TotalMilliseconds,
                $"Could not reach the middleware: {error.Message}", string.Empty);
        }
    }

    private static RequestLogEntry Entry(string method, string url, int status, double elapsedMs,
                                         string requestBody, string responseBody, JwtIdentity identity,
                                         RequestKind kind) => new()
    {
        Method = method,
        Url = url,
        Status = status,
        ElapsedMs = Math.Round(elapsedMs, 1),
        RequestBody = requestBody,
        ResponseBody = responseBody,
        CertificatePosId = null,
        Role = identity.Role,
        Subject = identity.Subject,
        Kind = kind,
    };

    private static ApiCallResult<T> Failure<T>(int status, double elapsedMs, string error, string rawBody) => new()
    {
        IsSuccess = false,
        Status = status,
        ElapsedMs = Math.Round(elapsedMs, 1),
        Error = error,
        RawBody = rawBody,
    };

    private static string Trim(string body) =>
        body.Length <= 200 ? body.Trim() : body[..200].Trim() + "…";

    public void Dispose() => _http.Dispose();
}

/// <summary>Checks the gateway TLS endpoint without a client certificate; 400 means it is up.</summary>
public sealed class GatewayProbe : IDisposable
{
    private readonly HttpClient _http;

    public GatewayProbe(X509Certificate2 authority)
    {
        _http = new HttpClient(ServerCertificateValidator.CreateHandler(authority, null))
        {
            Timeout = TimeSpan.FromSeconds(5),
        };
    }

    public async Task<(bool Up, int Status, double ElapsedMs, string? Error)> CheckAsync(
        string gatewayRootUrl, RequestLog log, CancellationToken cancellationToken = default)
    {
        var stopwatch = Stopwatch.StartNew();
        var url = gatewayRootUrl.TrimEnd('/') + "/";
        try
        {
            using var response = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            stopwatch.Stop();
            log.Add(new RequestLogEntry
            {
                Method = "GET",
                Url = url,
                Status = (int)response.StatusCode,
                ElapsedMs = Math.Round(stopwatch.Elapsed.TotalMilliseconds, 1),
                ResponseBody = body,
                Kind = RequestKind.Probe,
            });
            var up = (int)response.StatusCode == 400;
            return (up, (int)response.StatusCode, stopwatch.Elapsed.TotalMilliseconds,
                up ? null : $"Unexpected gateway status {(int)response.StatusCode}.");
        }
        catch (Exception error) when (error is HttpRequestException or OperationCanceledException)
        {
            stopwatch.Stop();
            log.Add(new RequestLogEntry
            {
                Method = "GET",
                Url = url,
                Status = 0,
                ElapsedMs = Math.Round(stopwatch.Elapsed.TotalMilliseconds, 1),
                ResponseBody = error.Message,
                Kind = RequestKind.Probe,
            });
            return (false, 0, stopwatch.Elapsed.TotalMilliseconds, error.Message);
        }
    }

    public void Dispose() => _http.Dispose();
}
