using DemoPos.Models;

namespace DemoPos.Services;

public interface IPosBackend
{
    bool IsMock { get; }

    Task<PosResult> SendAsync(string rawBody, CancellationToken cancellationToken = default);
}
