using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using DemoPos.Configuration;
using DemoPos.Security;
using Xunit;

namespace DemoPos.Tests;

public sealed class CertificateTests
{
    [Fact]
    public void AcceptsAServerCertificateIssuedByTheTrustedCa()
    {
        using var authority = TestCertificates.CreateAuthority();
        using var server = TestCertificates.CreateServerCertificate(authority);

        Assert.True(ServerCertificateValidator.Validate(server, SslPolicyErrors.None, authority));
    }

    [Fact]
    public void RejectsAServerCertificateFromAnotherCa()
    {
        using var trusted = TestCertificates.CreateAuthority("Trusted CA");
        using var other = TestCertificates.CreateAuthority("Other CA");
        using var server = TestCertificates.CreateServerCertificate(other);

        Assert.False(ServerCertificateValidator.Validate(server, SslPolicyErrors.None, trusted));
    }

    [Fact]
    public void RejectsAMissingCertificate()
    {
        using var authority = TestCertificates.CreateAuthority();

        Assert.False(ServerCertificateValidator.Validate(null, SslPolicyErrors.None, authority));
    }

    [Fact]
    public void LoadAuthorityAcceptsACaAndRejectsANonCaCertificate()
    {
        using var temporary = new TemporaryDirectory();
        using var authority = TestCertificates.CreateAuthority();
        using var server = TestCertificates.CreateServerCertificate(authority);
        var caPath = Path.Combine(temporary.Path, "ca.crt");
        var serverPath = Path.Combine(temporary.Path, "server.crt");
        File.WriteAllText(caPath, authority.ExportCertificatePem());
        File.WriteAllText(serverPath, server.ExportCertificatePem());

        using var loaded = ServerCertificateValidator.LoadAuthority(caPath);
        Assert.Equal(authority.Subject, loaded.Subject);

        Assert.Throws<ConfigurationException>(() => ServerCertificateValidator.LoadAuthority(serverPath));
    }
}
