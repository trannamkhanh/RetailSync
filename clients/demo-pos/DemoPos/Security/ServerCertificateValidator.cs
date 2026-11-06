using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using DemoPos.Configuration;

namespace DemoPos.Security;

/// <summary>Trusts only the development CA, for both port 8443 and port 9443.</summary>
public static class ServerCertificateValidator
{
    public static X509Certificate2 LoadAuthority(string path)
    {
        if (!File.Exists(path))
        {
            throw new ConfigurationException(
                $"Missing CA certificate: {path}\nRun:\n  {SetupCommands.GenerateCertificates}");
        }

        try
        {
            // The CA file contains only a CERTIFICATE block, so load it directly.
            var authority = new X509Certificate2(path);
            var constraints = authority.Extensions
                .OfType<X509BasicConstraintsExtension>()
                .FirstOrDefault();
            if (constraints is null || !constraints.CertificateAuthority)
            {
                authority.Dispose();
                throw new ConfigurationException($"The certificate is not a CA certificate: {path}");
            }

            return authority;
        }
        catch (ConfigurationException)
        {
            throw;
        }
        catch (Exception error)
        {
            throw new ConfigurationException($"Could not read the CA certificate: {path}", error);
        }
    }

    public static bool Validate(X509Certificate2? certificate, SslPolicyErrors errors,
                                X509Certificate2 authority)
    {
        if (certificate is null)
        {
            return false;
        }

        // Chain errors are expected here because the development CA is not in the
        // machine store. The custom chain below is the actual trust decision.
        if ((errors & SslPolicyErrors.RemoteCertificateNameMismatch) != 0)
        {
            return false;
        }

        using var chain = new X509Chain();
        chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
        chain.ChainPolicy.CustomTrustStore.Add(authority);
        chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
        chain.ChainPolicy.VerificationFlags = X509VerificationFlags.NoFlag;
        chain.ChainPolicy.DisableCertificateDownloads = true;
        return chain.Build(certificate);
    }

    public static SocketsHttpHandler CreateHandler(X509Certificate2 authority, X509Certificate2? clientCertificate)
    {
        var certificates = new X509CertificateCollection();
        if (clientCertificate is not null)
        {
            certificates.Add(clientCertificate);
        }

        return new SocketsHttpHandler
        {
            ConnectTimeout = TimeSpan.FromSeconds(5),
            AutomaticDecompression = DecompressionMethods.All,
            // Windows resolves localhost to ::1 first; compose publishes these
            // ports on 127.0.0.1 only, so an IPv6 attempt would wait for its
            // timeout before falling back. Try IPv4 first and keep the fallback.
            ConnectCallback = ConnectPreferIpv4Async,
            SslOptions = new SslClientAuthenticationOptions
            {
                EnabledSslProtocols = System.Security.Authentication.SslProtocols.Tls12
                                      | System.Security.Authentication.SslProtocols.Tls13,
                CertificateRevocationCheckMode = X509RevocationMode.NoCheck,
                ClientCertificates = certificates,
                RemoteCertificateValidationCallback = (_, certificate, _, errors) =>
                    certificate is X509Certificate2 server && Validate(server, errors, authority),
            },
        };
    }

    private static async ValueTask<Stream> ConnectPreferIpv4Async(
        SocketsHttpConnectionContext context, CancellationToken cancellationToken)
    {
        var host = context.DnsEndPoint.Host;
        var port = context.DnsEndPoint.Port;
        var addresses = IPAddress.TryParse(host, out var literal)
            ? new[] { literal }
            : await Dns.GetHostAddressesAsync(host, cancellationToken).ConfigureAwait(false);

        Exception? lastError = null;
        foreach (var address in addresses.OrderBy(
                     address => address.AddressFamily == AddressFamily.InterNetwork ? 0 : 1))
        {
            var socket = new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp)
            {
                NoDelay = true,
            };
            try
            {
                await socket.ConnectAsync(new IPEndPoint(address, port), cancellationToken)
                    .ConfigureAwait(false);
                return new NetworkStream(socket, ownsSocket: true);
            }
            catch (Exception error) when (error is SocketException or IOException)
            {
                socket.Dispose();
                lastError = error;
            }
        }

        throw new HttpRequestException($"Could not connect to {host}:{port}.", lastError);
    }
}
