using System.Diagnostics;
using System.Globalization;
using System.Net.Http.Headers;
using System.Security.Cryptography.X509Certificates;
using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Security;

namespace DemoPos.Services;

/// <summary>
/// Fetches active discounts from GET /api/v1/pos/discounts on the POS gateway (PB-50-2),
/// reusing the same client certificate, POS JWT token and CA validation as TerminalClient.
/// </summary>
public sealed class PosDiscountClient : IDisposable
{
    private static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(5);

    private readonly HttpClient _http;
    private readonly string _discountsUrl;
    private readonly string _token;
    private readonly string? _certificatePosId;
    private readonly RequestLog _log;

    public PosDiscountClient(string posBaseUrl, X509Certificate2 authority,
                             X509Certificate2? clientCertificate, string? certificatePosId,
                             string token, RequestLog log, HttpMessageHandler? handler = null)
    {
        _http = handler is null
            ? new HttpClient(ServerCertificateValidator.CreateHandler(authority, clientCertificate), disposeHandler: true)
            : new HttpClient(handler, disposeHandler: false);
        _http.Timeout = RequestTimeout;
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        _discountsUrl = posBaseUrl.TrimEnd('/') + "/pos/discounts";
        _token = token;
        _certificatePosId = certificatePosId;
        _log = log;
    }

    public string DiscountsUrl => _discountsUrl;

    public async Task<PosDiscountFetchResult> FetchAsync(CancellationToken cancellationToken = default)
    {
        var identity = JwtInspector.Describe(_token);
        var stopwatch = Stopwatch.StartNew();
        using var request = new HttpRequestMessage(HttpMethod.Get, _discountsUrl);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);

        try
        {
            using var response = await _http
                .SendAsync(request, HttpCompletionOption.ResponseContentRead, cancellationToken)
                .ConfigureAwait(false);
            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            stopwatch.Stop();
            var status = (int)response.StatusCode;
            var elapsed = Math.Round(stopwatch.Elapsed.TotalMilliseconds, 1);

            AddLog(status, elapsed, body, identity);

            if (status is 401 or 403)
            {
                var parsedError = PosResultParser.Parse(body, status, elapsed);
                Trace.TraceWarning(
                    $"[PB-50] GET {_discountsUrl} refused ({status} {parsedError.Code}) for terminal '{_certificatePosId ?? "none"}': {parsedError.Message}");
                return new PosDiscountFetchResult
                {
                    IsSuccess = false,
                    HttpStatus = status,
                    ElapsedMs = elapsed,
                    Error = $"{status} {parsedError.Code}: {PosDisplayNames.ServerMessage(parsedError.Code, parsedError.Message)}",
                };
            }

            if (!response.IsSuccessStatusCode)
            {
                return new PosDiscountFetchResult
                {
                    IsSuccess = false,
                    HttpStatus = status,
                    ElapsedMs = elapsed,
                    Error = $"HTTP {status}",
                };
            }

            if (!PosDiscounts.TryParse(body, out var list, out var parseError) || list is null)
            {
                return new PosDiscountFetchResult
                {
                    IsSuccess = false,
                    HttpStatus = status,
                    ElapsedMs = elapsed,
                    Error = parseError ?? "Phản hồi danh sách giảm giá không hợp lệ.",
                };
            }

            return new PosDiscountFetchResult
            {
                IsSuccess = true,
                HttpStatus = status,
                ElapsedMs = elapsed,
                Data = list,
            };
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            stopwatch.Stop();
            var elapsed = Math.Round(stopwatch.Elapsed.TotalMilliseconds, 1);
            AddLog(0, elapsed, "Request timed out after 5 seconds.", identity);
            return new PosDiscountFetchResult
            {
                IsSuccess = false,
                HttpStatus = 0,
                ElapsedMs = elapsed,
                Error = "Không có phản hồi trong 5 giây.",
            };
        }
        catch (HttpRequestException error)
        {
            stopwatch.Stop();
            var elapsed = Math.Round(stopwatch.Elapsed.TotalMilliseconds, 1);
            AddLog(0, elapsed, error.Message, identity);
            return new PosDiscountFetchResult
            {
                IsSuccess = false,
                HttpStatus = 0,
                ElapsedMs = elapsed,
                Error = $"Không kết nối được tới cổng POS: {error.Message}",
            };
        }
    }

    private void AddLog(int status, double elapsedMs, string responseBody, JwtIdentity identity) =>
        _log.Add(new RequestLogEntry
        {
            Method = "GET",
            Url = _discountsUrl,
            Status = status,
            ElapsedMs = elapsedMs,
            RequestBody = string.Empty,
            ResponseBody = responseBody,
            CertificatePosId = _certificatePosId,
            Role = identity.Role,
            Subject = identity.Subject,
            Kind = RequestKind.Pos,
        });

    public void Dispose() => _http.Dispose();
}

