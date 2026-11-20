using StaffApp.Models;

namespace StaffApp.Services;

/// <summary>Where a call was made, because 404 means something different on each screen.</summary>
public enum ApiArea
{
    Lookup,
    Alerts,
    Recommendations,
    Detail,
    Decision,
}

/// <summary>A failed call as the user sees it. <c>CanRetry</c> offers Retry; <c>Refresh</c> reloads the list.</summary>
public sealed record UserMessage(string Text, bool CanRetry, bool Refresh);

/// <summary>Maps a failed answer to the DS-08 messages ("Token invalid or expired", "Already decided" ...).</summary>
public static class UserMessages
{
    public const string TokenInvalid = "Token invalid or expired";
    public const string Forbidden = "This role cannot use this function";
    public const string ProductNotFound = "Product not found";
    public const string AlreadyDecided = "Already decided";
    public const string NoLongerValid = "No longer valid";
    public const string NoStores = "No stores available for lookup";
    public const string NoStock = "No store has this product in stock";
    public const string NoAlerts = "No near-expiry alerts";
    public const string NoRecommendations = "No recommendations to process";
    public const string InvalidBarcode = "Enter a barcode of 1 to 30 letters, digits or '-'";

    public static UserMessage For(ApiResult result, ApiArea area)
    {
        if (result.IsUnreachable)
        {
            return new UserMessage($"Cannot reach the server ({result.Message}). Check the network and press Retry.",
                CanRetry: true, Refresh: false);
        }

        return result.Status switch
        {
            401 => new UserMessage(TokenInvalid, false, false),
            403 => new UserMessage(Forbidden, false, false),
            404 when area == ApiArea.Lookup => new UserMessage(ProductNotFound, false, false),
            404 when area is ApiArea.Detail or ApiArea.Decision => new UserMessage(NoLongerValid, false, true),
            409 when result.Code == "ALREADY_DECIDED" => new UserMessage(AlreadyDecided, false, true),
            409 when result.Code == "RECOMMENDATION_EXPIRED" => new UserMessage(NoLongerValid, false, true),
            422 when area == ApiArea.Lookup => new UserMessage(InvalidBarcode, false, false),
            >= 500 => new UserMessage($"Server error (HTTP {result.Status}). Press Retry.", true, false),
            _ => new UserMessage(Describe(result), false, false),
        };
    }

    /// <summary>A parse failure of a 2xx answer: the server does not follow DS-04.</summary>
    public static UserMessage Unexpected(FormatException error) =>
        new($"Unexpected answer from the server: {error.Message}", CanRetry: true, Refresh: false);

    private static string Describe(ApiResult result)
    {
        var detail = result.Message.Length > 0 ? result.Message : result.Code;
        return detail.Length > 0 ? $"HTTP {result.Status}: {detail}" : $"HTTP {result.Status}";
    }
}
