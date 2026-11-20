namespace StaffApp.Configuration;

/// <summary>
/// appsettings.json, overridden key by key by appsettings.Local.json (never committed).
/// Relative paths are relative to the folder of the app, so it runs outside the repository.
/// </summary>
public sealed class AppSettings
{
    /// <summary>The middleware API, for example https://192.168.1.10:8443/api/v1.</summary>
    public string BaseUrl { get; set; } = "https://localhost:8443/api/v1";

    /// <summary>The development CA certificate (.certs/ca.crt of the server).</summary>
    public string CaCertificatePath { get; set; } = "ca.crt";

    /// <summary>A file with one staff token, or .tokens/demo_tokens.json (then <see cref="TokenName"/> picks it).</summary>
    public string TokenFile { get; set; } = "staff_token.txt";

    /// <summary>The key to read when <see cref="TokenFile"/> is a JSON object of tokens.</summary>
    public string TokenName { get; set; } = "staff_dn1";

    /// <summary>Base font size in points; DS-08 asks for large fonts.</summary>
    public float FontSize { get; set; } = 12f;
}

public sealed class ConfigurationException : Exception
{
    public ConfigurationException(string message, Exception? inner = null) : base(message, inner)
    {
    }
}

/// <summary>Settings with absolute paths, the token and what the token says.</summary>
public sealed record LoadedConfig(AppSettings Settings, string CaCertificatePath, string Token, TokenInfo TokenInfo);
