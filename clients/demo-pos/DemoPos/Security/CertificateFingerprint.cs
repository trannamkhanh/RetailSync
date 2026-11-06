using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace DemoPos.Security;

/// <summary>The fingerprint format used by pos_terminal.cert_fingerprint (PB-48).</summary>
public static class CertificateFingerprint
{
    public static string Compute(X509Certificate2 certificate) =>
        Convert.ToHexString(SHA256.HashData(certificate.RawData)).ToLowerInvariant();

    public static string Prefix(X509Certificate2 certificate, int length = 12)
    {
        var value = Compute(certificate);
        return value[..Math.Min(length, value.Length)];
    }
}
