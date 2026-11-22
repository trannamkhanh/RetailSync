using System.Net;
using System.Net.Sockets;
using StaffApp.Security;
using Xunit;

namespace StaffApp.Tests;

public sealed class Audit18ServerCertificateValidatorTests
{
    [Fact]
    public async Task Audit18_ServerCertificateValidatorDisposesSocketOnCancellation()
    {
        var created = new List<Socket>();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            await ServerCertificateValidator.ConnectAddressesAsync(
                new[] { IPAddress.Loopback },
                "127.0.0.1",
                1,
                cts.Token,
                family =>
                {
                    var socket = new Socket(family, SocketType.Stream, ProtocolType.Tcp);
                    created.Add(socket);
                    return socket;
                }));

        var socket = Assert.Single(created);
        Assert.Throws<ObjectDisposedException>(() => _ = socket.NoDelay);
    }
}
