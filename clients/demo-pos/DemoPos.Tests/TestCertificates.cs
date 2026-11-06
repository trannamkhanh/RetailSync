using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace DemoPos.Tests;

internal static class TestCertificates
{
    public static X509Certificate2 CreateAuthority(string commonName = "RetailSync Test CA")
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest(
            $"CN={commonName}", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        request.CertificateExtensions.Add(
            new X509BasicConstraintsExtension(true, false, 0, true));
        request.CertificateExtensions.Add(
            new X509KeyUsageExtension(
                X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign, true));
        return request.CreateSelfSigned(
            DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(2));
    }

    public static X509Certificate2 CreateServerCertificate(X509Certificate2 authority,
                                                           string dnsName = "localhost")
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest(
            $"CN={dnsName}", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        request.CertificateExtensions.Add(
            new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(
            new X509KeyUsageExtension(
                X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
        request.CertificateExtensions.Add(
            new X509EnhancedKeyUsageExtension(
                new OidCollection { new("1.3.6.1.5.5.7.3.1") }, false));
        var names = new SubjectAlternativeNameBuilder();
        names.AddDnsName(dnsName);
        request.CertificateExtensions.Add(names.Build());
        var serial = RandomNumberGenerator.GetBytes(16);
        var certificate = request.Create(
            authority, DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(1), serial);
        return certificate.CopyWithPrivateKey(key);
    }

    public static X509Certificate2 CreateClientCertificate(X509Certificate2 authority,
                                                           string posId = "POS-DN1-01")
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest(
            $"CN={posId}", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        request.CertificateExtensions.Add(
            new X509BasicConstraintsExtension(false, false, 0, true));
        request.CertificateExtensions.Add(
            new X509KeyUsageExtension(
                X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
        request.CertificateExtensions.Add(
            new X509EnhancedKeyUsageExtension(
                new OidCollection { new("1.3.6.1.5.5.7.3.2") }, false));
        var serial = RandomNumberGenerator.GetBytes(16);
        var certificate = request.Create(
            authority, DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(1), serial);
        return certificate.CopyWithPrivateKey(key);
    }

    public static (string CertificatePath, string KeyPath) WriteClientPem(
        string directory, X509Certificate2 certificate, string posId = "POS-DN1-01")
    {
        Directory.CreateDirectory(directory);
        var certificatePath = Path.Combine(directory, posId + ".crt");
        var keyPath = Path.Combine(directory, posId + ".key");
        File.WriteAllText(certificatePath, certificate.ExportCertificatePem());
        using var key = certificate.GetRSAPrivateKey()
                        ?? throw new InvalidOperationException("The test certificate has no RSA key.");
        File.WriteAllText(keyPath, key.ExportPkcs8PrivateKeyPem());
        return (certificatePath, keyPath);
    }
}

internal sealed class TemporaryDirectory : IDisposable
{
    public TemporaryDirectory()
    {
        Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(),
            "demopos-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path);
    }

    public string Path { get; }

    public void Dispose()
    {
        try
        {
            Directory.Delete(Path, recursive: true);
        }
        catch (IOException)
        {
            // A test may still hold a file; the OS will clean it up.
        }
    }
}
