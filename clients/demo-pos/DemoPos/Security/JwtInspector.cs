using System.Text.Json;

namespace DemoPos.Security;

public sealed record JwtIdentity(string Role, string Subject)
{
    public static readonly JwtIdentity Unknown = new("?", "?");
}

/// <summary>Reads role and subject for display. It never verifies or stores the token.</summary>
public static class JwtInspector
{
    public static JwtIdentity Describe(string? token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            return JwtIdentity.Unknown;
        }

        try
        {
            var parts = token.Split('.');
            if (parts.Length < 2)
            {
                return JwtIdentity.Unknown;
            }

            var payload = Base64UrlDecode(parts[1]);
            using var document = JsonDocument.Parse(payload);
            var root = document.RootElement;
            var role = ReadString(root, "role") ?? "?";
            var subject = ReadString(root, "sub") ?? "?";
            return new JwtIdentity(role, subject);
        }
        catch (Exception)
        {
            return JwtIdentity.Unknown;
        }
    }

    private static string? ReadString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static byte[] Base64UrlDecode(string value)
    {
        var text = value.Replace('-', '+').Replace('_', '/');
        var padding = (4 - text.Length % 4) % 4;
        text += new string('=', padding);
        return Convert.FromBase64String(text);
    }
}
