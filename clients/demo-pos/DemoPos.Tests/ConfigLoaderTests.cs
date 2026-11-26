using System.Diagnostics;
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
    public void StartsWithTheOwnTerminalTokenAndStoreStaffTokenOnly_PB45_6()
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
    public void MissingStoreStaffTokenStillBlocksStartup_PB45_6()
    {
        using var temporary = new TemporaryDirectory();
        var settings = PrepareTrimmedMachine(temporary.Path, ("POS-DN1-01", "terminal-token"));

        var loaded = ConfigLoader.Load(temporary.Path, settings);

        Assert.Contains(loaded.Problems, problem => problem.Contains("staff_dn1", StringComparison.Ordinal));
    }

    [Fact]
    public void MissingTerminalTokenStillBlocksStartup_PB45_6()
    {
        using var temporary = new TemporaryDirectory();
        var settings = PrepareTrimmedMachine(temporary.Path, ("staff_dn1", "staff-token"));

        var loaded = ConfigLoader.Load(temporary.Path, settings);

        Assert.Contains(loaded.Problems, problem => problem.Contains("Missing token 'POS-DN1-01'", StringComparison.Ordinal));
    }

    [Fact]
    public void Pb41_5_LocalSettingsNextToExecutableWinsOverProjectFolder()
    {
        using var temporary = new TemporaryDirectory();
        var (binDir, binSettings, projectDir) = PrepareRepoWithBinLayout(temporary.Path);
        var binLocal = Path.Combine(binDir, "appsettings.Local.json");
        var projectLocal = Path.Combine(projectDir, "appsettings.Local.json");
        File.WriteAllText(projectLocal, """{"PosBaseUrl": "https://10.0.0.10:9443/api/v1"}""");
        File.WriteAllText(binLocal, """{"PosBaseUrl": "https://192.168.1.99:9443/api/v1"}""");

        var (loaded, logs) = LoadWithTrace(() => ConfigLoader.Load(binDir, binSettings));

        Assert.Equal("https://192.168.1.99:9443/api/v1", loaded.Config.PosBaseUrl);
        Assert.Equal(Path.GetFullPath(binLocal), loaded.Paths.LocalSettingsFile);
        Assert.Contains(logs, line => line.Contains(Path.GetFullPath(binLocal), StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Pb41_5_LocalSettingsFallsBackToProjectFolderWhenMissingNextToExecutable()
    {
        using var temporary = new TemporaryDirectory();
        var (binDir, binSettings, projectDir) = PrepareRepoWithBinLayout(temporary.Path);
        var projectLocal = Path.Combine(projectDir, "appsettings.Local.json");
        File.WriteAllText(projectLocal,
            """{"PosBaseUrl": "https://192.168.1.10:9443/api/v1", "MonitorBaseUrl": "https://192.168.1.10:8443/api/v1"}""");

        var (loaded, logs) = LoadWithTrace(() => ConfigLoader.Load(binDir, binSettings));

        Assert.Equal("https://192.168.1.10:9443/api/v1", loaded.Config.PosBaseUrl);
        Assert.Equal("https://192.168.1.10:8443/api/v1", loaded.Config.MonitorBaseUrl);
        Assert.Equal(Path.GetFullPath(projectLocal), loaded.Paths.LocalSettingsFile);
        Assert.Contains(logs, line => line.Contains(Path.GetFullPath(projectLocal), StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Pb41_5_LoadsDefaultsWhenNoLocalSettingsExistInEitherLocation()
    {
        using var temporary = new TemporaryDirectory();
        var (binDir, binSettings, _) = PrepareRepoWithBinLayout(temporary.Path);

        var (loaded, logs) = LoadWithTrace(() => ConfigLoader.Load(binDir, binSettings));

        Assert.Equal("https://localhost:9443/api/v1", loaded.Config.PosBaseUrl);
        Assert.Equal("https://localhost:8443/api/v1", loaded.Config.MonitorBaseUrl);
        Assert.True(loaded.IsMock);
        Assert.False(File.Exists(loaded.Paths.LocalSettingsFile));
        Assert.Contains(logs, line => line.Contains("appsettings.Local.json", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Pb41_5_DemoPosProjectFileDoesNotCopyLocalSettingsToOutput()
    {
        var repoRoot = RepoRootLocator.Find(AppContext.BaseDirectory);
        var csprojPath = Path.Combine(repoRoot, "clients", "demo-pos", "DemoPos", "DemoPos.csproj");
        var csproj = File.ReadAllText(csprojPath);

        Assert.Contains("appsettings.json", csproj, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("appsettings.Local.json", csproj, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Pb41_5_MainFormStatusStripShowsResolvedLocalSettingsSource()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                using var temporary = new TemporaryDirectory();
                var (binDir, binSettings, projectDir) = PrepareRepoWithBinLayout(temporary.Path);

                // 1. Neither present -> "Local: không có"
                var noneLoaded = ConfigLoader.Load(binDir, binSettings);
                using (var form = new DemoPos.UI.MainForm(noneLoaded, temporary.Path))
                {
                    Assert.Contains("Local: không có", form.FilesStatusText, StringComparison.Ordinal);
                }

                // 2. Project-folder fallback -> shows project appsettings.Local.json
                var projectLocal = Path.Combine(projectDir, "appsettings.Local.json");
                File.WriteAllText(projectLocal, """{"PosBaseUrl": "https://192.168.1.50:9443/api/v1"}""");
                var projectLoaded = ConfigLoader.Load(binDir, binSettings);
                using (var form = new DemoPos.UI.MainForm(projectLoaded, temporary.Path))
                {
                    Assert.Contains("Local: appsettings.Local.json (project)", form.FilesStatusText, StringComparison.Ordinal);
                }

                // 3. Beside executable wins -> shows exe appsettings.Local.json
                var binLocal = Path.Combine(binDir, "appsettings.Local.json");
                File.WriteAllText(binLocal, """{"PosBaseUrl": "https://192.168.1.99:9443/api/v1"}""");
                var binLoaded = ConfigLoader.Load(binDir, binSettings);
                using (var form = new DemoPos.UI.MainForm(binLoaded, temporary.Path))
                {
                    Assert.Contains("Local: appsettings.Local.json (exe)", form.FilesStatusText, StringComparison.Ordinal);
                }
            }
            catch (Exception ex)
            {
                failure = ex;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private static (string BinDir, string BinSettings, string ProjectDir) PrepareRepoWithBinLayout(string root)
    {
        File.WriteAllText(Path.Combine(root, "compose.yaml"), "name: test\n");
        var projectDir = Path.Combine(root, "clients", "demo-pos", "DemoPos");
        var binDir = Path.Combine(projectDir, "bin", "Debug", "net8.0-windows");
        Directory.CreateDirectory(binDir);
        File.WriteAllText(Path.Combine(projectDir, "appsettings.json"), Settings);
        var binSettings = Path.Combine(binDir, "appsettings.json");
        File.WriteAllText(binSettings, Settings);
        return (binDir, binSettings, projectDir);
    }

    private static (T Result, List<string> Logs) LoadWithTrace<T>(Func<T> action)
    {
        var messages = new List<string>();
        using var listener = new CapturingTraceListener(messages);
        Trace.Listeners.Add(listener);
        try
        {
            return (action(), messages);
        }
        finally
        {
            Trace.Listeners.Remove(listener);
        }
    }

    private sealed class CapturingTraceListener : TraceListener
    {
        private readonly List<string> _messages;
        public CapturingTraceListener(List<string> messages) => _messages = messages;
        public override void Write(string? message) { if (message is not null) _messages.Add(message); }
        public override void WriteLine(string? message) { if (message is not null) _messages.Add(message); }
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
