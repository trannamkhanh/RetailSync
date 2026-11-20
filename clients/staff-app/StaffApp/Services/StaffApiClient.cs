using System.Net.Http.Headers;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.RegularExpressions;
using StaffApp.Models;
using StaffApp.Security;

namespace StaffApp.Services;

/// <summary>
/// The Staff API calls of the app (DS-04), with the one staff token. Calls never throw
/// for HTTP or network errors: they return an <see cref="ApiResult"/> whose status is 0
/// when nothing answered. The app never reads SQL.
/// </summary>
public sealed class StaffApiClient : IDisposable
{
    public static readonly TimeSpan Timeout = TimeSpan.FromSeconds(10);
    private static readonly Regex BarcodePattern = new("^[A-Za-z0-9-]{1,30}$", RegexOptions.Compiled);

    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private readonly string _token;

    public StaffApiClient(string baseUrl, X509Certificate2 authority, string token)
        : this(new HttpClient(ServerCertificateValidator.CreateHandler(authority, null)), baseUrl, token)
    {
    }

    internal StaffApiClient(HttpClient http, string baseUrl, string token)
    {
        _http = http;
        _http.Timeout = System.Threading.Timeout.InfiniteTimeSpan;
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _baseUrl = baseUrl.TrimEnd('/');
        _token = token;
    }

    /// <summary>The DS-04 barcode pattern, checked before a call so the user gets a clear message.</summary>
    public static bool IsValidBarcode(string barcode) => BarcodePattern.IsMatch(barcode);

    public Task<ApiResult> GetProductAsync(string barcode) =>
        SendAsync(HttpMethod.Get, $"/products/barcode/{Uri.EscapeDataString(barcode)}", null);

    public Task<ApiResult> GetCrossStoreStockAsync(string barcode, string fromStore) =>
        SendAsync(HttpMethod.Get,
            $"/products/barcode/{Uri.EscapeDataString(barcode)}/stock?from_store={Uri.EscapeDataString(fromStore)}",
            null);

    public Task<ApiResult> GetAlertsAsync() => SendAsync(HttpMethod.Get, "/near-expiry-alerts", null);

    public Task<ApiResult> GetRecommendationsAsync() => SendAsync(HttpMethod.Get, "/recommendations", null);

    public Task<ApiResult> GetRecommendationAsync(long recId) =>
        SendAsync(HttpMethod.Get, $"/recommendations/{recId}", null);

    public Task<ApiResult> DecideAsync(long recId, bool accept) =>
        SendAsync(HttpMethod.Post, $"/recommendations/{recId}/decision",
            accept ? "{\"decision\":\"ACCEPT\"}" : "{\"decision\":\"REJECT\"}");

    private async Task<ApiResult> SendAsync(HttpMethod method, string path, string? json)
    {
        using var request = new HttpRequestMessage(method, _baseUrl + path);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
        if (json is not null)
        {
            request.Content = new StringContent(json, Encoding.UTF8, "application/json");
        }

        using var cancellation = new CancellationTokenSource(Timeout);
        try
        {
            using var response = await _http.SendAsync(request, cancellation.Token).ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellation.Token).ConfigureAwait(false);
            var (code, message) = ApiParsers.ErrorOf(body);
            return new ApiResult((int)response.StatusCode, code, message, body);
        }
        catch (OperationCanceledException)
        {
            return new ApiResult(0, string.Empty, $"no answer within {Timeout.TotalSeconds:0} s", string.Empty);
        }
        catch (HttpRequestException error)
        {
            return new ApiResult(0, string.Empty, error.Message, string.Empty);
        }
    }

    public void Dispose() => _http.Dispose();
}
