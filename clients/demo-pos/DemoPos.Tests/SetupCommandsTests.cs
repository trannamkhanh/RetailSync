using DemoPos.Configuration;
using Xunit;

namespace DemoPos.Tests;

public sealed class SetupCommandsTests
{
    [Fact]
    public void Pb41_6_MiddlewareDockerComposeRunHintsIncludeNoDeps()
    {
        Assert.Contains("docker compose run --rm --no-deps", SetupCommands.RegisterFingerprints, StringComparison.Ordinal);
        Assert.Contains("docker compose run --rm --no-deps", SetupCommands.IssueTokens, StringComparison.Ordinal);
    }
}
