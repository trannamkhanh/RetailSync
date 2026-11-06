using System.Net;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace DemoPos.Models;

public enum PosOutcome
{
    OK,
    DUPLICATE,
    REJECTED,
    ERROR,
}

/// <summary>A normalised answer, matching the DS-04 PosEventResult or Error body.</summary>
public sealed class PosResult
{
    public required PosOutcome Outcome { get; init; }

    public required string Code { get; init; }

    public required string Message { get; init; }

    public IReadOnlyDictionary<string, int> CurrentStock { get; init; } =
        new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

    public int HttpStatus { get; init; }

    public double ElapsedMs { get; init; }

    public bool CanRetry { get; init; }

    public bool IsSuccess => Outcome is PosOutcome.OK or PosOutcome.DUPLICATE;

    public string StockText => CurrentStock.Count == 0
        ? string.Empty
        : string.Join(", ", CurrentStock
            .OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .Select(pair => $"{pair.Key}={pair.Value}"));

    public override string ToString() => $"{Outcome} {Code} ({HttpStatus}) {Message}";
}

public static class PosResultParser
{
    public static PosResult Parse(string? body, int httpStatus, double elapsedMs)
    {
        string? outcomeText = null;
        string? code = null;
        string? message = null;
        Dictionary<string, int>? stock = null;
        var hasJsonObject = false;

        if (!string.IsNullOrWhiteSpace(body))
        {
            try
            {
                using var document = JsonDocument.Parse(body);
                var root = document.RootElement;
                if (root.ValueKind == JsonValueKind.Object)
                {
                    hasJsonObject = true;
                    outcomeText = ReadString(root, "outcome");
                    code = ReadString(root, "code") ?? ReadString(root, "error_code");
                    message = ReadString(root, "message") ?? ReadString(root, "detail");
                    stock = ReadStock(root, "current_stock") ?? ReadStock(root, "currentStock");
                }
            }
            catch (JsonException)
            {
                // The gateway answers 400 with HTML, for example. Keep the status.
            }
        }

        if (!hasJsonObject && httpStatus is >= 200 and < 300)
        {
            return new PosResult
            {
                Outcome = PosOutcome.ERROR,
                Code = "INVALID_RESPONSE",
                Message = string.IsNullOrWhiteSpace(body)
                    ? "The service answered 200 without the expected JSON body."
                    : CleanBody(body),
                HttpStatus = httpStatus,
                ElapsedMs = Math.Round(elapsedMs, 1),
            };
        }

        var outcome = ResolveOutcome(outcomeText, httpStatus);
        code ??= ResolveCode(httpStatus, outcome);
        message ??= ResolveMessage(outcome, code, httpStatus, body);
        var canRetry = httpStatus >= 500
                       || outcome == PosOutcome.ERROR
                       && (httpStatus == 0
                           || code is "SERVICE_UNAVAILABLE" or "TIMEOUT" or "NETWORK_ERROR" or "NO_ANSWER");

        return new PosResult
        {
            Outcome = outcome,
            Code = code,
            Message = message,
            CurrentStock = stock ?? new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase),
            HttpStatus = httpStatus,
            ElapsedMs = Math.Round(elapsedMs, 1),
            CanRetry = canRetry,
        };
    }

    public static PosResult NetworkError(string code, string message, double elapsedMs) => new()
    {
        Outcome = PosOutcome.ERROR,
        Code = code,
        Message = message,
        HttpStatus = 0,
        ElapsedMs = Math.Round(elapsedMs, 1),
        CanRetry = true,
    };

    private static PosOutcome ResolveOutcome(string? value, int httpStatus)
    {
        if (!string.IsNullOrWhiteSpace(value)
            && Enum.TryParse<PosOutcome>(value, ignoreCase: true, out var parsed))
        {
            return parsed;
        }

        if (httpStatus is >= 200 and < 300)
        {
            return PosOutcome.OK;
        }

        return httpStatus >= 500 ? PosOutcome.ERROR : PosOutcome.REJECTED;
    }

    private static string ResolveCode(int status, PosOutcome outcome) => status switch
    {
        200 or 201 => outcome == PosOutcome.DUPLICATE ? "DUPLICATE_IGNORED" : "OK",
        400 => "HTTP_400",
        401 => "UNAUTHORIZED",
        403 => "FORBIDDEN",
        404 => "NOT_FOUND",
        409 => "CONFLICT",
        422 => "INVALID_EVENT",
        503 => "SERVICE_UNAVAILABLE",
        0 => "NO_ANSWER",
        _ => $"HTTP_{status}",
    };

    private static string ResolveMessage(PosOutcome outcome, string code, int status, string? body)
    {
        if (!string.IsNullOrWhiteSpace(body))
        {
            var raw = body.Trim();
            if (!raw.StartsWith('{') && !raw.StartsWith('['))
            {
                return CleanBody(raw);
            }
        }

        return status switch
        {
            400 => "The POS gateway answered 400; the request had no valid client certificate.",
            401 => "Missing, invalid or expired token.",
            403 => "The middleware refused the request (403 FORBIDDEN).",
            404 => "The requested resource or original sale was not found.",
            409 => "The middleware rejected the event by a business rule.",
            422 => "The middleware rejected the event body (422).",
            503 => "The service is unavailable. Retry with the same transaction_id.",
            0 => "No answer from the middleware.",
            _ => outcome == PosOutcome.OK ? "Event applied." : $"HTTP {status}.",
        };
    }

    private static string CleanBody(string body)
    {
        var text = Regex.Replace(body, "<[^>]+>", " ");
        text = WebUtility.HtmlDecode(text);
        text = Regex.Replace(text, @"\s+", " ").Trim();
        return text.Length <= 300 ? text : text[..300] + "…";
    }

    private static string? ReadString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static Dictionary<string, int>? ReadStock(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        var result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in value.EnumerateObject())
        {
            if (property.Value.ValueKind == JsonValueKind.Number
                && property.Value.TryGetInt32(out var quantity))
            {
                result[property.Name] = quantity;
            }
        }

        return result;
    }
}
