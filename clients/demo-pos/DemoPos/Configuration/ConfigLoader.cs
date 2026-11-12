using System.Text.Json;
using System.Text.Json.Nodes;
using DemoPos.Services;

namespace DemoPos.Configuration;

/// <summary>Loads appsettings.json, merges appsettings.Local.json, and checks demo assets.</summary>
public static class ConfigLoader
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public static LoadedConfig Load(string? startDirectory = null, string? settingsFile = null)
    {
        string root;
        try
        {
            root = RepoRootLocator.Find(startDirectory ?? AppContext.BaseDirectory);
        }
        catch (ConfigurationException)
        {
            // The published demo POS runs from a folder outside the repository; its settings and
            // assets are found next to the executable or through absolute paths.
            root = Path.GetFullPath(startDirectory ?? AppContext.BaseDirectory);
        }
        var file = settingsFile ?? FindSettingsFile(root);
        if (!File.Exists(file))
        {
            throw new ConfigurationException(
                $"Missing {file}. Restore the committed DemoPos/appsettings.json.");
        }

        JsonObject document;
        try
        {
            document = ParseObject(File.ReadAllText(file), file);
        }
        catch (JsonException error)
        {
            throw new ConfigurationException($"appsettings.json is not valid JSON: {file}", error);
        }

        var localFile = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(file))!, "appsettings.Local.json");
        if (File.Exists(localFile))
        {
            try
            {
                Merge(document, ParseObject(File.ReadAllText(localFile), localFile));
            }
            catch (JsonException error)
            {
                throw new ConfigurationException($"appsettings.Local.json is not valid JSON: {localFile}", error);
            }
        }

        AppConfig config;
        try
        {
            config = document.Deserialize<AppConfig>(Options)
                     ?? throw new ConfigurationException($"appsettings.json is empty: {file}");
        }
        catch (JsonException error)
        {
            throw new ConfigurationException($"appsettings.json has invalid values: {file}", error);
        }

        Validate(config);

        var paths = new AppPaths
        {
            RepoRoot = root,
            CaCertificate = Resolve(root, config.TrustedCertificatePath),
            ClientCertificateDir = Resolve(root, config.ClientCertificateDir),
            TokensFile = Resolve(root, config.TokensPath),
            SettingsFile = Path.GetFullPath(file),
            LocalSettingsFile = localFile,
        };

        var tokens = TokenStore.Load(paths.TokensFile);
        var problems = config.UseMock
            ? new List<string>()
            : CheckLiveAssets(config, paths, tokens);

        return new LoadedConfig
        {
            Config = config,
            Paths = paths,
            Tokens = tokens,
            Problems = problems,
        };
    }

    private static string FindSettingsFile(string root)
    {
        var nextToExecutable = Path.Combine(AppContext.BaseDirectory, "appsettings.json");
        if (File.Exists(nextToExecutable))
        {
            return nextToExecutable;
        }

        var inProject = Path.Combine(root, "clients", "demo-pos", "DemoPos", "appsettings.json");
        return File.Exists(inProject) ? inProject : nextToExecutable;
    }

    private static JsonObject ParseObject(string text, string file)
    {
        var node = JsonNode.Parse(text);
        return node as JsonObject
               ?? throw new ConfigurationException($"Expected a JSON object in {file}.");
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

    private static void Validate(AppConfig config)
    {
        RequireHttps(config.PosBaseUrl, nameof(config.PosBaseUrl));
        RequireHttps(config.MonitorBaseUrl, nameof(config.MonitorBaseUrl));

        if (config.Terminals.Count == 0)
        {
            throw new ConfigurationException("appsettings.json must list at least one terminal.");
        }

        var terminals = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var terminal in config.Terminals)
        {
            if (string.IsNullOrWhiteSpace(terminal.StoreId)
                || string.IsNullOrWhiteSpace(terminal.StoreName)
                || string.IsNullOrWhiteSpace(terminal.PosId))
            {
                throw new ConfigurationException("Every terminal needs StoreId, StoreName and PosId.");
            }

            if (!terminals.Add(terminal.PosId))
            {
                throw new ConfigurationException($"Duplicate terminal PosId: {terminal.PosId}");
            }
        }

        if (config.Products.Count == 0)
        {
            throw new ConfigurationException("appsettings.json must list at least one product.");
        }

        var products = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var product in config.Products)
        {
            if (string.IsNullOrWhiteSpace(product.Sku) || string.IsNullOrWhiteSpace(product.Name))
            {
                throw new ConfigurationException("Every product needs Sku and Name.");
            }

            if (product.UnitPrice < 0)
            {
                throw new ConfigurationException($"Product {product.Sku} has a negative UnitPrice.");
            }

            if (!products.Add(product.Sku))
            {
                throw new ConfigurationException($"Duplicate product SKU: {product.Sku}");
            }
        }
    }

    private static void RequireHttps(string value, string name)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)
            || uri.Scheme != Uri.UriSchemeHttps)
        {
            throw new ConfigurationException($"{name} must be an absolute https URL, got '{value}'.");
        }
    }

    private static List<string> CheckLiveAssets(AppConfig config, AppPaths paths,
                                                IReadOnlyDictionary<string, string> tokens)
    {
        var problems = new List<string>();

        if (!File.Exists(paths.CaCertificate))
        {
            problems.Add($"Missing CA certificate: {paths.CaCertificate}\nRun:\n  {SetupCommands.GenerateCertificates}");
        }

        foreach (var terminal in config.Terminals)
        {
            var crt = paths.CertificateFile(terminal.PosId);
            var key = paths.KeyFile(terminal.PosId);
            if (!File.Exists(crt) || !File.Exists(key))
            {
                problems.Add(
                    $"Missing client certificate or key for {terminal.PosId}: {crt} / {key}\n" +
                    $"Run:\n  {SetupCommands.GenerateCertificates}\n" +
                    $"Then register the fingerprints:\n  {SetupCommands.RegisterFingerprints}");
            }
        }

        if (!File.Exists(paths.TokensFile))
        {
            problems.Add($"Missing token file: {paths.TokensFile}\nRun:\n  {SetupCommands.IssueTokens}");
            return problems;
        }

        foreach (var terminal in config.Terminals)
        {
            if (!tokens.ContainsKey(terminal.PosId))
            {
                problems.Add($"Missing token '{terminal.PosId}' in {paths.TokensFile}.\nRun:\n  {SetupCommands.IssueTokens}");
            }
        }

        foreach (var storeId in config.Terminals.Select(terminal => terminal.StoreId).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var key = TokenNames.StaffForStore(storeId);
            if (key is null || !tokens.ContainsKey(key))
            {
                problems.Add($"Missing store token '{key ?? "staff_*"}' for {storeId}.\nRun:\n  {SetupCommands.IssueTokens}");
            }
        }

        if (!tokens.ContainsKey(TokenNames.Auditor))
        {
            problems.Add($"Missing '{TokenNames.Auditor}' token in {paths.TokensFile}.\nRun:\n  {SetupCommands.IssueTokens}");
        }

        return problems.Distinct(StringComparer.Ordinal).ToList();
    }

    private static string Resolve(string root, string value) =>
        Path.GetFullPath(Path.IsPathRooted(value) ? value : Path.Combine(root, value));
}
