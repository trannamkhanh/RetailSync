namespace DemoPos.Configuration;

/// <summary>The committed appsettings.json shape (DS-04 demo client).</summary>
public sealed class AppConfig
{
    public string PosBaseUrl { get; set; } = "https://localhost:9443/api/v1";

    public string MonitorBaseUrl { get; set; } = "https://localhost:8443/api/v1";

    public string TrustedCertificatePath { get; set; } = ".certs/ca.crt";

    public string ClientCertificateDir { get; set; } = ".certs/pos";

    public string TokensPath { get; set; } = ".tokens/demo_tokens.json";

    public bool UseMock { get; set; }

    public List<TerminalConfig> Terminals { get; set; } = new();

    public List<ProductConfig> Products { get; set; } = new();
}

public sealed class TerminalConfig
{
    public string StoreId { get; set; } = string.Empty;

    public string StoreName { get; set; } = string.Empty;

    public string PosId { get; set; } = string.Empty;

    public string DisplayName => $"{StoreName} · {PosId}";
}

public sealed class ProductConfig
{
    public string Sku { get; set; } = string.Empty;

    public string Barcode { get; set; } = string.Empty;

    public string Name { get; set; } = string.Empty;

    public decimal UnitPrice { get; set; }
}

/// <summary>Absolute paths derived from the repository root.</summary>
public sealed class AppPaths
{
    public required string RepoRoot { get; init; }

    public required string CaCertificate { get; init; }

    public required string ClientCertificateDir { get; init; }

    public required string TokensFile { get; init; }

    public required string SettingsFile { get; init; }

    public required string LocalSettingsFile { get; init; }

    public string CertificateFile(string posId) => Path.Combine(ClientCertificateDir, posId + ".crt");

    public string KeyFile(string posId) => Path.Combine(ClientCertificateDir, posId + ".key");
}

/// <summary>Configuration plus the demo assets and any setup problems for LIVE mode.</summary>
public sealed class LoadedConfig
{
    public required AppConfig Config { get; init; }

    public required AppPaths Paths { get; init; }

    public required IReadOnlyDictionary<string, string> Tokens { get; init; }

    public required IReadOnlyList<string> Problems { get; init; }

    public bool IsMock => Config.UseMock;

    public string? TokenForTerminal(TerminalConfig terminal) =>
        Tokens.TryGetValue(terminal.PosId, out var token) ? token : null;

    public string? StaffTokenForStore(string storeId)
    {
        var key = TokenNames.StaffForStore(storeId);
        return key is not null && Tokens.TryGetValue(key, out var token) ? token : null;
    }

    public string? AuditorToken => Tokens.TryGetValue(TokenNames.Auditor, out var token) ? token : null;
}

public static class TokenNames
{
    public const string Auditor = "auditor";

    /// <summary>STORE-DN1 maps to the seeded staff_dn1 account.</summary>
    public static string? StaffForStore(string storeId)
    {
        if (string.IsNullOrWhiteSpace(storeId))
        {
            return null;
        }

        var value = storeId.Trim();
        const string prefix = "STORE-";
        if (!value.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        var suffix = value[prefix.Length..];
        return suffix.Length == 0 ? null : "staff_" + suffix.ToLowerInvariant();
    }
}

public static class SetupCommands
{
    public const string GenerateCertificates =
        "& \"$env:ProgramFiles\\Git\\bin\\bash.exe\" scripts/generate_dev_certs.sh";

    public const string RegisterFingerprints =
        "docker compose run --rm --no-deps --volume \"${PWD}:/repo:ro\" --workdir /repo middleware python scripts/register_pos_certificates.py";

    public const string IssueTokens =
        "docker compose run --rm --volume \"${PWD}:/repo\" --workdir /repo middleware python scripts/issue_demo_tokens.py";

    public const string StartServices =
        "docker compose up -d --wait middleware pos-gateway";

    public const string GatewaySecret =
        "Add POS_GATEWAY_SECRET to .env; see the POS gateway section of README.md.";
}
