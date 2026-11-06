using DemoPos.Configuration;
using DemoPos.Services;
using Xunit;

namespace DemoPos.Tests;

public sealed class TokenStoreTests
{
    [Fact]
    public void MissingTokenFileReturnsAnEmptySetWithoutCrashing()
    {
        using var temporary = new TemporaryDirectory();
        var tokens = TokenStore.Load(Path.Combine(temporary.Path, "missing.json"));

        Assert.Empty(tokens);
    }

    [Fact]
    public void ReadsTheCommittedShapeOfTheTokenFile()
    {
        using var temporary = new TemporaryDirectory();
        var path = Path.Combine(temporary.Path, "demo_tokens.json");
        File.WriteAllText(path, """{"POS-DN1-01":"a.b.c","staff_dn1":"d.e.f","auditor":"g.h.i"}""");

        var tokens = TokenStore.Load(path);

        Assert.Equal(3, tokens.Count);
        Assert.Equal("a.b.c", tokens["POS-DN1-01"]);
        Assert.Equal("d.e.f", tokens["staff_dn1"]);
    }

    [Fact]
    public void InvalidTokenJsonIsAConfigurationError()
    {
        using var temporary = new TemporaryDirectory();
        var path = Path.Combine(temporary.Path, "demo_tokens.json");
        File.WriteAllText(path, "not json");

        Assert.Throws<ConfigurationException>(() => TokenStore.Load(path));
    }

    [Fact]
    public void StoreNamesMapToTheSeededStaffAccounts()
    {
        Assert.Equal("staff_dn1", TokenNames.StaffForStore("STORE-DN1"));
        Assert.Equal("staff_dn3", TokenNames.StaffForStore("STORE-DN3"));
        Assert.Null(TokenNames.StaffForStore("OTHER"));
    }
}
