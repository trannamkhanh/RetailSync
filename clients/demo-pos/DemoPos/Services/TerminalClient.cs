using System.Diagnostics;
using System.Net.Http.Headers;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using DemoPos.Models;
using DemoPos.Security;

namespace DemoPos.Services;

/// <summary>One POS terminal: its own HttpClient, client certificate and bearer token.</summary>
public sealed class TerminalClient : IDisposable
{
    private static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(5);

    private readonly HttpClient _http;
    private readonly string _eventsUrl;
    private readonly string _token;
    private readonly string? _certificatePosId;
    private readonly RequestLog _log;

    public TerminalClient(string posBaseUrl, X509Certificate2 authority,
                          X509Certificate2? clientCertificate, string? certificatePosId,
                          string token, RequestLog log, HttpMessageHandler? handler = null)
    {
        _http = handler is null
            ? new HttpClient(ServerCertificateValidator.CreateHandler(authority, clientCertificate))
            : new HttpClient(handler);
        _http.Timeout = RequestTimeout;
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _eventsUrl = posBaseUrl.TrimEnd('/') + "/pos/events";
        _token = token;
        _certificatePosId = certificatePosId;
        _log = log;
    }

    public string EventsUrl => _eventsUrl;

    public async Task<PosResult> SendAsync(string rawBody, CancellationToken cancellationToken = default)
    {
        var identity = JwtInspector.Describe(_token);
        var stopwatch = Stopwatch.StartNew();
        using var request = new HttpRequestMessage(HttpMethod.Post, _eventsUrl)
        {
            Content = new StringContent(rawBody, Encoding.UTF8, "application/json"),
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);

        try
        {
            using var response = await _http
                .SendAsync(request, HttpCompletionOption.ResponseContentRead, cancellationToken)
                .ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            stopwatch.Stop();
            AddLog("POST", _eventsUrl, (int)response.StatusCode, stopwatch.Elapsed.TotalMilliseconds,
                rawBody, body, identity, RequestKind.Pos);
            return PosResultParser.Parse(body, (int)response.StatusCode, stopwatch.Elapsed.TotalMilliseconds);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            stopwatch.Stop();
            AddLog("POST", _eventsUrl, 0, stopwatch.Elapsed.TotalMilliseconds, rawBody,
                "Request timed out after 5 seconds.", identity, RequestKind.Pos);
            return PosResultParser.NetworkError(
                "TIMEOUT",
                "No answer within 5 seconds. Keep the cart and Retry with the same transaction_id.",
                stopwatch.Elapsed.TotalMilliseconds);
        }
        catch (HttpRequestException error)
        {
            stopwatch.Stop();
            AddLog("POST", _eventsUrl, 0, stopwatch.Elapsed.TotalMilliseconds, rawBody,
                error.Message, identity, RequestKind.Pos);
            return PosResultParser.NetworkError(
                "NETWORK_ERROR",
                $"Could not reach the POS gateway: {error.Message}. Retry with the same transaction_id.",
                stopwatch.Elapsed.TotalMilliseconds);
        }
    }

    private void AddLog(string method, string url, int status, double elapsedMs,
                        string requestBody, string responseBody, JwtIdentity identity, RequestKind kind) =>
        _log.Add(new RequestLogEntry
        {
            Method = method,
            Url = url,
            Status = status,
            ElapsedMs = Math.Round(elapsedMs, 1),
            RequestBody = requestBody,
            ResponseBody = responseBody,
            CertificatePosId = _certificatePosId,
            Role = identity.Role,
            Subject = identity.Subject,
            Kind = kind,
        });

    public void Dispose() => _http.Dispose();
}
