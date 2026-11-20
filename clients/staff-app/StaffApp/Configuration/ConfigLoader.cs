using System.Text.Json;

namespace StaffApp.Configuration;

/// <summary>
/// Loads appsettings.json and appsettings.Local.json from the app folder, then the token.
/// Like the demo POS, the local file overrides only the keys it contains. The token file
/// holds either one token (one line) or a JSON object of tokens such as
/// .tokens/demo_tokens.json, from which <see cref="AppSettings.TokenName"/> is taken.
/// </summary>
public static class ConfigLoader
{
    public const string SettingsFile = "appsettings.json";
    public const string LocalSettingsFile = "appsettings.Local.json";

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public static LoadedConfig Load(string appFolder)
    {
        var settings = new AppSettings();
        Apply(settings, Path.Combine(appFolder, SettingsFile), required: true);
        Apply(settings, Path.Combine(appFolder, LocalSettingsFile), required: false);
        Validate(settings);

        var token = ReadToken(Resolve(appFolder, settings.TokenFile), settings.TokenName);
        var info = TokenInfo.Read(token);
        if (string.IsNullOrEmpty(info.StoreId))
        {
            throw new ConfigurationException(
                $"The token of '{info.Subject}' has no store_id; use a staff_dn* token (Staff role).");
        }

        return new LoadedConfig(settings, Resolve(appFolder, settings.CaCertificatePath), token, info);
    }

    internal static string ReadToken(string path, string tokenName)
    {
        if (!File.Exists(path))
        {
            throw new ConfigurationException(
                $"Missing token file: {path}\nPut one staff_dn* token in it (see clients/staff-app/README.md).");
        }

        var text = File.ReadAllText(path).Trim();
        if (!text.StartsWith('{'))
        {
            return text.Length > 0 ? text : throw new ConfigurationException($"The token file is empty: {path}");
        }

        try
        {
            var tokens = JsonSerializer.Deserialize<Dictionary<string, string>>(text, Options);
            return tokens is not null && tokens.TryGetValue(tokenName, out var token) && token.Length > 0
                ? token.Trim()
                : throw new ConfigurationException($"No token '{tokenName}' in {path}.");
        }
        catch (JsonException error)
        {
            throw new ConfigurationException($"The token file is not valid JSON: {path}", error);
        }
    }

    private static void Apply(AppSettings settings, string path, bool required)
    {
        if (!File.Exists(path))
        {
            if (required)
            {
                throw new ConfigurationException($"Missing {path}.");
            }

            return;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path),
                new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
            var root = document.RootElement;
            settings.BaseUrl = String(root, nameof(AppSettings.BaseUrl)) ?? settings.BaseUrl;
            settings.CaCertificatePath = String(root, nameof(AppSettings.CaCertificatePath)) ?? settings.CaCertificatePath;
            settings.TokenFile = String(root, nameof(AppSettings.TokenFile)) ?? settings.TokenFile;
            settings.TokenName = String(root, nameof(AppSettings.TokenName)) ?? settings.TokenName;
            if (root.TryGetProperty(nameof(AppSettings.FontSize), out var size) && size.TryGetSingle(out var points))
            {
                settings.FontSize = points;
            }
        }
        catch (JsonException error)
        {
            throw new ConfigurationException($"{path} is not valid JSON.", error);
        }
    }

    private static string? String(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static void Validate(AppSettings settings)
    {
        if (!Uri.TryCreate(settings.BaseUrl, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps)
        {
            throw new ConfigurationException($"BaseUrl must be an https URL, got '{settings.BaseUrl}'.");
        }

        if (settings.FontSize is < 8 or > 32)
        {
            throw new ConfigurationException($"FontSize must be between 8 and 32, got {settings.FontSize}.");
        }
    }

    private static string Resolve(string appFolder, string path) =>
        Path.IsPathRooted(path) ? path : Path.GetFullPath(Path.Combine(appFolder, path));
}
