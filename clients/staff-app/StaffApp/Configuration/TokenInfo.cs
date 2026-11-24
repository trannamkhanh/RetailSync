using System.Text.Json;

namespace StaffApp.Configuration;

/// <summary>
/// The claims of the staff token, read without checking the signature (the server checks it).
/// The store comes from <c>store_id</c>; the title bar shows the store and <c>sub</c>.
/// </summary>
public sealed record TokenInfo(string Subject, string Role, string? StoreId, DateTimeOffset? ExpiresAt)
{
    public bool IsExpired(DateTimeOffset now) => ExpiresAt is { } expires && expires <= now;

    public static TokenInfo Read(string token)
    {
        var parts = token.Split('.');
        if (parts.Length != 3)
        {
            throw new ConfigurationException("Token không phải JWT (header.payload.signature).");
        }

        try
        {
            using var document = JsonDocument.Parse(Base64UrlDecode(parts[1]));
            var root = document.RootElement;
            var subject = root.TryGetProperty("sub", out var sub) && sub.ValueKind == JsonValueKind.String
                ? sub.GetString()!
                : throw new ConfigurationException("Token không có claim 'sub'.");
            var role = root.TryGetProperty("role", out var value) && value.ValueKind == JsonValueKind.String
                ? value.GetString()!
                : string.Empty;
            var store = root.TryGetProperty("store_id", out var storeId) && storeId.ValueKind == JsonValueKind.String
                ? storeId.GetString()
                : null;
            DateTimeOffset? expires = root.TryGetProperty("exp", out var exp) && exp.TryGetInt64(out var seconds)
                ? DateTimeOffset.FromUnixTimeSeconds(seconds)
                : null;
            return new TokenInfo(subject, role, store, expires);
        }
        catch (Exception error) when (error is JsonException or FormatException or ArgumentException)
        {
            throw new ConfigurationException("Không đọc được phần payload của token.", error);
        }
    }

    private static byte[] Base64UrlDecode(string text)
    {
        var padded = text.Replace('-', '+').Replace('_', '/');
        padded += (padded.Length % 4) switch { 2 => "==", 3 => "=", _ => string.Empty };
        return Convert.FromBase64String(padded);
    }
}