/// <summary>
/// Holds the active discount list of one terminal, preserving the last valid list across
/// fetch failures and dropping any list whose business_date is before today (UTC+7).
/// </summary>
public sealed class PosDiscountBook
{
    private readonly Dictionary<string, PosDiscountItem> _bySku = new(StringComparer.OrdinalIgnoreCase);
    private PosDiscountList? _current;

    public DateTime? LastUpdatedLocal { get; private set; }

    public bool LastFetchFailed { get; private set; }

    public string? LastError { get; private set; }

    public bool EvictIfExpired(DateTime utcNow)
    {
        if (_current is null || _current.BusinessDate >= PosDiscounts.CurrentBusinessDate(utcNow))
        {
            return false;
        }

        _current = null;
        _bySku.Clear();
        LastUpdatedLocal = null;
        return true;
    }

    public int ActiveCount(DateTime? utcNow = null)
    {
        EvictIfExpired(utcNow ?? DateTime.UtcNow);
        return _bySku.Count;
    }

    public bool RestoreCached(PosDiscountList cached, DateTime updatedAtLocal, DateTime utcNow)
    {
        ArgumentNullException.ThrowIfNull(cached);
        if (cached.BusinessDate < PosDiscounts.CurrentBusinessDate(utcNow))
        {
            _current = null;
            _bySku.Clear();
            LastUpdatedLocal = null;
            return false;
        }

        _current = cached;
        LastUpdatedLocal = updatedAtLocal;
        LastFetchFailed = false;
        LastError = null;
        _bySku.Clear();
        foreach (var item in cached.Items)
        {
            _bySku[item.Sku] = item;
        }

        return true;
    }

    public void ApplySuccess(PosDiscountList fetched, DateTime utcNow, DateTime localNow)
    {
        ArgumentNullException.ThrowIfNull(fetched);
        LastFetchFailed = false;
        LastError = null;

        if (fetched.BusinessDate < PosDiscounts.CurrentBusinessDate(utcNow))
        {
            _current = null;
            _bySku.Clear();
            LastUpdatedLocal = null;
            return;
        }

        _current = fetched;
        LastUpdatedLocal = localNow;
        _bySku.Clear();
        foreach (var item in fetched.Items)
        {
            _bySku[item.Sku] = item;
        }
    }

    public void ApplyFailure(string error, DateTime utcNow)
    {
        EvictIfExpired(utcNow);
        LastFetchFailed = true;
        LastError = error;
    }

    public bool TryGetDiscount(string sku, DateTime utcNow, out PosDiscountItem? discount)
    {
        EvictIfExpired(utcNow);
        return _bySku.TryGetValue(sku, out discount);
    }

    public decimal PriceFor(ProductConfig product, DateTime? utcNow = null)
    {
        ArgumentNullException.ThrowIfNull(product);
        return PriceFor(product.Sku, product.UnitPrice, utcNow);
    }

    public decimal PriceFor(string sku, decimal listPrice, DateTime? utcNow = null) =>
        TryGetDiscount(sku, utcNow ?? DateTime.UtcNow, out var discount) && discount is not null
            ? discount.DiscountedPrice
            : listPrice;

    public string FormatStatusText(DateTime utcNow, bool isMock = false)
    {
        EvictIfExpired(utcNow);
        if (LastFetchFailed)
        {
            return _current is not null && LastUpdatedLocal is { } updatedAt
                ? $"Giảm giá: cập nhật lúc {updatedAt.ToString("HH:mm", CultureInfo.InvariantCulture)}"
                : "Giảm giá: chưa tải được";
        }

        if (isMock)
        {
            return $"Giảm giá: {_bySku.Count} mã (MOCK)";
        }

        if (_current is null)
        {
            return "Giảm giá: —";
        }

        return _bySku.Count == 0
            ? "Giảm giá: không có"
            : $"Giảm giá: {_bySku.Count} mã";
    }
}
