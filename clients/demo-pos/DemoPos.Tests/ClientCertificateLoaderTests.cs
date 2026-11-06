using DemoPos.Configuration;
using DemoPos.Security;
using Xunit;

namespace DemoPos.Tests;

public sealed class ClientCertificateLoaderTests
{
    [Fact]
    public void ReportsMissingCertificateAndKey()
    {
        using var temporary = new TemporaryDirectory();
        var info = ClientCertificateLoader.Load("POS-DN1-01",
            Path.Combine(temporary.Path, "POS-DN1-01.crt"),
            Path.Combine(temporary.Path, "POS-DN1-01.key"));

        Assert.False(info.IsUsable);
        Assert.False(info.CertificateExists);
        Assert.False(info.KeyExists);
        Assert.NotNull(info.Error);
        Assert.Contains("Missing", info.Error);
    }

    [Fact]
    public void LoadsTheSelectedTerminalCertificateAndItsFingerprint()
    {
        using var temporary = new TemporaryDirectory();
        using var authority = TestCertificates.CreateAuthority();
        using var client = TestCertificates.CreateClientCertificate(authority, "POS-DN1-01");
        var (crt, key) = TestCertificates.WriteClientPem(temporary.Path, client, "POS-DN1-01");

        var info = ClientCertificateLoader.Load("POS-DN1-01", crt, key);

        Assert.True(info.IsUsable, info.Error);
        Assert.True(info.CertificateExists);
        Assert.True(info.KeyExists);
        Assert.NotNull(info.Certificate);
        Assert.Contains("POS-DN1-01", info.Certificate!.Subject);
        Assert.Equal(12, info.FingerprintPrefix.Length);
        Assert.Equal(info.FingerprintPrefix, CertificateFingerprint.Prefix(info.Certificate));
    }

    [Fact]
    public void LoadsTheFileNamesOfTheTerminal()
    {
        using var temporary = new TemporaryDirectory();
        using var authority = TestCertificates.CreateAuthority();
        using var client = TestCertificates.CreateClientCertificate(authority, "POS-DN2-02");
        TestCertificates.WriteClientPem(temporary.Path, client, "POS-DN2-02");
        var paths = new AppPaths
        {
            RepoRoot = temporary.Path,
            CaCertificate = Path.Combine(temporary.Path, "ca.crt"),
            ClientCertificateDir = temporary.Path,
            TokensFile = Path.Combine(temporary.Path, "tokens.json"),
            SettingsFile = Path.Combine(temporary.Path, "appsettings.json"),
            LocalSettingsFile = Path.Combine(temporary.Path, "appsettings.Local.json"),
        };
        var terminal = new TerminalConfig
        {
            StoreId = "STORE-DN2",
            StoreName = "Cửa hàng Thanh Khê",
            PosId = "POS-DN2-02",
        };

        var info = ClientCertificateLoader.Load(terminal, paths);

        Assert.True(info.IsUsable, info.Error);
        Assert.Equal(paths.CertificateFile("POS-DN2-02"), info.CertificatePath);
        Assert.Equal(paths.KeyFile("POS-DN2-02"), info.KeyPath);
    }
}
