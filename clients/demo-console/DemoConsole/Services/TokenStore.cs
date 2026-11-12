using System.Text.Json;
using DemoConsole.Configuration;

namespace DemoConsole.Services;

/// <summary>Copied from the demo POS. Reads .tokens/demo_tokens.json. The file is git-ignored and never logged.</summary>
public static class TokenStore
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public static IReadOnlyDictionary<string, string> Load(string path)
    {
        if (!File.Exists(path))
        {
            return new Dictionary<string, string>(StringComparer.Ordinal);
        }

        try
        {
            var json = File.ReadAllText(path);
            var tokens = JsonSerializer.Deserialize<Dictionary<string, string>>(json, Options);
            return tokens is null
                ? new Dictionary<string, string>(StringComparer.Ordinal)
                : new Dictionary<string, string>(tokens, StringComparer.Ordinal);
        }
        catch (JsonException error)
        {
            throw new ConfigurationException($"Token file is not valid JSON: {path}", error);
        }
        catch (IOException error)
        {
            throw new ConfigurationException($"Could not read the token file: {path}", error);
        }
    }
}
