using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using DemoConsole.Services;

namespace DemoConsole.Configuration;

/// <summary>
/// Loads appsettings.json, merges appsettings.Local.json, reads the SQL password from
/// the repository .env and the tokens from .tokens. Refuses RTS_DB and RTS_DB_TEST.
/// </summary>
public static class ConfigLoader
{
    /// <summary>Development databases the console must never connect to.</summary>
    public static readonly IReadOnlyList<string> ForbiddenDatabases = new[] { "RTS_DB", "RTS_DB_TEST" };

    /// <summary>Tokens the console needs besides one Staff token per store.</summary>
    public static readonly IReadOnlyList<string> RoleTokens = new[] { "admin", "auditor", "hq_operator" };

    private static readonly Regex PlainIdentifier = new("^[A-Za-z0-9_]{1,64}$", RegexOptions.CultureInvariant);

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public static LoadedConsoleConfig Load(string? startDirectory = null, string? settingsFile = null)
    {
        var root = RepoRootLocator.Find(startDirectory ?? AppContext.BaseDirectory);
        var file = settingsFile ?? FindSettingsFile(root);
        if (!File.Exists(file))
        {
            throw new ConfigurationException($"Missing {file}. Restore the committed DemoConsole/appsettings.json.");
        }

        var document = ReadObject(file);
        var localFile = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(file))!, "appsettings.Local.json");
        if (File.Exists(localFile))
        {
            Merge(document, ReadObject(localFile));
        }

        ConsoleConfig config;
        try
        {
            config = document.Deserialize<ConsoleConfig>(Options)
                     ?? throw new ConfigurationException($"appsettings.json is empty: {file}");
        }
        catch (JsonException error)
        {
            throw new ConfigurationException($"appsettings.json has invalid values: {file}", error);
        }

        Validate(config);

        var paths = new ConsolePaths
        {
            RepoRoot = root,
            CaCertificate = Resolve(root, config.TrustedCertificatePath),
            TokensFile = Resolve(root, config.TokensPath),
            EnvFile = Resolve(root, config.EnvFilePath),
            SettingsFile = Path.GetFullPath(file),
        };

        var problems = new List<string>();
        if (!File.Exists(paths.CaCertificate))
        {
            problems.Add($"Missing CA certificate: {paths.CaCertificate}");
        }

        var tokens = TokenStore.Load(paths.TokensFile);
        foreach (var name in RequiredTokens(config).Where(name => !tokens.ContainsKey(name)))
        {
            problems.Add($"No token '{name}' in {paths.TokensFile}. Run scripts/demo/reset_demo_db.ps1.");
        }

        var password = EnvFile.Read(paths.EnvFile).GetValueOrDefault("MSSQL_SA_PASSWORD") ?? string.Empty;
        if (password.Length == 0)
        {
            problems.Add($"No MSSQL_SA_PASSWORD in {paths.EnvFile}; the SQL panels stay empty.");
        }

        return new LoadedConsoleConfig
        {
            Config = config,
            Paths = paths,
            Tokens = tokens,
            SqlPassword = password,
            Problems = problems,
        };
    }

    public static IEnumerable<string> RequiredTokens(ConsoleConfig config) =>
        RoleTokens.Concat(config.Stores.Select(store => store.Token)).Distinct(StringComparer.Ordinal);

    /// <summary>Throws for a name that is not a plain identifier or is a development database.</summary>
    public static void CheckDatabaseName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name) || !PlainIdentifier.IsMatch(name))
        {
            throw new ConfigurationException($"Database '{name}' is not a plain SQL Server identifier.");
        }

        if (ForbiddenDatabases.Any(forbidden => string.Equals(forbidden, name, StringComparison.OrdinalIgnoreCase)))
        {
            throw new ConfigurationException(
                $"Refusing database '{name}': it is a development database. Use RTS_DB_DEMO.");
        }
    }

    private static void Validate(ConsoleConfig config)
    {
        RequireHttps(config.MiddlewareBaseUrl, nameof(config.MiddlewareBaseUrl));
        RequireHttps(config.HqBaseUrl, nameof(config.HqBaseUrl));
        CheckDatabaseName(config.Database);

        if (string.IsNullOrWhiteSpace(config.SqlServer))
        {
            throw new ConfigurationException("SqlServer must name the SQL Server, for example 127.0.0.1,14333.");
        }

        if (config.RefreshSeconds is < 1 or > 300)
        {
            throw new ConfigurationException($"RefreshSeconds must be between 1 and 300, got {config.RefreshSeconds}.");
        }

        if (config.HighlightSeconds is < 0 or > 3600)
        {
            throw new ConfigurationException($"HighlightSeconds must be between 0 and 3600, got {config.HighlightSeconds}.");
        }

        if (config.FontSize is < 8 or > 40)
        {
            throw new ConfigurationException($"FontSize must be between 8 and 40, got {config.FontSize}.");
        }

        if (config.Stores.Count == 0)
        {
            throw new ConfigurationException("appsettings.json must list at least one store.");
        }

        var stores = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var store in config.Stores)
        {
            if (string.IsNullOrWhiteSpace(store.StoreId) || string.IsNullOrWhiteSpace(store.Token))
            {
                throw new ConfigurationException("Every store needs StoreId and Token.");
            }

            if (!stores.Add(store.StoreId))
            {
                throw new ConfigurationException($"Duplicate store: {store.StoreId}");
            }
        }
    }

    private static void RequireHttps(string value, string name)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps)
        {
            throw new ConfigurationException($"{name} must be an absolute https URL, got '{value}'.");
        }
    }

    private static string FindSettingsFile(string root)
    {
        var nextToExecutable = Path.Combine(AppContext.BaseDirectory, "appsettings.json");
        if (File.Exists(nextToExecutable))
        {
            return nextToExecutable;
        }

        var inProject = Path.Combine(root, "clients", "demo-console", "DemoConsole", "appsettings.json");
        return File.Exists(inProject) ? inProject : nextToExecutable;
    }

    private static JsonObject ReadObject(string file)
    {
        try
        {
            return JsonNode.Parse(File.ReadAllText(file), documentOptions: new JsonDocumentOptions
                   {
                       AllowTrailingCommas = true,
                       CommentHandling = JsonCommentHandling.Skip,
                   }) as JsonObject
                   ?? throw new ConfigurationException($"Expected a JSON object in {file}.");
        }
        catch (JsonException error)
        {
            throw new ConfigurationException($"{Path.GetFileName(file)} is not valid JSON: {file}", error);
        }
    }

    private static void Merge(JsonObject target, JsonObject overlay)
    {
        foreach (var (key, value) in overlay)
        {
            if (value is JsonObject overlayObject && target[key] is JsonObject targetObject)
            {
                Merge(targetObject, overlayObject);
                continue;
            }

            target[key] = value?.DeepClone();
        }
    }

    private static string Resolve(string root, string path) =>
        Path.GetFullPath(Path.IsPathRooted(path) ? path : Path.Combine(root, path));
}
