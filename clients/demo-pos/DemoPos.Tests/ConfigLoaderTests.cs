using System.Text.Json;
using DemoPos.Configuration;
using Xunit;

namespace DemoPos.Tests;

public sealed class ConfigLoaderTests
{
    private const string Settings = """
    {
      "PosBaseUrl": "https://localhost:9443/api/v1",
      "MonitorBaseUrl": "https://localhost:8443/api/v1",
      "TrustedCertificatePath": ".certs/ca.crt",
      "ClientCertificateDir": ".certs/pos",
      "TokensPath": ".tokens/demo_tokens.json",
      "UseMock": true,
      "Terminals": [
        { "StoreId": "STORE-DN1", "StoreName": "Cửa hàng Hải Châu", "PosId": "POS-DN1-01" }
      ],
      "Products": [
        { "Sku": "SKU-0001", "Barcode": "8930000000011", "Name": "Fresh milk 1L", "UnitPrice": 32000 }
      ]
    }
    """;

    [Fact]
    public void FindsTheRepositoryRootByComposeFile()
    {
        using var temporary = new TemporaryDirectory();
        File.WriteAllText(Path.Combine(temporary.Path, "compose.yaml"), "name: test");

        var root = RepoRootLocator.Find(temporary.Path);

        Assert.Equal(Path.GetFullPath(temporary.Path), root);
    }

    [Fact]
    public void LoadsSettingsAndMergesTheLocalOverride()
    {
        using var temporary = new TemporaryDirectory();
        File.WriteAllText(Path.Combine(temporary.Path, "compose.yaml"), "name: test");
        var settings = Path.Combine(temporary.Path, "appsettings.json");
        File.WriteAllText(settings, Settings);

        var loaded = ConfigLoader.Load(temporary.Path, settings);
        Assert.True(loaded.IsMock);
        Assert.Single(loaded.Config.Terminals);
        Assert.Single(loaded.Config.Products);
        Assert.Equal(Path.Combine(temporary.Path, ".certs", "ca.crt"), loaded.Paths.CaCertificate);

        File.WriteAllText(Path.Combine(temporary.Path, "appsettings.Local.json"),
            """{"UseMock": false}""");
        var overridden = ConfigLoader.Load(temporary.Path, settings);
        Assert.False(overridden.IsMock);
        Assert.NotEmpty(overridden.Problems);
        Assert.Contains(overridden.Problems, problem => problem.Contains("token file", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void MissingSettingsFileIsAConfigurationError()
    {
        using var temporary = new TemporaryDirectory();
        File.WriteAllText(Path.Combine(temporary.Path, "compose.yaml"), "name: test");

        Assert.Throws<ConfigurationException>(() =>
            ConfigLoader.Load(temporary.Path, Path.Combine(temporary.Path, "missing.json")));
    }

    [Fact]
    public void RejectsANonHttpsBaseUrl()
    {
        using var temporary = new TemporaryDirectory();
        File.WriteAllText(Path.Combine(temporary.Path, "compose.yaml"), "name: test");
        var settings = Path.Combine(temporary.Path, "appsettings.json");
        File.WriteAllText(settings, Settings.Replace("https://localhost:9443/api/v1",
            "http://localhost:9443/api/v1", StringComparison.Ordinal));

        Assert.Throws<ConfigurationException>(() => ConfigLoader.Load(temporary.Path, settings));
    }

    [Fact]
    public void MissingTokenFileIsReportedForLiveMode()
    {
        using var temporary = new TemporaryDirectory();
        File.WriteAllText(Path.Combine(temporary.Path, "compose.yaml"), "name: test");
        var settings = Path.Combine(temporary.Path, "appsettings.json");
        File.WriteAllText(settings, Settings.Replace("\"UseMock\": true", "\"UseMock\": false",
            StringComparison.Ordinal));

        var loaded = ConfigLoader.Load(temporary.Path, settings);

        Assert.Contains(loaded.Problems, problem => problem.Contains("token file", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(loaded.Problems, problem => problem.Contains("CA certificate", StringComparison.OrdinalIgnoreCase));
        Assert.Empty(loaded.Tokens);
    }

    [Fact]
    public void StartsWithTheOwnTerminalTokenAndTheStoreStaffTokenOnly()
    {
        using var temporary = new TemporaryDirectory();
        var settings = PrepareTrimmedMachine(temporary.Path,
            ("POS-DN1-01", "terminal-token"), ("staff_dn1", "staff-token"));

        var loaded = ConfigLoader.Load(temporary.Path, settings);

        Assert.Empty(loaded.Problems);
        Assert.False(loaded.IsMock);
        Assert.Null(loaded.AuditorToken);
        Assert.Equal("terminal-token", loaded.TokenForTerminal(loaded.Config.Terminals[0]));
        Assert.Equal("staff-token", loaded.StaffTokenForStore("STORE-DN1"));
    }

    [Fact]
    public void MissingStoreStaffTokenStillBlocksStartup()
    {
        using var temporary = new TemporaryDirectory();
        var settings = PrepareTrimmedMachine(temporary.Path, ("POS-DN1-01", "terminal-token"));

        var loaded = ConfigLoader.Load(temporary.Path, settings);

        Assert.Contains(loaded.Problems, problem => problem.Contains("staff_dn1", StringComparison.Ordinal));
    }

    [Fact]
    public void MissingTerminalTokenStillBlocksStartup()
    {
        using var temporary = new TemporaryDirectory();
        var settings = PrepareTrimmedMachine(temporary.Path, ("staff_dn1", "staff-token"));

        var loaded = ConfigLoader.Load(temporary.Path, settings);

        Assert.Contains(loaded.Problems, problem => problem.Contains("Missing token 'POS-DN1-01'", StringComparison.Ordinal));
    }

    /// <summary>One terminal, its own certificate and key, the CA, and no Auditor token.</summary>
    private static string PrepareTrimmedMachine(string root, params (string Name, string Value)[] tokens)
    {
        File.WriteAllText(Path.Combine(root, "compose.yaml"), "name: test");
        using var authority = TestCertificates.CreateAuthority();
        using var client = TestCertificates.CreateClientCertificate(authority, "POS-DN1-01");
        var certificates = Path.Combine(root, ".certs", "pos");
        Directory.CreateDirectory(certificates);
        TestCertificates.WriteClientPem(certificates, client, "POS-DN1-01");
        File.WriteAllText(Path.Combine(root, ".certs", "ca.crt"), authority.ExportCertificatePem());

        var tokenDirectory = Path.Combine(root, ".tokens");
        Directory.CreateDirectory(tokenDirectory);
        File.WriteAllText(Path.Combine(tokenDirectory, "demo_tokens.json"),
            JsonSerializer.Serialize(tokens.ToDictionary(pair => pair.Name, pair => pair.Value)));

        var settings = Path.Combine(root, "appsettings.json");
        File.WriteAllText(settings, Settings.Replace("\"UseMock\": true", "\"UseMock\": false",
            StringComparison.Ordinal));
        return settings;
    }
}
