using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using DemoPos.Configuration;

namespace DemoPos.Security;

/// <summary>One terminal's .crt/.key pair, or the reason it cannot be used.</summary>
public sealed class ClientCertificateInfo : IDisposable
{
    public required string PosId { get; init; }

    public required string CertificatePath { get; init; }

    public required string KeyPath { get; init; }

    public bool CertificateExists { get; init; }

    public bool KeyExists { get; init; }

    public X509Certificate2? Certificate { get; init; }

    public string? Error { get; init; }

    public bool IsUsable => Certificate is not null && Error is null;

    public string FingerprintPrefix =>
        Certificate is null ? "—" : CertificateFingerprint.Prefix(Certificate);

    public void Dispose()
    {
        Certificate?.Dispose();
    }
}

public static class ClientCertificateLoader
{
    public static ClientCertificateInfo Load(TerminalConfig terminal, AppPaths paths) =>
        Load(terminal.PosId, paths.CertificateFile(terminal.PosId), paths.KeyFile(terminal.PosId));

    public static ClientCertificateInfo Load(string posId, string certificatePath, string keyPath)
    {
        var crtExists = File.Exists(certificatePath);
        var keyExists = File.Exists(keyPath);
        if (!crtExists || !keyExists)
        {
            return new ClientCertificateInfo
            {
                PosId = posId,
                CertificatePath = certificatePath,
                KeyPath = keyPath,
                CertificateExists = crtExists,
                KeyExists = keyExists,
                Error = $"Missing {(crtExists ? "key" : "certificate")} for {posId}.",
            };
        }

        try
        {
            using var pem = X509Certificate2.CreateFromPemFile(certificatePath, keyPath);
            // SslStream on Windows cannot use the ephemeral key returned from PEM.
            // Re-import from a PKCS#12 export once so the private key has a usable container.
            var pkcs12 = pem.Export(X509ContentType.Pkcs12);
            var certificate = new X509Certificate2(
                pkcs12, (string?)null, X509KeyStorageFlags.Exportable);

            if (!certificate.HasPrivateKey)
            {
                certificate.Dispose();
                return new ClientCertificateInfo
                {
                    PosId = posId,
                    CertificatePath = certificatePath,
                    KeyPath = keyPath,
                    CertificateExists = true,
                    KeyExists = true,
                    Error = $"Certificate for {posId} has no private key.",
                };
            }

            return new ClientCertificateInfo
            {
                PosId = posId,
                CertificatePath = certificatePath,
                KeyPath = keyPath,
                CertificateExists = true,
                KeyExists = true,
                Certificate = certificate,
            };
        }
        catch (Exception error) when (error is CryptographicException or IOException or FormatException or UnauthorizedAccessException)
        {
            return new ClientCertificateInfo
            {
                PosId = posId,
                CertificatePath = certificatePath,
                KeyPath = keyPath,
                CertificateExists = true,
                KeyExists = true,
                Error = $"Could not load the certificate for {posId}: {error.Message}",
            };
        }
    }
}
