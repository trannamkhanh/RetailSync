namespace DemoConsole.Configuration;

/// <summary>appsettings.json of the demo console; appsettings.Local.json may override any value.</summary>
public sealed class ConsoleConfig
{
    public string MiddlewareBaseUrl { get; set; } = "https://localhost:8443/api/v1";
    public string HqBaseUrl { get; set; } = "https://localhost:9000/api/v1";
    public string TrustedCertificatePath { get; set; } = ".certs/ca.crt";
    public string TokensPath { get; set; } = ".tokens/demo_tokens.json";
    public string EnvFilePath { get; set; } = ".env";
    public string SqlServer { get; set; } = "127.0.0.1,14333";
    public string Database { get; set; } = "RTS_DB_DEMO";
    public int RefreshSeconds { get; set; } = 3;
    /// <summary>
    /// PB-49: the Dashboard has its own, slower timer. It aggregates a range, so
    /// refreshing it every <see cref="RefreshSeconds"/> would send a heavy query on
    /// every tick of the other four tabs.
    /// </summary>
    public int DashboardRefreshSeconds { get; set; } = 30;
    public int HighlightSeconds { get; set; } = 15;
    public float FontSize { get; set; } = 13;
    public List<StoreSetting> Stores { get; set; } = new();
    public List<ProductSetting> Products { get; set; } = new();
}

public sealed class StoreSetting
{
    public string StoreId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Token { get; set; } = string.Empty;
}

public sealed class ProductSetting
{
    public string Sku { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
}

/// <summary>Absolute paths resolved against the repository root.</summary>
public sealed class ConsolePaths
{
    public required string RepoRoot { get; init; }
    public required string CaCertificate { get; init; }
    public required string TokensFile { get; init; }
    public required string EnvFile { get; init; }
    public required string SettingsFile { get; init; }
    public string? LocalSettingsFile { get; init; }
}

public sealed class LoadedConsoleConfig
{
    public required ConsoleConfig Config { get; init; }
    public required ConsolePaths Paths { get; init; }
    public required IReadOnlyDictionary<string, string> Tokens { get; init; }
    public required string SqlPassword { get; init; }

    /// <summary>Missing files or tokens; the window still opens and shows them.</summary>
    public required IReadOnlyList<string> Problems { get; init; }
}
